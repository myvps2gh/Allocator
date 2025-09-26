#!/usr/bin/env python3
"""
Recalculate Discarded Whales Script

This script recalculates all existing whales in the database and marks those
that don't meet minimum requirements (20 trades, 5 tokens) as discarded.
"""

import sys
import os
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from allocator.data.database import DatabaseManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def recalculate_discarded_whales():
    """Recalculate all whales and mark those that don't meet requirements as discarded"""
    
    logger.info("Starting discarded whales recalculation...")
    
    # Initialize database
    db_manager = DatabaseManager("whales.db")
    
    # Get all whales from database (including already discarded ones)
    all_whales = db_manager.conn.execute("SELECT * FROM whales").fetchall()
    logger.info(f"Found {len(all_whales)} total whales in database")
    
    # Separate discarded and non-discarded whales
    non_discarded = [w for w in all_whales if w[11] is None]  # discarded_timestamp is None
    already_discarded = [w for w in all_whales if w[11] is not None]
    
    logger.info(f"  - {len(non_discarded)} non-discarded whales")
    logger.info(f"  - {len(already_discarded)} already discarded whales")
    
    # Process non-discarded whales
    newly_discarded = 0
    valid_whales = 0
    
    logger.info("\nProcessing non-discarded whales...")
    
    for i, whale_data in enumerate(non_discarded, 1):
        address = whale_data[0]
        trades = whale_data[3] if len(whale_data) > 3 else 0
        
        logger.info(f"Processing whale {i}/{len(non_discarded)}: {address[:10]}... (trades: {trades})")
        
        try:
            # Get token count for this whale
            token_breakdown = db_manager.get_whale_token_breakdown(address)
            token_count = len([t for t in token_breakdown if t[0] != "PROCESSED"])  # Exclude PROCESSED marker
            
            logger.info(f"  Token count: {token_count}")
            
            # Check minimum requirements
            MIN_TRADES = 20
            MIN_TOKENS = 5
            
            if trades < MIN_TRADES or token_count < MIN_TOKENS:
                reason = f"< {MIN_TRADES} trades ({trades}) or < {MIN_TOKENS} tokens ({token_count})"
                logger.info(f"  ❌ Does not meet requirements: {reason}")
                
                # Mark as discarded
                success = db_manager.mark_whale_discarded(address, reason)
                if success:
                    newly_discarded += 1
                    logger.info(f"  ✅ Marked as discarded")
                else:
                    logger.error(f"  ❌ Failed to mark as discarded")
            else:
                logger.info(f"  ✅ Meets requirements (trades: {trades}, tokens: {token_count})")
                valid_whales += 1
                
        except Exception as e:
            logger.error(f"  ❌ Error processing whale {address}: {e}")
            continue
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("RECALCULATION SUMMARY:")
    logger.info(f"  Total whales processed: {len(non_discarded)}")
    logger.info(f"  Valid whales: {valid_whales}")
    logger.info(f"  Newly discarded: {newly_discarded}")
    logger.info(f"  Already discarded: {len(already_discarded)}")
    logger.info(f"  Total discarded: {len(already_discarded) + newly_discarded}")
    
    # Show some examples of discarded whales
    if newly_discarded > 0:
        logger.info(f"\nRecently discarded whales:")
        recent_discarded = db_manager.conn.execute("""
            SELECT address, trades, score, discarded_timestamp 
            FROM whales 
            WHERE discarded_timestamp IS NOT NULL 
            ORDER BY discarded_timestamp DESC 
            LIMIT 10
        """).fetchall()
        
        for address, trades, score, discarded_time in recent_discarded:
            logger.info(f"  {address[:10]}... | trades: {trades} | score: {score:.2f} | discarded: {discarded_time}")
    
    logger.info(f"\nRecalculation completed!")
    logger.info(f"Dashboard will now show only {valid_whales} valid whales.")

def show_discarded_stats():
    """Show statistics about discarded whales"""
    
    logger.info("Discarded Whales Statistics:")
    
    db_manager = DatabaseManager("whales.db")
    
    # Get discarded whales
    discarded_whales = db_manager.get_discarded_whales()
    
    if not discarded_whales:
        logger.info("  No discarded whales found")
        return
    
    logger.info(f"  Total discarded whales: {len(discarded_whales)}")
    
    # Analyze reasons for discarding
    low_trades = 0
    low_tokens = 0
    both_low = 0
    
    for whale_data in discarded_whales:
        address = whale_data[0]
        trades = whale_data[3] if len(whale_data) > 3 else 0
        
        # Get token count
        token_breakdown = db_manager.get_whale_token_breakdown(address)
        token_count = len([t for t in token_breakdown if t[0] != "PROCESSED"])
        
        if trades < 20 and token_count < 5:
            both_low += 1
        elif trades < 20:
            low_trades += 1
        elif token_count < 5:
            low_tokens += 1
    
    logger.info(f"  - Low trades only (< 20): {low_trades}")
    logger.info(f"  - Low tokens only (< 5): {low_tokens}")
    logger.info(f"  - Both low: {both_low}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Recalculate discarded whales")
    parser.add_argument("--stats", action="store_true", 
                       help="Show discarded whales statistics only")
    parser.add_argument("--recalculate", action="store_true", 
                       help="Recalculate and mark whales as discarded")
    
    args = parser.parse_args()
    
    if args.stats:
        show_discarded_stats()
    elif args.recalculate:
        recalculate_discarded_whales()
    else:
        # Default: show stats then ask for confirmation
        show_discarded_stats()
        print("\n" + "="*60)
        response = input("Do you want to recalculate and mark whales as discarded? (y/N): ")
        if response.lower() in ['y', 'yes']:
            recalculate_discarded_whales()
        else:
            logger.info("Recalculation cancelled.")
