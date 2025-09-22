"""
Adaptive whale discovery using percentile-based thresholds
"""

import logging
import statistics
from decimal import Decimal
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from web3 import Web3

logger = logging.getLogger(__name__)


class AdaptiveDiscoveryEngine:
    """Percentile-based adaptive whale discovery"""
    
    def __init__(self, w3: Web3, market_analyzer=None):
        self.w3 = w3
        self.market_analyzer = market_analyzer
        
        # Uniswap router addresses
        self.monitored_routers = {
            "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D".lower(),  # Uniswap V2
            "0xE592427A0AEce92De3Edee1F18E0157C05861564".lower()   # Uniswap V3
        }
    
    def discover_whales_percentile(self, activity_percentile: float = 5.0, 
                                 profit_percentile: float = 25.0,
                                 blocks_back: int = 10000) -> Dict:
        """
        Discover whales using percentile-based thresholds
        
        Args:
            activity_percentile: Top X% most active addresses (e.g., 5.0 = top 5%)
            profit_percentile: Top X% most profitable addresses (e.g., 25.0 = top 25%)
            blocks_back: Number of blocks to analyze
        """
        try:
            current_block = self.w3.eth.block_number
            start_block = max(0, current_block - blocks_back)
            
            logger.info(f"Adaptive discovery: analyzing {blocks_back} blocks for "
                       f"top {activity_percentile}% activity, top {profit_percentile}% profit")
            
            # Collect all address activity
            address_stats = defaultdict(lambda: {"trades": 0, "profit": Decimal(0), "volume": Decimal(0)})
            
            # Sample every 5th block for performance
            sample_blocks = range(start_block, current_block, 5)
            total_blocks = len(list(sample_blocks))
            processed = 0
            
            for block_num in sample_blocks:
                try:
                    block = self.w3.eth.get_block(block_num, full_transactions=True)
                    
                    for tx in block.transactions:
                        if tx.to and tx.to.lower() in self.monitored_routers:
                            actor = tx["from"].lower()
                            eth_value = Decimal(tx.value) / (10**18)
                            
                            address_stats[actor]["trades"] += 1
                            address_stats[actor]["profit"] += eth_value
                            address_stats[actor]["volume"] += eth_value
                    
                    processed += 1
                    if processed % 500 == 0:
                        progress = (processed / total_blocks) * 100
                        logger.info(f"Adaptive discovery: {progress:.1f}% complete ({processed}/{total_blocks} blocks)")
                        
                except Exception as e:
                    logger.debug(f"Failed to process block {block_num}: {e}")
                    continue
            
            if not address_stats:
                logger.warning("No address activity found for percentile analysis")
                return {
                    "candidates": [],
                    "thresholds": {"trades": 0, "profit": 0},
                    "total_addresses": 0,
                    "method": "percentile"
                }
            
            # Calculate percentile thresholds
            all_addresses = list(address_stats.values())
            trade_counts = [addr["trades"] for addr in all_addresses]
            profit_amounts = [float(addr["profit"]) for addr in all_addresses]
            
            # Calculate percentile thresholds
            activity_threshold = self._calculate_percentile(trade_counts, 100 - activity_percentile)
            profit_threshold = self._calculate_percentile(profit_amounts, 100 - profit_percentile)
            
            # Apply market condition adjustments if available
            if self.market_analyzer:
                market_conditions = self.market_analyzer.analyze_market_conditions()
                multiplier = market_conditions.get('threshold_multiplier', 1.0)
                
                activity_threshold = max(1, int(activity_threshold * multiplier))
                profit_threshold = max(0.1, profit_threshold * multiplier)
                
                logger.info(f"Market-adjusted thresholds: trades≥{activity_threshold}, profit≥{profit_threshold:.2f} ETH "
                           f"(multiplier: {multiplier:.2f})")
            else:
                logger.info(f"Percentile thresholds: trades≥{activity_threshold}, profit≥{profit_threshold:.2f} ETH")
            
            # Find candidates meeting both thresholds
            candidates = []
            for address, stats in address_stats.items():
                if (stats["trades"] >= activity_threshold and 
                    float(stats["profit"]) >= profit_threshold):
                    candidates.append(address)
            
            result = {
                "candidates": candidates,
                "thresholds": {
                    "trades": activity_threshold,
                    "profit": profit_threshold
                },
                "total_addresses": len(address_stats),
                "method": "percentile",
                "percentiles": {
                    "activity": activity_percentile,
                    "profit": profit_percentile
                },
                "blocks_analyzed": processed
            }
            
            logger.info(f"Adaptive discovery found {len(candidates)} candidates from {len(address_stats)} addresses "
                       f"(activity≥{activity_threshold} trades, profit≥{profit_threshold:.2f} ETH)")
            
            return result
            
        except Exception as e:
            logger.error(f"Adaptive discovery failed: {e}")
            return {
                "candidates": [],
                "thresholds": {"trades": 0, "profit": 0},
                "total_addresses": 0,
                "method": "percentile_failed",
                "error": str(e)
            }
    
    def _calculate_percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile value from data"""
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(k)
        c = k - f
        
        if f + 1 < len(sorted_data):
            return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
        else:
            return sorted_data[f]
    
    def discover_whales_adaptive_sliding(self, base_trades: int, base_pnl: float,
                                       blocks_back: int = 5000) -> Dict:
        """
        Sliding window adaptive discovery with volatility normalization
        """
        try:
            # Get market conditions
            if self.market_analyzer:
                conditions = self.market_analyzer.analyze_market_conditions()
                adaptive_trades, adaptive_pnl = self.market_analyzer.get_adaptive_thresholds(
                    base_trades, base_pnl, conditions
                )
                
                logger.info(f"Sliding adaptive: {base_trades}→{adaptive_trades} trades, "
                           f"{base_pnl}→{adaptive_pnl:.1f} ETH (regime: {conditions['market_regime']})")
            else:
                adaptive_trades, adaptive_pnl = base_trades, base_pnl
                conditions = {}
            
            # Use standard discovery with adaptive thresholds
            current_block = self.w3.eth.block_number
            start_block = max(0, current_block - blocks_back)
            
            candidate_stats = defaultdict(lambda: {"profit": Decimal(0), "trades": 0})
            
            for block_num in range(start_block, current_block + 1):
                try:
                    block = self.w3.eth.get_block(block_num, full_transactions=True)
                    
                    for tx in block.transactions:
                        if tx.to and tx.to.lower() in self.monitored_routers:
                            actor = tx["from"].lower()
                            candidate_stats[actor]["trades"] += 1
                            candidate_stats[actor]["profit"] += Decimal(tx.value) / (10**18)
                            
                except Exception as e:
                    logger.debug(f"Failed to process block {block_num}: {e}")
                    continue
            
            # Filter with adaptive thresholds
            candidates = []
            for addr, stats in candidate_stats.items():
                if (stats["trades"] >= adaptive_trades and 
                    float(stats["profit"]) >= adaptive_pnl):
                    candidates.append(addr)
            
            return {
                "candidates": candidates,
                "thresholds": {
                    "trades": adaptive_trades,
                    "profit": adaptive_pnl
                },
                "base_thresholds": {
                    "trades": base_trades,
                    "profit": base_pnl
                },
                "total_addresses": len(candidate_stats),
                "method": "adaptive_sliding",
                "market_conditions": conditions,
                "blocks_analyzed": blocks_back
            }
            
        except Exception as e:
            logger.error(f"Adaptive sliding discovery failed: {e}")
            return {
                "candidates": [],
                "thresholds": {"trades": base_trades, "profit": base_pnl},
                "total_addresses": 0,
                "method": "adaptive_sliding_failed",
                "error": str(e)
            }
