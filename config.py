# config.py
DISCOVERY_MODE = "quick_profit_whale"   # options: "bot_hunter", "active_whale", "lazy_whale", "quick_profit_whale" = profit in 72h

DISCOVERY_MODES = {
    "bot_hunter": {
        "blocks_back": 2000,     # ~6–7h
        "min_trades": 30,        # high frequency
        "min_pnl_threshold": 200 # ~200 ETH routed
    },
    "active_whale": {
        "blocks_back": 15000,
        "min_trades": 20,
        "min_pnl_threshold": 100
    },
    "lazy_whale": {
        "blocks_back": 50000,    # ~12d (fits if db supports)
        "min_trades": 10,
        "min_pnl_threshold": 300
    },
    "quick_profit_whale": {
        "blocks_back": 15000,     # ~72h
        "min_trades": 5,         # fewer trades ok
        "min_pnl_threshold": 50, # look for whales banking profit quickly
        "profit_window_hours": 72  # optional: explicit param to check entry+exit within timeframe
    },
    "fast_mover_whale": {
        "blocks_back": 17000,           # max ~3d window under prune=minimal
        "min_trades": 8,                # minimum trades to be relevant
        "min_pnl_threshold": 50,        # ETH profit baseline
        "min_roi": 0.20,                # ~20% ROI cutoff
        "description": "3-day fast movers, looser entry to avoid starvation"
    }
}
             