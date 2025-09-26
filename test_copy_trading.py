#!/usr/bin/env python3
"""
Test Copy Trading Script

This script demonstrates how to use the new TEST mode to simulate
copy trading from specific whales.

Usage:
    python test_copy_trading.py

Or run directly with main.py:
    python main.py --mode TEST --test-whales 0x5c632b2ececab529fc0b16fda766c61fb6439d0e 0x56c64102bf25b3a6e364e4aa0dfe6b5770a4ac0a
"""

import subprocess
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Run TEST mode with top whales from your analysis"""
    
    # Top whales from your analysis (you can modify these)
    test_whales = [
        "0x5c632b2ececab529fc0b16fda766c61fb6439d0e",  # Score: 199.70
        "0x56c64102bf25b3a6e364e4aa0dfe6b5770a4ac0a",  # Score: 174.55
        "0x2060e98c76fd24ee92333a3e3d5d3aba9175b8fa",  # Score: 160.06
    ]
    
    logger.info("🚀 Starting TEST mode copy trading simulation...")
    logger.info(f"📊 Testing copy trading from {len(test_whales)} whales:")
    for i, whale in enumerate(test_whales, 1):
        logger.info(f"   {i}. {whale}")
    
    # Build command
    cmd = [
        sys.executable, "main.py",
        "--mode", "TEST",
        "--test-whales"
    ] + test_whales
    
    logger.info(f"🔧 Running command: {' '.join(cmd)}")
    logger.info("📈 The system will now monitor these whales and simulate copy trades")
    logger.info("🌐 Dashboard will be available at http://localhost:8080")
    logger.info("⏹️  Press Ctrl+C to stop")
    
    try:
        # Run the command
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        logger.info("🛑 Test simulation stopped by user")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Error running test simulation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
