"""
Whale tracking and scoring system for Allocator AI
"""

import time
import logging
import requests
import math
import decimal
from decimal import Decimal
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..utils.math_utils import calculate_win_rate, calculate_volatility, calculate_sharpe_ratio
from ..data.cache import CacheManager, RateLimiter
from ..analytics.market_conditions import MarketConditionAnalyzer
from ..analytics.adaptive_discovery import AdaptiveDiscoveryEngine
from ..analytics.moralis_feedback import MoralisFeedbackTracker

logger = logging.getLogger(__name__)


@dataclass
class WhaleStats:
    """Whale performance statistics"""
    address: str
    score: Decimal
    roi: Decimal
    trades: int
    win_rate: Decimal
    volatility: Decimal
    sharpe_ratio: Decimal
    moralis_roi_pct: Optional[Decimal] = None
    moralis_profit_usd: Optional[Decimal] = None
    moralis_trades: Optional[int] = None
    last_updated: float = 0


class WhaleTracker:
    """Advanced whale tracking and scoring system"""
    
    def __init__(self, moralis_api_key: str, cache_manager: CacheManager, db_manager, discovery_config=None):
        self.moralis_api_key = moralis_api_key
        self.cache = cache_manager
        self.db = db_manager
        self.rate_limiter = RateLimiter(max_calls=100, time_window=3600)  # 100 calls per hour
        
        # New adaptive components
        self.market_analyzer = None  # Will be initialized when needed
        self.adaptive_engine = None  # Will be initialized when needed
        self.moralis_feedback = MoralisFeedbackTracker(db_manager)
        
        # Whale performance tracking
        self.whale_history = defaultdict(lambda: deque(maxlen=50))  # Keep last 50 trades
        self.whale_scores = defaultdict(lambda: WhaleStats(
            address="",
            score=Decimal("0"),
            roi=Decimal("0"),
            trades=0,
            win_rate=Decimal("0"),
            volatility=Decimal("1"),
            sharpe_ratio=Decimal("0")
        ))
        
        # Tracked whales
        self.tracked_whales = set()
        
        # Discovery modes configuration (load from config or use defaults)
        if discovery_config and discovery_config.mode_settings:
            self.discovery_modes = discovery_config.mode_settings
        else:
            # Default fallback settings
            self.discovery_modes = {
                "bot_hunter": {
                    "blocks_back": 5000,
                    "min_trades": 15,
                    "min_pnl_threshold": 50
                },
                "active_whale": {
                    "blocks_back": 18000,
                    "min_trades": 8,
                    "min_pnl_threshold": 25
                },
                "lazy_whale": {
                    "blocks_back": 18500,
                    "min_trades": 6,
                    "min_pnl_threshold": 100
                },
                "quick_profit_whale": {
                    "blocks_back": 15000,
                    "min_trades": 5,
                    "min_pnl_threshold": 40,
                    "profit_window_hours": 72
                },
                "fast_mover_whale": {
                    "blocks_back": 17000,
                    "min_trades": 6,
                    "min_pnl_threshold": 35,
                    "min_roi": 0.15
                }
            }
    
    def update_whale_score(self, whale_address: str, pnl_eth: Decimal) -> WhaleStats:
        """Update whale performance after a mirrored trade settles"""
        whale_address = whale_address.lower()
        
        # Add to history
        self.whale_history[whale_address].append(pnl_eth)
        
        # Calculate statistics
        pnl_list = list(self.whale_history[whale_address])
        total_pnl = sum(pnl_list)
        win_rate = calculate_win_rate(pnl_list)
        volatility = calculate_volatility(pnl_list)
        sharpe_ratio = calculate_sharpe_ratio(pnl_list)
        
        # Calculate composite score
        # Higher PnL + higher win rate + lower volatility = better score
        if volatility > 0:
            score = (total_pnl * win_rate) / volatility
        else:
            score = total_pnl * win_rate
        
        # Update whale stats
        self.whale_scores[whale_address] = WhaleStats(
            address=whale_address,
            score=score,
            roi=total_pnl,
            trades=len(pnl_list),
            win_rate=win_rate,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            last_updated=time.time()
        )
        
        # Update database with new performance metrics
        self.db.update_whale_performance(
            whale_address,
            cumulative_pnl=float(total_pnl),
            score=float(score),
            win_rate=float(win_rate)
        )
        
        logger.debug(f"Updated whale {whale_address}: score={score:.4f}, roi={total_pnl:.4f}, win_rate={win_rate:.2%}")
        
        return self.whale_scores[whale_address]
    
    def should_follow_whale(self, whale_address: str, min_roi_pct: Decimal = Decimal("5"), 
                          min_profit_usd: Decimal = Decimal("500"), 
                          min_trades: int = 5) -> bool:
        """Determine if whale should be followed based on performance"""
        whale_address = whale_address.lower()
        stats = self.whale_scores.get(whale_address)
        
        if not stats:
            return True  # No info yet, default to follow
        
        # Check live performance
        if stats.roi < 0:
            logger.info(f"[CULL] Dropping whale {whale_address} - negative ROI")
            return False
        
        if stats.win_rate < Decimal("0.4"):  # Less than 40% win rate
            logger.info(f"[CULL] Dropping whale {whale_address} - low win rate: {stats.win_rate:.2%}")
            return False
        
        if stats.score < 0:
            logger.info(f"[CULL] Dropping whale {whale_address} - negative score")
            return False
        
        # Check Moralis bootstrap data if available
        if stats.moralis_roi_pct is not None:
            if stats.moralis_roi_pct < min_roi_pct:
                logger.info(f"[CULL] Dropping whale {whale_address} - low Moralis ROI: {stats.moralis_roi_pct}%")
                return False
            
            if stats.moralis_profit_usd is not None and stats.moralis_profit_usd < min_profit_usd:
                logger.info(f"[CULL] Dropping whale {whale_address} - low Moralis profit: ${stats.moralis_profit_usd}")
                return False
            
            if stats.moralis_trades is not None and stats.moralis_trades < min_trades:
                logger.info(f"[CULL] Dropping whale {whale_address} - insufficient trades: {stats.moralis_trades}")
                return False
        
        return True
    
    def get_whale_rankings(self, top_n: int = 10) -> List[Tuple[str, WhaleStats]]:
        """Get top N whales by score"""
        ranked = sorted(
            self.whale_scores.items(), 
            key=lambda kv: kv[1].score, 
            reverse=True
        )
        return ranked[:top_n]
    
    def fetch_moralis_data(self, whale_address: str) -> Optional[Dict]:
        """Fetch whale data from Moralis API with caching and rate limiting"""
        whale_address = whale_address.lower()
        
        # Check cache first
        cached_data = self.cache.get('moralis', whale_address)
        if cached_data:
            return cached_data
        
        # Check rate limiting
        if not self.rate_limiter.can_make_call("moralis_api"):
            logger.warning(f"Rate limited for Moralis API call for {whale_address}")
            return None
        
        try:
            headers = {"X-API-Key": self.moralis_api_key}
            url = f"https://deep-index.moralis.io/api/v2.2/wallets/{whale_address}/profitability/summary?chain=eth"
            
            response = requests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract relevant data from the summary endpoint
                moralis_data = {
                    "realized_usd": Decimal(str(data.get("total_realized_profit_usd", 0))),
                    "realized_pct": Decimal(str(data.get("total_realized_profit_percentage", 0))),
                    "total_trades": data.get("total_count_of_trades", 0),
                    "timestamp": time.time()
                }
                
                # Cache the result
                self.cache.set('moralis', whale_address, moralis_data)
                self.rate_limiter.record_call("moralis_api")
                
                logger.debug(f"Fetched Moralis data for {whale_address}: ${moralis_data['realized_usd']} profit, {moralis_data['realized_pct']}% ROI")
                
                return moralis_data
            else:
                logger.warning(f"Moralis API error for {whale_address}: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to fetch Moralis data for {whale_address}: {e}")
            return None
    
    def bootstrap_whale_from_moralis(self, whale_address: str, min_roi_pct: Decimal = Decimal("5"),
                                   min_profit_usd: Decimal = Decimal("500"), 
                                   min_trades: int = 5) -> bool:
        """Bootstrap whale data from Moralis and add to tracking if meets criteria"""
        whale_address = whale_address.lower()
        
        # Check if already tracked
        if whale_address in self.tracked_whales:
            return True
        
        # Check database cache first
        db_data = self.db.get_whale(whale_address)
        if db_data:
            _, roi_pct, usd, trades, _, last_refresh = db_data
            if time.time() - (last_refresh or 0) < 24 * 3600:  # 24 hours
                # Use cached data
                self.whale_scores[whale_address].moralis_roi_pct = Decimal(str(roi_pct))
                self.whale_scores[whale_address].moralis_profit_usd = Decimal(str(usd))
                self.whale_scores[whale_address].moralis_trades = trades
                self.tracked_whales.add(whale_address)
                logger.info(f"Loaded whale {whale_address} from DB cache")
                return True
        
        # Fetch fresh data from Moralis
        logger.info(f"Fetching Moralis data for {whale_address[:10]}...")
        moralis_data = self.fetch_moralis_data(whale_address)
        if not moralis_data:
            logger.warning(f"Failed to fetch Moralis data for {whale_address[:10]}...")
            return False
        
        # Check if meets criteria
        logger.info(f"Validating whale {whale_address}: {moralis_data['realized_pct']}% ROI, ${moralis_data['realized_usd']} profit, {moralis_data['total_trades']} trades")
        if (moralis_data["realized_pct"] < min_roi_pct or 
            moralis_data["realized_usd"] < min_profit_usd or 
            moralis_data["total_trades"] < min_trades):
            logger.info(f"Whale {whale_address} doesn't meet criteria: {moralis_data['realized_pct']}% ROI, ${moralis_data['realized_usd']} profit, {moralis_data['total_trades']} trades")
            return False
        
        # Add to tracking
        self.whale_scores[whale_address].moralis_roi_pct = moralis_data["realized_pct"]
        self.whale_scores[whale_address].moralis_profit_usd = moralis_data["realized_usd"]
        self.whale_scores[whale_address].moralis_trades = moralis_data["total_trades"]
        self.tracked_whales.add(whale_address)
        
        # Calculate additional metrics for database storage
        # Get current whale stats (will be default/empty for new whales)
        whale_stats = self.get_whale_stats(whale_address)
        
        # Calculate more meaningful initial values based on Moralis data
        moralis_roi_pct = Decimal(str(moralis_data["realized_pct"]))
        moralis_profit_usd = Decimal(str(moralis_data["realized_usd"]))
        moralis_trades = moralis_data["total_trades"]
        
        # Estimate initial allocation size based on Moralis ROI and capital
        base_capital = Decimal("1000")  # Default base capital for calculation
        # Scale allocation based on Moralis performance (better whales get more allocation)
        roi_multiplier = min(max(moralis_roi_pct / Decimal("100"), Decimal("0.5")), Decimal("2.0"))
        initial_allocation = float(base_capital * Decimal("0.1") * roi_multiplier)
        
        # Initial risk multiplier based on Moralis performance
        if moralis_roi_pct > 50:
            initial_risk = 1.5  # High performing whale
        elif moralis_roi_pct > 20:
            initial_risk = 1.2  # Good performing whale
        elif moralis_roi_pct > 0:
            initial_risk = 1.0  # Positive whale
        else:
            initial_risk = 0.8  # Poor performing whale
        
        # Estimate initial score based on Moralis data
        # Simple heuristic: ROI% * sqrt(trades) / 10
        if moralis_trades > 0:
            estimated_score = float(moralis_roi_pct * Decimal(str(moralis_trades ** 0.5)) / Decimal("10"))
        else:
            estimated_score = 0.0
        
        # Estimate win rate based on ROI (rough approximation)
        if moralis_roi_pct > 30:
            estimated_win_rate = 0.7  # 70% win rate for high ROI
        elif moralis_roi_pct > 10:
            estimated_win_rate = 0.6  # 60% win rate
        elif moralis_roi_pct > 0:
            estimated_win_rate = 0.55  # 55% win rate
        else:
            estimated_win_rate = 0.4  # 40% win rate for losing whales
        
        # Convert Moralis USD profit to rough ETH estimate (assuming $2000/ETH)
        estimated_pnl_eth = float(moralis_profit_usd / Decimal("2000"))
        
        # Save to database with meaningful initial values
        logger.info(f"Saving whale {whale_address} to database...")
        db_start_time = time.time()
        self.db.save_whale(
            whale_address,
            float(moralis_data["realized_pct"]),
            float(moralis_data["realized_usd"]),
            moralis_data["total_trades"],
            cumulative_pnl=estimated_pnl_eth,  # Estimated ETH PnL from USD
            risk_multiplier=initial_risk,
            allocation_size=initial_allocation,
            score=estimated_score,
            win_rate=estimated_win_rate
        )
        db_elapsed = time.time() - db_start_time
        logger.info(f"Database save completed in {db_elapsed:.1f}s for {whale_address}")
        
        logger.info(f"Initialized whale {whale_address} metrics: risk={initial_risk:.2f}, allocation={initial_allocation:.2f} ETH, score={estimated_score:.2f}")        
        
        # Note: Token data fetching is now handled separately to avoid blocking the main discovery process
        # Use --fetch-tokens command or the test_adaptive_discovery.py script to fetch token data
        
        logger.info(f"Added whale {whale_address} to tracking: {moralis_data['realized_pct']}% ROI, ${moralis_data['realized_usd']} profit")
        logger.info(f"bootstrap_whale_from_moralis completed for {whale_address}")
        return True
    
    def discover_whales_from_blocks(self, w3, mode: str = "active_whale", 
                                  simulate: bool = False) -> List[str]:
        """Discover whales by scanning recent blocks"""
        if mode not in self.discovery_modes:
            logger.warning(f"Unknown discovery mode: {mode}")
            mode = "active_whale"
        
        params = self.discovery_modes[mode]
        blocks_back = params["blocks_back"]
        min_trades = params["min_trades"]
        min_pnl_thr = params["min_pnl_threshold"]
        
        logger.info(f"Discovering whales with mode {mode}: {blocks_back} blocks back, min {min_trades} trades, min {min_pnl_thr} ETH")
        
        start_block = max(0, w3.eth.block_number - blocks_back)
        end_block = w3.eth.block_number
        
        # Track candidate statistics
        candidate_stats = defaultdict(lambda: {"profit": Decimal(0), "trades": 0})
        
        # Scan blocks for whale candidates with progress logging
        total_blocks = end_block - start_block + 1
        logger.info(f"Scanning {total_blocks} blocks from {start_block} to {end_block}")
        
        for i, block_num in enumerate(range(start_block, end_block + 1)):
            try:
                # Progress logging every 500 blocks
                if i % 500 == 0 and i > 0:
                    progress = (i / total_blocks) * 100
                    logger.info(f"Mode {mode}: {progress:.1f}% complete ({i}/{total_blocks} blocks)")
                
                block = w3.eth.get_block(block_num, full_transactions=True)
                
                for tx in block.transactions:
                    # Check if transaction is to Uniswap
                    if tx.to and tx.to.lower() in [
                        "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D".lower(),  # Uniswap V2
                        "0xE592427A0AEce92De3Edee1F18E0157C05861564".lower()   # Uniswap V3
                    ]:
                        actor = tx["from"].lower()
                        candidate_stats[actor]["trades"] += 1
                        candidate_stats[actor]["profit"] += Decimal(tx.value) / (10**18)
                        
            except Exception as e:
                logger.debug(f"Failed to process block {block_num}: {e}")
                continue
        
        logger.info(f"Completed scanning {total_blocks} blocks")
        
        # Filter candidates
        new_whales = []
        for addr, stats in candidate_stats.items():
            if (stats["trades"] >= min_trades and 
                stats["profit"] >= min_pnl_thr):
                new_whales.append(addr)
        
        logger.info(f"Found {len(new_whales)} whale candidates from {len(candidate_stats)} addresses")
        
        if simulate:
            return new_whales
        
        # Bootstrap candidates with Moralis data
        added_whales = []
        for whale in new_whales:
            if self.bootstrap_whale_from_moralis(whale):
                added_whales.append(whale)
        
        logger.info(f"Successfully added {len(added_whales)} whales to tracking")
        return added_whales
    
    def discover_whales_adaptive(self, w3, adaptive_config: Dict, simulate: bool = False) -> List[str]:
        """Run adaptive whale discovery using percentile-based thresholds"""
        try:
            # Initialize adaptive components if needed
            if self.market_analyzer is None:
                self.market_analyzer = MarketConditionAnalyzer(w3, self.cache)
            
            if self.adaptive_engine is None:
                self.adaptive_engine = AdaptiveDiscoveryEngine(w3, self.market_analyzer)
            
            # Get adaptive configuration
            percentile_config = getattr(adaptive_config, "percentile_mode", {}) or {}
            
            if not percentile_config.get("enabled", False):
                logger.info("Adaptive percentile discovery is disabled")
                return []
            
            activity_percentile = percentile_config.get("activity_percentile", 5.0)
            profit_percentile = percentile_config.get("profit_percentile", 25.0)
            blocks_back = percentile_config.get("blocks_back", 10000)
            
            logger.info(f"Running adaptive discovery: top {activity_percentile}% activity, "
                       f"top {profit_percentile}% profit over {blocks_back} blocks (sampling every 5th block)")
            
            # Run adaptive discovery
            result = self.adaptive_engine.discover_whales_percentile(
                activity_percentile=activity_percentile,
                profit_percentile=profit_percentile,
                blocks_back=blocks_back
            )
            
            candidates = result.get("candidates", [])
            
            if simulate:
                return candidates
            
            # Validate with Moralis
            validated_whales = []
            logger.info(f"Starting Moralis validation for {len(candidates)} adaptive candidates...")
            
            candidates_to_validate = candidates
            
            for i, whale_address in enumerate(candidates_to_validate):
                try:
                    start_time = time.time()
                    logger.info(f"Validating candidate {i+1}/{len(candidates_to_validate)}: {whale_address[:10]}...")
                    
                    if self.bootstrap_whale_from_moralis(whale_address):
                        validated_whales.append(whale_address)
                        elapsed = time.time() - start_time
                        logger.info(f"✅ Candidate {whale_address[:10]}... validated and added ({elapsed:.1f}s)")
                        # Track acceptance
                        self.moralis_feedback.track_moralis_acceptance(
                            address=whale_address,
                            roi_pct=0.0,  # Will be updated with actual values
                            profit_usd=0.0,
                            trades=0,
                            discovery_mode="adaptive_percentile"
                        )
                    else:
                        elapsed = time.time() - start_time
                        logger.info(f"❌ Candidate {whale_address[:10]}... rejected by Moralis ({elapsed:.1f}s)")
                        # Track rejection (reason will be determined in bootstrap_whale_from_moralis)
                        self.moralis_feedback.track_moralis_rejection(
                            address=whale_address,
                            reason="failed_validation",
                            discovery_mode="adaptive_percentile"
                        )
                    
                    # Add small delay to prevent overwhelming the API
                    time.sleep(0.5)
                    
                except Exception as e:
                    elapsed = time.time() - start_time
                    logger.warning(f"Failed to validate adaptive candidate {whale_address[:10]}...: {e} ({elapsed:.1f}s)")
                    self.moralis_feedback.track_moralis_rejection(
                        address=whale_address,
                        reason="api_error",
                        discovery_mode="adaptive_percentile"
                    )
            
            logger.info(f"Adaptive discovery: {len(validated_whales)}/{len(candidates)} whales validated")
            return validated_whales
            
        except Exception as e:
            logger.error(f"Adaptive discovery failed: {e}")
            return []
    
    def get_adaptive_suggestions(self, mode: str, current_thresholds: Dict) -> Dict:
        """Get adjustment suggestions based on Moralis feedback"""
        return self.moralis_feedback.get_adjustment_suggestions(mode, current_thresholds)
    
    def get_moralis_feedback_summary(self) -> Dict:
        """Get summary of Moralis feedback for dashboard"""
        return self.moralis_feedback.get_rejection_summary()
    
    def simulate_whale_trades(self, whale_address: str, num_trades: int = 5) -> None:
        """Simulate some trade history for a whale (useful for DRY_RUN mode testing)"""
        import random
        whale_address = whale_address.lower()
        
        logger.info(f"Simulating {num_trades} trades for whale {whale_address}")
        
        # Common tokens to simulate trading
        tokens = ["ETH", "WBTC", "USDC", "LINK", "UNI", "AAVE", "PEPE", "SHIB", "DOGE"]
        
        for i in range(num_trades):
            # Generate random PnL based on whale's Moralis performance
            whale_stats = self.whale_scores.get(whale_address)
            if whale_stats and whale_stats.moralis_roi_pct:
                # Base PnL on historical performance with some randomness
                base_performance = float(whale_stats.moralis_roi_pct) / 100
                random_factor = random.uniform(0.5, 1.5)
                simulated_pnl = base_performance * random_factor * random.uniform(0.1, 2.0)
            else:
                # Random PnL between -1 and +2 ETH
                simulated_pnl = random.uniform(-1.0, 2.0)
            
            # Pick a random token for this trade
            token = random.choice(tokens)
            
            # Update token-level PnL (this will also recalculate Score v2.0)
            self.update_whale_token_trade(whale_address, token, simulated_pnl)
            
            # Also update the traditional whale score for backward compatibility
            self.update_whale_score(whale_address, Decimal(str(simulated_pnl)))
            
        logger.info(f"Completed simulation for whale {whale_address}")
    
    def get_whale_stats(self, whale_address: str) -> Optional[WhaleStats]:
        """Get current stats for a whale"""
        return self.whale_scores.get(whale_address.lower())
    
    def get_all_tracked_whales(self) -> List[str]:
        """Get list of all tracked whale addresses"""
        return list(self.tracked_whales)
    
    def remove_whale(self, whale_address: str) -> bool:
        """Remove whale from tracking"""
        whale_address = whale_address.lower()
        if whale_address in self.tracked_whales:
            self.tracked_whales.remove(whale_address)
            logger.info(f"Removed whale {whale_address} from tracking")
            return True
        return False
    
    def refresh_all_whale_metrics(self, simulate_trades: bool = False) -> None:
        """Refresh metrics for all tracked whales (useful for DRY_RUN mode)"""
        logger.info("Refreshing metrics for all tracked whales")
        
        for whale_address in list(self.tracked_whales):
            try:
                # Get existing whale data from database
                whale_data = self.db.get_whale(whale_address)
                if not whale_data:
                    continue
                
                # whale_data columns: address, moralis_roi_pct, roi_usd, trades, cumulative_pnl, 
                # risk_multiplier, allocation_size, score, win_rate, bootstrap_time, last_refresh
                moralis_roi_pct = whale_data[1] if whale_data[1] is not None else 0
                moralis_profit_usd = whale_data[2] if whale_data[2] is not None else 0
                moralis_trades = whale_data[3] if whale_data[3] is not None else 0
                
                # If the performance fields are still 0/default, refresh them
                if (whale_data[4] == 0 and whale_data[7] == 0):  # cumulative_pnl and score are 0
                    logger.info(f"Refreshing metrics for whale {whale_address}")
                    
                    # Recalculate initial values (same logic as bootstrap)
                    moralis_roi_decimal = Decimal(str(moralis_roi_pct))
                    moralis_profit_decimal = Decimal(str(moralis_profit_usd))
                    
                    # Calculate improved metrics
                    base_capital = Decimal("1000")
                    roi_multiplier = min(max(moralis_roi_decimal / Decimal("100"), Decimal("0.5")), Decimal("2.0"))
                    new_allocation = float(base_capital * Decimal("0.1") * roi_multiplier)
                    
                    if moralis_roi_pct > 50:
                        new_risk = 1.5
                    elif moralis_roi_pct > 20:
                        new_risk = 1.2
                    elif moralis_roi_pct > 0:
                        new_risk = 1.0
                    else:
                        new_risk = 0.8
                    
                    if moralis_trades > 0:
                        new_score = float(moralis_roi_decimal * Decimal(str(moralis_trades ** 0.5)) / Decimal("10"))
                    else:
                        new_score = 0.0
                    
                    if moralis_roi_pct > 30:
                        new_win_rate = 0.7
                    elif moralis_roi_pct > 10:
                        new_win_rate = 0.6
                    elif moralis_roi_pct > 0:
                        new_win_rate = 0.55
                    else:
                        new_win_rate = 0.4
                    
                    new_pnl_eth = float(moralis_profit_decimal / Decimal("2000"))
                    
                    # Update database with calculated values
                    self.db.update_whale_performance(
                        whale_address,
                        cumulative_pnl=new_pnl_eth,
                        risk_multiplier=new_risk,
                        allocation_size=new_allocation,
                        score=new_score,
                        win_rate=new_win_rate
                    )
                    
                    # Optionally simulate some trade history
                    if simulate_trades:
                        self.simulate_whale_trades(whale_address, num_trades=3)
                        
            except Exception as e:
                logger.error(f"Error refreshing whale {whale_address}: {e}")
        
        logger.info("Completed refreshing whale metrics")
    
    def calculate_diversity_factor(self, whale_address: str) -> float:
        """Calculate diversity factor based on token concentration (0=concentrated, 1=diverse)"""
        whale_address = whale_address.lower()
        
        # Get token breakdown from database
        token_breakdown = self.db.get_whale_token_breakdown(whale_address)
        
        if not token_breakdown or len(token_breakdown) < 2:
            # Only 1 token or no data = maximum concentration penalty
            return 0.1
        
        # Build pnl_by_token dict
        pnl_by_token = {}
        total_pnl = 0
        
        for token_symbol, token_address, cumulative_pnl, trade_count, last_updated in token_breakdown:
            # Skip the PROCESSED marker token
            if token_symbol == "PROCESSED":
                continue
            try:
                # Handle various data types and invalid values
                if cumulative_pnl is None or cumulative_pnl == '':
                    pnl_value = 0.0
                elif isinstance(cumulative_pnl, (int, float)):
                    pnl_value = float(cumulative_pnl)
                elif isinstance(cumulative_pnl, str):
                    # Check for obviously invalid strings
                    if cumulative_pnl.strip() in ['', 'None', 'null', 'NULL']:
                        pnl_value = 0.0
                    else:
                        # Try to convert string to float
                        pnl_value = float(cumulative_pnl)
                else:
                    logger.warning(f"Unexpected cumulative_pnl type for {token_symbol}: {type(cumulative_pnl)} = {cumulative_pnl}")
                    pnl_value = 0.0
                
                # Check for reasonable bounds to prevent overflow
                if abs(pnl_value) > 1e12:  # Cap at 1 trillion
                    logger.warning(f"Extremely large PnL value for {token_symbol}: {pnl_value}, capping to 0")
                    pnl_value = 0.0
                
                if pnl_value > 0:  # Only count profitable tokens for concentration calc
                    pnl_by_token[token_symbol] = pnl_value
                    total_pnl += pnl_value
            except (ValueError, TypeError, decimal.ConversionSyntax) as e:
                # Skip tokens with invalid PnL data
                logger.warning(f"Skipping token {token_symbol} due to invalid PnL data: {cumulative_pnl} (error: {e})")
                continue
        
        if total_pnl <= 0 or len(pnl_by_token) == 0:
            return 0.1  # No profitable tokens = max penalty
        
        # Calculate Herfindahl-Hirschman Index (HHI)
        concentration = 0
        for token_pnl in pnl_by_token.values():
            weight = token_pnl / total_pnl
            concentration += weight ** 2
        
        # Diversity factor = 1 - concentration
        diversity_factor = 1 - concentration
        
        # Cap at 0.6 as "solidly diverse" as mentioned
        diversity_factor = min(diversity_factor, 0.6)
        
        logger.debug(f"Whale {whale_address} diversity: {len(pnl_by_token)} tokens, "
                    f"concentration={concentration:.3f}, diversity_factor={diversity_factor:.3f}")
        
        return diversity_factor
    
    def calculate_score_v2(self, whale_address: str) -> float:
        """Calculate Score Formula 2.0 with diversity penalty"""
        whale_address = whale_address.lower()
        
        try:
            # Get current whale stats
            whale_stats = self.get_whale_stats(whale_address)
            if not whale_stats:
                logger.warning(f"No whale stats found for {whale_address}")
                return 0.0
            
            # Get whale data from database for additional metrics
            whale_data = self.db.get_whale(whale_address)
            if not whale_data:
                logger.warning(f"No whale data found for {whale_address}")
                return 0.0
            
            logger.debug(f"Processing whale {whale_address}: whale_data={whale_data}")
            logger.debug(f"Whale data types: {[type(x) for x in whale_data]}")
            logger.debug(f"Whale data values: {whale_data}")
            logger.debug(f"Whale stats for {whale_address}: score={whale_stats.score}, roi={whale_stats.roi}, trades={whale_stats.trades}, win_rate={whale_stats.win_rate}")
            logger.debug(f"Whale stats types: score={type(whale_stats.score)}, roi={type(whale_stats.roi)}, trades={type(whale_stats.trades)}, win_rate={type(whale_stats.win_rate)}")
            
        except Exception as e:
            logger.error(f"Error getting whale data for {whale_address}: {e}")
            return 0.0
        
        # Extract metrics with safe conversion
        # whale_data[1] = moralis_roi_pct (correct)
        try:
            if whale_data[1] is None or whale_data[1] == '':
                roi_pct = 0.0
            elif isinstance(whale_data[1], (int, float)):
                roi_pct = float(whale_data[1])
            else:
                roi_pct = float(str(whale_data[1]))
        except (ValueError, TypeError, decimal.ConversionSyntax):
            logger.warning(f"Invalid ROI data for {whale_address}: {whale_data[1]}")
            roi_pct = 0.0
            
        try:
            if whale_stats.win_rate is None or whale_stats.win_rate == '':
                win_rate = 0.0
            elif isinstance(whale_stats.win_rate, Decimal):
                win_rate = float(whale_stats.win_rate)
            elif isinstance(whale_stats.win_rate, (int, float)):
                win_rate = float(whale_stats.win_rate)
            else:
                win_rate = float(str(whale_stats.win_rate))
        except (ValueError, TypeError, decimal.ConversionSyntax, decimal.InvalidOperation) as e:
            logger.warning(f"Invalid win_rate data for {whale_address}: {whale_stats.win_rate} (type: {type(whale_stats.win_rate)}, error: {e})")
            win_rate = 0.0
            
        try:
            if whale_stats.trades is None or whale_stats.trades == '':
                trades = 0
            elif isinstance(whale_stats.trades, (int, float)):
                trades = int(whale_stats.trades)
            elif isinstance(whale_stats.trades, Decimal):
                trades = int(whale_stats.trades)
            else:
                trades = int(float(str(whale_stats.trades)))
        except (ValueError, TypeError, decimal.ConversionSyntax, decimal.InvalidOperation) as e:
            logger.warning(f"Invalid trades data for {whale_address}: {whale_stats.trades} (type: {type(whale_stats.trades)}, error: {e})")
            trades = 0
            
        try:
            if whale_stats.roi is None or whale_stats.roi == '':
                cumulative_pnl = 0.0
            elif isinstance(whale_stats.roi, Decimal):
                cumulative_pnl = float(whale_stats.roi)
            elif isinstance(whale_stats.roi, (int, float)):
                cumulative_pnl = float(whale_stats.roi)
            else:
                cumulative_pnl = float(str(whale_stats.roi))
        except (ValueError, TypeError, decimal.ConversionSyntax, decimal.InvalidOperation) as e:
            logger.warning(f"Invalid ROI data for {whale_address}: {whale_stats.roi} (type: {type(whale_stats.roi)}, error: {e})")
            cumulative_pnl = 0.0
        
        # Calculate base score using the new formula
        base_score = (
            roi_pct * 0.35 +
            win_rate * 100 * 0.25 +  # Convert win_rate to percentage
            math.log(trades + 1) * 0.15 +
            cumulative_pnl * 0.15
        )
        
        # Calculate diversity factor
        try:
            diversity_factor = self.calculate_diversity_factor(whale_address)
            logger.debug(f"Diversity factor calculated for {whale_address}: {diversity_factor}")
        except Exception as e:
            logger.error(f"Error calculating diversity factor for {whale_address}: {e}")
            diversity_factor = 0.1  # Default to minimum diversity
        
        # Check minimum requirements for valid whale
        MIN_TRADES = 20
        MIN_TOKENS = 5
        
        # Get token count for this whale
        token_breakdown = self.db.get_whale_token_breakdown(whale_address)
        token_count = len([t for t in token_breakdown if t[0] != "PROCESSED"])  # Exclude PROCESSED marker
        
        # Check if whale meets minimum requirements
        if trades < MIN_TRADES or token_count < MIN_TOKENS:
            reason = f"< {MIN_TRADES} trades ({trades}) or < {MIN_TOKENS} tokens ({token_count})"
            logger.info(f"Whale {whale_address} does not meet minimum requirements: {reason}")
            
            # Mark as discarded
            self.db.mark_whale_discarded(whale_address, reason)
            return 0.0  # Return 0 score for discarded whales
        
        # Apply diversity adjustment
        try:
            adjusted_score = base_score * (0.1 + 0.9 * diversity_factor)
        except Exception as e:
            logger.error(f"Error calculating adjusted score for {whale_address}: {e}")
            adjusted_score = base_score
        
        logger.info(f"Whale {whale_address} Score v2.0: base={base_score:.2f}, "
                   f"diversity={diversity_factor:.3f}, adjusted={adjusted_score:.2f}, "
                   f"trades={trades}, tokens={token_count}")
        
        return adjusted_score
    
    def update_whale_token_trade(self, whale_address: str, token_symbol: str, 
                                pnl_change: float, token_address: str = None) -> None:
        """Update token-level PnL and recalculate whale score"""
        whale_address = whale_address.lower()
        
        # Update token-level PnL in database
        self.db.update_whale_token_pnl(whale_address, token_symbol, pnl_change, token_address)
        
        # Recalculate Score v2.0
        new_score = self.calculate_score_v2(whale_address)
        
        # Update whale's overall score in database
        self.db.update_whale_performance(whale_address, score=new_score)
        
        # Update in-memory whale stats
        if whale_address in self.whale_scores:
            self.whale_scores[whale_address].score = Decimal(str(new_score))
        
        logger.info(f"Updated whale {whale_address} token {token_symbol}: PnL {pnl_change:+.4f}, new score: {new_score:.2f}")
    
    def fetch_token_data_from_moralis(self, whale_address: str) -> None:
        """Fetch real token-level data from Moralis for existing whales"""
        whale_address = whale_address.lower()
        
        # Check if whale already has token data (including "PROCESSED" marker)
        existing_tokens = self.db.get_whale_token_breakdown(whale_address)
        if existing_tokens:
            # Filter out the PROCESSED marker for counting
            real_tokens = [t for t in existing_tokens if t[0] != "PROCESSED"]
            if real_tokens or any(t[0] == "PROCESSED" for t in existing_tokens):
                logger.debug(f"Whale {whale_address} already processed ({len(real_tokens)} real tokens)")
                return
        
        logger.info(f"Fetching token-level data from Moralis for whale {whale_address}")
        
        try:
            # Check rate limiting
            if not self.rate_limiter.can_make_call("moralis_api"):
                logger.warning(f"Rate limited for Moralis API call for {whale_address}")
                return
            
            # Use the full profitability endpoint for token data
            profitability_url = f"https://deep-index.moralis.io/api/v2.2/wallets/{whale_address}/profitability?chain=eth"
            
            headers = {
                "X-API-Key": self.moralis_api_key
            }
            
            # Call the full profitability endpoint to get the token breakdown
            logger.info(f"Calling Moralis full profitability API for {whale_address}")
            api_start_time = time.time()
            response = requests.get(profitability_url, headers=headers, timeout=30)
            api_elapsed = time.time() - api_start_time
            logger.info(f"Moralis API call completed in {api_elapsed:.1f}s for {whale_address}")
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"Full profitability response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                
                # The full profitability endpoint returns: {"result": [array of token objects]}
                if "result" in data and isinstance(data["result"], list):
                    # Process the token breakdown from the result array
                    logger.info(f"Processing {len(data['result'])} tokens for {whale_address}")
                    processing_start_time = time.time()
                    if self._process_profitability_breakdown(whale_address, data):
                        processing_elapsed = time.time() - processing_start_time
                        logger.info(f"Token processing completed in {processing_elapsed:.1f}s for {whale_address}")
                        return
                else:
                    logger.warning(f"Unexpected profitability structure for {whale_address}: {list(data.keys())}")
                
                logger.warning(f"Could not process profitability data for {whale_address}")
            else:
                logger.warning(f"Profitability API failed ({response.status_code}) for {whale_address}: {response.text}")
            
            # Fallback to token transfers method (commented out for debugging)
            # 
            # token_transfers_url = f"https://deep-index.moralis.io/api/v2.2/{whale_address}/erc20/transfers"
            # params = {
            #     "chain": "eth", 
            #     "from_date": "2024-08-01",  # Adjust based on your needs
            #     "limit": 50  # Conservative limit to avoid API errors
            # }
            # 
            # logger.info(f"Calling Moralis token transfers API for {whale_address}")
            # response = requests.get(token_transfers_url, headers=headers, params=params, timeout=30)
            
            # Skip fallback processing for debugging
            logger.warning(f"Could not process token data for {whale_address} - profitability endpoint failed")
            return
            
        except Exception as e:
            logger.error(f"Error fetching token data from Moralis for {whale_address}: {e}")
            return
    
    def _process_profitability_breakdown(self, whale_address: str, data) -> bool:
        """Process the profitability breakdown API response"""
        try:
            logger.info(f"Profitability breakdown response: {len(data.get('result', []))} tokens")
            
            # The breakdown endpoint returns: {"result": [array of token objects]}
            tokens = data.get("result", [])
            if not tokens:
                logger.warning("No tokens found in profitability breakdown response")
                return False
            
            meaningful_tokens = 0
            
            for token_data in tokens:
                try:
                    # Extract data from the breakdown response
                    token_symbol = token_data.get("symbol", "UNKNOWN")
                    token_address = token_data.get("token_address", "")
                    realized_profit_usd = float(token_data.get("realized_profit_usd", 0))
                    trade_count = int(token_data.get("count_of_trades", 0))
                    
                    # Convert USD to ETH (rough approximation - could be improved with price feeds)
                    # Using ~$2000/ETH as rough conversion
                    realized_profit_eth = realized_profit_usd / 2000.0
                    
                    # Store if meaningful activity (realized profit or multiple trades)
                    if abs(realized_profit_eth) > 0.001 or trade_count >= 2:  # $2+ profit or 2+ trades
                        db_start_time = time.time()
                        self.db.update_whale_token_pnl(whale_address, token_symbol, realized_profit_eth, token_address, trade_count)
                        db_elapsed = time.time() - db_start_time
                        meaningful_tokens += 1
                        logger.debug(f"Stored {token_symbol}: ${realized_profit_usd:.2f} ({realized_profit_eth:.6f} ETH), {trade_count} trades (DB: {db_elapsed:.3f}s)")
                    else:
                        logger.debug(f"Skipped {token_symbol}: too small profit (${realized_profit_usd:.2f})")
                        
                except Exception as e:
                    logger.error(f"Error processing token data: {e}")
                    continue
            
            if meaningful_tokens == 0:
                # Add a marker to indicate this whale has been processed (no meaningful tokens)
                self.db.update_whale_token_pnl(whale_address, "PROCESSED", 0.0, "")
                logger.info(f"No meaningful token activity found for whale {whale_address}")
            else:
                logger.info(f"Stored {meaningful_tokens} tokens from profitability data for whale {whale_address}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing profitability breakdown: {e}")
            return False
    
    def _store_profitability_token(self, whale_address: str, token_key: str, token_info) -> bool:
        """Store a single token's profitability data"""
        try:
            # Extract token information
            if isinstance(token_info, dict):
                # Extract common fields (structure to be determined from actual API response)
                token_symbol = token_info.get("symbol", token_info.get("token_symbol", token_key if token_key and not token_key.startswith('0x') else "UNKNOWN"))
                token_address = token_info.get("address", token_info.get("token_address", token_key if token_key and token_key.startswith('0x') else ""))
                
                # Look for PnL/profit fields - try various common field names
                pnl = None
                for pnl_field in ["pnl", "profit", "total_pnl", "realized_pnl", "unrealized_pnl", "profit_loss", "net_profit", "total_profit"]:
                    if pnl_field in token_info:
                        try:
                            pnl = float(token_info[pnl_field])
                            break
                        except (ValueError, TypeError):
                            continue
                
                # Look for trade count fields
                trade_count = 1  # Default
                for count_field in ["trades", "trade_count", "count", "transactions", "tx_count"]:
                    if count_field in token_info:
                        try:
                            trade_count = int(token_info[count_field])
                            break
                        except (ValueError, TypeError):
                            continue
                
                # Convert to ETH if needed (assuming USD values)
                if pnl is not None:
                    # Rough conversion - could be improved with price feeds
                    pnl_eth = pnl / 2000.0  # Assuming ~$2000/ETH
                    
                    # Store the token data
                    self.db.update_whale_token_pnl(whale_address, token_symbol, pnl_eth, token_address, trade_count)
                    logger.debug(f"Stored {token_symbol}: {pnl_eth:.6f} ETH, {trade_count} trades")
                    return True
                else:
                    logger.debug(f"No PnL data found for token {token_symbol}")
                    return False
            else:
                logger.warning(f"Unexpected token_info type: {type(token_info)}")
                return False
                
        except Exception as e:
            logger.error(f"Error storing profitability token data: {e}")
            return False
            
            logger.info(f"Moralis returned {len(transfers)} transfers for whale {whale_address}")
            
            if not transfers:
                logger.info(f"No token transfers found for whale {whale_address}")
                return
            
            # Analyze transfers to build token PnL estimates
            token_activity = defaultdict(lambda: {"in_value": 0, "out_value": 0, "trades": 0, "address": ""})
            
            processed_transfers = 0
            skipped_dust = 0
            skipped_unrelated = 0
            
            for transfer in transfers:
                try:
                    token_symbol = transfer.get("token_symbol", "UNKNOWN")
                    token_address = transfer.get("token_address", "")
                    from_address = transfer.get("from_address", "").lower()
                    to_address = transfer.get("to_address", "").lower()
                    
                    # Try multiple value fields - Moralis API might use different field names
                    value = None
                    for value_field in ["value_formatted", "value", "amount"]:
                        raw_value = transfer.get(value_field)
                        if raw_value is not None:
                            try:
                                value = float(raw_value)
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    if value is None:
                        value = 0.0
                    
                    # Debug first few transfers to understand the data format
                    if processed_transfers + skipped_dust < 5:
                        logger.info(f"Transfer sample: {token_symbol} from {from_address[:10]}... to {to_address[:10]}... value: {value}")
                        logger.info(f"  Whale address: {whale_address[:10]}...")
                        if processed_transfers + skipped_dust == 0:
                            logger.debug(f"  Raw transfer data: {transfer}")
                    
                    # More lenient dust filter - tokens might have different decimal places
                    if value < 0.000001:  # Much lower threshold
                        skipped_dust += 1
                        continue
                    
                    # Track inflows and outflows
                    if from_address == whale_address:
                        # Whale selling/sending tokens
                        token_activity[token_symbol]["out_value"] += value
                        token_activity[token_symbol]["trades"] += 1
                        token_activity[token_symbol]["address"] = token_address
                        processed_transfers += 1
                    elif to_address == whale_address:
                        # Whale buying/receiving tokens
                        token_activity[token_symbol]["in_value"] += value
                        token_activity[token_symbol]["trades"] += 1
                        token_activity[token_symbol]["address"] = token_address
                        processed_transfers += 1
                    else:
                        skipped_unrelated += 1
                        
                except Exception as e:
                    logger.debug(f"Error processing transfer: {e}")
                    continue
            
            logger.info(f"Processed {processed_transfers} transfers, skipped {skipped_dust} dust, {skipped_unrelated} unrelated")
            
            # Convert activity to PnL estimates and store in database
            tokens_added = 0
            total_estimated_pnl = 0
            
            for token_symbol, activity in token_activity.items():
                if activity["trades"] == 0:
                    continue
                
                # Simple PnL estimation: assume whale is net positive on tokens they're actively trading
                # This is a rough heuristic - real PnL would need price data at trade time
                net_volume = abs(activity["in_value"] - activity["out_value"])
                trade_count = activity["trades"]
                
                # Estimate PnL as a percentage of volume (crude approximation)
                # Active traders might make 5-20% on their trades
                estimated_pnl_pct = min(0.15, max(0.01, trade_count / 100))  # 1-15% based on activity
                estimated_pnl = net_volume * estimated_pnl_pct
                
                logger.debug(f"Token {token_symbol}: volume={net_volume:.4f}, trades={trade_count}, est_pnl={estimated_pnl:.6f}")
                
                if estimated_pnl > 0.0001:  # Lower threshold to catch more activity
                    # Convert to ETH equivalent (rough approximation)
                    if token_symbol in ["USDC", "USDT", "DAI"]:
                        estimated_pnl_eth = estimated_pnl / 2000  # USD to ETH
                    elif token_symbol == "WBTC":
                        estimated_pnl_eth = estimated_pnl * 15    # BTC to ETH (rough ratio)
                    elif token_symbol == "ETH" or token_symbol == "WETH":
                        estimated_pnl_eth = estimated_pnl
                    else:
                        estimated_pnl_eth = estimated_pnl * 0.001  # Alt coins to ETH (very rough)
                    
                    # Store in database
                    token_address = activity.get('address', '')
                    self.db.update_whale_token_pnl(whale_address, token_symbol, estimated_pnl_eth, token_address)
                    
                    tokens_added += 1
                    total_estimated_pnl += estimated_pnl_eth
                    
                    logger.debug(f"  {token_symbol}: {estimated_pnl_eth:.6f} ETH PnL ({trade_count} trades)")
                else:
                    logger.debug(f"  {token_symbol}: Skipped - PnL too small ({estimated_pnl:.6f})")
            
            if tokens_added > 0:
                logger.info(f"Fetched token data for whale {whale_address}: "
                           f"{tokens_added} tokens, {total_estimated_pnl:.4f} ETH total estimated PnL")
            else:
                logger.info(f"No meaningful token activity found for whale {whale_address}")
                # Even if no tokens found, mark as processed by adding a dummy record
                self.db.update_whale_token_pnl(whale_address, "PROCESSED", 0.0, "0x0")
            
        except Exception as e:
            logger.error(f"Error fetching token data from Moralis for {whale_address}: {e}")
            return
    
    def _process_profitability_breakdown(self, whale_address: str, data) -> bool:
        """Process the profitability breakdown API response"""
        try:
            logger.info(f"Profitability breakdown response: {len(data.get('result', []))} tokens")
            
            # The breakdown endpoint returns: {"result": [array of token objects]}
            tokens = data.get("result", [])
            if not tokens:
                logger.warning("No tokens found in profitability breakdown response")
                return False
            
            meaningful_tokens = 0
            
            for token_data in tokens:
                try:
                    # Extract data from the breakdown response
                    token_symbol = token_data.get("symbol", "UNKNOWN")
                    token_address = token_data.get("token_address", "")
                    realized_profit_usd = float(token_data.get("realized_profit_usd", 0))
                    trade_count = int(token_data.get("count_of_trades", 0))
                    
                    # Convert USD to ETH (rough approximation - could be improved with price feeds)
                    # Using ~$2000/ETH as rough conversion
                    realized_profit_eth = realized_profit_usd / 2000.0
                    
                    # Store if meaningful activity (realized profit or multiple trades)
                    if abs(realized_profit_eth) > 0.001 or trade_count >= 2:  # $2+ profit or 2+ trades
                        db_start_time = time.time()
                        self.db.update_whale_token_pnl(whale_address, token_symbol, realized_profit_eth, token_address, trade_count)
                        db_elapsed = time.time() - db_start_time
                        meaningful_tokens += 1
                        logger.debug(f"Stored {token_symbol}: ${realized_profit_usd:.2f} ({realized_profit_eth:.6f} ETH), {trade_count} trades (DB: {db_elapsed:.3f}s)")
                    else:
                        logger.debug(f"Skipped {token_symbol}: too small profit (${realized_profit_usd:.2f})")
                        
                except Exception as e:
                    logger.error(f"Error processing token data: {e}")
                    continue
            
            if meaningful_tokens == 0:
                # Add a marker to indicate this whale has been processed (no meaningful tokens)
                self.db.update_whale_token_pnl(whale_address, "PROCESSED", 0.0, "")
                logger.info(f"No meaningful token activity found for whale {whale_address}")
            else:
                logger.info(f"Stored {meaningful_tokens} tokens from profitability data for whale {whale_address}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing profitability breakdown: {e}")
            return False
    
    def _store_profitability_token(self, whale_address: str, token_key: str, token_info) -> bool:
        """Store a single token's profitability data"""
        try:
            # Extract token information
            if isinstance(token_info, dict):
                # Extract common fields (structure to be determined from actual API response)
                token_symbol = token_info.get("symbol", token_info.get("token_symbol", token_key if token_key and not token_key.startswith('0x') else "UNKNOWN"))
                token_address = token_info.get("address", token_info.get("token_address", token_key if token_key and token_key.startswith('0x') else ""))
                
                # Look for PnL/profit fields - try various common field names
                pnl = None
                for pnl_field in ["pnl", "profit", "total_pnl", "realized_pnl", "unrealized_pnl", "profit_loss", "net_profit", "total_profit"]:
                    if pnl_field in token_info:
                        try:
                            pnl = float(token_info[pnl_field])
                            break
                        except (ValueError, TypeError):
                            continue
                
                # Look for trade count
                trades = token_info.get("trades", token_info.get("trade_count", token_info.get("transactions", token_info.get("tx_count", 1))))
                try:
                    trades = int(trades)
                except (ValueError, TypeError):
                    trades = 1
                
                # If no direct PnL, try to calculate from buy/sell values
                if pnl is None:
                    buy_value = token_info.get("buy_value", token_info.get("total_buy", token_info.get("invested", 0)))
                    sell_value = token_info.get("sell_value", token_info.get("total_sell", token_info.get("realized", 0)))
                    try:
                        buy_value = float(buy_value) if buy_value else 0
                        sell_value = float(sell_value) if sell_value else 0
                        if buy_value > 0 or sell_value > 0:
                            pnl = sell_value - buy_value
                    except (ValueError, TypeError):
                        pass
                
            elif isinstance(token_info, (int, float)):
                # Simple value, assume it's the PnL
                pnl = float(token_info)
                token_symbol = token_key if token_key and not token_key.startswith('0x') else "UNKNOWN"
                token_address = token_key if token_key and token_key.startswith('0x') else ""
                trades = 1
            else:
                logger.warning(f"Unexpected token_info type: {type(token_info)}")
                return False
            
            # Store if meaningful
            if pnl is not None and (abs(pnl) > 0.0001 or trades >= 2):
                self.db.update_whale_token_pnl(whale_address, token_symbol, pnl, token_address, trades)
                logger.debug(f"Stored {token_symbol}: PnL={pnl:.6f}, trades={trades}")
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error storing profitability token data: {e}")
            return False
    