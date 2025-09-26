# Whale Manager - Allocator AI

## Overview

The Whale Manager is a separate management script that provides commands to manage whales without affecting the main Allocator service. This ensures your main service runs continuously while you can perform management tasks in parallel.

## ✅ Fixed Service Issue

### Problem
The main Allocator service was exiting when using management commands, preventing continuous operation and dashboard access.

### Solution
- **Created `whale_manager.py`** - Separate management script
- **Removed commands from `main.py`** - Prevents service interruption
- **Main service now runs continuously** - Dashboard always accessible

## 🚀 Usage

### For Continuous Service
```bash
# Start the main service (runs continuously)
python main.py --config config.json
```

### For Whale Management (in separate terminal)
```bash
# Show top 10 whales for copying
python whale_manager.py --top 10

# Show top 20 whales
python whale_manager.py --top 20

# Show discarded whales
python whale_manager.py --discarded

# Rescan a specific whale
python whale_manager.py --rescan 0x103da694ee0b8a6b3b548f2d195959c01c31d2f9

# Show adaptive candidates status
python whale_manager.py --adaptive

# Show detailed info about a specific whale
python whale_manager.py --details 0x103da694ee0b8a6b3b548f2d195959c01c31d2f9
```

## 🎯 Finding Whales to Copy

### 1. Dashboard (Visual)
- **Sort by Score v2.0** (already default)
- **Click "Copy" button** next to any whale
- **View token breakdown** to see what they trade
- **Color coding**: Green = high ROI, Yellow = positive, Red = negative

### 2. CLI Command (Quick)
```bash
# Show top 10 whales
python whale_manager.py --top 10

# Show top 20 whales  
python whale_manager.py --top 20

# Show top 5 whales
python whale_manager.py --top 5
```

### 3. What to Look For

**🏆 Best Whales:**
- **High Score v2.0** (200+ is excellent)
- **High trade count** (100+ trades = more reliable)
- **Multiple tokens** (10+ tokens = diversified)
- **High win rate** (60%+ is good)
- **Positive ROI** (20%+ is excellent)
- **Lower risk multiplier** (1.0-1.2 = conservative)

**⚠️ Avoid:**
- Low trade count (<50 trades)
- Few tokens (<5 tokens)
- Negative ROI
- High risk multiplier (>1.5)

## 📊 Commands Reference

### `--top N`
Shows top N whales ranked by Score v2.0
```bash
python whale_manager.py --top 10
```
**Output:**
```
Rank | Address | Score | Trades | Tokens | ROI% | Win Rate | Risk
 1   | 0x103da6... | 763.58 |   1344 |     15 | 1851.9% |   67.2% | 1.50
 2   | 0x5c632b... | 199.70 |    125 |      8 |  50.6% |   58.1% | 1.20
```

### `--discarded`
Shows all whales marked as discarded (don't meet minimum requirements)
```bash
python whale_manager.py --discarded
```

### `--rescan ADDRESS`
Removes discarded status from a whale to allow rescanning
```bash
python whale_manager.py --rescan 0x103da694ee0b8a6b3b548f2d195959c01c31d2f9
```

### `--adaptive`
Shows status of adaptive discovery candidates
```bash
python whale_manager.py --adaptive
```

### `--details ADDRESS`
Shows detailed information about a specific whale
```bash
python whale_manager.py --details 0x103da694ee0b8a6b3b548f2d195959c01c31d2f9
```

## 🔧 Discarded Whale System

### Minimum Requirements
- **20+ trades** required
- **5+ different tokens** required
- Whales that don't meet requirements are marked as discarded

### Benefits
- **Filters out "lucky shot" whales** with few trades
- **Focuses on proven performers** with sustained activity
- **Keeps data in database** for potential rescanning
- **Dashboard only shows valid whales**

### Management
```bash
# See discarded whales
python whale_manager.py --discarded

# Rescan a discarded whale
python whale_manager.py --rescan 0xADDRESS

# Recalculate all whales (mark new ones as discarded)
python recalculate_discarded.py --recalculate
```

## 🌐 Dashboard Features

### Copy Functionality
- **Copy buttons** next to each whale
- **One-click copying** to clipboard
- **Visual feedback** when copied

### Token Breakdown
- **Click "Show Tokens"** to see detailed token performance
- **View PnL per token** and trade counts
- **Understand whale's strategy** before copying

### Sorting
- **Default: Score v2.0 descending**
- **Database-level sorting** for performance
- **Real-time updates** as new whales are discovered

## 🚀 Quick Start

1. **Start the main service:**
   ```bash
   python main.py --config config.json
   ```

2. **Access dashboard:**
   - Open `http://your-vps-ip:8080`
   - View whales sorted by Score v2.0

3. **Find whales to copy:**
   ```bash
   python whale_manager.py --top 10
   ```

4. **Copy whale addresses:**
   - Use dashboard "Copy" buttons, or
   - Copy addresses from CLI output

5. **Start following the whales!**

## 📝 Notes

- **Main service runs continuously** - no interruption for management tasks
- **Dashboard always accessible** at port 8080
- **All management commands** are in separate script
- **Database persists** all whale data including discarded ones
- **Easy to rescan** discarded whales if needed

## 🔄 Workflow

1. **Service runs 24/7** discovering and tracking whales
2. **Dashboard shows** only valid whales (≥20 trades, ≥5 tokens)
3. **Use whale_manager.py** to find best whales to copy
4. **Copy addresses** and start following them
5. **Monitor performance** through dashboard
6. **Manage discarded whales** as needed

This setup ensures your Allocator AI runs continuously while providing powerful management tools for finding and copying the best whales!
