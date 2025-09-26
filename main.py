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
from allocator.analytics.adaptive_discovery import AdaptiveDiscoveryEngine
from allocator.analytics.market_conditions import MarketConditionAnalyzer

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
        
        # Create adaptive candidates table
        self._create_adaptive_candidates_table()
        
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
            min_risk_multiplier=0.25,
            db_manager=self.db_manager
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
    
    def _create_adaptive_candidates_table(self):
        """Create table for adaptive discovery candidates"""
        with self.db_manager.lock:
            self.db_manager.conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_candidates (
                    address TEXT PRIMARY KEY,
                    activity_score INTEGER,
                    profit_eth REAL,
                    trades INTEGER,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    moralis_validated BOOLEAN DEFAULT FALSE,
                    moralis_roi_pct REAL,
                    moralis_profit_usd REAL,
                    moralis_trades INTEGER,
                    status TEXT DEFAULT 'discovered'
                )
            """)
            self.db_manager.conn.commit()
    
    def _store_adaptive_candidate(self, address: str, discovery_result: dict) -> bool:
        """Store candidate in database if not already exists"""
        try:
            # Check if already exists
            existing = self.db_manager.conn.execute(
                "SELECT address FROM adaptive_candidates WHERE address = ?", (address,)
            ).fetchone()
            
            if existing:
                logger.debug(f"Candidate {address[:10]}... already exists in database")
                return False
            
            # Get candidate stats from discovery result
            thresholds = discovery_result.get("thresholds", {})
            activity_threshold = thresholds.get("trades", 0)
            profit_threshold = thresholds.get("profit", 0)
            
            # Store candidate with initial status
            self.db_manager.conn.execute("""
                INSERT INTO adaptive_candidates 
                (address, activity_score, profit_eth, trades, status, moralis_validated)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (address, activity_threshold, profit_threshold, activity_threshold, "discovered", False))
            
            self.db_manager.conn.commit()
            logger.info(f"Stored new candidate: {address[:10]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store candidate {address}: {e}")
            return False
    
    def _update_adaptive_candidate_status(self, address: str, status: str):
        """Update candidate status"""
        try:
            self.db_manager.conn.execute("""
                UPDATE adaptive_candidates 
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE address = ?
            """, (status, address))
            self.db_manager.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update status for {address}: {e}")
    
    def _update_adaptive_candidate_moralis(self, address: str, moralis_data: dict, status: str):
        """Update candidate with Moralis data"""
        try:
            self.db_manager.conn.execute("""
                UPDATE adaptive_candidates 
                SET moralis_validated = ?,
                    moralis_roi_pct = ?,
                    moralis_profit_usd = ?,
                    moralis_trades = ?,
                    status = ?,
                    processed_at = CURRENT_TIMESTAMP
                WHERE address = ?
            """, (
                status == "validated",
                float(moralis_data["realized_pct"]),
                float(moralis_data["realized_usd"]),
                moralis_data["total_trades"],
                status,
                address
            ))
            self.db_manager.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update Moralis data for {address}: {e}")
    
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
        """Setup mempool monitoring with separate WebSocket connection"""
        from allocator.utils.web3_utils import Web3Manager
        
        tracked_whales = set(self.config.tracked_whales)
        
        # Create separate WebSocket connection for mempool monitoring
        # to avoid conflicts with discovery process
        mempool_web3 = Web3Manager(self.config.web3.rpc_url)
        
        self.mempool_watcher = MempoolWatcher(
            mempool_web3.w3,
            tracked_whales,
            self.handle_whale_trade
        )
        
        logger.info(f"Setup monitoring for {len(tracked_whales)} whales with separate WebSocket connection")
    
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
        """Start simple, reliable sequential whale discovery"""
        
        def run_discovery_mode_http(mode: str):
            """Run discovery mode using HTTP connection (no WebSocket conflicts)"""
            try:
                from allocator.utils.web3_utils import Web3Manager
                from web3 import Web3
                
                logger.info(f"Starting discovery with mode: {mode}")
                start_time = time.time()
                
                # Create HTTP connection for this discovery mode (no async conflicts)
                # Try HTTP on port 8545 first, fallback to same port as WebSocket
                ws_url = self.config.web3.rpc_url
                if ':8546' in ws_url:
                    http_rpc = ws_url.replace('ws://', 'http://').replace(':8546', ':8545')
                else:
                    http_rpc = ws_url.replace('ws://', 'http://').replace('wss://', 'https://')
                
                try:
                    discovery_w3 = Web3(Web3.HTTPProvider(http_rpc))
                    # Test the connection
                    discovery_w3.eth.block_number
                    logger.info(f"Mode {mode}: Using HTTP connection {http_rpc}")
                except Exception as e:
                    # Fallback: try HTTP on the same port as WebSocket
                    logger.warning(f"Mode {mode}: HTTP port 8545 failed ({e}), trying same port as WebSocket")
                    http_rpc_fallback = ws_url.replace('ws://', 'http://').replace('wss://', 'https://')
                    discovery_w3 = Web3(Web3.HTTPProvider(http_rpc_fallback))
                    discovery_w3.eth.block_number  # Test this connection too
                    logger.info(f"Mode {mode}: Using HTTP connection {http_rpc_fallback}")
                
                # Get candidates from blockchain scanning
                candidate_whales = self.whale_tracker.discover_whales_from_blocks(
                    discovery_w3,
                    mode,
                    simulate=True  # Always simulate to get candidates only
                )
                
                scan_duration = time.time() - start_time
                logger.info(f"Discovery mode {mode} found {len(candidate_whales)} candidate whales in {scan_duration:.1f}s")
                
                # Immediately validate with Moralis (unless in DRY_RUN_WO_MOR mode)
                validated_whales = []
                if self.mode == "DRY_RUN_WO_MOR":
                    logger.info(f"Mode {mode}: Skipping Moralis validation (DRY_RUN_WO_MOR)")
                    validated_whales = candidate_whales  # Return candidates without validation
                else:
                    if len(candidate_whales) > 0:
                        logger.info(f"Mode {mode}: Validating {len(candidate_whales)} candidates with Moralis...")
                        
                        for whale_address in candidate_whales:
                            try:
                                # Check Moralis PnL to see if whale is worth tracking
                                if self.whale_tracker.bootstrap_whale_from_moralis(
                                    whale_address,
                                    min_roi_pct=self.config.trading.min_moralis_roi_pct,
                                    min_profit_usd=self.config.trading.min_moralis_profit_usd,
                                    min_trades=self.config.trading.min_moralis_trades
                                ):
                                    validated_whales.append(whale_address)
                                    logger.info(f"Mode {mode}: Whale {whale_address[:10]}... validated and added to tracking")
                            except Exception as e:
                                logger.warning(f"Mode {mode}: Failed to validate whale {whale_address[:10]}...: {e}")
                    
                    logger.info(f"Mode {mode}: {len(validated_whales)}/{len(candidate_whales)} whales validated by Moralis")
                
                total_duration = time.time() - start_time
                logger.info(f"Discovery mode {mode} completed in {total_duration:.1f}s")
                return mode, validated_whales
                
            except Exception as e:
                logger.error(f"Discovery mode {mode} failed: {e}")
                return mode, []

        def discovery_worker():
            while self.is_running:
                try:
                    # Only run adaptive discovery (hardcoded modes commented out)
                    discovery_modes = []
                    
                    # Add adaptive discovery mode if enabled
                    adaptive_config = getattr(self.config.discovery, 'adaptive_discovery', None)
                    if adaptive_config and getattr(adaptive_config, 'enabled', False):
                        discovery_modes.append('adaptive_percentile')
                    
                    # Comment out hardcoded discovery modes to focus on adaptive discovery
                    # discovery_modes = list(self.config.discovery.modes)
                    # discovery_modes.extend(['bot_hunter', 'active_whale', 'quick_profit_whale'])
                    
                    if not discovery_modes:
                        logger.info("No discovery modes enabled, skipping discovery round")
                        time.sleep(60)  # Wait 1 minute before checking again
                        continue
                    
                    logger.info(f"Starting discovery for modes: {discovery_modes}")
                    
                    # Run discovery modes
                    all_validated_whales = {}
                    
                    for mode in discovery_modes:
                        try:
                            if mode == 'adaptive_percentile':
                                # Run adaptive discovery
                                result_mode, validated_whales = self._run_adaptive_discovery_mode()
                                all_validated_whales[result_mode] = validated_whales
                                logger.info(f"Discovery mode {result_mode} completed successfully")
                            else:
                                # Run standard discovery (commented out)
                                # result_mode, validated_whales = run_discovery_mode_http(mode)
                                # all_validated_whales[result_mode] = validated_whales
                                logger.info(f"Standard discovery mode {mode} is disabled")
                        except Exception as e:
                            logger.error(f"Discovery mode {mode} exception: {e}")
                            all_validated_whales[mode] = []
                    
                    # Summary of the discovery round
                    total_validated = sum(len(whales) for whales in all_validated_whales.values())
                    if self.mode == "DRY_RUN_WO_MOR":
                        logger.info(f"Discovery round completed. Total candidates found: {total_validated} (not validated with Moralis)")
                    else:
                        logger.info(f"Discovery round completed. Total validated whales: {total_validated}")
                    
                    # Log detailed results per mode
                    for mode, whales in all_validated_whales.items():
                        if len(whales) > 0:
                            whale_preview = [whale[:10] + "..." for whale in whales[:3]]
                            logger.info(f"Mode {mode} result: {len(whales)} whales {whale_preview}")
                    
                    # Token data fetching is now handled immediately during validation
                    
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
        logger.info(f"Started PARALLEL whale discovery for {len(self.config.discovery.modes)} modes using HTTP connections")
    
    
    def _run_adaptive_discovery_mode(self):
        """Run adaptive percentile-based discovery mode with automatic validation and token fetching"""
        try:
            logger.info("Starting discovery with mode: adaptive_percentile")
            start_time = time.time()
            
            # Get adaptive configuration
            adaptive_config = getattr(self.config.discovery, 'adaptive_discovery', None)
            if not adaptive_config:
                logger.warning("Adaptive discovery config not found")
                return "adaptive_percentile", []
            
            # Initialize adaptive components if needed
            if self.whale_tracker.market_analyzer is None:
                self.whale_tracker.market_analyzer = MarketConditionAnalyzer(self.web3_manager.w3, self.whale_tracker.cache)
            
            if self.whale_tracker.adaptive_engine is None:
                self.whale_tracker.adaptive_engine = AdaptiveDiscoveryEngine(self.web3_manager.w3, self.whale_tracker.market_analyzer)
            
            # Get percentile configuration
            percentile_config = getattr(adaptive_config, "percentile_mode", {}) or {}
            if not percentile_config.get("enabled", False):
                logger.info("Adaptive percentile discovery is disabled")
                return "adaptive_percentile", []
            
            activity_percentile = percentile_config.get("activity_percentile", 5.0)
            profit_percentile = percentile_config.get("profit_percentile", 25.0)
            blocks_back = percentile_config.get("blocks_back", 10000)
            
            logger.info(f"Running adaptive discovery: top {activity_percentile}% activity, "
                       f"top {profit_percentile}% profit over {blocks_back} blocks")
            
            # Run adaptive discovery
            result = self.whale_tracker.adaptive_engine.discover_whales_percentile(
                activity_percentile=activity_percentile,
                profit_percentile=profit_percentile,
                blocks_back=blocks_back
            )
            
            candidates = result.get("candidates", [])
            logger.info(f"Found {len(candidates)} adaptive candidates")
            
            # Store candidates in database and get candidates to process
            new_candidates = []
            for candidate in candidates:
                if self._store_adaptive_candidate(candidate, result):
                    new_candidates.append(candidate)
            
            logger.info(f"Stored {len(new_candidates)} new candidates in database")
            
            # Get candidates to process (both new and existing unvalidated ones)
            candidates_to_process = []
            
            # Add new candidates
            candidates_to_process.extend(new_candidates)
            
            # Add existing unvalidated candidates
            existing_unvalidated = self.db_manager.conn.execute("""
                SELECT address FROM adaptive_candidates 
                WHERE moralis_validated = FALSE 
                AND status IN ('discovered', 'failed_moralis', 'error')
                ORDER BY discovered_at 
            """).fetchall()
            
            for (address,) in existing_unvalidated:
                if address not in candidates_to_process:
                    candidates_to_process.append(address)
            
            logger.info(f"Processing {len(candidates_to_process)} candidates (new: {len(new_candidates)}, existing: {len(candidates_to_process) - len(new_candidates)})")
            
            # Validate candidates with Moralis (like test_adaptive_discovery.py)
            validated_whales = []
            if candidates_to_process and self.mode != "DRY_RUN_WO_MOR":
                logger.info(f"Validating {len(candidates_to_process)} candidates with Moralis...")
                
                for i, candidate in enumerate(candidates_to_process):
                    try:
                        logger.info(f"Validating candidate {i+1}/{len(candidates_to_process)}: {candidate[:10]}...")
                        candidate_start_time = time.time()
                        
                        # Fetch Moralis data
                        moralis_data = self.whale_tracker.fetch_moralis_data(candidate)
                        if not moralis_data:
                            logger.warning(f"Failed to fetch Moralis data for {candidate[:10]}...")
                            self._update_adaptive_candidate_status(candidate, "failed_moralis")
                            continue
                        
                        # Check if meets criteria
                        min_roi_pct = self.config.trading.min_moralis_roi_pct
                        min_profit_usd = self.config.trading.min_moralis_profit_usd
                        min_trades = self.config.trading.min_moralis_trades
                        
                        if (moralis_data["realized_pct"] < min_roi_pct or 
                            moralis_data["realized_usd"] < min_profit_usd or 
                            moralis_data["total_trades"] < min_trades):
                            logger.info(f"Candidate {candidate[:10]}... rejected: "
                                      f"{moralis_data['realized_pct']}% ROI, "
                                      f"${moralis_data['realized_usd']} profit, "
                                      f"{moralis_data['total_trades']} trades")
                            self._update_adaptive_candidate_moralis(candidate, moralis_data, "rejected")
                            continue
                        
                        # Add to main whales table
                        if self.whale_tracker.bootstrap_whale_from_moralis(candidate):
                            validated_whales.append(candidate)
                            self._update_adaptive_candidate_moralis(candidate, moralis_data, "validated")
                            
                            # Immediately fetch token data (like test_adaptive_discovery.py)
                            try:
                                logger.info(f"Fetching token data for validated whale {candidate[:10]}...")
                                token_start_time = time.time()
                                self.whale_tracker.fetch_token_data_from_moralis(candidate)
                                self._update_adaptive_candidate_status(candidate, "tokens_fetched")
                                token_elapsed = time.time() - token_start_time
                                logger.info(f"✅ Token data fetched for {candidate[:10]}... ({token_elapsed:.1f}s)")
                            except Exception as e:
                                logger.error(f"Error fetching token data for {candidate[:10]}...: {e}")
                                self._update_adaptive_candidate_status(candidate, "token_error")
                            
                            candidate_elapsed = time.time() - candidate_start_time
                            logger.info(f"✅ Candidate {candidate[:10]}... validated and added to tracking ({candidate_elapsed:.1f}s)")
                        else:
                            logger.info(f"❌ Candidate {candidate[:10]}... rejected by bootstrap_whale_from_moralis")
                            self._update_adaptive_candidate_moralis(candidate, moralis_data, "rejected")
                        
                        # Small delay to respect rate limits
                        time.sleep(0.5)
                        
                    except Exception as e:
                        logger.error(f"Error validating {candidate[:10]}...: {e}")
                        self._update_adaptive_candidate_status(candidate, "error")
                
                logger.info(f"Validated {len(validated_whales)} candidates successfully")
            elif self.mode == "DRY_RUN_WO_MOR":
                logger.info("Mode adaptive_percentile: Skipping Moralis validation (DRY_RUN_WO_MOR)")
                validated_whales = candidates_to_process
            
            # Log detailed summary like the test script
            if validated_whales:
                whale_preview = [whale[:10] + "..." for whale in validated_whales[:3]]
                logger.info(f"Adaptive discovery result: {len(validated_whales)} whales validated {whale_preview}")
            
            # Return validated whales like the old discovery modes
            total_duration = time.time() - start_time
            logger.info(f"Discovery mode adaptive_percentile completed in {total_duration:.1f}s")
            return "adaptive_percentile", validated_whales
            
        except Exception as e:
            logger.error(f"Discovery mode adaptive_percentile failed: {e}")
            return "adaptive_percentile", []
    
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
    parser.add_argument("--refresh-whales", action="store_true", 
                       help="Refresh metrics for all tracked whales and exit")
    parser.add_argument("--simulate-trades", action="store_true",
                       help="Include trade simulation when refreshing whale metrics")
    parser.add_argument("--recalc-scores", action="store_true",
                       help="Recalculate all whale scores using Score Formula v2.0 and exit")
    parser.add_argument("--fetch-tokens", action="store_true",
                       help="Fetch real token-level data from Moralis for all whales and exit")
    parser.add_argument("--clear-tokens", action="store_true",
                       help="Clear all whale token data and exit")
    parser.add_argument("--process-adaptive", action="store_true",
                       help="Process adaptive candidates (validate with Moralis and fetch tokens)")
    parser.add_argument("--show-adaptive", action="store_true",
                       help="Show status of adaptive candidates")
    
    args = parser.parse_args()
    
    try:
        # Create and run Allocator AI
        allocator = AllocatorAI(args.config)
        
        # Handle whale refresh command
        if args.refresh_whales:
            logger.info("Refreshing whale metrics...")
            allocator.whale_tracker.refresh_all_whale_metrics(simulate_trades=args.simulate_trades)
            logger.info("Whale metrics refresh completed!")
            return
        
        # Handle score recalculation command
        if args.recalc_scores:
            logger.info("Recalculating all whale scores using Score Formula v2.0...")
            
            # Load existing whales from database
            db_whales = allocator.db_manager.get_all_whales()
            for whale_data in db_whales:
                allocator.whale_tracker.tracked_whales.add(whale_data[0])
            
            logger.info(f"Found {len(allocator.whale_tracker.tracked_whales)} tracked whales")
            
            # First, fetch real token data from Moralis for whales that don't have it
            logger.info("Step 1: Fetching real token data from Moralis for existing whales...")
            fetch_count = 0
            for whale_address in allocator.whale_tracker.tracked_whales:
                try:
                    # Check if whale has token data
                    existing_tokens = allocator.db_manager.get_whale_token_breakdown(whale_address)
                    if not existing_tokens:
                        allocator.whale_tracker.fetch_token_data_from_moralis(whale_address)
                        fetch_count += 1
                        
                        # Add small delay to respect rate limits
                        import time
                        time.sleep(1)
                    else:
                        logger.debug(f"Whale {whale_address} already has {len(existing_tokens)} token records")
                except Exception as e:
                    logger.error(f"Error fetching token data for {whale_address}: {e}")
            
            logger.info(f"Fetched real token data from Moralis for {fetch_count} whales")
            
            # Now recalculate scores for all whales
            logger.info("Step 2: Recalculating scores using Score Formula v2.0...")
            updated_count = 0
            for whale_address in allocator.whale_tracker.tracked_whales:
                try:
                    # Load whale stats into memory first
                    whale_data = allocator.db_manager.get_whale(whale_address)
                    if whale_data:
                        # Create whale stats object if it doesn't exist
                        if whale_address not in allocator.whale_tracker.whale_scores:
                            from allocator.core.whale_tracker import WhaleStats
                            from decimal import Decimal
                            import decimal
                            
                            # Safe conversion function for Decimal fields
                            def safe_decimal(value, default="0"):
                                if value is None or value == '':
                                    return Decimal(default)
                                try:
                                    return Decimal(str(value))
                                except (ValueError, decimal.InvalidOperation, decimal.ConversionSyntax):
                                    logger.warning(f"Invalid decimal value: {value}, using default: {default}")
                                    return Decimal(default)
                            
                            allocator.whale_tracker.whale_scores[whale_address] = WhaleStats(
                                address=whale_address,
                                score=safe_decimal(whale_data[9], "0"),  # score (index 9)
                                roi=safe_decimal(whale_data[6], "0"),    # cumulative_pnl (index 6)
                                trades=whale_data[3] or 0,               # trades (index 3)
                                win_rate=safe_decimal(whale_data[10], "0"), # win_rate (index 10)
                                volatility=Decimal("1"),
                                sharpe_ratio=Decimal("0"),
                                moralis_roi_pct=safe_decimal(whale_data[1], "0"),  # moralis_roi_pct (index 1)
                                moralis_profit_usd=safe_decimal(whale_data[2], "0"), # roi_usd (index 2)
                                moralis_trades=whale_data[3] or 0  # trades (index 3)
                            )
                    
                    # Calculate new score
                    new_score = allocator.whale_tracker.calculate_score_v2(whale_address)
                    if new_score is not None and new_score > 0:
                        allocator.db_manager.update_whale_performance(whale_address, score=new_score)
                        updated_count += 1
                        
                        # Get diversity factor for logging
                        diversity = allocator.whale_tracker.calculate_diversity_factor(whale_address)
                        tokens = allocator.db_manager.get_whale_token_breakdown(whale_address)
                        
                        logger.info(f"Updated {whale_address[:10]}...: Score v2.0 = {new_score:.2f} "
                                  f"(diversity: {diversity:.3f}, tokens: {len(tokens)})")
                    elif new_score is None:
                        logger.warning(f"Whale {whale_address} calculated score is None - skipping update")
                    else:
                        logger.warning(f"Whale {whale_address} calculated score is 0 - skipping update")
                        
                except Exception as e:
                    logger.error(f"Error recalculating score for {whale_address}: {e}")
                    logger.error(f"Error type: {type(e)}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
            
            logger.info(f"Score recalculation completed! Updated {updated_count}/{len(allocator.whale_tracker.tracked_whales)} whales.")
            return
        
        # Handle clear tokens command
        if args.clear_tokens:
            logger.info("Clearing all whale token data...")
            
            # Clear the whale_token_pnl table
            with allocator.db_manager.lock:
                cursor = allocator.db_manager.conn.execute("DELETE FROM whale_token_pnl")
                deleted_count = cursor.rowcount
                allocator.db_manager.conn.commit()
            
            logger.info(f"Cleared {deleted_count} token records from database")
            return
        
        # Handle adaptive candidates processing
        if args.process_adaptive:
            logger.info("Processing adaptive candidates...")
            
            # Get unvalidated candidates
            candidates = allocator.db_manager.conn.execute("""
                SELECT address FROM adaptive_candidates 
                WHERE moralis_validated = FALSE 
                ORDER BY discovered_at 
                LIMIT 20
            """).fetchall()
            
            if not candidates:
                logger.info("No unvalidated adaptive candidates found")
                return
            
            logger.info(f"Validating {len(candidates)} adaptive candidates with Moralis...")
            validated_count = 0
            
            for i, (address,) in enumerate(candidates):
                try:
                    logger.info(f"Validating candidate {i+1}/{len(candidates)}: {address[:10]}...")
                    start_time = time.time()
                    
                    # Fetch Moralis data
                    moralis_data = allocator.whale_tracker.fetch_moralis_data(address)
                    if not moralis_data:
                        logger.warning(f"Failed to fetch Moralis data for {address[:10]}...")
                        continue
                    
                    # Check if meets criteria
                    min_roi_pct = Decimal("5")
                    min_profit_usd = Decimal("500")
                    min_trades = 5
                    
                    if (moralis_data["realized_pct"] < min_roi_pct or 
                        moralis_data["realized_usd"] < min_profit_usd or 
                        moralis_data["total_trades"] < min_trades):
                        logger.info(f"Candidate {address[:10]}... rejected: "
                                  f"{moralis_data['realized_pct']}% ROI, "
                                  f"${moralis_data['realized_usd']} profit, "
                                  f"{moralis_data['total_trades']} trades")
                        continue
                    
                    # Add to main whales table
                    if allocator.whale_tracker.bootstrap_whale_from_moralis(address):
                        validated_count += 1
                        logger.info(f"✅ Candidate {address[:10]}... added to main whales")
                        
                        # Update adaptive candidates table
                        allocator.db_manager.conn.execute("""
                            UPDATE adaptive_candidates 
                            SET moralis_validated = TRUE,
                                moralis_roi_pct = ?,
                                moralis_profit_usd = ?,
                                moralis_trades = ?,
                                status = 'validated',
                                processed_at = CURRENT_TIMESTAMP
                            WHERE address = ?
                        """, (
                            float(moralis_data["realized_pct"]),
                            float(moralis_data["realized_usd"]),
                            moralis_data["total_trades"],
                            address
                        ))
                        allocator.db_manager.conn.commit()
                    
                    elapsed = time.time() - start_time
                    logger.info(f"Processed {address[:10]}... in {elapsed:.1f}s")
                    
                    # Small delay to respect rate limits
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error processing {address[:10]}...: {e}")
            
            logger.info(f"Processed {validated_count} adaptive candidates successfully")
            return
        
        # Handle show adaptive candidates status
        if args.show_adaptive:
            logger.info("Adaptive Candidates Status:")
            
            # Get summary statistics
            stats = allocator.db_manager.conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN moralis_validated = TRUE THEN 1 ELSE 0 END) as validated,
                    SUM(CASE WHEN status = 'tokens_fetched' THEN 1 ELSE 0 END) as tokens_fetched,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
                FROM adaptive_candidates
            """).fetchone()
            
            logger.info(f"  Total discovered: {stats[0]}")
            logger.info(f"  Moralis validated: {stats[1]}")
            logger.info(f"  Token data fetched: {stats[2]}")
            logger.info(f"  Rejected: {stats[3]}")
            
            # Show recent candidates
            recent = allocator.db_manager.conn.execute("""
                SELECT address, status, moralis_roi_pct, moralis_profit_usd, moralis_trades
                FROM adaptive_candidates 
                ORDER BY discovered_at DESC 
                LIMIT 10
            """).fetchall()
            
            if recent:
                logger.info("Recent candidates:")
                for address, status, roi, profit, trades in recent:
                    logger.info(f"  {address[:10]}... | {status} | {roi or 'N/A'}% ROI | ${profit or 'N/A'} | {trades or 'N/A'} trades")
            
            return
        
        
        # Handle token data fetching command
        if args.fetch_tokens:
            logger.info("Fetching real token-level data from Moralis for all whales...")
            
            # Load existing whales from database
            db_whales = allocator.db_manager.get_all_whales()
            for whale_data in db_whales:
                allocator.whale_tracker.tracked_whales.add(whale_data[0])
            
            logger.info(f"Found {len(allocator.whale_tracker.tracked_whales)} tracked whales")
            
            # Fetch token data from Moralis
            fetch_count = 0
            total_tokens = 0
            for whale_address in allocator.whale_tracker.tracked_whales:
                try:
                    logger.info(f"Processing whale {whale_address[:10]}... ({fetch_count + 1}/{len(allocator.whale_tracker.tracked_whales)})")
                    
                    # Check if whale already has token data
                    existing_tokens = allocator.db_manager.get_whale_token_breakdown(whale_address)
                    if existing_tokens:
                        logger.info(f"  Already has {len(existing_tokens)} token records - skipping")
                        continue
                    
                    # Fetch from Moralis
                    allocator.whale_tracker.fetch_token_data_from_moralis(whale_address)
                    fetch_count += 1
                    
                    # Check what was fetched
                    new_tokens = allocator.db_manager.get_whale_token_breakdown(whale_address)
                    total_tokens += len(new_tokens)
                    
                    # Rate limiting delay
                    import time
                    time.sleep(1.2)  # 50 requests per minute max for free Moralis
                    
                except Exception as e:
                    logger.error(f"Error fetching token data for {whale_address}: {e}")
            
            logger.info(f"Token data fetching completed! Processed {fetch_count} whales, got {total_tokens} total token records.")
            return
        
        allocator.run(mode=args.mode, use_mempool=not args.no_mempool)
        
    except Exception as e:
        logger.error(f"Failed to start Allocator AI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
