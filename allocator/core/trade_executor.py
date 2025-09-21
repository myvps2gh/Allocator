"""
Trade execution engine for Allocator AI
"""

import time
import threading
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from web3 import Web3
from web3.exceptions import TransactionNotFound
from eth_account import Account

from ..utils.web3_utils import TokenManager
from ..utils.validation import validate_trade_data, ValidationError

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Advanced trade execution engine with error handling and optimization"""
    
    def __init__(self, w3: Web3, wallet_address: str, private_key: bytes, 
                 token_manager: TokenManager, gas_boost: Decimal = Decimal("1.1")):
        self.w3 = w3
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.token_manager = token_manager
        self.gas_boost = gas_boost
        
        # Contract addresses
        self.uniswap_v2 = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
        self.uniswap_v3 = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        
        # Load contract ABIs
        self.v2_abi = self._load_abi("uniswap_v2_router")
        self.v3_abi = self._load_abi("uniswap_v3_router")
        self.erc20_abi = self._load_erc20_abi()
        
        # Create contract instances
        self.uni_v2_contract = w3.eth.contract(address=self.uniswap_v2, abi=self.v2_abi)
        self.uni_v3_contract = w3.eth.contract(address=self.uniswap_v3, abi=self.v3_abi)
        
        # Transaction management
        self.nonce_lock = threading.Lock()
        self.pending_txs = {}  # Track pending transactions
    
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
    
    def _load_erc20_abi(self) -> list:
        """Load ERC20 ABI"""
        return [
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [
                    {"name": "_owner", "type": "address"},
                    {"name": "_spender", "type": "address"}
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            }
        ]
    
    def execute_trade(self, trade_data: Dict[str, Any], 
                     allocation_size: Decimal) -> Optional[Tuple[str, Dict]]:
        """Execute a trade with the given allocation size"""
        
        # Validate trade data
        if not validate_trade_data(trade_data):
            logger.error("Invalid trade data provided")
            return None
        
        try:
            # Determine execution method based on router
            router = trade_data.get("to", "").lower()
            
            if "uniswap" in router:
                if "v3" in router or "0xe592427a" in router:
                    return self._execute_uniswap_v3(trade_data, allocation_size)
                else:
                    return self._execute_uniswap_v2(trade_data, allocation_size)
            else:
                logger.warning(f"Unsupported router: {router}")
                return None
                
        except Exception as e:
            logger.error(f"Trade execution failed: {e}", exc_info=True)
            return None
    
    def _execute_uniswap_v2(self, trade_data: Dict[str, Any], 
                           allocation_size: Decimal) -> Optional[Tuple[str, Dict]]:
        """Execute Uniswap V2 trade"""
        token_in = trade_data["token_in"]
        token_out = trade_data["token_out"]
        
        # Convert allocation to raw amount
        raw_amount = self.token_manager.parse_amount(
            allocation_size, 
            token_in["decimals"]
        )
        
        # Build transaction
        path = [token_in["address"], token_out["address"]]
        deadline = int(time.time()) + 600  # 10 minutes
        
        # Check if approval is needed
        if token_in["symbol"] != "ETH":
            self._ensure_approval(token_in["address"], self.uniswap_v2)
        
        # Build swap transaction
        tx = self.uni_v2_contract.functions.swapExactTokensForTokens(
            raw_amount,
            0,  # Minimum amount out (slippage handled separately)
            path,
            self.wallet_address,
            deadline
        ).build_transaction({
            'from': self.wallet_address,
            'value': 0
        })
        
        return self._send_transaction(tx)
    
    def _execute_uniswap_v3(self, trade_data: Dict[str, Any], 
                           allocation_size: Decimal) -> Optional[Tuple[str, Dict]]:
        """Execute Uniswap V3 trade"""
        token_in = trade_data["token_in"]
        token_out = trade_data["token_out"]
        
        # Convert allocation to raw amount
        raw_amount = self.token_manager.parse_amount(
            allocation_size, 
            token_in["decimals"]
        )
        
        # V3 parameters
        fee = 3000  # 0.3% fee tier
        deadline = int(time.time()) + 600
        
        # Check if approval is needed
        if token_in["symbol"] != "ETH":
            self._ensure_approval(token_in["address"], self.uniswap_v3)
        
        # Build swap parameters
        params = {
            'tokenIn': token_in["address"],
            'tokenOut': token_out["address"],
            'fee': fee,
            'recipient': self.wallet_address,
            'deadline': deadline,
            'amountIn': raw_amount,
            'amountOutMinimum': 0,  # Slippage handled separately
            'sqrtPriceLimitX96': 0
        }
        
        # Build transaction
        tx = self.uni_v3_contract.functions.exactInputSingle(params).build_transaction({
            'from': self.wallet_address,
            'value': raw_amount if token_in["symbol"] == "ETH" else 0
        })
        
        return self._send_transaction(tx)
    
    def _ensure_approval(self, token_address: str, spender: str) -> bool:
        """Ensure token approval for spender"""
        try:
            token_contract = self.w3.eth.contract(address=token_address, abi=self.erc20_abi)
            
            # Check current allowance
            allowance = token_contract.functions.allowance(
                self.wallet_address, 
                spender
            ).call()
            
            # If allowance is less than max, approve max
            if allowance < 2**255:
                approve_tx = token_contract.functions.approve(
                    spender, 
                    2**256 - 1
                ).build_transaction({
                    'from': self.wallet_address
                })
                
                tx_hash, receipt = self._send_transaction(approve_tx)
                if tx_hash:
                    logger.info(f"Approved {token_address} for {spender}")
                    return True
                else:
                    logger.error(f"Failed to approve {token_address}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Approval failed for {token_address}: {e}")
            return False
    
    def _send_transaction(self, tx_dict: Dict[str, Any]) -> Optional[Tuple[str, Dict]]:
        """Send transaction with proper gas estimation and error handling"""
        import threading
        
        with self.nonce_lock:
            try:
                # Set nonce
                tx_dict['nonce'] = self.w3.eth.get_transaction_count(self.wallet_address)
                
                # Set gas price with boost
                gas_price = int(self.w3.eth.gas_price * float(self.gas_boost))
                tx_dict['gasPrice'] = gas_price
                
                # Estimate gas
                if 'gas' not in tx_dict:
                    try:
                        gas_estimate = self.w3.eth.estimate_gas(tx_dict)
                        tx_dict['gas'] = int(gas_estimate * 1.2)  # 20% buffer
                    except Exception as e:
                        logger.warning(f"Gas estimation failed: {e}")
                        tx_dict['gas'] = 500000  # Fallback
                
                # Sign transaction
                signed_tx = self.w3.eth.account.sign_transaction(tx_dict, self.private_key)
                
                # Send transaction
                tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                tx_hash_hex = tx_hash.hex()
                
                logger.info(f"Transaction sent: {tx_hash_hex}")
                
                # Wait for receipt
                try:
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                    
                    if receipt.status == 1:
                        logger.info(f"Transaction successful: {tx_hash_hex}")
                        return tx_hash_hex, receipt
                    else:
                        logger.error(f"Transaction failed: {tx_hash_hex}")
                        return None
                        
                except Exception as e:
                    logger.error(f"Transaction receipt error: {e}")
                    return tx_hash_hex, None
                    
            except Exception as e:
                logger.error(f"Transaction send failed: {e}")
                return None
    
    def simulate_trade(self, trade_data: Dict[str, Any], 
                      allocation_size: Decimal) -> Optional[Dict[str, Any]]:
        """Simulate a trade to estimate output and costs"""
        try:
            token_in = trade_data["token_in"]
            token_out = trade_data["token_out"]
            
            # Convert to raw amount
            raw_amount = self.token_manager.parse_amount(
                allocation_size, 
                token_in["decimals"]
            )
            
            router = trade_data.get("to", "").lower()
            
            if "uniswap" in router:
                if "v3" in router:
                    return self._simulate_uniswap_v3(token_in, token_out, raw_amount)
                else:
                    return self._simulate_uniswap_v2(token_in, token_out, raw_amount)
            
            return None
            
        except Exception as e:
            logger.error(f"Trade simulation failed: {e}")
            return None
    
    def _simulate_uniswap_v2(self, token_in: Dict, token_out: Dict, 
                            raw_amount: int) -> Dict[str, Any]:
        """Simulate Uniswap V2 trade"""
        try:
            path = [token_in["address"], token_out["address"]]
            
            # Get amounts out
            amounts = self.uni_v2_contract.functions.getAmountsOut(
                raw_amount, path
            ).call()
            
            expected_out = self.token_manager.format_amount(
                amounts[-1], 
                token_out["decimals"]
            )
            
            return {
                "expected_out": expected_out,
                "path": path,
                "router": "uniswap_v2"
            }
            
        except Exception as e:
            logger.error(f"V2 simulation failed: {e}")
            return None
    
    def _simulate_uniswap_v3(self, token_in: Dict, token_out: Dict, 
                            raw_amount: int) -> Dict[str, Any]:
        """Simulate Uniswap V3 trade"""
        try:
            # For V3, we'd need a quoter contract
            # This is a simplified simulation
            fee = 3000
            
            # Placeholder calculation (in real implementation, use quoter)
            expected_out = allocation_size * Decimal("0.98")  # Assume 2% slippage
            
            return {
                "expected_out": expected_out,
                "fee": fee,
                "router": "uniswap_v3"
            }
            
        except Exception as e:
            logger.error(f"V3 simulation failed: {e}")
            return None
    
    def get_transaction_status(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get status of a transaction"""
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            
            return {
                "hash": tx_hash,
                "status": receipt.status,
                "gas_used": receipt.gasUsed,
                "gas_price": tx.gasPrice,
                "block_number": receipt.blockNumber
            }
            
        except TransactionNotFound:
            return {"hash": tx_hash, "status": "pending"}
        except Exception as e:
            logger.error(f"Failed to get transaction status: {e}")
            return None
