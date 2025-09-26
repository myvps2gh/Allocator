# 🧪 TEST Mode - Copy Trading Simulation

The new **TEST mode** allows you to simulate copy trading from specific whales without risking real money.

## 🎯 What TEST Mode Does

- **Monitors specific whales** you choose (no discovery)
- **Simulates copy trades** when those whales trade
- **Uses block monitoring** (more reliable than mempool)
- **Shows simulation results** in logs and dashboard
- **No real money** at risk

## 🚀 How to Use

### Method 1: Direct Command
```bash
python main.py --mode TEST --test-whales 0x5c632b2ececab529fc0b16fda766c61fb6439d0e 0x56c64102bf25b3a6e364e4aa0dfe6b5770a4ac0a
```

### Method 2: Using the Test Script
```bash
python test_copy_trading.py
```

### Method 3: Multiple Whales
```bash
python main.py --mode TEST --test-whales \
  0x5c632b2ececab529fc0b16fda766c61fb6439d0e \
  0x56c64102bf25b3a6e364e4aa0dfe6b5770a4ac0a \
  0x2060e98c76fd24ee92333a3e3d5d3aba9175b8fa
```

## 📊 What You'll See

### Console Output:
```
[TEST] Would execute trade: 0.06 ETH (following 0x5c632b2e...)
[TEST] Would execute trade: 0.12 ETH (following 0x56c64102...)
[TEST] Trade simulation: +$45.67 profit
```

### Dashboard:
- Visit `http://localhost:8080`
- See your test whales in the dashboard
- Monitor simulated trades in real-time

## 🎛️ Available Modes

| Mode | Description | Discovery | Trading | Monitoring |
|------|-------------|-----------|---------|------------|
| **TEST** | Simulate copy trading from specific whales | ❌ | 🧪 Simulated | Block |
| **DRY_RUN** | Full simulation with discovery | ✅ | 🧪 Simulated | Mempool |
| **DRY_RUN_WO_MOR** | Simulation without Moralis API | ✅ | 🧪 Simulated | Mempool |
| **LIVE** | Real trading with real money | ✅ | 💰 Real | Mempool |

## 🔧 Configuration

The TEST mode uses your existing `config.json` but overrides the `tracked_whales` with your specified test whales.

## 📈 Best Whales to Test

Based on your analysis, these are the top performers:

1. **0x5c632b2ececab529fc0b16fda766c61fb6439d0e** - Score: 199.70
   - 125.05% ROI, $101,285 profit, 255 trades
   - 8 tokens, 70% win rate

2. **0x56c64102bf25b3a6e364e4aa0dfe6b5770a4ac0a** - Score: 174.55
   - 88.61% ROI, $155,193 profit, 388 trades
   - 25 tokens, 70% win rate

3. **0x2060e98c76fd24ee92333a3e3d5d3aba9175b8fa** - Score: 160.06
   - 105.08% ROI, $76,942 profit, 232 trades
   - 19 tokens, 70% win rate

## 🛑 Stopping the Test

Press `Ctrl+C` to stop the simulation at any time.

## 🔍 Troubleshooting

- **No trades detected**: Make sure the whale addresses are correct and active
- **Connection issues**: Check your Web3 RPC connection in `config.json`
- **Dashboard not loading**: Ensure port 8080 is available

## 📝 Notes

- TEST mode skips discovery entirely - it only monitors your specified whales
- Uses block monitoring for better reliability
- All trades are simulated - no real transactions
- Perfect for testing strategies before going live
