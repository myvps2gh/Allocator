"""
Input validation utilities for Allocator AI
"""

import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Union, Dict, Any
from web3 import Web3

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


def validate_ethereum_address(address: str) -> bool:
    """Validate Ethereum address format"""
    if not address or not isinstance(address, str):
        return False
    
    # Check format: 0x + 40 hex characters
    pattern = r'^0x[a-fA-F0-9]{40}$'
    if not re.match(pattern, address):
        return False
    
    # Additional checksum validation
    try:
        # This will validate checksum if present
        return Web3.is_address(address)
    except:
        return False


def validate_amount(amount: Union[str, int, float, Decimal]) -> bool:
    """Validate trade amount is reasonable"""
    try:
        amount = Decimal(str(amount))
        # Must be positive and less than 1 million ETH (safety limit)
        return amount > 0 and amount < Decimal('1000000')
    except (ValueError, TypeError, InvalidOperation):
        return False


def validate_percentage(value: Union[str, int, float, Decimal]) -> bool:
    """Validate percentage values (0-100)"""
    try:
        value = Decimal(str(value))
        return value >= 0 and value <= 100
    except (ValueError, TypeError, InvalidOperation):
        return False


def validate_positive_number(value: Union[str, int, float, Decimal]) -> bool:
    """Validate positive numbers"""
    try:
        value = Decimal(str(value))
        return value >= 0
    except (ValueError, TypeError, InvalidOperation):
        return False


def safe_validate(func, *args, **kwargs):
    """Safely execute validation function with error handling"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Validation error in {func.__name__}: {e}")
        return False


def validate_trade_data(trade_data: Dict[str, Any]) -> bool:
    """Comprehensive validation of trade data"""
    required_fields = ['from', 'to', 'token_in', 'token_out', 'amount_in']
    
    # Check required fields
    for field in required_fields:
        if field not in trade_data:
            logger.warning(f"Missing required field: {field}")
            return False
    
    # Validate addresses
    if not validate_ethereum_address(trade_data['from']):
        logger.warning(f"Invalid 'from' address: {trade_data['from']}")
        return False
    
    if not validate_ethereum_address(trade_data['to']):
        logger.warning(f"Invalid 'to' address: {trade_data['to']}")
        return False
    
    # Validate amounts
    if not validate_amount(trade_data['amount_in']):
        logger.warning(f"Invalid amount_in: {trade_data['amount_in']}")
        return False
    
    # Validate token data structure
    if not isinstance(trade_data.get('token_in'), dict) or not isinstance(trade_data.get('token_out'), dict):
        logger.warning("Invalid token data structure")
        return False
    
    return True


def validate_config_data(config_data: Dict[str, Any]) -> bool:
    """Validate configuration data"""
    required_fields = ['web3_rpc', 'capital', 'base_risk', 'max_slippage', 'min_profit', 'gas_boost']
    
    for field in required_fields:
        if field not in config_data:
            logger.error(f"Missing required config field: {field}")
            return False
    
    # Validate numeric fields
    numeric_fields = {
        'capital': (0, 1000000),
        'base_risk': (0, 1),
        'max_slippage': (0, 0.1),
        'min_profit': (0, 0.1),
        'gas_boost': (1, 5)
    }
    
    for field, (min_val, max_val) in numeric_fields.items():
        try:
            value = Decimal(str(config_data[field]))
            if not (min_val <= value <= max_val):
                logger.error(f"Invalid {field}: {value} (must be between {min_val} and {max_val})")
                return False
        except (ValueError, TypeError, InvalidOperation):
            logger.error(f"Invalid {field} value: {config_data[field]}")
            return False
    
    return True
