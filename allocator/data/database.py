"""
Database management for Allocator AI
"""

import sqlite3
import threading
import time
import logging
from typing import Optional, List, Tuple, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Optimized database manager with connection pooling and better performance"""
    
    def __init__(self, db_file: str = "whales.db"):
        self.db_file = db_file
        self.conn = None
        self.lock = threading.Lock()
        self._init_connection()
    
    def _init_connection(self):
        """Initialize database connection with optimizations"""
        with self.lock:
            if self.conn is None:
                self.conn = sqlite3.connect(
                    self.db_file, 
                    check_same_thread=False,
                    timeout=30.0
                )
                # Performance optimizations
                self.conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
                self.conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
                self.conn.execute("PRAGMA cache_size=10000")  # Larger cache
                self.conn.execute("PRAGMA temp_store=MEMORY")  # In-memory temp tables
                self._create_tables()
    
    def _create_tables(self):
        """Create database tables if they don't exist"""
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS whales (
            address TEXT PRIMARY KEY,
            moralis_roi_pct REAL,
            roi_usd REAL,
            trades INTEGER,
            cumulative_pnl REAL DEFAULT 0.0,
            risk_multiplier REAL DEFAULT 1.0,
            allocation_size REAL DEFAULT 0.0,
            score REAL DEFAULT 0.0,
            win_rate REAL DEFAULT 0.0,
            bootstrap_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_refresh TIMESTAMP
        )
        """)
        
        # Create trades table for detailed trade history
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actor TEXT NOT NULL,
            whale_address TEXT NOT NULL,
            router TEXT,
            path TEXT,
            side TEXT,
            amount_in REAL,
            amount_out REAL,
            token_in TEXT,
            token_out TEXT,
            price_impact REAL,
            gas_cost REAL,
            pnl REAL,
            cum_pnl REAL,
            risk_mult REAL,
            mode TEXT,
            tx_hash TEXT,
            FOREIGN KEY (whale_address) REFERENCES whales (address)
        )
        """)
        
        # Create indexes for better performance
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_whale ON trades(whale_address)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_actor ON trades(actor)")
        
        self.conn.commit()
    
    def get_whale(self, addr: str) -> Optional[Tuple]:
        """Get whale data from database"""
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "SELECT * FROM whales WHERE address=?", 
                    (addr.lower(),)
                )
                return cursor.fetchone()
            except sqlite3.Error as e:
                logger.error(f"Database error getting whale {addr}: {e}")
                return None
    
    def save_whale(self, addr: str, roi_pct: float, usd: float, trades: int, 
                   cumulative_pnl: float = 0.0, risk_multiplier: float = 1.0, 
                   allocation_size: float = 0.0, score: float = 0.0, win_rate: float = 0.0) -> bool:
        """Save whale data to database"""
        with self.lock:
            try:
                self.conn.execute("""
                    INSERT OR REPLACE INTO whales 
                    (address, moralis_roi_pct, roi_usd, trades, cumulative_pnl, 
                     risk_multiplier, allocation_size, score, win_rate, last_refresh)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (addr.lower(), float(roi_pct), float(usd), int(trades), 
                      float(cumulative_pnl), float(risk_multiplier), float(allocation_size),
                      float(score), float(win_rate), int(time.time())))
                self.conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error(f"Database error saving whale {addr}: {e}")
                return False
    
    def get_all_whales(self) -> List[Tuple]:
        """Get all whales from database"""
        with self.lock:
            try:
                cursor = self.conn.execute("SELECT * FROM whales ORDER BY last_refresh DESC")
                return cursor.fetchall()
            except sqlite3.Error as e:
                logger.error(f"Database error getting all whales: {e}")
                return []
    
    def update_whale_performance(self, addr: str, cumulative_pnl: float = None, 
                                risk_multiplier: float = None, allocation_size: float = None,
                                score: float = None, win_rate: float = None) -> bool:
        """Update whale performance metrics in database"""
        with self.lock:
            try:
                # Build dynamic query based on provided parameters
                update_fields = []
                values = []
                
                if cumulative_pnl is not None:
                    update_fields.append("cumulative_pnl = ?")
                    values.append(float(cumulative_pnl))
                
                if risk_multiplier is not None:
                    update_fields.append("risk_multiplier = ?")
                    values.append(float(risk_multiplier))
                
                if allocation_size is not None:
                    update_fields.append("allocation_size = ?")
                    values.append(float(allocation_size))
                
                if score is not None:
                    update_fields.append("score = ?")
                    values.append(float(score))
                
                if win_rate is not None:
                    update_fields.append("win_rate = ?")
                    values.append(float(win_rate))
                
                if not update_fields:
                    return True  # Nothing to update
                
                # Add address and timestamp
                values.append(int(time.time()))
                values.append(addr.lower())
                
                query = f"""
                    UPDATE whales 
                    SET {', '.join(update_fields)}, last_refresh = ?
                    WHERE address = ?
                """
                
                self.conn.execute(query, values)
                self.conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error(f"Database error updating whale performance {addr}: {e}")
                return False
    
    def save_trade(self, trade_data: dict) -> bool:
        """Save trade data to database"""
        with self.lock:
            try:
                self.conn.execute("""
                    INSERT INTO trades 
                    (actor, whale_address, router, path, side, amount_in, amount_out,
                     token_in, token_out, price_impact, gas_cost, pnl, cum_pnl, 
                     risk_mult, mode, tx_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_data.get('actor', ''),
                    trade_data.get('whale', ''),
                    trade_data.get('router', ''),
                    trade_data.get('path', ''),
                    trade_data.get('side', ''),
                    trade_data.get('amount_in', 0),
                    trade_data.get('amount_out', 0),
                    trade_data.get('token_in', ''),
                    trade_data.get('token_out', ''),
                    trade_data.get('price_impact', 0),
                    trade_data.get('gas_cost', 0),
                    trade_data.get('pnl', 0),
                    trade_data.get('cum_pnl', 0),
                    trade_data.get('risk_mult', 1),
                    trade_data.get('mode', ''),
                    trade_data.get('tx_hash', '')
                ))
                self.conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error(f"Database error saving trade: {e}")
                return False
    
    def get_recent_trades(self, limit: int = 100) -> List[Tuple]:
        """Get recent trades from database"""
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", 
                    (limit,)
                )
                return cursor.fetchall()
            except sqlite3.Error as e:
                logger.error(f"Database error getting recent trades: {e}")
                return []
    
    def get_whale_trades(self, whale_address: str, limit: int = 50) -> List[Tuple]:
        """Get trades for a specific whale"""
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "SELECT * FROM trades WHERE whale_address = ? ORDER BY timestamp DESC LIMIT ?",
                    (whale_address.lower(), limit)
                )
                return cursor.fetchall()
            except sqlite3.Error as e:
                logger.error(f"Database error getting whale trades: {e}")
                return []
    
    def get_stats(self) -> dict:
        """Get database statistics"""
        with self.lock:
            try:
                # Get whale count
                whale_count = self.conn.execute("SELECT COUNT(*) FROM whales").fetchone()[0]
                
                # Get trade count
                trade_count = self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                
                # Get total PnL
                total_pnl = self.conn.execute("SELECT SUM(pnl) FROM trades WHERE actor = 'allocator'").fetchone()[0] or 0
                
                return {
                    "whale_count": whale_count,
                    "trade_count": trade_count,
                    "total_pnl": total_pnl
                }
            except sqlite3.Error as e:
                logger.error(f"Database error getting stats: {e}")
                return {"whale_count": 0, "trade_count": 0, "total_pnl": 0}
    
    def close(self):
        """Close database connection"""
        with self.lock:
            if self.conn:
                self.conn.close()
                self.conn = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
