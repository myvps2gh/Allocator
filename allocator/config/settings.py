"""
Configuration settings and data classes for Allocator AI
"""

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional
from pathlib import Path


@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    file_path: str = "whales.db"
    journal_mode: str = "WAL"
    timeout: int = 30
    cache_size: int = 10000
    temp_store: str = "MEMORY"


@dataclass
class TradingConfig:
    """Trading configuration settings"""
    capital: Decimal = Decimal("2")
    base_risk: Decimal = Decimal("0.05")
    max_slippage: Decimal = Decimal("0.01")
    min_profit: Decimal = Decimal("0.005")
    gas_boost: Decimal = Decimal("1.1")
    min_moralis_roi_pct: Decimal = Decimal("5")
    min_moralis_profit_usd: Decimal = Decimal("500")
    min_moralis_trades: int = 5


@dataclass
class Web3Config:
    """Web3 and blockchain configuration"""
    rpc_url: str = "ws://152.53.148.57:8546"
    chain_id: Optional[int] = None
    max_retries: int = 3
    timeout: int = 30


@dataclass
class DiscoveryConfig:
    """Whale discovery configuration"""
    modes: List[str] = None
    refresh_interval: int = 600  # 10 minutes
    max_whales: int = 100
    
    def __post_init__(self):
        if self.modes is None:
            self.modes = ["active_whale", "quick_profit_whale", "fast_mover_whale"]


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = "allocator.log"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


@dataclass
class Config:
    """Main configuration class"""
    database: DatabaseConfig
    trading: TradingConfig
    web3: Web3Config
    discovery: DiscoveryConfig
    logging: LoggingConfig
    moralis_api_key: str
    wallet_password: str
    tracked_whales: List[str] = None
    
    def __post_init__(self):
        if self.tracked_whales is None:
            self.tracked_whales = []
    
    @classmethod
    def from_env_and_file(cls, config_file: str = "config.json"):
        """Load configuration from environment variables and config file"""
        import json
        
        # Load from config file
        config_data = {}
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config_data = json.load(f)
        
        # Override with environment variables
        return cls(
            database=DatabaseConfig(
                file_path=os.environ.get("DB_FILE", config_data.get("db_file", "whales.db"))
            ),
            trading=TradingConfig(
                capital=Decimal(str(os.environ.get("CAPITAL", config_data.get("capital", "2")))),
                base_risk=Decimal(str(os.environ.get("BASE_RISK", config_data.get("base_risk", "0.05")))),
                max_slippage=Decimal(str(os.environ.get("MAX_SLIPPAGE", config_data.get("max_slippage", "0.01")))),
                min_profit=Decimal(str(os.environ.get("MIN_PROFIT", config_data.get("min_profit", "0.005")))),
                gas_boost=Decimal(str(os.environ.get("GAS_BOOST", config_data.get("gas_boost", "1.1")))),
                min_moralis_roi_pct=Decimal(str(config_data.get("min_moralis_roi_pct", "5"))),
                min_moralis_profit_usd=Decimal(str(config_data.get("min_moralis_profit_usd", "500"))),
                min_moralis_trades=config_data.get("min_moralis_trades", 5)
            ),
            web3=Web3Config(
                rpc_url=os.environ.get("WEB3_RPC", config_data.get("web3_rpc", "ws://152.53.148.57:8546"))
            ),
            discovery=DiscoveryConfig(),
            logging=LoggingConfig(
                level=os.environ.get("LOG_LEVEL", "INFO"),
                log_dir=os.environ.get("LOG_DIR", "logs")
            ),
            moralis_api_key=os.environ.get("MORALIS_API_KEY"),
            wallet_password=os.environ.get("WALLET_PASS"),
            tracked_whales=config_data.get("tracked_whales", [])
        )
    
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.moralis_api_key:
            raise ValueError("MORALIS_API_KEY is required")
        if not self.wallet_password:
            raise ValueError("WALLET_PASS is required")
        if not self.web3.rpc_url:
            raise ValueError("Web3 RPC URL is required")
        
        return True
