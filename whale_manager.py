#!/usr/bin/env python3
"""
Whale Manager Script

This script provides commands to manage whales without affecting the main Allocator service.
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

def show_top_whales(n=10):
    """Show top N whales for copying"""
    logger.info(f"Top {n} Whales for Copying:")
    
    db_manager = DatabaseManager("whales.db")
    top_whales = db_manager.get_all_whales_sorted_by_score()[:n]
    
    if not top_whales:
        logger.info("  No whales found")
        return
    
    logger.info("  Rank | Address | Score | Trades | Tokens | ROI% | Win Rate | Risk")
    logger.info("  " + "-" * 100)
    
    for i, whale_data in enumerate(top_whales, 1):
        address = whale_data[0]
        score = whale_data[9] if len(whale_data) > 9 else 0
        trades = whale_data[3] if len(whale_data) > 3 else 0
        roi = whale_data[1] if len(whale_data) > 1 else 0
        win_rate = whale_data[10] if len(whale_data) > 10 else 0
        risk = whale_data[7] if len(whale_data) > 7 else 1.0
        
        # Get token count
        token_breakdown = db_manager.get_whale_token_breakdown(address)
        token_count = len([t for t in token_breakdown if t[0] != "PROCESSED"])
        
        logger.info(f"  {i:2d}   | {address} | {score:6.2f} | {trades:6d} | {token_count:6d} | {roi:5.1f}% | {win_rate*100:7.1f}% | {risk:4.2f}")
    
    logger.info(f"\n💡 Copy any address above to start following that whale!")
    logger.info(f"💡 Higher score = better overall performance")
    logger.info(f"💡 More trades + tokens = more reliable data")
    logger.info(f"💡 Lower risk multiplier = more conservative")

def show_discarded_whales():
    """Show all discarded whales"""
    logger.info("Discarded Whales:")
    
    db_manager = DatabaseManager("whales.db")
    discarded_whales = db_manager.get_discarded_whales()
    
    if not discarded_whales:
        logger.info("  No discarded whales found")
        return
    
    logger.info(f"  Found {len(discarded_whales)} discarded whales:")
    logger.info("  Address | Score | Trades | ROI% | Discarded Time")
    logger.info("  " + "-" * 80)
    
    for whale_data in discarded_whales:
        address = whale_data[0]
        score = whale_data[9] if len(whale_data) > 9 else 0
        trades = whale_data[3] if len(whale_data) > 3 else 0
        roi = whale_data[1] if len(whale_data) > 1 else 0
        discarded_time = whale_data[11] if len(whale_data) > 11 else "Unknown"
        
        # Convert timestamp to readable format
        if discarded_time and discarded_time != "Unknown":
            try:
                import datetime
                discarded_time = datetime.datetime.fromtimestamp(int(discarded_time)).strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        
        logger.info(f"  {address[:10]}... | {score:.2f} | {trades} | {roi:.2f}% | {discarded_time}")

def rescan_whale(address):
    """Remove discarded status from a whale to allow rescanning"""
    logger.info(f"Removing discarded status from whale {address}...")
    
    db_manager = DatabaseManager("whales.db")
    success = db_manager.rescan_whale(address)
    
    if success:
        logger.info(f"Successfully removed discarded status from {address}")
        logger.info("Whale is now ready for rescanning")
    else:
        logger.error(f"Failed to remove discarded status from {address}")

def show_adaptive_candidates():
    """Show status of adaptive candidates"""
    logger.info("Adaptive Candidates Status:")
    
    db_manager = DatabaseManager("whales.db")
    
    # Get summary statistics
    stats = db_manager.conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN moralis_validated = TRUE THEN 1 ELSE 0 END) as validated,
            SUM(CASE WHEN status = 'tokens_fetched' THEN 1 ELSE 0 END) as tokens_fetched,
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM adaptive_candidates
    """).fetchone()
    
    total, validated, tokens_fetched, rejected = stats
    logger.info(f"  Total candidates: {total}")
    logger.info(f"  Validated with Moralis: {validated}")
    logger.info(f"  Tokens fetched: {tokens_fetched}")
    logger.info(f"  Rejected: {rejected}")
    
    # Show recent candidates
    recent = db_manager.conn.execute("""
        SELECT address, status, moralis_roi_pct, moralis_profit_usd, moralis_trades
        FROM adaptive_candidates 
        ORDER BY created_at DESC 
        LIMIT 10
    """).fetchall()
    
    if recent:
        logger.info("Recent candidates:")
        for address, status, roi, profit, trades in recent:
            logger.info(f"  {address[:10]}... | {status} | {roi or 'N/A'}% ROI | ${profit or 'N/A'} | {trades or 'N/A'} trades")

def show_whale_details(address):
    """Show detailed information about a specific whale"""
    logger.info(f"Whale Details for {address}:")
    
    db_manager = DatabaseManager("whales.db")
    whale_data = db_manager.get_whale(address)
    
    if not whale_data:
        logger.error(f"Whale {address} not found in database")
        return
    
    logger.info(f"  Address: {whale_data[0]}")
    logger.info(f"  Moralis ROI: {whale_data[1]:.2f}%")
    logger.info(f"  Moralis Profit: ${whale_data[2]:.2f}")
    logger.info(f"  Trades: {whale_data[3]}")
    logger.info(f"  Cumulative PnL: {whale_data[6]:.4f} ETH")
    logger.info(f"  Risk Multiplier: {whale_data[7]:.2f}")
    logger.info(f"  Allocation Size: {whale_data[8]:.4f} ETH")
    logger.info(f"  Score v2.0: {whale_data[9]:.2f}")
    logger.info(f"  Win Rate: {whale_data[10]*100:.1f}%")
    logger.info(f"  Bootstrap Time: {whale_data[4]}")
    logger.info(f"  Last Refresh: {whale_data[5]}")
    
    # Show token breakdown
    token_breakdown = db_manager.get_whale_token_breakdown(address)
    if token_breakdown:
        logger.info(f"  Token Breakdown ({len(token_breakdown)} tokens):")
        for token_symbol, token_address, token_pnl, trade_count, last_updated in token_breakdown:
            if token_symbol != "PROCESSED":
                logger.info(f"    {token_symbol}: {token_pnl:.4f} ETH ({trade_count} trades)")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Whale Manager - Manage whales without affecting main service")
    parser.add_argument("--top", type=int, metavar="N", default=10,
                       help="Show top N whales for copying (default: 10)")
    parser.add_argument("--discarded", action="store_true",
                       help="Show all discarded whales")
    parser.add_argument("--rescan", type=str, metavar="ADDRESS",
                       help="Remove discarded status from a whale to allow rescanning")
    parser.add_argument("--adaptive", action="store_true",
                       help="Show status of adaptive candidates")
    parser.add_argument("--details", type=str, metavar="ADDRESS",
                       help="Show detailed information about a specific whale")
    
    args = parser.parse_args()
    
    if args.top:
        show_top_whales(args.top)
    elif args.discarded:
        show_discarded_whales()
    elif args.rescan:
        rescan_whale(args.rescan)
    elif args.adaptive:
        show_adaptive_candidates()
    elif args.details:
        show_whale_details(args.details)
    else:
        # Default: show top 10 whales
        show_top_whales(10)
