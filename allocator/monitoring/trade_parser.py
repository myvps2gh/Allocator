"""
Trade parsing utilities for mempool transactions
"""

import logging
from typing import Dict, Any, Optional, List
from web3 import Web3
from decimal import Decimal

from ..utils.web3_utils import TokenManager

logger = logging.getLogger(__name__)


class TradeParser:
    """Parse swap transactions from various DEX protocols"""
    
    def __init__(self, w3: Web3, token_manager: Optional[TokenManager] = None):
        self.w3 = w3
        self.token_manager = token_manager or TokenManager(w3)
        
        # Router addresses (checksummed)
        self.uniswap_v2 = Web3.to_checksum_address("0x7a250d5630b4cf539739df2c5dacb4c659f2488d")
        self.uniswap_v3 = Web3.to_checksum_address("0xe592427a0aece92de3ede1f18e0157c05861564")
        
        # Load contract ABIs
        self.v2_abi = self._load_abi("uniswap_v2_router")
        self.v3_abi = self._load_abi("uniswap_v3_router")
        
        # Create contract instances
        self.uni_v2_contract = w3.eth.contract(address=self.uniswap_v2, abi=self.v2_abi)
        self.uni_v3_contract = w3.eth.contract(address=self.uniswap_v3, abi=self.v3_abi)
    
    def _load_abi(self, abi_name: str) -> list:
        """Load ABI from file"""
        import json
        import os
        
        abi_path = os.path.join("abis", f"{abi_name}.json")
        if os.path.exists(abi_path):
            with open(abi_path, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"ABI file not found: {abi_path}")
            return []
    
    def parse_swap_transaction(self, tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a swap transaction and extract trade details"""
        try:
            to_address = tx.get("to", "").lower()
            input_data = tx.get("input", "")
            
            if not input_data or not input_data.startswith("0x"):
                return None
            
            # Determine router type and parse accordingly
            if to_address == self.uniswap_v2.lower():
                return self._parse_uniswap_v2_tx(tx, input_data)
            elif to_address == self.uniswap_v3.lower():
                return self._parse_uniswap_v3_tx(tx, input_data)
            else:
                return None
                
        except Exception as e:
            logger.debug(f"Failed to parse swap transaction: {e}")
            return None
    
    def _parse_uniswap_v2_tx(self, tx: Dict[str, Any], input_data: str) -> Optional[Dict[str, Any]]:
        """Parse Uniswap V2 transaction"""
        try:
            # Decode function call
            func_obj, params = self.uni_v2_contract.decode_function_input(input_data)
            func_name = func_obj.fn_name
            
            # Extract token addresses and amounts
            if func_name in ["swapExactTokensForTokens", "swapExactETHForTokens"]:
                path = params.get("path", [])
                amount_in = params.get("amountIn", 0)
                amount_out_min = params.get("amountOutMin", 0)
                
                if len(path) < 2:
                    return None
                
                token_in_addr = path[0]
                token_out_addr = path[-1]
                
            elif func_name in ["swapTokensForExactTokens", "swapTokensForExactETH"]:
                path = params.get("path", [])
                amount_in_max = params.get("amountInMax", 0)
                amount_out = params.get("amountOut", 0)
                
                if len(path) < 2:
                    return None
                
                token_in_addr = path[0]
                token_out_addr = path[-1]
                amount_in = amount_in_max
                amount_out_min = amount_out
                
            else:
                return None
            
            # Get token information
            token_in = self.token_manager.get_token_info(token_in_addr)
            token_out = self.token_manager.get_token_info(token_out_addr)
            
            # Convert amounts to human readable
            amount_in_human = self.token_manager.format_amount(amount_in, token_in["decimals"])
            amount_out_min_human = self.token_manager.format_amount(amount_out_min, token_out["decimals"])
            
            return {
                "from": tx["from"],
                "to": tx["to"],
                "fn_name": func_name,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in_human,
                "amount_out_min": amount_out_min_human,
                "raw": tx
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse V2 transaction: {e}")
            return None
    
    def _parse_uniswap_v3_tx(self, tx: Dict[str, Any], input_data: str) -> Optional[Dict[str, Any]]:
        """Parse Uniswap V3 transaction"""
        try:
            # Decode function call
            func_obj, params = self.uni_v3_contract.decode_function_input(input_data)
            func_name = func_obj.fn_name
            
            if func_name == "exactInputSingle":
                # Single token swap
                swap_params = params.get("params", {})
                token_in_addr = swap_params.get("tokenIn")
                token_out_addr = swap_params.get("tokenOut")
                amount_in = swap_params.get("amountIn", 0)
                amount_out_min = swap_params.get("amountOutMinimum", 0)
                fee = swap_params.get("fee", 3000)
                
            elif func_name == "exactInput":
                # Multi-hop swap - would need more complex parsing
                # For now, return None as it's more complex
                return None
                
            else:
                return None
            
            if not token_in_addr or not token_out_addr:
                return None
            
            # Get token information
            token_in = self.token_manager.get_token_info(token_in_addr)
            token_out = self.token_manager.get_token_info(token_out_addr)
            
            # Convert amounts to human readable
            amount_in_human = self.token_manager.format_amount(amount_in, token_in["decimals"])
            amount_out_min_human = self.token_manager.format_amount(amount_out_min, token_out["decimals"])
            
            return {
                "from": tx["from"],
                "to": tx["to"],
                "fn_name": func_name,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in_human,
                "amount_out_min": amount_out_min_human,
                "fee": fee,
                "raw": tx
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse V3 transaction: {e}")
            return None
    
    def extract_token_path(self, tx: Dict[str, Any]) -> Optional[List[str]]:
        """Extract token path from transaction"""
        try:
            to_address = tx.get("to", "").lower()
            input_data = tx.get("input", "")
            
            if to_address == self.uniswap_v2.lower():
                func_obj, params = self.uni_v2_contract.decode_function_input(input_data)
                return params.get("path", [])
            elif to_address == self.uniswap_v3.lower():
                func_obj, params = self.uni_v3_contract.decode_function_input(input_data)
                if func_obj.fn_name == "exactInputSingle":
                    swap_params = params.get("params", {})
                    return [swap_params.get("tokenIn"), swap_params.get("tokenOut")]
            
            return None
            
        except Exception as e:
            logger.debug(f"Failed to extract token path: {e}")
            return None
    
    def is_swap_transaction(self, tx: Dict[str, Any]) -> bool:
        """Check if transaction is a swap transaction"""
        try:
            to_address = tx.get("to", "").lower()
            input_data = tx.get("input", "")
            
            if not input_data or not input_data.startswith("0x"):
                return False
            
            # Check if it's a known router
            if to_address not in [self.uniswap_v2.lower(), self.uniswap_v3.lower()]:
                return False
            
            # Try to decode the function call
            if to_address == self.uniswap_v2.lower():
                func_obj, _ = self.uni_v2_contract.decode_function_input(input_data)
                return func_obj.fn_name.startswith("swap")
            elif to_address == self.uniswap_v3.lower():
                func_obj, _ = self.uni_v3_contract.decode_function_input(input_data)
                return func_obj.fn_name in ["exactInputSingle", "exactInput"]
            
            return False
            
        except Exception:
            return False
