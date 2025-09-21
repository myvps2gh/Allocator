"""
Main entry point for Allocator AI - Modular Version
"""

import os
import sys
import time
import threading
import logging
import argparse
import json
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, try to load manually
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

# Add the allocator package to the path
sys.path.insert(0, str(Path(__file__).parent))

from allocator.config import Config
from allocator.data import DatabaseManager, CacheManager
from allocator.core import WhaleTracker, TradeExecutor, RiskManager, AllocationEngine
from allocator.monitoring import MempoolWatcher
from allocator.web import create_app
from allocator.utils.web3_utils import Web3Manager, TokenManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("allocator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("allocator")


class AllocatorAI:
    """Main Allocator AI application class"""
    
    def __init__(self, config_file: str = "config.json"):
        # Load configuration
        self.config = Config.from_env_and_file(config_file)
        self.config.validate()
        
        # Initialize components
        self.db_manager = DatabaseManager(self.config.database.file_path)
        self.cache_manager = CacheManager()
        
        # Initialize Web3
        self.web3_manager = Web3Manager(self.config.web3.rpc_url)
        self.token_manager = TokenManager(self.web3_manager.w3, self.cache_manager)
        
        # Initialize core components
        self.whale_tracker = WhaleTracker(
            self.config.moralis_api_key,
            self.cache_manager,
            self.db_manager,
            self.config.discovery
        )
        
        self.risk_manager = RiskManager(
            self.config.trading.base_risk,
            max_risk_multiplier=3.0,
            min_risk_multiplier=0.25
        )
        
        self.allocation_engine = AllocationEngine(
            self.config.trading.capital,
            self.config.trading.base_risk
        )
        
        # Initialize trade executor (will be set up when wallet is loaded)
        self.trade_executor = None
        
        # Initialize monitoring
        self.mempool_watcher = None
        
        # Application state
        self.is_running = False
        self.mode = "LIVE"  # Will be set by command line args
    
    def setup_wallet(self, wallet_file: str = "wallet.json"):
        """Setup wallet and trade executor"""
        try:
            from eth_account import Account
            
            # Load wallet
            with open(wallet_file, 'r') as f:
                keyfile = json.load(f)
            
            password = self.config.wallet_password
            private_key = Account.decrypt(keyfile, password)
            account = Account.from_key(private_key)
            wallet_address = account.address
            
            logger.info(f"Loaded wallet: {wallet_address}")
            
            # Initialize trade executor
            self.trade_executor = TradeExecutor(
                self.web3_manager.w3,
                wallet_address,
                private_key,
                self.token_manager,
                self.config.trading.gas_boost
            )
            
            return wallet_address
            
        except Exception as e:
            logger.error(f"Failed to setup wallet: {e}")
            raise
    
    def setup_monitoring(self):
        """Setup mempool monitoring"""
        tracked_whales = set(self.config.tracked_whales)
        
        self.mempool_watcher = MempoolWatcher(
            self.web3_manager.w3,
            tracked_whales,
            self.handle_whale_trade
        )
        
        logger.info(f"Setup monitoring for {len(tracked_whales)} whales")
    
    def handle_whale_trade(self, trade_data: dict):
        """Handle incoming whale trade"""
        try:
            whale_address = trade_data.get("whale_address", "").lower()
            
            # Check if we should follow this whale
            if not self.whale_tracker.should_follow_whale(
                whale_address,
                self.config.trading.min_moralis_roi_pct,
                self.config.trading.min_moralis_profit_usd,
                self.config.trading.min_moralis_trades
            ):
                logger.info(f"Skipping trade from whale {whale_address} - doesn't meet criteria")
                return
            
            # Get whale stats for allocation decision
            whale_stats = self.whale_tracker.get_whale_stats(whale_address)
            risk_profile = self.risk_manager.get_whale_risk_profile(whale_address)
            
            # Make allocation decision
            allocation_decision = self.allocation_engine.decide_allocation(
                trade_data,
                whale_stats.__dict__ if whale_stats else None,
                risk_profile["risk_multiplier"]
            )
            
            if not allocation_decision.should_trade:
                logger.info(f"Skipping trade: {allocation_decision.reason}")
                return
            
            # Check risk limits
            if not self.risk_manager.should_execute_trade(
                whale_address, 
                allocation_decision.allocation_size
            ):
                logger.warning(f"Trade rejected by risk manager for whale {whale_address}")
                return
            
            # Execute trade if not in dry run mode
            if self.mode == "LIVE" and self.trade_executor:
                result = self.trade_executor.execute_trade(trade_data, allocation_decision.allocation_size)
                if result:
                    tx_hash, receipt = result
                    logger.info(f"Executed trade: {tx_hash}")
                    
                    # Log trade to database
                    self._log_trade(trade_data, allocation_decision, tx_hash)
                else:
                    logger.error("Trade execution failed")
            else:
                logger.info(f"[{self.mode}] Would execute trade: {allocation_decision.allocation_size} ETH")
                self._log_trade(trade_data, allocation_decision, "SIMULATED")
            
        except Exception as e:
            logger.error(f"Error handling whale trade: {e}", exc_info=True)
    
    def _log_trade(self, trade_data: dict, allocation_decision, tx_hash: str):
        """Log trade to database"""
        try:
            trade_log = {
                "actor": "allocator",
                "whale": trade_data.get("whale_address", ""),
                "router": trade_data.get("to", ""),
                "path": f"{trade_data.get('token_in', {}).get('symbol', '?')} -> {trade_data.get('token_out', {}).get('symbol', '?')}",
                "side": "buy",  # Simplified
                "amount_in": float(allocation_decision.allocation_size),
                "amount_out": 0,  # Would be filled after execution
                "token_in": trade_data.get("token_in", {}).get("symbol", "?"),
                "token_out": trade_data.get("token_out", {}).get("symbol", "?"),
                "price_impact": 0,
                "gas_cost": 0,
                "pnl": 0,  # Would be calculated after execution
                "cum_pnl": 0,
                "risk_mult": float(allocation_decision.allocation_size / 1000),  # Simplified
                "mode": self.mode,
                "tx_hash": tx_hash
            }
            
            self.db_manager.save_trade(trade_log)
            
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
    
    def start_discovery(self):
        """Start simultaneous whale discovery for all modes"""
        import concurrent.futures
        from allocator.utils.web3_utils import Web3Manager
        
        def run_discovery_mode(mode: str):
            """Run a single discovery mode with its own WebSocket connection"""
            try:
                # Create separate WebSocket connection for this discovery mode
                discovery_web3 = Web3Manager(self.config.web3.rpc_url)
                
                logger.info(f"Starting discovery with mode: {mode}")
                new_whales = self.whale_tracker.discover_whales_from_blocks(
                    discovery_web3.w3,
                    mode,
                    simulate=(self.mode != "LIVE")
                )
                logger.info(f"Discovery mode {mode} found {len(new_whales)} candidate whales")
                return mode, new_whales
                
            except Exception as e:
                logger.error(f"Discovery mode {mode} failed: {e}")
                return mode, []
        
        def discovery_worker():
            while self.is_running:
                try:
                    logger.info(f"Starting simultaneous discovery for modes: {self.config.discovery.modes}")
                    
                    # Run all discovery modes simultaneously with separate WebSocket connections
                    all_candidates = {}
                    
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.config.discovery.modes)) as executor:
                        # Submit all discovery modes simultaneously
                        futures = {
                            executor.submit(run_discovery_mode, mode): mode 
                            for mode in self.config.discovery.modes
                        }
                        
                        # Collect results from all modes
                        for future in concurrent.futures.as_completed(futures):
                            mode = futures[future]
                            try:
                                result_mode, candidates = future.result()
                                all_candidates[result_mode] = candidates
                                logger.info(f"Discovery mode {result_mode} completed successfully")
                            except Exception as e:
                                logger.error(f"Discovery mode {mode} exception: {e}")
                                all_candidates[mode] = []
                    
                    # Validate discovered candidates with Moralis (unless in DRY_RUN_WO_MOR mode)
                    if self.mode == "DRY_RUN_WO_MOR":
                        logger.info("DRY_RUN_WO_MOR mode: Skipping Moralis validation to preserve CU")
                        total_candidates = sum(len(candidates) for candidates in all_candidates.values())
                        logger.info(f"Discovery round completed. Total candidates found: {total_candidates} (not validated)")
                    else:
                        total_validated = 0
                        for mode, candidates in all_candidates.items():
                            logger.info(f"Validating {len(candidates)} candidates from {mode} with Moralis...")
                            
                            validated_count = 0
                            for whale_address in candidates:
                                # Check Moralis PnL to see if whale is worth tracking
                                if self.whale_tracker.bootstrap_whale_from_moralis(
                                    whale_address,
                                    min_roi_pct=self.config.trading.min_moralis_roi_pct,
                                    min_profit_usd=self.config.trading.min_moralis_profit_usd,
                                    min_trades=self.config.trading.min_moralis_trades
                                ):
                                    validated_count += 1
                            
                            logger.info(f"Mode {mode}: {validated_count}/{len(candidates)} whales validated by Moralis")
                            total_validated += validated_count
                        
                        logger.info(f"Discovery round completed. Total validated whales: {total_validated}")
                    
                    # Wait before next discovery round
                    refresh_interval = self.config.discovery.refresh_interval
                    logger.info(f"Discovery round completed. Waiting {refresh_interval} seconds before next round...")
                    time.sleep(refresh_interval)
                    logger.info("Starting next discovery round...")
                    
                except Exception as e:
                    logger.error(f"Discovery worker error: {e}")
                    time.sleep(60)  # Wait before retrying
        
        discovery_thread = threading.Thread(target=discovery_worker, daemon=True)
        discovery_thread.start()
        logger.info(f"Started simultaneous whale discovery for {len(self.config.discovery.modes)} modes")
    
    def start_monitoring(self):
        """Start mempool monitoring"""
        if self.mempool_watcher:
            # Determine mempool usage based on mode
            use_mempool = self.mode in ["LIVE", "DRY_RUN", "DRY_RUN_WO_MOR", "TEST"]
            self.mempool_watcher.start_watching(use_mempool=use_mempool)
            
            monitoring_type = "mempool" if use_mempool else "block"
            logger.info(f"Started {monitoring_type} monitoring for mode: {self.mode}")
    
    def start_dashboard(self, host: str = "0.0.0.0", port: int = 8080):
        """Start web dashboard"""
        try:
            logger.info("Attempting to start dashboard...")
            app = create_app(
                self.whale_tracker,
                self.risk_manager,
                self.db_manager,
                self.mode
            )
            logger.info("Dashboard app created successfully")
            
            def run_dashboard():
                try:
                    logger.info(f"Starting Flask app on {host}:{port}")
                    app.run(host=host, port=port, debug=False, use_reloader=False)
                except Exception as e:
                    logger.error(f"Dashboard runtime error: {e}", exc_info=True)
            
            dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
            dashboard_thread.start()
            logger.info(f"Started dashboard on http://{host}:{port}")
        except Exception as e:
            logger.error(f"Failed to start dashboard: {e}", exc_info=True)
    
    def run(self, mode: str = "LIVE", use_mempool: bool = True):
        """Run the Allocator AI system"""
        self.mode = mode
        self.is_running = True
        
        logger.info(f"Starting Allocator AI in {mode} mode")
        
        try:
            # Setup wallet (skip in test modes if wallet.json doesn't exist)
            if self.mode == "LIVE" or os.path.exists("wallet.json"):
                self.setup_wallet()
            else:
                logger.info(f"Skipping wallet setup for {self.mode} mode (no wallet.json found)")
            
            # Setup monitoring
            self.setup_monitoring()
            
            # Start components (dashboard first, then discovery)
            self.start_dashboard()
            logger.info("Dashboard startup completed")
            
            self.start_monitoring()
            logger.info("Monitoring startup completed")
            
            logger.info("About to start discovery...")
            self.start_discovery()
            logger.info("Discovery startup completed")
            
            # Keep running
            logger.info("Allocator AI is running. Press Ctrl+C to stop.")
            while self.is_running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Shutting down Allocator AI...")
            self.is_running = False
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            self.is_running = False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Allocator AI - Whale Following Trading Bot")
    parser.add_argument("--mode", choices=["LIVE", "DRY_RUN", "DRY_RUN_WO_MOR", "DRY_RUN_MEMPOOLHACK", "TEST"], default="TEST",
                       help="Operation mode: LIVE (real trading), DRY_RUN (simulate with Moralis), DRY_RUN_WO_MOR (simulate without Moralis to save CU), DRY_RUN_MEMPOOLHACK (block monitoring), TEST (basic test)")
    parser.add_argument("--config", default="config.json", help="Configuration file")
    parser.add_argument("--no-mempool", action="store_true", help="Use block monitoring instead of mempool")
    
    args = parser.parse_args()
    
    try:
        # Create and run Allocator AI
        allocator = AllocatorAI(args.config)
        allocator.run(mode=args.mode, use_mempool=not args.no_mempool)
        
    except Exception as e:
        logger.error(f"Failed to start Allocator AI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
