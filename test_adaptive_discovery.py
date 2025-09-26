#!/usr/bin/env python3
"""
Test script for adaptive whale discovery
Fetches adaptive candidates and processes them separately from the main bot
"""

import os
import sys
import time
import logging
import argparse
from pathlib import Path
from decimal import Decimal

# Add the allocator package to the path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual env loading
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

from allocator.config import Config
from allocator.data import DatabaseManager, CacheManager
from allocator.core import WhaleTracker
from allocator.utils.web3_utils import Web3Manager
from allocator.analytics.adaptive_discovery import AdaptiveDiscoveryEngine
from allocator.analytics.market_conditions import MarketConditionAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("adaptive_discovery.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("adaptive_discovery")


class AdaptiveDiscoveryTester:
    """Test adaptive discovery independently"""
    
    def __init__(self, config_file: str = "config.json"):
        # Load configuration
        self.config = Config.from_env_and_file(config_file)
        self.config.validate()
        
        # Initialize components
        self.db_manager = DatabaseManager(self.config.database.file_path)
        self.cache_manager = CacheManager()
        
        # Initialize Web3
        self.web3_manager = Web3Manager(self.config.web3.rpc_url)
        
        # Initialize adaptive components
        self.market_analyzer = MarketConditionAnalyzer(self.web3_manager.w3, self.cache_manager)
        self.adaptive_engine = AdaptiveDiscoveryEngine(self.web3_manager.w3, self.market_analyzer)
        
        # Initialize whale tracker for Moralis calls
        self.whale_tracker = WhaleTracker(
            self.config.moralis_api_key,
            self.cache_manager,
            self.db_manager,
            self.config.discovery
        )
        
        # Create adaptive candidates table
        self._create_adaptive_candidates_table()
    
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
            logger.info("Adaptive candidates table ready")
    
    def discover_adaptive_candidates(self, max_candidates: int = 50) -> list:
        """Discover adaptive candidates using percentile-based thresholds"""
        try:
            # Get adaptive configuration
            adaptive_config = getattr(self.config.discovery, 'adaptive_discovery', None)
            if not adaptive_config:
                logger.error("Adaptive discovery config not found")
                return []
            
            percentile_config = getattr(adaptive_config, "percentile_mode", {}) or {}
            if not percentile_config.get("enabled", False):
                logger.error("Adaptive percentile discovery is disabled")
                return []
            
            activity_percentile = percentile_config.get("activity_percentile", 5.0)
            profit_percentile = percentile_config.get("profit_percentile", 25.0)
            blocks_back = percentile_config.get("blocks_back", 10000)
            
            logger.info(f"Running adaptive discovery: top {activity_percentile}% activity, "
                       f"top {profit_percentile}% profit over {blocks_back} blocks")
            
            # Run adaptive discovery
            result = self.adaptive_engine.discover_whales_percentile(
                activity_percentile=activity_percentile,
                profit_percentile=profit_percentile,
                blocks_back=blocks_back
            )
            
            candidates = result.get("candidates", [])
            logger.info(f"Found {len(candidates)} adaptive candidates")
            
            # Store candidates in database
            new_candidates = []
            for candidate in candidates[:max_candidates]:
                if self._store_candidate(candidate, result):
                    new_candidates.append(candidate)
            
            logger.info(f"Stored {len(new_candidates)} new candidates in database")
            return new_candidates
            
        except Exception as e:
            logger.error(f"Adaptive discovery failed: {e}")
            return []
    
    def _store_candidate(self, address: str, discovery_result: dict) -> bool:
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
            
            # Store candidate
            self.db_manager.conn.execute("""
                INSERT INTO adaptive_candidates 
                (address, activity_score, profit_eth, trades, status)
                VALUES (?, ?, ?, ?, ?)
            """, (address, activity_threshold, profit_threshold, activity_threshold, "discovered"))
            
            self.db_manager.conn.commit()
            logger.info(f"Stored new candidate: {address[:10]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store candidate {address}: {e}")
            return False
    
    def validate_candidates_with_moralis(self, max_candidates: int = 20) -> list:
        """Validate candidates with Moralis API"""
        try:
            # Get unprocessed candidates
            candidates = self.db_manager.conn.execute("""
                SELECT address FROM adaptive_candidates 
                WHERE moralis_validated = FALSE 
                ORDER BY discovered_at 
                LIMIT ?
            """, (max_candidates,)).fetchall()
            
            if not candidates:
                logger.info("No unvalidated candidates found")
                return []
            
            logger.info(f"Validating {len(candidates)} candidates with Moralis...")
            validated_candidates = []
            
            for i, (address,) in enumerate(candidates):
                try:
                    logger.info(f"Validating candidate {i+1}/{len(candidates)}: {address[:10]}...")
                    start_time = time.time()
                    
                    # Fetch Moralis data
                    moralis_data = self.whale_tracker.fetch_moralis_data(address)
                    if not moralis_data:
                        logger.warning(f"Failed to fetch Moralis data for {address[:10]}...")
                        self._update_candidate_status(address, "failed_moralis")
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
                        self._update_candidate_status(address, "rejected")
                        continue
                    
                    # Update candidate with Moralis data
                    self._update_candidate_moralis(address, moralis_data)
                    validated_candidates.append(address)
                    
                    elapsed = time.time() - start_time
                    logger.info(f"✅ Candidate {address[:10]}... validated ({elapsed:.1f}s)")
                    
                    # Small delay to respect rate limits
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error validating {address[:10]}...: {e}")
                    self._update_candidate_status(address, "error")
            
            logger.info(f"Validated {len(validated_candidates)} candidates successfully")
            return validated_candidates
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return []
    
    def _update_candidate_status(self, address: str, status: str):
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
    
    def _update_candidate_moralis(self, address: str, moralis_data: dict):
        """Update candidate with Moralis data"""
        try:
            self.db_manager.conn.execute("""
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
            self.db_manager.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update Moralis data for {address}: {e}")
    
    def fetch_token_data_for_validated(self, max_candidates: int = 10) -> int:
        """Fetch token data for validated candidates"""
        try:
            # Get validated candidates without token data
            candidates = self.db_manager.conn.execute("""
                SELECT address FROM adaptive_candidates 
                WHERE moralis_validated = TRUE 
                AND status = 'validated'
                ORDER BY processed_at 
                LIMIT ?
            """, (max_candidates,)).fetchall()
            
            if not candidates:
                logger.info("No validated candidates found for token data fetching")
                return 0
            
            logger.info(f"Fetching token data for {len(candidates)} validated candidates...")
            processed_count = 0
            
            for i, (address,) in enumerate(candidates):
                try:
                    logger.info(f"Fetching tokens for candidate {i+1}/{len(candidates)}: {address[:10]}...")
                    start_time = time.time()
                    
                    # Fetch token data
                    self.whale_tracker.fetch_token_data_from_moralis(address)
                    
                    # Update status
                    self._update_candidate_status(address, "tokens_fetched")
                    processed_count += 1
                    
                    elapsed = time.time() - start_time
                    logger.info(f"✅ Token data fetched for {address[:10]}... ({elapsed:.1f}s)")
                    
                    # Delay to respect rate limits
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error fetching token data for {address[:10]}...: {e}")
                    self._update_candidate_status(address, "token_error")
            
            logger.info(f"Fetched token data for {processed_count} candidates")
            return processed_count
            
        except Exception as e:
            logger.error(f"Token data fetching failed: {e}")
            return 0
    
    def show_candidates_summary(self):
        """Show summary of all candidates"""
        try:
            # Get summary statistics
            stats = self.db_manager.conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN moralis_validated = TRUE THEN 1 ELSE 0 END) as validated,
                    SUM(CASE WHEN status = 'tokens_fetched' THEN 1 ELSE 0 END) as tokens_fetched,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
                FROM adaptive_candidates
            """).fetchone()
            
            logger.info(f"Adaptive Candidates Summary:")
            logger.info(f"  Total discovered: {stats[0]}")
            logger.info(f"  Moralis validated: {stats[1]}")
            logger.info(f"  Token data fetched: {stats[2]}")
            logger.info(f"  Rejected: {stats[3]}")
            
            # Show recent candidates
            recent = self.db_manager.conn.execute("""
                SELECT address, status, moralis_roi_pct, moralis_profit_usd, moralis_trades
                FROM adaptive_candidates 
                ORDER BY discovered_at DESC 
                LIMIT 10
            """).fetchall()
            
            if recent:
                logger.info("Recent candidates:")
                for address, status, roi, profit, trades in recent:
                    logger.info(f"  {address[:10]}... | {status} | {roi or 'N/A'}% ROI | ${profit or 'N/A'} | {trades or 'N/A'} trades")
            
        except Exception as e:
            logger.error(f"Failed to show summary: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Test Adaptive Discovery")
    parser.add_argument("--discover", action="store_true", help="Discover new adaptive candidates")
    parser.add_argument("--validate", action="store_true", help="Validate candidates with Moralis")
    parser.add_argument("--fetch-tokens", action="store_true", help="Fetch token data for validated candidates")
    parser.add_argument("--summary", action="store_true", help="Show candidates summary")
    parser.add_argument("--max-candidates", type=int, default=20, help="Maximum candidates to process")
    parser.add_argument("--config", default="config.json", help="Configuration file")
    
    args = parser.parse_args()
    
    try:
        tester = AdaptiveDiscoveryTester(args.config)
        
        if args.discover:
            logger.info("Starting adaptive discovery...")
            candidates = tester.discover_adaptive_candidates(args.max_candidates)
            logger.info(f"Discovery completed. Found {len(candidates)} new candidates.")
        
        if args.validate:
            logger.info("Starting Moralis validation...")
            validated = tester.validate_candidates_with_moralis(args.max_candidates)
            logger.info(f"Validation completed. {len(validated)} candidates validated.")
        
        if args.fetch_tokens:
            logger.info("Starting token data fetching...")
            processed = tester.fetch_token_data_for_validated(args.max_candidates)
            logger.info(f"Token fetching completed. {processed} candidates processed.")
        
        if args.summary:
            tester.show_candidates_summary()
        
        if not any([args.discover, args.validate, args.fetch_tokens, args.summary]):
            logger.info("No action specified. Use --help for available options.")
            tester.show_candidates_summary()
            
    except Exception as e:
        logger.error(f"Script failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
