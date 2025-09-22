"""
Market condition analysis for adaptive whale discovery
"""

import logging
import statistics
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque
from web3 import Web3

logger = logging.getLogger(__name__)


class MarketConditionAnalyzer:
    """Analyzes market conditions to adapt discovery thresholds"""
    
    def __init__(self, w3: Web3, cache_manager=None):
        self.w3 = w3
        self.cache = cache_manager
        
        # Cache for market data
        self.block_activity_cache = deque(maxlen=1000)
        self.price_volatility_cache = deque(maxlen=1000)
        self.transaction_volume_cache = deque(maxlen=1000)
        
    def analyze_market_conditions(self, blocks_back: int = 1000) -> Dict:
        """Analyze current market conditions"""
        try:
            current_block = self.w3.eth.block_number
            start_block = max(0, current_block - blocks_back)
            
            logger.info(f"Analyzing market conditions over {blocks_back} blocks ({start_block} to {current_block})")
            
            # Sample blocks for analysis (every 10th block to reduce load)
            sample_blocks = range(start_block, current_block, 10)
            
            block_data = []
            transaction_counts = []
            gas_prices = []
            
            for block_num in sample_blocks:
                try:
                    block = self.w3.eth.get_block(block_num, full_transactions=False)
                    
                    tx_count = len(block.transactions)
                    avg_gas_price = block.get('baseFeePerGas', 0) or 0
                    
                    transaction_counts.append(tx_count)
                    gas_prices.append(avg_gas_price)
                    
                    block_data.append({
                        'block': block_num,
                        'tx_count': tx_count,
                        'gas_price': avg_gas_price,
                        'timestamp': block.timestamp
                    })
                    
                except Exception as e:
                    logger.debug(f"Failed to analyze block {block_num}: {e}")
                    continue
            
            if not transaction_counts:
                logger.warning("No block data available for market analysis")
                return self._default_conditions()
            
            # Calculate market metrics
            conditions = {
                'activity_level': self._calculate_activity_level(transaction_counts),
                'volatility_index': self._calculate_volatility(gas_prices),
                'liquidity_score': self._calculate_liquidity_score(block_data),
                'market_regime': self._determine_market_regime(transaction_counts, gas_prices),
                'threshold_multiplier': self._calculate_threshold_multiplier(transaction_counts, gas_prices),
                'blocks_analyzed': len(block_data),
                'timestamp': self.w3.eth.get_block('latest').timestamp
            }
            
            logger.info(f"Market conditions: {conditions['market_regime']} regime, "
                       f"activity={conditions['activity_level']:.2f}, "
                       f"volatility={conditions['volatility_index']:.2f}, "
                       f"threshold_multiplier={conditions['threshold_multiplier']:.2f}")
            
            return conditions
            
        except Exception as e:
            logger.error(f"Market condition analysis failed: {e}")
            return self._default_conditions()
    
    def _calculate_activity_level(self, transaction_counts: List[int]) -> float:
        """Calculate network activity level (0.0 to 2.0+)"""
        if not transaction_counts:
            return 1.0
        
        mean_txs = statistics.mean(transaction_counts)
        median_txs = statistics.median(transaction_counts)
        
        # Activity level relative to historical average (assume ~150 tx/block baseline)
        baseline_activity = 150
        activity_ratio = mean_txs / baseline_activity
        
        return max(0.1, min(5.0, activity_ratio))
    
    def _calculate_volatility(self, gas_prices: List[int]) -> float:
        """Calculate gas price volatility (0.0 to 2.0+)"""
        if len(gas_prices) < 2:
            return 1.0
        
        # Convert to Gwei for easier calculation
        gas_prices_gwei = [price / 1e9 for price in gas_prices if price > 0]
        
        if len(gas_prices_gwei) < 2:
            return 1.0
        
        try:
            mean_gas = statistics.mean(gas_prices_gwei)
            stdev_gas = statistics.stdev(gas_prices_gwei)
            
            if mean_gas == 0:
                return 1.0
            
            # Coefficient of variation as volatility measure
            volatility = stdev_gas / mean_gas
            
            # Normalize to 0-2 range (typical CV for gas is 0.1-0.5)
            normalized_volatility = min(2.0, max(0.1, volatility * 4))
            
            return normalized_volatility
            
        except statistics.StatisticsError:
            return 1.0
    
    def _calculate_liquidity_score(self, block_data: List[Dict]) -> float:
        """Calculate liquidity score based on consistent block filling"""
        if not block_data:
            return 1.0
        
        # Measure consistency of transaction counts
        tx_counts = [block['tx_count'] for block in block_data]
        
        if len(tx_counts) < 2:
            return 1.0
        
        try:
            mean_txs = statistics.mean(tx_counts)
            stdev_txs = statistics.stdev(tx_counts)
            
            if mean_txs == 0:
                return 0.5
            
            # Lower coefficient of variation = higher liquidity (more consistent)
            consistency = 1.0 - min(1.0, stdev_txs / mean_txs)
            
            # Combine with absolute activity level
            activity_score = min(1.0, mean_txs / 200)  # 200 tx/block = high activity
            
            liquidity_score = (consistency * 0.6) + (activity_score * 0.4)
            
            return max(0.1, min(2.0, liquidity_score))
            
        except statistics.StatisticsError:
            return 1.0
    
    def _determine_market_regime(self, transaction_counts: List[int], gas_prices: List[int]) -> str:
        """Determine current market regime"""
        activity = self._calculate_activity_level(transaction_counts)
        volatility = self._calculate_volatility(gas_prices)
        
        if activity > 1.5 and volatility > 1.3:
            return "high_activity_volatile"
        elif activity > 1.2 and volatility < 0.8:
            return "high_activity_stable"
        elif activity < 0.7 and volatility > 1.2:
            return "low_activity_volatile"
        elif activity < 0.8 and volatility < 0.8:
            return "low_activity_stable"
        else:
            return "normal"
    
    def _calculate_threshold_multiplier(self, transaction_counts: List[int], gas_prices: List[int]) -> float:
        """Calculate multiplier for adjusting discovery thresholds"""
        activity = self._calculate_activity_level(transaction_counts)
        volatility = self._calculate_volatility(gas_prices)
        
        # Base multiplier
        base_multiplier = 1.0
        
        # Adjust based on activity (high activity = raise thresholds)
        activity_adjustment = (activity - 1.0) * 0.3
        
        # Adjust based on volatility (high volatility = slightly raise thresholds)
        volatility_adjustment = (volatility - 1.0) * 0.2
        
        # Combined multiplier (range: 0.3 to 2.0)
        multiplier = base_multiplier + activity_adjustment + volatility_adjustment
        
        return max(0.3, min(2.0, multiplier))
    
    def _default_conditions(self) -> Dict:
        """Return default market conditions when analysis fails"""
        return {
            'activity_level': 1.0,
            'volatility_index': 1.0,
            'liquidity_score': 1.0,
            'market_regime': 'normal',
            'threshold_multiplier': 1.0,
            'blocks_analyzed': 0,
            'timestamp': 0
        }
    
    def get_adaptive_thresholds(self, base_min_trades: int, base_min_pnl: float, 
                              conditions: Optional[Dict] = None) -> Tuple[int, float]:
        """Get adaptive thresholds based on market conditions"""
        if conditions is None:
            conditions = self.analyze_market_conditions()
        
        multiplier = conditions['threshold_multiplier']
        
        # Adjust thresholds
        adaptive_min_trades = max(1, int(base_min_trades * multiplier))
        adaptive_min_pnl = max(0.1, base_min_pnl * multiplier)
        
        logger.debug(f"Adaptive thresholds: trades {base_min_trades}→{adaptive_min_trades}, "
                    f"pnl {base_min_pnl}→{adaptive_min_pnl:.1f} (multiplier: {multiplier:.2f})")
        
        return adaptive_min_trades, adaptive_min_pnl
