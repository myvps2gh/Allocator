"""
Whale tracking and scoring system for Allocator AI
"""

import time
import logging
import requests
from decimal import Decimal
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..utils.math_utils import calculate_win_rate, calculate_volatility, calculate_sharpe_ratio
from ..data.cache import CacheManager, RateLimiter

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
    
    def __init__(self, moralis_api_key: str, cache_manager: CacheManager, db_manager):
        self.moralis_api_key = moralis_api_key
        self.cache = cache_manager
        self.db = db_manager
        self.rate_limiter = RateLimiter(max_calls=100, time_window=3600)  # 100 calls per hour
        
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
        
        # Discovery modes configuration
        self.discovery_modes = {
            "bot_hunter": {
                "blocks_back": 2000,
                "min_trades": 30,
                "min_pnl_threshold": 200
            },
            "active_whale": {
                "blocks_back": 15000,
                "min_trades": 20,
                "min_pnl_threshold": 100
            },
            "lazy_whale": {
                "blocks_back": 50000,
                "min_trades": 10,
                "min_pnl_threshold": 300
            },
            "quick_profit_whale": {
                "blocks_back": 15000,
                "min_trades": 5,
                "min_pnl_threshold": 50,
                "profit_window_hours": 72
            },
            "fast_mover_whale": {
                "blocks_back": 17000,
                "min_trades": 8,
                "min_pnl_threshold": 50,
                "min_roi": 0.20
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
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract relevant data
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
        moralis_data = self.fetch_moralis_data(whale_address)
        if not moralis_data:
            return False
        
        # Check if meets criteria
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
        
        # Save to database
        self.db.save_whale(
            whale_address,
            float(moralis_data["realized_pct"]),
            float(moralis_data["realized_usd"]),
            moralis_data["total_trades"]
        )
        
        logger.info(f"Added whale {whale_address} to tracking: {moralis_data['realized_pct']}% ROI, ${moralis_data['realized_usd']} profit")
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
        
        # Scan blocks for whale candidates
        for block_num in range(start_block, end_block + 1):
            try:
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
