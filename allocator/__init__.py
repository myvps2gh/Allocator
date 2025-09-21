"""
Allocator AI - Automated Whale Following Trading Bot

A sophisticated cryptocurrency trading bot that automatically mirrors trades
from successful "whale" traders in real-time.
"""

__version__ = "2.0.0"
__author__ = "Allocator AI Team"

from .core.whale_tracker import WhaleTracker
from .core.trade_executor import TradeExecutor
from .core.risk_manager import RiskManager
from .data.database import DatabaseManager
from .monitoring.mempool_watcher import MempoolWatcher
from .web.dashboard import create_app

__all__ = [
    "WhaleTracker",
    "TradeExecutor", 
    "RiskManager",
    "DatabaseManager",
    "MempoolWatcher",
    "create_app"
]
