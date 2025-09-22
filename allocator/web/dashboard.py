"""
Web dashboard for Allocator AI
"""

import logging
from flask import Flask, render_template_string, jsonify
from typing import Dict, Any, List
from decimal import Decimal

logger = logging.getLogger(__name__)

# Dashboard HTML template
DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Allocator AI - {{ mode }} Mode</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8f9fa;
            color: #333;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
        }
        .mode-badge {
            background: rgba(255,255,255,0.2);
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.2s ease;
        }
        .stat-card:hover {
            transform: translateY(-2px);
        }
        .stat-value {
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }
        .positive { color: #28a745; }
        .negative { color: #dc3545; }
        .neutral { color: #007bff; }
        .stat-label {
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .table-container {
            background: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
            margin-bottom: 30px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #f8f9fa;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #495057;
            border-bottom: 2px solid #dee2e6;
        }
        td {
            padding: 15px;
            border-bottom: 1px solid #dee2e6;
        }
        tr:hover {
            background-color: #f8f9fa;
        }
        .whale-row-profitable { background-color: rgba(40,167,69,0.05); }
        .whale-row-medium { background-color: rgba(255,193,7,0.05); }
        .whale-row-risky { background-color: rgba(220,53,69,0.05); }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-online { background-color: #28a745; }
        .status-offline { background-color: #dc3545; }
        .refresh-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
        }
        .refresh-btn:hover {
            background: #0056b3;
        }
        @media (max-width: 768px) {
            .header {
                flex-direction: column;
                text-align: center;
            }
            .stats-grid {
                grid-template-columns: 1fr;
            }
            table {
                font-size: 0.9em;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🐋 Allocator AI</h1>
        <div>
            <span class="mode-badge">{{ mode }} MODE</span>
            <button class="refresh-btn" onclick="location.reload()">Refresh</button>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Total PnL</div>
            <div class="stat-value {{ 'positive' if total_pnl > 0 else 'negative' if total_pnl < 0 else 'neutral' }}">
                {{ '%.4f' | format(total_pnl) }} ETH
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Active Capital</div>
            <div class="stat-value neutral">{{ '%.4f' | format(capital) }} ETH</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Tracked Whales</div>
            <div class="stat-value neutral">{{ whale_count }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Total Trades</div>
            <div class="stat-value neutral">{{ trade_count }}</div>
        </div>
    </div>

    <div class="table-container">
        <h2 style="margin: 0; padding: 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">Discovery Status</h2>
        <table>
            <thead>
                <tr>
                    <th>Mode</th>
                    <th>Status</th>
                    <th>Blocks to Scan</th>
                    <th>Min Trades</th>
                    <th>Min PnL Threshold</th>
                    <th>Candidates Found</th>
                    <th>Validated Whales</th>
                    <th>Last Run Time</th>
                </tr>
            </thead>
            <tbody>
                {% for discovery in discovery_status %}
                <tr>
                    <td><strong>{{ discovery.mode }}</strong></td>
                    <td>
                        <span class="status-indicator {{ 'status-online' if discovery.status == 'running' else 'status-idle' if discovery.status == 'completed' else 'status-offline' }}"></span>
                        {{ discovery.status.title() }}
                    </td>
                    <td>{{ '{:,}'.format(discovery.blocks_back) }}</td>
                    <td>{{ discovery.min_trades }}</td>
                    <td>{{ discovery.min_pnl_threshold }} ETH</td>
                    <td class="neutral">{{ discovery.candidates_found if discovery.candidates_found is not none else 'N/A' }}</td>
                    <td class="{{ 'positive' if discovery.validated_whales and discovery.validated_whales > 0 else 'neutral' }}">
                        {{ discovery.validated_whales if discovery.validated_whales is not none else 'N/A' }}
                    </td>
                    <td>{{ discovery.last_run_duration if discovery.last_run_duration else 'N/A' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="table-container">
        <h2 style="margin: 0; padding: 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">Whale Performance</h2>
        <table>
            <thead>
                <tr>
                    <th>Whale Address</th>
                    <th>Cumulative PnL</th>
                    <th>Risk Multiplier</th>
                    <th>Allocation Size</th>
                    <th>Trade Count</th>
                    <th>Score</th>
                    <th>Win Rate</th>
                    <th>Moralis ROI%</th>
                    <th>Moralis PnL $</th>
                    <th>Moralis Trades</th>
                </tr>
            </thead>
            <tbody>
                {% for w in whales %}
                <tr class="
                    {% if w.moralis_roi is not none and w.moralis_roi >= 20 %}
                        whale-row-profitable
                    {% elif w.moralis_roi is not none and w.moralis_roi > 0 %}
                        whale-row-medium
                    {% else %}
                        whale-row-risky
                    {% endif %}
                ">
                    <td>
                        <span class="status-indicator status-online"></span>
                        {{ w.address[:6] }}...{{ w.address[-4:] }}
                    </td>
                    <td class="{{ 'positive' if w.pnl > 0 else 'negative' if w.pnl < 0 else 'neutral' }}">
                        {{ '%.4f' | format(w.pnl) }}
                    </td>
                    <td>{{ '%.2f' | format(w.risk) }}x</td>
                    <td>{{ '%.4f' | format(w.allocation) }} ETH</td>
                    <td>{{ w.count }}</td>
                    <td>{{ '%.4f' | format(w.score) }}</td>
                    <td>{{ '%.0f' | format(w.winrate) }}%</td>
                    <td>{% if w.moralis_roi is not none %}{{ '%.2f' | format(w.moralis_roi) }}%{% else %}N/A{% endif %}</td>
                    <td>{% if w.moralis_profit_usd is not none %}{{ '%.2f' | format(w.moralis_profit_usd) }}${% else %}N/A{% endif %}</td>
                    <td>{% if w.moralis_trades is not none %}{{ w.moralis_trades }}{% else %}N/A{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="table-container">
        <h2 style="margin: 0; padding: 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">Recent Trades</h2>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Direction</th>
                    <th>Amount In</th>
                    <th>Amount Out</th>
                    <th>PnL</th>
                    <th>Mode</th>
                </tr>
            </thead>
            <tbody>
                {% for t in trades %}
                <tr>
                    <td>{{ t.timestamp }}</td>
                    <td>{{ t.actor }}</td>
                    <td>{{ t.token_in }} → {{ t.token_out }}</td>
                    <td>{{ '%.4f' | format(t.amount_in) }}</td>
                    <td>{{ '%.4f' | format(t.amount_out) }}</td>
                    <td class="{{ 'positive' if t.pnl > 0 else 'negative' if t.pnl < 0 else 'neutral' }}">
                        {{ '%.4f' | format(t.pnl) }}
                    </td>
                    <td>{{ t.mode }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setTimeout(function() {
            location.reload();
        }, 30000);
    </script>
</body>
</html>
"""


def create_app(whale_tracker, risk_manager, db_manager, mode: str = "LIVE") -> Flask:
    """Create Flask application for the dashboard"""
    
    app = Flask(__name__)
    
    @app.route("/")
    def index():
        """Main dashboard page"""
        try:
            # Get whale data from database
            whale_data = []
            db_whales = db_manager.get_all_whales()
            
            for whale_row in db_whales:
                # Database columns: 0=address, 1=moralis_roi_pct, 2=roi_usd, 3=trades, 4=cumulative_pnl, 
                # 5=risk_multiplier, 6=allocation_size, 7=score, 8=win_rate, 9=bootstrap_time, 10=last_refresh
                try:
                    def safe_float(value, default=0.0):
                        """Safely convert to float with default fallback"""
                        if value is None:
                            return default
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return default
                    
                    def safe_int(value, default=0):
                        """Safely convert to int with default fallback"""
                        if value is None:
                            return default
                        try:
                            return int(float(value))  # Convert via float first to handle string numbers
                        except (ValueError, TypeError):
                            return default
                    
                    whale_data.append({
                        "address": whale_row[0] if whale_row[0] is not None else "unknown",  # address
                        "pnl": safe_float(whale_row[4]),  # cumulative_pnl
                        "risk": safe_float(whale_row[5], 1.0),  # risk_multiplier
                        "allocation": safe_float(whale_row[6]),  # allocation_size
                        "count": safe_int(whale_row[3]),  # trades
                        "score": safe_float(whale_row[7]),  # score
                        "winrate": safe_float(whale_row[8]) * 100,  # win_rate (convert to percentage)
                        "moralis_roi": safe_float(whale_row[1]) if whale_row[1] is not None else None,  # moralis_roi_pct
                        "moralis_profit_usd": safe_float(whale_row[2]) if whale_row[2] is not None else None,  # roi_usd
                        "moralis_trades": safe_int(whale_row[3]) if whale_row[3] is not None else None,  # trades (same as count)
                        "bootstrap_time": whale_row[9] if whale_row[9] is not None else None,  # bootstrap_time
                        "last_refresh": whale_row[10] if whale_row[10] is not None else None  # last_refresh
                    })
                except Exception as e:
                    logger.warning(f"Error processing whale row {whale_row}: {e}")
                    continue
            
            # Sort by PnL
            whale_data.sort(key=lambda x: x["pnl"], reverse=True)
            
            # Get recent trades
            recent_trades = db_manager.get_recent_trades(20)
            trades_data = []
            for trade in recent_trades:
                trades_data.append({
                    "timestamp": trade[1],  # timestamp column
                    "actor": trade[2],      # actor column
                    "token_in": trade[8],   # token_in column
                    "token_out": trade[9],  # token_out column
                    "amount_in": trade[6],  # amount_in column
                    "amount_out": trade[7], # amount_out column
                    "pnl": trade[12],       # pnl column
                    "mode": trade[15]       # mode column
                })
            
            # Get stats
            stats = db_manager.get_stats()
            
            # Get discovery status
            discovery_status = []
            if hasattr(whale_tracker, 'discovery_modes') and whale_tracker.discovery_modes:
                for mode_name, config in whale_tracker.discovery_modes.items():
                    # Check if this mode is in the active discovery list
                    discovery_status.append({
                        "mode": mode_name,
                        "status": "idle",  # We'll enhance this later with real-time status
                        "blocks_back": config.get("blocks_back", 0),
                        "min_trades": config.get("min_trades", 0),
                        "min_pnl_threshold": config.get("min_pnl_threshold", 0),
                        "candidates_found": None,
                        "validated_whales": None,
                        "last_run_duration": None
                    })
            
            return render_template_string(
                DASHBOARD_TEMPLATE,
                whales=whale_data,
                trades=trades_data,
                discovery_status=discovery_status,
                total_pnl=stats["total_pnl"],
                capital=2000,  # This should come from config
                whale_count=len(whale_data),
                trade_count=stats["trade_count"],
                mode=mode
            )
            
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            return f"Dashboard error: {e}", 500
    
    @app.route("/api/stats")
    def api_stats():
        """API endpoint for stats"""
        try:
            stats = db_manager.get_stats()
            return jsonify({
                "total_pnl": stats["total_pnl"],
                "whale_count": stats["whale_count"],
                "trade_count": stats["trade_count"],
                "mode": mode
            })
        except Exception as e:
            logger.error(f"API stats error: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/api/whales")
    def api_whales():
        """API endpoint for whale data"""
        try:
            whale_data = []
            db_whales = db_manager.get_all_whales()
            
            for whale_row in db_whales:
                # Database columns: 0=address, 1=moralis_roi_pct, 2=roi_usd, 3=trades, 4=cumulative_pnl, 
                # 5=risk_multiplier, 6=allocation_size, 7=score, 8=win_rate, 9=bootstrap_time, 10=last_refresh
                try:
                    def safe_float(value, default=0.0):
                        """Safely convert to float with default fallback"""
                        if value is None:
                            return default
                        try:
                            return float(value)
                        except (ValueError, TypeError):
                            return default
                    
                    def safe_int(value, default=0):
                        """Safely convert to int with default fallback"""
                        if value is None:
                            return default
                        try:
                            return int(float(value))  # Convert via float first to handle string numbers
                        except (ValueError, TypeError):
                            return default
                    
                    whale_data.append({
                        "address": whale_row[0] if whale_row[0] is not None else "unknown",  # address
                        "pnl": safe_float(whale_row[4]),  # cumulative_pnl
                        "risk_multiplier": safe_float(whale_row[5], 1.0),  # risk_multiplier
                        "score": safe_float(whale_row[7]),  # score
                        "win_rate": safe_float(whale_row[8]),  # win_rate
                        "trades": safe_int(whale_row[3]),  # trades
                        "bootstrap_time": whale_row[9] if whale_row[9] is not None else None,  # bootstrap_time
                        "last_refresh": whale_row[10] if whale_row[10] is not None else None  # last_refresh
                    })
                except Exception as e:
                    logger.warning(f"Error processing whale row in API {whale_row}: {e}")
                    continue
            
            return jsonify(whale_data)
        except Exception as e:
            logger.error(f"API whales error: {e}")
            return jsonify({"error": str(e)}), 500
    
    @app.route("/health")
    def health():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "mode": mode,
            "whales_tracked": len(whale_tracker.get_all_tracked_whales())
        })
    
    return app
