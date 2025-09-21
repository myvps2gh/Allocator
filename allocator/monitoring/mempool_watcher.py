"""
Mempool monitoring and transaction processing
"""

import time
import logging
from typing import Dict, Any, List, Optional, Callable
from web3 import Web3
from web3.exceptions import TransactionNotFound

from .trade_parser import TradeParser
from ..utils.validation import validate_trade_data

logger = logging.getLogger(__name__)


class MempoolWatcher:
    """Advanced mempool watcher with filtering and processing"""
    
    def __init__(self, w3: Web3, tracked_whales: set, 
                 trade_callback: Optional[Callable] = None):
        self.w3 = w3
        self.tracked_whales = tracked_whales
        self.trade_callback = trade_callback
        self.trade_parser = TradeParser(w3)
        
        # Router addresses to monitor (checksummed)
        self.monitored_routers = {
            Web3.to_checksum_address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D").lower(),  # Uniswap V2
            Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564").lower()   # Uniswap V3
        }
        
        # State
        self.is_running = False
        self.last_processed_block = 0
        
    def start_watching(self, use_mempool: bool = True) -> None:
        """Start watching for whale transactions"""
        import threading
        
        self.is_running = True
        
        def watch_worker():
            if use_mempool:
                self._watch_mempool()
            else:
                self._watch_blocks()
        
        # Run monitoring in background thread
        watch_thread = threading.Thread(target=watch_worker, daemon=True)
        watch_thread.start()
        logger.info(f"Started {'mempool' if use_mempool else 'block'} monitoring in background thread")
    
    def stop_watching(self) -> None:
        """Stop watching"""
        self.is_running = False
        logger.info("Mempool watcher stopped")
    
    def _watch_mempool(self) -> None:
        """Watch pending mempool transactions"""
        logger.info("Starting mempool monitoring...")
        
        try:
            pending_filter = self.w3.eth.filter("pending")
            
            while self.is_running:
                try:
                    # Get new pending transactions
                    for tx_hash in pending_filter.get_new_entries():
                        if not self.is_running:
                            break
                        
                        try:
                            self._process_transaction(tx_hash)
                        except TransactionNotFound:
                            # Transaction was removed from mempool
                            continue
                        except Exception as e:
                            logger.debug(f"Error processing transaction {tx_hash}: {e}")
                            continue
                    
                    time.sleep(0.5)  # Small delay to prevent excessive CPU usage
                    
                except Exception as e:
                    logger.error(f"Mempool watcher error: {e}")
                    time.sleep(3)  # Wait before retrying
                    
        except Exception as e:
            logger.error(f"Failed to start mempool watcher: {e}")
            self.is_running = False
    
    def _watch_blocks(self) -> None:
        """Watch confirmed blocks (fallback when mempool not available)"""
        logger.info("Starting block monitoring (mempool fallback)...")
        
        last_block = self.w3.eth.block_number
        
        while self.is_running:
            try:
                current_block = self.w3.eth.block_number
                
                if current_block > last_block:
                    # Process new blocks
                    for block_num in range(last_block + 1, current_block + 1):
                        if not self.is_running:
                            break
                        
                        self._process_block(block_num)
                    
                    last_block = current_block
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.error(f"Block watcher error: {e}")
                time.sleep(5)
    
    def _process_transaction(self, tx_hash: str) -> None:
        """Process a single transaction"""
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            self._process_tx_data(tx)
        except Exception as e:
            logger.debug(f"Failed to process transaction {tx_hash}: {e}")
    
    def _process_block(self, block_number: int) -> None:
        """Process all transactions in a block"""
        try:
            block = self.w3.eth.get_block(block_number, full_transactions=True)
            
            for tx in block.transactions:
                if not self.is_running:
                    break
                
                self._process_tx_data(tx)
                
        except Exception as e:
            logger.debug(f"Failed to process block {block_number}: {e}")
    
    def _process_tx_data(self, tx: Dict[str, Any]) -> None:
        """Process transaction data and check if it's from a tracked whale"""
        try:
            # Check if transaction is from a tracked whale
            from_address = tx.get("from", "").lower()
            if from_address not in self.tracked_whales:
                return
            
            # Check if transaction is to a monitored router
            to_address = tx.get("to", "").lower()
            if to_address not in self.monitored_routers:
                return
            
            # Parse the trade
            trade_data = self.trade_parser.parse_swap_transaction(tx)
            if not trade_data:
                return
            
            # Validate trade data
            if not validate_trade_data(trade_data):
                logger.warning(f"Invalid trade data from {from_address}")
                return
            
            # Add whale address to trade data
            trade_data["whale_address"] = from_address
            
            logger.info(f"Detected whale trade: {from_address} -> {trade_data.get('token_in', {}).get('symbol', '?')} to {trade_data.get('token_out', {}).get('symbol', '?')}")
            
            # Call the trade callback if provided
            if self.trade_callback:
                try:
                    self.trade_callback(trade_data)
                except Exception as e:
                    logger.error(f"Trade callback error: {e}")
                    
        except Exception as e:
            logger.debug(f"Error processing transaction data: {e}")
    
    def add_whale(self, whale_address: str) -> None:
        """Add a whale to the watch list"""
        self.tracked_whales.add(whale_address.lower())
        logger.info(f"Added whale to watch list: {whale_address}")
    
    def remove_whale(self, whale_address: str) -> None:
        """Remove a whale from the watch list"""
        self.tracked_whales.discard(whale_address.lower())
        logger.info(f"Removed whale from watch list: {whale_address}")
    
    def get_watched_whales(self) -> List[str]:
        """Get list of watched whale addresses"""
        return list(self.tracked_whales)
    
    def is_whale_tracked(self, whale_address: str) -> bool:
        """Check if a whale is being tracked"""
        return whale_address.lower() in self.tracked_whales
    
    def get_status(self) -> Dict[str, Any]:
        """Get watcher status"""
        return {
            "is_running": self.is_running,
            "tracked_whales": len(self.tracked_whales),
            "monitored_routers": len(self.monitored_routers),
            "last_processed_block": self.last_processed_block
        }
