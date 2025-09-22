#!/usr/bin/env python3
"""
Quick script to refresh whale metrics
"""

import sys
import logging
from pathlib import Path

# Add the allocator package to the path
sys.path.insert(0, str(Path(__file__).parent))

from allocator.config import Config
from allocator.data import DatabaseManager
from allocator.core import WhaleTracker
from allocator.data.cache import CacheManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("whale_refresh")

def main():
    try:
        # Load configuration
        config = Config.from_env_and_file("config.json")
        
        # Initialize components
        db_manager = DatabaseManager(config.database.file_path)
        cache_manager = CacheManager()
        
        # Initialize whale tracker
        whale_tracker = WhaleTracker(
            config.moralis_api_key,
            cache_manager,
            db_manager,
            config.discovery
        )
        
        # Load existing whales from database
        db_whales = db_manager.get_all_whales()
        for whale_data in db_whales:
            whale_tracker.tracked_whales.add(whale_data[0])  # Add address to tracked set
        
        logger.info(f"Found {len(whale_tracker.tracked_whales)} tracked whales")
        
        # Refresh metrics
        whale_tracker.refresh_all_whale_metrics(simulate_trades=True)
        
        logger.info("✅ Whale metrics refresh completed!")
        
    except Exception as e:
        logger.error(f"❌ Error refreshing whale metrics: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
