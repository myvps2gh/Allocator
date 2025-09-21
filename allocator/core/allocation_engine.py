"""
Allocation engine for determining trade sizes and strategies
"""

import logging
from decimal import Decimal
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AllocationDecision:
    """Allocation decision result"""
    should_trade: bool
    allocation_size: Decimal
    reason: str
    confidence: Decimal  # 0-1 scale


class AllocationEngine:
    """Advanced allocation engine for determining trade sizes"""
    
    def __init__(self, base_capital: Decimal = Decimal("2000"),
                 base_risk: Decimal = Decimal("0.05"),
                 max_allocation: Decimal = Decimal("5000")):
        self.base_capital = base_capital
        self.base_risk = base_risk
        self.max_allocation = max_allocation
        
        # Router preferences and biases
        self.router_preferences = {
            "uniswap_v2": Decimal("0.8"),    # 20% discount for V2
            "uniswap_v3": Decimal("1.2"),    # 20% premium for V3
            "balancer": Decimal("1.0"),      # Neutral
            "sushiswap": Decimal("0.9")      # 10% discount
        }
        
        # Function preferences
        self.function_preferences = {
            "exactInputSingle": Decimal("1.5"),      # Prefer V3 single swaps
            "exactInput": Decimal("1.2"),            # V3 multi-hop
            "swapExactTokensForTokens": Decimal("1.0"),  # V2 token swaps
            "swapExactETHForTokens": Decimal("0.5"),     # Discourage ETH->token
            "swapTokensForExactTokens": Decimal("0.8")   # Slightly prefer exact input
        }
        
        # Token preferences (can be updated based on performance)
        self.token_preferences = {
            "WETH": Decimal("1.0"),
            "USDC": Decimal("1.1"),
            "USDT": Decimal("1.0"),
            "DAI": Decimal("1.0")
        }
    
    def decide_allocation(self, trade_data: Dict[str, Any], 
                         whale_stats: Optional[Dict] = None,
                         risk_multiplier: Decimal = Decimal("1.0")) -> AllocationDecision:
        """Make allocation decision for a trade"""
        
        # Extract trade information
        token_in = trade_data.get("token_in", {})
        token_out = trade_data.get("token_out", {})
        amount_in = Decimal(str(trade_data.get("amount_in", 0)))
        fn_name = trade_data.get("fn_name", "")
        router = trade_data.get("to", "").lower()
        
        # Basic validation
        if amount_in <= 0:
            return AllocationDecision(
                should_trade=False,
                allocation_size=Decimal("0"),
                reason="Invalid trade amount",
                confidence=Decimal("0")
            )
        
        # Skip dust trades
        if amount_in < 100:  # Less than 100 units
            return AllocationDecision(
                should_trade=False,
                allocation_size=Decimal("0"),
                reason="Trade amount too small (dust)",
                confidence=Decimal("0")
            )
        
        # Calculate base allocation
        base_allocation = self._calculate_base_allocation(amount_in, risk_multiplier)
        
        # Apply router bias
        router_bias = self._get_router_bias(router)
        base_allocation *= router_bias
        
        # Apply function bias
        function_bias = self._get_function_bias(fn_name)
        base_allocation *= function_bias
        
        # Apply token preferences
        token_bias = self._get_token_bias(token_in, token_out)
        base_allocation *= token_bias
        
        # Apply whale performance bias
        whale_bias = self._get_whale_bias(whale_stats)
        base_allocation *= whale_bias
        
        # Apply maximum allocation limit
        final_allocation = min(base_allocation, self.max_allocation)
        
        # Determine confidence based on various factors
        confidence = self._calculate_confidence(trade_data, whale_stats)
        
        # Final decision
        should_trade = final_allocation > 0 and confidence > Decimal("0.3")
        
        reason = self._generate_reason(should_trade, final_allocation, confidence, 
                                     router_bias, function_bias, token_bias, whale_bias)
        
        return AllocationDecision(
            should_trade=should_trade,
            allocation_size=final_allocation,
            reason=reason,
            confidence=confidence
        )
    
    def _calculate_base_allocation(self, whale_amount: Decimal, risk_multiplier: Decimal) -> Decimal:
        """Calculate base allocation size"""
        # Use 10% of whale's trade size as baseline
        base_scale = whale_amount * Decimal("0.1")
        
        # Apply risk multiplier
        risk_adjusted = base_scale * risk_multiplier
        
        # Apply base risk percentage
        return risk_adjusted * self.base_risk
    
    def _get_router_bias(self, router: str) -> Decimal:
        """Get bias multiplier for router type"""
        if "uniswap" in router:
            if "v3" in router or "0xe592427a" in router:
                return self.router_preferences["uniswap_v3"]
            else:
                return self.router_preferences["uniswap_v2"]
        elif "balancer" in router:
            return self.router_preferences["balancer"]
        elif "sushi" in router:
            return self.router_preferences["sushiswap"]
        else:
            return Decimal("1.0")  # Neutral for unknown routers
    
    def _get_function_bias(self, fn_name: str) -> Decimal:
        """Get bias multiplier for function type"""
        return self.function_preferences.get(fn_name, Decimal("1.0"))
    
    def _get_token_bias(self, token_in: Dict, token_out: Dict) -> Decimal:
        """Get bias multiplier for token pair"""
        symbol_in = token_in.get("symbol", "").upper()
        symbol_out = token_out.get("symbol", "").upper()
        
        bias_in = self.token_preferences.get(symbol_in, Decimal("1.0"))
        bias_out = self.token_preferences.get(symbol_out, Decimal("1.0"))
        
        # Average the biases
        return (bias_in + bias_out) / Decimal("2")
    
    def _get_whale_bias(self, whale_stats: Optional[Dict]) -> Decimal:
        """Get bias multiplier based on whale performance"""
        if not whale_stats:
            return Decimal("1.0")
        
        # Extract performance metrics
        score = Decimal(str(whale_stats.get("score", 0)))
        win_rate = Decimal(str(whale_stats.get("win_rate", 0.5)))
        trades = whale_stats.get("trades", 0)
        
        # Calculate bias based on performance
        if score > 100:  # High performing whale
            return Decimal("1.5")
        elif score > 50:
            return Decimal("1.2")
        elif score > 0:
            return Decimal("1.0")
        elif score > -50:
            return Decimal("0.8")
        else:
            return Decimal("0.5")  # Poor performing whale
    
    def _calculate_confidence(self, trade_data: Dict[str, Any], 
                            whale_stats: Optional[Dict]) -> Decimal:
        """Calculate confidence score for the trade"""
        confidence = Decimal("0.5")  # Base confidence
        
        # Increase confidence for larger trades (whales are more confident)
        amount_in = Decimal(str(trade_data.get("amount_in", 0)))
        if amount_in > 10000:
            confidence += Decimal("0.2")
        elif amount_in > 1000:
            confidence += Decimal("0.1")
        
        # Increase confidence for V3 trades (more sophisticated)
        fn_name = trade_data.get("fn_name", "")
        if "exactInput" in fn_name:
            confidence += Decimal("0.1")
        
        # Increase confidence based on whale performance
        if whale_stats:
            score = Decimal(str(whale_stats.get("score", 0)))
            if score > 100:
                confidence += Decimal("0.2")
            elif score > 50:
                confidence += Decimal("0.1")
            elif score < -50:
                confidence -= Decimal("0.2")
        
        # Cap confidence between 0 and 1
        return max(Decimal("0"), min(Decimal("1"), confidence))
    
    def _generate_reason(self, should_trade: bool, allocation: Decimal, 
                        confidence: Decimal, router_bias: Decimal,
                        function_bias: Decimal, token_bias: Decimal,
                        whale_bias: Decimal) -> str:
        """Generate human-readable reason for the decision"""
        if not should_trade:
            return f"Trade rejected: confidence {confidence:.2f} too low"
        
        reasons = []
        if router_bias != Decimal("1.0"):
            reasons.append(f"router_bias={router_bias:.2f}")
        if function_bias != Decimal("1.0"):
            reasons.append(f"function_bias={function_bias:.2f}")
        if token_bias != Decimal("1.0"):
            reasons.append(f"token_bias={token_bias:.2f}")
        if whale_bias != Decimal("1.0"):
            reasons.append(f"whale_bias={whale_bias:.2f}")
        
        reason = f"Allocation: {allocation:.2f} ETH, confidence: {confidence:.2f}"
        if reasons:
            reason += f" (factors: {', '.join(reasons)})"
        
        return reason
    
    def update_token_preference(self, token_symbol: str, preference: Decimal) -> None:
        """Update token preference"""
        self.token_preferences[token_symbol.upper()] = preference
        logger.info(f"Updated token preference for {token_symbol}: {preference}")
    
    def update_router_preference(self, router: str, preference: Decimal) -> None:
        """Update router preference"""
        self.router_preferences[router] = preference
        logger.info(f"Updated router preference for {router}: {preference}")
    
    def get_allocation_stats(self) -> Dict[str, Any]:
        """Get allocation engine statistics"""
        return {
            "base_capital": self.base_capital,
            "base_risk": self.base_risk,
            "max_allocation": self.max_allocation,
            "router_preferences": {k: float(v) for k, v in self.router_preferences.items()},
            "function_preferences": {k: float(v) for k, v in self.function_preferences.items()},
            "token_preferences": {k: float(v) for k, v in self.token_preferences.items()}
        }
