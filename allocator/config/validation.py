"""
Configuration validation utilities
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


def validate_config(config_dict: Dict[str, Any]) -> bool:
    """Validate configuration dictionary"""
    try:
        # Validate required fields
        required_fields = ["web3_rpc", "capital", "base_risk", "max_slippage", "min_profit", "gas_boost"]
        for field in required_fields:
            if field not in config_dict:
                logger.error(f"Missing required config field: {field}")
                return False
        
        # Validate numeric fields
        numeric_fields = {
            "capital": (0, 1000000),  # 0 to 1M ETH
            "base_risk": (0, 1),      # 0 to 100%
            "max_slippage": (0, 0.1), # 0 to 10%
            "min_profit": (0, 0.1),   # 0 to 10%
            "gas_boost": (1, 5)       # 1x to 5x
        }
        
        for field, (min_val, max_val) in numeric_fields.items():
            try:
                value = Decimal(str(config_dict[field]))
                if not (min_val <= value <= max_val):
                    logger.error(f"Invalid {field}: {value} (must be between {min_val} and {max_val})")
                    return False
            except (ValueError, TypeError, InvalidOperation):
                logger.error(f"Invalid {field} value: {config_dict[field]}")
                return False
        
        # Validate tracked_whales if present
        if "tracked_whales" in config_dict:
            if not isinstance(config_dict["tracked_whales"], list):
                logger.error("tracked_whales must be a list")
                return False
            
            for whale in config_dict["tracked_whales"]:
                if not isinstance(whale, str) or len(whale) != 42 or not whale.startswith("0x"):
                    logger.error(f"Invalid whale address format: {whale}")
                    return False
        
        return True
        
    except Exception as e:
        logger.error(f"Configuration validation error: {e}")
        return False


def validate_environment() -> bool:
    """Validate environment variables"""
    import os
    
    required_env_vars = ["MORALIS_API_KEY", "WALLET_PASS"]
    missing_vars = []
    
    for var in required_env_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False
    
    return True
