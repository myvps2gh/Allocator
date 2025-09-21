"""
Mathematical utilities for Allocator AI
"""

import statistics
from decimal import Decimal
from typing import List, Union
import logging

logger = logging.getLogger(__name__)


def calculate_win_rate(pnl_list: List[Decimal]) -> Decimal:
    """Calculate win rate from PnL list"""
    if not pnl_list:
        return Decimal('0')
    
    wins = sum(1 for pnl in pnl_list if pnl > 0)
    total = len(pnl_list)
    return Decimal(str(wins)) / Decimal(str(total))


def calculate_volatility(pnl_list: List[Decimal]) -> Decimal:
    """Calculate volatility (standard deviation) from PnL list"""
    if len(pnl_list) <= 1:
        return Decimal('1')
    
    try:
        # Convert to float for statistics calculation
        float_list = [float(pnl) for pnl in pnl_list]
        stdev = statistics.pstdev(float_list)
        return Decimal(str(stdev))
    except Exception as e:
        logger.warning(f"Volatility calculation failed: {e}")
        return Decimal('1')


def calculate_sharpe_ratio(pnl_list: List[Decimal], risk_free_rate: Decimal = Decimal('0')) -> Decimal:
    """Calculate Sharpe ratio from PnL list"""
    if not pnl_list:
        return Decimal('0')
    
    try:
        mean_return = sum(pnl_list) / len(pnl_list)
        volatility = calculate_volatility(pnl_list)
        
        if volatility == 0:
            return Decimal('0')
        
        return (mean_return - risk_free_rate) / volatility
    except Exception as e:
        logger.warning(f"Sharpe ratio calculation failed: {e}")
        return Decimal('0')


def safe_divide(numerator: Union[Decimal, int, float], denominator: Union[Decimal, int, float], default: Decimal = Decimal('0')) -> Decimal:
    """Safely divide two numbers, returning default if division by zero"""
    try:
        num = Decimal(str(numerator))
        den = Decimal(str(denominator))
        
        if den == 0:
            return default
        
        return num / den
    except Exception as e:
        logger.warning(f"Safe divide failed: {e}")
        return default


def calculate_percentage_change(old_value: Decimal, new_value: Decimal) -> Decimal:
    """Calculate percentage change between two values"""
    if old_value == 0:
        return Decimal('0')
    
    return ((new_value - old_value) / old_value) * 100


def calculate_compound_growth(initial: Decimal, final: Decimal, periods: int) -> Decimal:
    """Calculate compound annual growth rate"""
    if initial <= 0 or final <= 0 or periods <= 0:
        return Decimal('0')
    
    try:
        growth_rate = (final / initial) ** (1 / periods) - 1
        return Decimal(str(growth_rate)) * 100
    except Exception as e:
        logger.warning(f"Compound growth calculation failed: {e}")
        return Decimal('0')


def calculate_max_drawdown(pnl_list: List[Decimal]) -> Decimal:
    """Calculate maximum drawdown from PnL list"""
    if not pnl_list:
        return Decimal('0')
    
    try:
        cumulative = []
        running_total = Decimal('0')
        
        for pnl in pnl_list:
            running_total += pnl
            cumulative.append(running_total)
        
        peak = cumulative[0]
        max_dd = Decimal('0')
        
        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_dd:
                max_dd = drawdown
        
        return max_dd
    except Exception as e:
        logger.warning(f"Max drawdown calculation failed: {e}")
        return Decimal('0')


def calculate_sortino_ratio(pnl_list: List[Decimal], target_return: Decimal = Decimal('0')) -> Decimal:
    """Calculate Sortino ratio (downside deviation) from PnL list"""
    if not pnl_list:
        return Decimal('0')
    
    try:
        mean_return = sum(pnl_list) / len(pnl_list)
        
        # Calculate downside deviation
        downside_returns = [pnl for pnl in pnl_list if pnl < target_return]
        if not downside_returns:
            return Decimal('0')
        
        downside_variance = sum((pnl - target_return) ** 2 for pnl in downside_returns) / len(downside_returns)
        downside_deviation = Decimal(str(downside_variance)) ** Decimal('0.5')
        
        if downside_deviation == 0:
            return Decimal('0')
        
        return (mean_return - target_return) / downside_deviation
    except Exception as e:
        logger.warning(f"Sortino ratio calculation failed: {e}")
        return Decimal('0')


def normalize_score(score: Decimal, min_score: Decimal, max_score: Decimal) -> Decimal:
    """Normalize score to 0-1 range"""
    if max_score == min_score:
        return Decimal('0.5')
    
    normalized = (score - min_score) / (max_score - min_score)
    return max(Decimal('0'), min(Decimal('1'), normalized))


def calculate_ema(values: List[Decimal], alpha: Decimal = Decimal('0.1')) -> List[Decimal]:
    """Calculate exponential moving average"""
    if not values:
        return []
    
    ema_values = [values[0]]
    
    for i in range(1, len(values)):
        ema = alpha * values[i] + (1 - alpha) * ema_values[-1]
        ema_values.append(ema)
    
    return ema_values
