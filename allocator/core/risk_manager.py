"""
Risk management system for Allocator AI
"""

import logging
from decimal import Decimal
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class RiskManager:
    """Advanced risk management system with dynamic position sizing"""
    
    def __init__(self, base_risk: Decimal = Decimal("0.05"), 
                 max_risk_multiplier: Decimal = Decimal("3.0"),
                 min_risk_multiplier: Decimal = Decimal("0.25"),
                 db_manager=None):
        self.base_risk = base_risk
        self.max_risk_multiplier = max_risk_multiplier
        self.min_risk_multiplier = min_risk_multiplier
        self.db_manager = db_manager
        
        # Track PnL and risk multipliers per whale
        self.whale_pnl = defaultdict(lambda: Decimal("0"))
        self.risk_multipliers = defaultdict(lambda: Decimal("1.0"))
        
        # Risk limits
        self.max_position_size = Decimal("10000")  # Max 10k ETH per position
        self.max_daily_loss = Decimal("1000")      # Max 1k ETH daily loss
        self.max_total_exposure = Decimal("50000") # Max 50k ETH total exposure
        
        # Daily tracking
        self.daily_pnl = Decimal("0")
        self.daily_reset_time = 0
        
    def update_whale_pnl(self, whale_address: str, pnl: Decimal) -> None:
        """Update PnL for a whale and adjust risk multiplier"""
        whale_address = whale_address.lower()
        self.whale_pnl[whale_address] += pnl
        
        # Update daily PnL
        self._update_daily_pnl(pnl)
        
        # Calculate new risk multiplier based on performance
        self._calculate_risk_multiplier(whale_address)
        
        # Update database with new risk metrics
        if self.db_manager:
            self.db_manager.update_whale_performance(
                whale_address,
                cumulative_pnl=float(self.whale_pnl[whale_address]),
                risk_multiplier=float(self.risk_multipliers[whale_address])
            )
        
        logger.debug(f"Updated PnL for {whale_address}: {self.whale_pnl[whale_address]}, risk_mult: {self.risk_multipliers[whale_address]}")
    
    def _update_daily_pnl(self, pnl: Decimal) -> None:
        """Update daily PnL tracking"""
        import time
        current_time = time.time()
        
        # Reset daily PnL at midnight
        if current_time - self.daily_reset_time > 24 * 3600:
            self.daily_pnl = Decimal("0")
            self.daily_reset_time = current_time
        
        self.daily_pnl += pnl
    
    def _calculate_risk_multiplier(self, whale_address: str) -> None:
        """Calculate dynamic risk multiplier based on whale performance"""
        whale_pnl = self.whale_pnl[whale_address]
        
        if whale_pnl > 0:
            # Profitable whale - increase risk (capped at max)
            # Risk increases by 0.1x for every 1000 ETH profit
            risk_boost = whale_pnl / Decimal("1000") * Decimal("0.1")
            new_multiplier = Decimal("1.0") + risk_boost
            self.risk_multipliers[whale_address] = min(new_multiplier, self.max_risk_multiplier)
        else:
            # Unprofitable whale - decrease risk (floored at min)
            # Risk decreases by 0.1x for every 1000 ETH loss
            risk_penalty = abs(whale_pnl) / Decimal("1000") * Decimal("0.1")
            new_multiplier = Decimal("1.0") - risk_penalty
            self.risk_multipliers[whale_address] = max(new_multiplier, self.min_risk_multiplier)
    
    def calculate_position_size(self, whale_address: str, base_capital: Decimal, 
                              whale_trade_amount: Decimal) -> Decimal:
        """Calculate position size for a whale trade"""
        whale_address = whale_address.lower()
        
        # Check daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            logger.warning(f"Daily loss limit reached: {self.daily_pnl}")
            return Decimal("0")
        
        # Get risk multiplier for this whale
        risk_mult = self.risk_multipliers[whale_address]
        
        # Calculate base position size
        base_position = base_capital * self.base_risk * risk_mult
        
        # Scale by whale trade size (but don't exceed whale's trade)
        # Use 10% of whale's trade size as baseline
        whale_scale = whale_trade_amount * Decimal("0.1")
        
        # Take the smaller of base position or whale scale
        position_size = min(base_position, whale_scale)
        
        # Apply maximum position size limit
        position_size = min(position_size, self.max_position_size)
        
        # Check total exposure limit
        current_exposure = sum(self.whale_pnl.values())
        if current_exposure + position_size > self.max_total_exposure:
            remaining_exposure = self.max_total_exposure - current_exposure
            position_size = max(Decimal("0"), remaining_exposure)
        
        return position_size
    
    def should_execute_trade(self, whale_address: str, trade_amount: Decimal) -> bool:
        """Determine if a trade should be executed based on risk criteria"""
        whale_address = whale_address.lower()
        
        # Check daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            logger.warning(f"Trade rejected: daily loss limit reached")
            return False
        
        # Check if whale is too risky
        if self.whale_pnl[whale_address] < -Decimal("5000"):  # -5k ETH loss
            logger.warning(f"Trade rejected: whale {whale_address} has too much loss")
            return False
        
        # Check position size limits
        base_capital = Decimal("2000")  # This should come from config
        position_size = self.calculate_position_size(whale_address, base_capital, trade_amount)
        
        if position_size <= 0:
            logger.warning(f"Trade rejected: position size too small or limits exceeded")
            return False
        
        return True
    
    def get_risk_metrics(self) -> Dict[str, Decimal]:
        """Get current risk metrics"""
        total_pnl = sum(self.whale_pnl.values())
        active_whales = len([pnl for pnl in self.whale_pnl.values() if pnl != 0])
        avg_risk_mult = sum(self.risk_multipliers.values()) / len(self.risk_multipliers) if self.risk_multipliers else Decimal("1")
        
        return {
            "total_pnl": total_pnl,
            "daily_pnl": self.daily_pnl,
            "active_whales": active_whales,
            "average_risk_multiplier": avg_risk_mult,
            "max_daily_loss": self.max_daily_loss,
            "max_total_exposure": self.max_total_exposure
        }
    
    def get_whale_risk_profile(self, whale_address: str) -> Dict[str, Decimal]:
        """Get risk profile for a specific whale"""
        whale_address = whale_address.lower()
        
        return {
            "pnl": self.whale_pnl[whale_address],
            "risk_multiplier": self.risk_multipliers[whale_address],
            "position_limit": self.max_position_size
        }
    
    def reset_whale_risk(self, whale_address: str) -> None:
        """Reset risk profile for a whale"""
        whale_address = whale_address.lower()
        self.whale_pnl[whale_address] = Decimal("0")
        self.risk_multipliers[whale_address] = Decimal("1.0")
        logger.info(f"Reset risk profile for whale {whale_address}")
    
    def emergency_stop(self) -> None:
        """Emergency stop - reset all risk profiles"""
        self.whale_pnl.clear()
        self.risk_multipliers.clear()
        self.daily_pnl = Decimal("0")
        logger.warning("Emergency stop: all risk profiles reset")
    
    def update_risk_limits(self, max_position: Optional[Decimal] = None,
                          max_daily_loss: Optional[Decimal] = None,
                          max_total_exposure: Optional[Decimal] = None) -> None:
        """Update risk limits"""
        if max_position is not None:
            self.max_position_size = max_position
        if max_daily_loss is not None:
            self.max_daily_loss = max_daily_loss
        if max_total_exposure is not None:
            self.max_total_exposure = max_total_exposure
        
        logger.info(f"Updated risk limits: max_position={self.max_position_size}, "
                   f"max_daily_loss={self.max_daily_loss}, max_total_exposure={self.max_total_exposure}")
