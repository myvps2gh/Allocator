"""
Web3 utilities for Allocator AI
"""

import logging
from typing import Dict, Any, Optional
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from decimal import Decimal

logger = logging.getLogger(__name__)


class Web3Manager:
    """Web3 connection manager with optimizations"""
    
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.w3 = None
        self._connect()
    
    def _connect(self):
        """Establish Web3 connection"""
        try:
            if self.rpc_url.startswith('ws'):
                # Use LegacyWebSocketProvider with larger message limits for Erigon 3.0.17
                self.w3 = Web3(Web3.LegacyWebSocketProvider(
                    self.rpc_url,
                    websocket_kwargs={
                        'max_size': 20 * 1024 * 1024,  # 20MB message limit
                        'read_limit': 20 * 1024 * 1024,  # 20MB read buffer
                        'write_limit': 20 * 1024 * 1024,  # 20MB write buffer
                    }
                ))
            else:
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            
            # Inject PoA fix (needed on Sepolia, Görli, BSC etc)
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            
            if not self.w3.is_connected():
                raise ConnectionError(f"Failed to connect to RPC: {self.rpc_url}")
            
            logger.info(f"Connected to Web3: {self.w3.eth.chain_id}")
            
        except Exception as e:
            logger.error(f"Web3 connection failed: {e}")
            raise
    
    def is_connected(self) -> bool:
        """Check if Web3 is connected"""
        try:
            return self.w3.is_connected()
        except:
            return False
    
    def get_chain_id(self) -> Optional[int]:
        """Get chain ID"""
        try:
            return self.w3.eth.chain_id
        except:
            return None
    
    def get_gas_price(self) -> Optional[int]:
        """Get current gas price"""
        try:
            return self.w3.eth.gas_price
        except:
            return None
    
    def get_block_number(self) -> Optional[int]:
        """Get latest block number"""
        try:
            return self.w3.eth.block_number
        except:
            return None


class TokenManager:
    """Token metadata and contract management"""
    
    def __init__(self, w3: Web3, cache_manager=None):
        self.w3 = w3
        self.cache = cache_manager
        self.erc20_abi = self._load_erc20_abi()
    
    def _load_erc20_abi(self) -> list:
        """Load ERC20 ABI"""
        # Simplified ERC20 ABI for basic operations
        return [
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "name",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            }
        ]
    
    def get_token_info(self, address: str) -> Dict[str, Any]:
        """Get token information with caching"""
        addr = Web3.to_checksum_address(address)
        
        # Check cache first
        if self.cache:
            cached_info = self.cache.get('token', addr)
            if cached_info:
                return cached_info
        
        try:
            contract = self.w3.eth.contract(address=addr, abi=self.erc20_abi)
            
            # Safe fetch metadata with validation
            try:
                decimals = contract.functions.decimals().call()
                if not isinstance(decimals, int) or decimals < 0 or decimals > 77:
                    decimals = 18
            except Exception as e:
                logger.warning(f"Failed to fetch decimals for {addr}: {e}")
                decimals = 18
            
            try:
                symbol = contract.functions.symbol().call()
                if not isinstance(symbol, str) or len(symbol) > 20:
                    symbol = addr[:6] + "…" + addr[-4:]
            except Exception as e:
                logger.warning(f"Failed to fetch symbol for {addr}: {e}")
                symbol = addr[:6] + "…" + addr[-4:]
            
            try:
                name = contract.functions.name().call()
                if not isinstance(name, str) or len(name) > 50:
                    name = symbol
            except Exception as e:
                logger.warning(f"Failed to fetch name for {addr}: {e}")
                name = symbol
            
            token_info = {
                "contract": contract,
                "decimals": decimals,
                "symbol": symbol,
                "name": name,
                "address": addr
            }
            
            # Cache the result
            if self.cache:
                self.cache.set('token', addr, token_info)
            
            return token_info
            
        except Exception as e:
            logger.error(f"Token info fetch failed for {address}: {e}")
            fallback_info = {
                "contract": None,
                "decimals": 18,
                "symbol": "UNK",
                "name": "Unknown Token",
                "address": addr
            }
            
            if self.cache:
                self.cache.set('token', addr, fallback_info)
            
            return fallback_info
    
    def format_amount(self, raw_amount: int, decimals: int) -> Decimal:
        """Convert raw onchain integer to human float"""
        return Decimal(raw_amount) / (10 ** decimals)
    
    def parse_amount(self, amount: Decimal, decimals: int) -> int:
        """Convert human float to raw onchain integer"""
        return int(amount * (10 ** decimals))
