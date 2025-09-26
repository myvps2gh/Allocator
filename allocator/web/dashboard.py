"""
Web dashboard for Allocator AI
"""

import logging
import time
from flask import Flask, render_template_string, jsonify, request, make_response
from typing import Dict, Any, List
from decimal import Decimal
from datetime import datetime

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
        /* Global table styles removed to prevent conflicts with inline styles */
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
        .btn-expand {
            background: #28a745;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
        }
        .btn-expand:hover {
            background: #1e7e34;
        }
        .token-breakdown {
            background-color: #f8f9fa;
        }
        .token-details {
            padding: 20px;
        }
        .token-table-div {
            width: 100%;
            margin: 10px 0;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            overflow: hidden;
            font-size: 0.9em;
        }
        .token-header {
            display: flex;
            background: #e9ecef;
            font-weight: bold;
            border-bottom: 1px solid #dee2e6;
        }
        .token-row {
            display: flex;
            border-bottom: 1px solid #dee2e6;
        }
        .token-row:last-child {
            border-bottom: none;
        }
        .token-col {
            flex: 1;
            padding: 8px;
            text-align: left;
        }
        .token-col:first-child {
            flex: 1.5;
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
            <a href="/analysis" style="background: #28a745; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; margin-right: 10px;">📊 Whale Analysis</a>
            <button class="refresh-btn" onclick="location.reload()">Refresh</button>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-label">Total PnL</div>
            <div class="stat-value {% if total_pnl > 0 %}positive{% elif total_pnl < 0 %}negative{% else %}neutral{% endif %}">
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
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Mode</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Status</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Blocks to Scan</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Min Trades</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Min PnL Threshold</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Candidates Found</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Validated Whales</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Last Run Time</th>
                </tr>
            </thead>
            <tbody>
                {% for discovery in discovery_status %}
                <tr>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;"><strong>{{ discovery.mode }}</strong></td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                        <span class="status-indicator {{ 'status-online' if discovery.status == 'running' else 'status-idle' if discovery.status == 'completed' else 'status-offline' }}"></span>
                        {{ discovery.status.title() }}
                    </td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ '{:,}'.format(discovery.blocks_back|int) if discovery.blocks_back else 'N/A' }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ discovery.min_trades }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ discovery.min_pnl_threshold }} ETH</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;" class="neutral">{{ discovery.candidates_found if discovery.candidates_found is not none else 'N/A' }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;" class="{{ 'positive' if discovery.validated_whales and discovery.validated_whales > 0 else 'neutral' }}">
                        {{ discovery.validated_whales if discovery.validated_whales is not none else 'N/A' }}
                    </td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ discovery.last_run_duration if discovery.last_run_duration else 'N/A' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="table-container">
        <h2 style="margin: 0; padding: 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">Whale Performance</h2>
        <div style="overflow-x: auto;">
            <table id="whale-performance-table" style="width: 100%; min-width: 1200px; border-collapse: collapse;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Whale Address</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Cumulative PnL</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Risk Multiplier</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Allocation Size</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Trade Count</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Score v2.0 ↓</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap;">Win Rate</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap; width: 100px;">Moralis ROI%</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap; width: 120px;">Moralis PnL $</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap; width: 80px;">Tokens</th>
                        <th style="padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6; white-space: nowrap; width: 100px;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for w in whales %}
                    <tr style="border-bottom: 1px solid #dee2e6; {% if w.moralis_roi is not none and w.moralis_roi >= 20 %}background-color: rgba(40,167,69,0.05);{% elif w.moralis_roi is not none and w.moralis_roi > 0 %}background-color: rgba(255,193,7,0.05);{% else %}background-color: rgba(220,53,69,0.05);{% endif %}">
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #28a745; margin-right: 8px;"></span>
                            {{ w.address[:6] }}...{{ w.address[-4:] }}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; {% if w.pnl > 0 %}color: #28a745;{% elif w.pnl < 0 %}color: #dc3545;{% else %}color: #007bff;{% endif %}">
                            {{ '%.4f' | format(w.pnl) }}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                            {{ '%.2f' | format(w.risk) }}x
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                            {{ '%.4f' | format(w.allocation) }} ETH
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                            {{ w.count }}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; font-weight: bold;">
                            {{ '%.2f' | format(w.score) }}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">
                            {{ '%.0f' | format(w.winrate) }}%
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; width: 100px; text-align: center; overflow: hidden; text-overflow: ellipsis;">
                            {% if w.moralis_roi is not none %}
                                {% if w.moralis_roi > 999999 or w.moralis_roi < -999999 %}
                                    {{ 'ERROR' }}
                                {% else %}
                                    {{ '%.2f' | format(w.moralis_roi) }}%
                                {% endif %}
                            {% else %}
                                N/A
                            {% endif %}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; width: 120px; text-align: center; overflow: hidden; text-overflow: ellipsis;">
                            {% if w.moralis_profit_usd is not none %}
                                {% if w.moralis_profit_usd > 999999999 or w.moralis_profit_usd < -999999999 %}
                                    {{ 'ERROR' }}
                                {% else %}
                                    {{ '%.2f' | format(w.moralis_profit_usd) }}$
                                {% endif %}
                            {% else %}
                                N/A
                            {% endif %}
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; width: 80px; text-align: center;">
                            {{ w.tokens|length }} tokens
                        </td>
                        <td style="padding: 15px; border-bottom: 1px solid #dee2e6; width: 100px; text-align: center;">
                            <button style="background: #28a745; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer; font-size: 12px; margin-right: 5px;" onclick="toggleTokens('{{ w.address }}')">Show Tokens</button>
                            <button style="background: #007bff; color: white; border: none; padding: 5px 10px; border-radius: 3px; cursor: pointer; font-size: 12px;" onclick="copyAddress('{{ w.address }}')">Copy</button>
                        </td>
                    </tr>
                    <!-- Token breakdown row (hidden by default) -->
                    <tr id="tokens-{{ w.address }}" style="display: none; background-color: #f8f9fa;">
                        <td colspan="11" style="padding: 20px; border-bottom: 1px solid #dee2e6;">
                            <h4 style="margin: 0 0 15px 0; color: #495057;">Token Breakdown for {{ w.address[:6] }}...{{ w.address[-4:] }}</h4>
                            {% if w.tokens %}
                            <table style="width: 100%; border-collapse: collapse; background: white; border: 1px solid #dee2e6; border-radius: 4px;">
                                <thead>
                                    <tr style="background: #e9ecef;">
                                        <th style="padding: 10px; text-align: left; border-bottom: 1px solid #dee2e6; font-weight: 600;">Token</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 1px solid #dee2e6; font-weight: 600;">PnL (ETH)</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 1px solid #dee2e6; font-weight: 600;">Trades</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 1px solid #dee2e6; font-weight: 600;">Weight</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for token in w.tokens %}
                                    <tr>
                                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;"><strong>{{ token.symbol }}</strong></td>
                                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6; {% if token.pnl > 0 %}color: #28a745;{% elif token.pnl < 0 %}color: #dc3545;{% else %}color: #007bff;{% endif %}">
                                            {{ '%.4f' | format(token.pnl) }}
                                        </td>
                                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">{{ token.trades }}</td>
                                        <td style="padding: 10px; border-bottom: 1px solid #dee2e6;">
                                            {% if w.pnl > 0 %}
                                                {{ '%.1f' | format((token.pnl / w.pnl) * 100) }}%
                                            {% else %}
                                                N/A
                                            {% endif %}
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                            {% else %}
                            <p style="color: #6c757d; font-style: italic;">No token-level data available yet.</p>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <div class="table-container">
        <h2 style="margin: 0; padding: 20px; background: #f8f9fa; border-bottom: 1px solid #dee2e6;">Recent Trades</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Time</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Actor</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Direction</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Amount In</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Amount Out</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">PnL</th>
                    <th style="background: #f8f9fa; padding: 15px; text-align: left; font-weight: 600; color: #495057; border-bottom: 2px solid #dee2e6;">Mode</th>
                </tr>
            </thead>
            <tbody>
                {% for t in trades %}
                <tr>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ t.timestamp }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ t.actor }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ t.token_in }} → {{ t.token_out }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ '%.4f' | format(t.amount_in) }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ '%.4f' | format(t.amount_out) }}</td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;" class="{% if t.pnl > 0 %}positive{% elif t.pnl < 0 %}negative{% else %}neutral{% endif %}">
                        {{ '%.4f' | format(t.pnl) }}
                    </td>
                    <td style="padding: 15px; border-bottom: 1px solid #dee2e6;">{{ t.mode }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <script>
        // Toggle token breakdown display
        function toggleTokens(whaleAddress) {
            const row = document.getElementById('tokens-' + whaleAddress);
            const button = document.querySelector(`button[onclick="toggleTokens('${whaleAddress}')"]`);
            
            if (row && button) {
                if (row.style.display === 'none' || row.style.display === '') {
                    row.style.display = 'table-row';
                    button.textContent = 'Hide Tokens';
                    button.style.background = '#dc3545';
                } else {
                    row.style.display = 'none';
                    button.textContent = 'Show Tokens';
                    button.style.background = '#28a745';
                }
            }
        }
        
        // Copy whale address to clipboard
        function copyAddress(whaleAddress) {
            navigator.clipboard.writeText(whaleAddress).then(function() {
                // Show feedback
                const button = document.querySelector(`button[onclick="copyAddress('${whaleAddress}')"]`);
                const originalText = button.textContent;
                button.textContent = 'Copied!';
                button.style.background = '#28a745';
                
                setTimeout(function() {
                    button.textContent = originalText;
                    button.style.background = '#007bff';
                }, 1500);
            }).catch(function(err) {
                console.error('Failed to copy address: ', err);
                alert('Failed to copy address to clipboard');
            });
        }

        // Table sorting removed - using database-level sorting by Score v2.0
    </script>
</body>
</html>
"""

# Analysis HTML template
ANALYSIS_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Whale Copy Trading Analysis - Allocator AI</title>
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
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
        }
        .header p {
            margin: 10px 0 0 0;
            font-size: 1.2em;
            opacity: 0.9;
        }
        .nav {
            text-align: center;
            margin-bottom: 30px;
        }
        .nav a {
            display: inline-block;
            background: #007bff;
            color: white;
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 5px;
            margin: 0 10px;
        }
        .nav a:hover {
            background: #0056b3;
        }
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .summary-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }
        .summary-card h3 {
            margin: 0 0 10px 0;
            color: #667eea;
        }
        .summary-card .number {
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }
        .whale-card {
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border-left: 5px solid #ddd;
        }
        .whale-card.excellent { border-left-color: #28a745; }
        .whale-card.good { border-left-color: #17a2b8; }
        .whale-card.fair { border-left-color: #ffc107; }
        .whale-card.poor { border-left-color: #fd7e14; }
        .whale-card.avoid { border-left-color: #dc3545; }
        .whale-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .whale-address {
            font-family: 'Courier New', monospace;
            font-size: 1.1em;
            font-weight: bold;
            color: #333;
        }
        .copy-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .copy-btn:hover {
            background: #0056b3;
        }
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .metric {
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .metric-label {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }
        .metric-value {
            font-size: 1.2em;
            font-weight: bold;
            color: #333;
        }
        .recommendation {
            background: #e9ecef;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
        }
        .recommendation.excellent { background: #d4edda; color: #155724; }
        .recommendation.good { background: #d1ecf1; color: #0c5460; }
        .recommendation.fair { background: #fff3cd; color: #856404; }
        .recommendation.poor { background: #f8d7da; color: #721c24; }
        .recommendation.avoid { background: #f5c6cb; color: #721c24; }
        .reasons {
            margin-top: 15px;
        }
        .reasons h4 {
            margin: 0 0 10px 0;
            color: #333;
        }
        .reasons ul {
            margin: 0;
            padding-left: 20px;
        }
        .reasons li {
            margin-bottom: 5px;
        }
        .token-breakdown {
            margin-top: 20px;
        }
        .token-breakdown h4 {
            margin: 0 0 10px 0;
            color: #333;
        }
        .token-list {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .token {
            background: #e9ecef;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.9em;
        }
        .token.positive { background: #d4edda; color: #155724; }
        .token.negative { background: #f8d7da; color: #721c24; }
        .risk-indicator {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
        }
        .risk-low { background: #d4edda; color: #155724; }
        .risk-medium { background: #fff3cd; color: #856404; }
        .risk-high { background: #f8d7da; color: #721c24; }
        .risk-very-high { background: #f5c6cb; color: #721c24; }
        .footer {
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #666;
            border-top: 1px solid #dee2e6;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🐋 Whale Copy Trading Analysis</h1>
        <p>Generated on {{ moment }} | Mode: {{ mode }}</p>
    </div>
    
    <div class="nav">
        <a href="/">← Back to Dashboard</a>
        <a href="/analysis">Refresh Analysis</a>
    </div>
    
    <div class="summary">
        <div class="summary-card">
            <h3>Total Whales</h3>
            <div class="number">{{ total_whales }}</div>
        </div>
        <div class="summary-card">
            <h3>Excellent</h3>
            <div class="number">{{ excellent_count }}</div>
        </div>
        <div class="summary-card">
            <h3>Good</h3>
            <div class="number">{{ good_count }}</div>
        </div>
        <div class="summary-card">
            <h3>Fair</h3>
            <div class="number">{{ fair_count }}</div>
        </div>
        <div class="summary-card">
            <h3>Poor/Avoid</h3>
            <div class="number">{{ poor_count }}</div>
        </div>
    </div>
    
    <div class="whales">
        {% for whale in analyses %}
        <div class="whale-card {{ whale.recommendation.lower() }}">
            <div class="whale-header">
                <div>
                    <div class="whale-address">{{ whale.address }}</div>
                    <div style="font-size: 0.9em; color: #666; margin-top: 5px;">
                        Rank #{{ loop.index }} | Copy Trading Score: {{ whale.copy_trading_score:.1f }}/100
                    </div>
                </div>
                <button class="copy-btn" onclick="copyAddress('{{ whale.address }}')">Copy Address</button>
            </div>
            
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">Score v2.0</div>
                    <div class="metric-value">{{ whale.score_v2:.2f }}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">ROI</div>
                    <div class="metric-value">{{ whale.roi_pct:.1f }}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Profit</div>
                    <div class="metric-value">${{ whale.profit_usd:,.0f }}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Trades</div>
                    <div class="metric-value">{{ whale.trades:, }}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value">{{ whale.win_rate*100:.1f }}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Tokens</div>
                    <div class="metric-value">{{ whale.token_count }}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Diversification</div>
                    <div class="metric-value">{{ whale.diversification_score:.1f }}/100</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Risk Level</div>
                    <div class="metric-value">
                        <span class="risk-indicator risk-{{ whale.risk_level.lower().replace(' ', '-') }}">{{ whale.risk_level }}</span>
                    </div>
                </div>
            </div>
            
            <div class="recommendation {{ whale.recommendation.lower() }}">
                <strong>Recommendation: {{ whale.recommendation }}</strong>
            </div>
            
            <div class="reasons">
                <h4>Analysis:</h4>
                <ul>
                    {% for reason in whale.reasons %}
                    <li>{{ reason }}</li>
                    {% endfor %}
                </ul>
            </div>
            
            <div class="token-breakdown">
                <h4>Top Tokens:</h4>
                <div class="token-list">
                    {% for symbol, pnl, trades in whale.token_breakdown %}
                    {% if loop.index <= 5 %}
                    {% if symbol != 'PROCESSED' %}
                    <span class="token {% if pnl > 0 %}positive{% else %}negative{% endif %}">{{ symbol }}: {{ pnl:.2f }} ETH ({{ trades }} trades)</span>
                    {% endif %}
                    {% endif %}
                    {% endfor %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    
    <div class="footer">
        <p>Generated by Whale Analyzer - Allocator AI</p>
        <p>Higher scores indicate better copy trading suitability</p>
    </div>
    
    <script>
        function copyAddress(address) {
            navigator.clipboard.writeText(address).then(function() {
                // Show feedback
                event.target.textContent = 'Copied!';
                event.target.style.background = '#28a745';
                
                setTimeout(function() {
                    event.target.textContent = 'Copy Address';
                    event.target.style.background = '#007bff';
                }, 1500);
            }).catch(function(err) {
                console.error('Failed to copy address: ', err);
                alert('Failed to copy address to clipboard');
            });
        }
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
        import time
        request_time = time.time()
        print(f"=== DASHBOARD REQUEST [{request_time}] ===")
        print(f"Method: {request.method}")
        print(f"URL: {request.url}")
        print(f"User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
        print(f"Referrer: {request.referrer}")
        print(f"Args: {request.args}")
        print(f"Headers: {dict(request.headers)}")
        print(f"=== END REQUEST [{request_time}] ===")
        try:
            # Get whale data from database, sorted by Score v2.0 (descending)
            whale_data = []
            db_whales = db_manager.get_all_whales_sorted_by_score()
            
            for whale_row in db_whales:
                # Database columns: 0=address, 1=moralis_roi_pct, 2=roi_usd, 3=trades, 4=bootstrap_time, 
                # 5=last_refresh, 6=cumulative_pnl, 7=risk_multiplier, 8=allocation_size, 9=score, 10=win_rate
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
                    
                    # Get token breakdown for this whale
                    token_breakdown = db_manager.get_whale_token_breakdown(whale_row[0])
                    tokens_data = []
                    for token_symbol, token_address, token_pnl, trade_count, last_updated in token_breakdown:
                        # Skip the PROCESSED marker token
                        if token_symbol == "PROCESSED":
                            continue
                        tokens_data.append({
                            "symbol": token_symbol,
                            "address": token_address,
                            "pnl": safe_float(token_pnl),
                            "trades": safe_int(trade_count)
                        })
                    
                    whale_data.append({
                        "address": whale_row[0] if whale_row[0] is not None else "unknown",  # address (index 0)
                        "pnl": safe_float(whale_row[6]),  # cumulative_pnl (index 6)
                        "risk": safe_float(whale_row[7], 1.0),  # risk_multiplier (index 7)
                        "allocation": safe_float(whale_row[8]),  # allocation_size (index 8)
                        "count": safe_int(whale_row[3]),  # trades (index 3)
                        "score": safe_float(whale_row[9]),  # score (index 9)
                        "winrate": safe_float(whale_row[10]) * 100,  # win_rate (index 10, convert to percentage)
                        "moralis_roi": safe_float(whale_row[1]) if whale_row[1] is not None else None,  # moralis_roi_pct (index 1)
                        "moralis_profit_usd": safe_float(whale_row[2]) if whale_row[2] is not None else None,  # roi_usd (index 2)
                        "moralis_trades": safe_int(whale_row[3]) if whale_row[3] is not None else None,  # trades (index 3)
                        "bootstrap_time": whale_row[4] if whale_row[4] is not None else None,  # bootstrap_time (index 4)
                        "last_refresh": whale_row[5] if whale_row[5] is not None else None,  # last_refresh (index 5)
                        "tokens": tokens_data  # Token breakdown
                    })
                except Exception as e:
                    logger.warning(f"Error processing whale row {whale_row}: {e}")
                    continue
            
            # Keep database sort order (already sorted by Score v2.0)
            # whale_data.sort(key=lambda x: x["pnl"], reverse=True)  # Removed - keeping DB sort order
            
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
            
            # Add adaptive discovery status
            try:
                adaptive_stats = db_manager.conn.execute("""
                    SELECT 
                        COUNT(*) as total_candidates,
                        SUM(CASE WHEN moralis_validated = TRUE THEN 1 ELSE 0 END) as validated_candidates,
                        SUM(CASE WHEN status = 'tokens_fetched' THEN 1 ELSE 0 END) as tokens_fetched
                    FROM adaptive_candidates
                """).fetchone()
                
                discovery_status.append({
                    "mode": "adaptive_percentile",
                    "status": "running",
                    "blocks_back": "Dynamic",
                    "min_trades": "Adaptive",
                    "min_pnl_threshold": "Market-based",
                    "candidates_found": adaptive_stats[0] if adaptive_stats else 0,
                    "validated_whales": adaptive_stats[1] if adaptive_stats else 0,
                    "last_run_duration": f"{adaptive_stats[2] if adaptive_stats else 0} tokens fetched"
                })
            except Exception as e:
                logger.warning(f"Could not get adaptive discovery stats: {e}")
                discovery_status.append({
                    "mode": "adaptive_percentile",
                    "status": "error",
                    "blocks_back": "N/A",
                    "min_trades": "N/A",
                    "min_pnl_threshold": "N/A",
                    "candidates_found": 0,
                    "validated_whales": 0,
                    "last_run_duration": "Error"
                })
            
            # Add standard discovery modes (commented out for now)
            # if hasattr(whale_tracker, 'discovery_modes') and whale_tracker.discovery_modes:
            #     for mode_name, config in whale_tracker.discovery_modes.items():
            #         discovery_status.append({
            #             "mode": mode_name,
            #             "status": "disabled",
            #             "blocks_back": config.get("blocks_back", 0),
            #             "min_trades": config.get("min_trades", 0),
            #             "min_pnl_threshold": config.get("min_pnl_threshold", 0),
            #             "candidates_found": None,
            #             "validated_whales": None,
            #             "last_run_duration": "Disabled"
            #         })
            
            response = make_response(render_template_string(
                DASHBOARD_TEMPLATE,
                whales=whale_data,  # Use real whale data
                trades=trades_data,  # Use real trades data
                discovery_status=discovery_status,  # Use real discovery status
                total_pnl=stats["total_pnl"],
                capital=stats.get("capital", 0.0),  # Use capital from stats or default to 0
                whale_count=stats["whale_count"],
                trade_count=stats["trade_count"],
                mode=mode
            ))
            
            # Disable all caching to prevent browser issues
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            page_id = int(time.time() * 1000)  # Unique timestamp
            print(f"Returning dashboard [ID:{page_id}] with {len(whale_data)} whales and {len(discovery_status)} discovery modes")
            
            # Add the page ID to the response as a comment for debugging
            response_data = response.get_data(as_text=True)
            response_data = response_data.replace("</body>", f"<!-- Page ID: {page_id} -->\n</body>")
            response.set_data(response_data)
            
            return response
            
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
        print(f"=== API /api/whales CALLED ===")
        print(f"Time: {time.time()}")
        print(f"User-Agent: {request.headers.get('User-Agent', 'Unknown')}")
        print(f"Referrer: {request.referrer}")
        print(f"Request method: {request.method}")
        print(f"Request URL: {request.url}")
        print(f"Request args: {request.args}")
        print(f"=== END API CALL ===")
        try:
            whale_data = []
            db_whales = db_manager.get_all_whales()
            
            for whale_row in db_whales:
                # Database columns: 0=address, 1=moralis_roi_pct, 2=roi_usd, 3=trades, 4=bootstrap_time, 
                # 5=last_refresh, 6=cumulative_pnl, 7=risk_multiplier, 8=allocation_size, 9=score, 10=win_rate
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
                    
                    # Get token breakdown for this whale
                    token_breakdown = db_manager.get_whale_token_breakdown(whale_row[0])
                    tokens_data = []
                    for token_symbol, token_address, token_pnl, trade_count, last_updated in token_breakdown:
                        # Skip the PROCESSED marker token
                        if token_symbol == "PROCESSED":
                            continue
                        tokens_data.append({
                            "symbol": token_symbol,
                            "address": token_address,
                            "pnl": safe_float(token_pnl),
                            "trades": safe_int(trade_count)
                        })
                    
                    whale_data.append({
                        "address": whale_row[0] if whale_row[0] is not None else "unknown",  # address (index 0)
                        "pnl": safe_float(whale_row[6]),  # cumulative_pnl (index 6)
                        "risk": safe_float(whale_row[7], 1.0),  # risk_multiplier (index 7)
                        "allocation": safe_float(whale_row[8]),  # allocation_size (index 8)
                        "count": safe_int(whale_row[3]),  # trades (index 3)
                        "score": safe_float(whale_row[9]),  # score (index 9)
                        "winrate": safe_float(whale_row[10]) * 100,  # win_rate (index 10, convert to percentage)
                        "moralis_roi": safe_float(whale_row[1]) if whale_row[1] is not None else None,  # moralis_roi_pct (index 1)
                        "moralis_profit_usd": safe_float(whale_row[2]) if whale_row[2] is not None else None,  # roi_usd (index 2)
                        "moralis_trades": safe_int(whale_row[3]) if whale_row[3] is not None else None,  # trades (index 3)
                        "bootstrap_time": whale_row[4] if whale_row[4] is not None else None,  # bootstrap_time (index 4)
                        "last_refresh": whale_row[5] if whale_row[5] is not None else None,  # last_refresh (index 5)
                        "tokens": tokens_data  # Token breakdown
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
    
    @app.route("/favicon.ico")
    def favicon():
        """Favicon handler to prevent 404s"""
        print("Favicon request intercepted")
        return "", 204
    
    @app.route("/analysis")
    def whale_analysis():
        """Whale copy trading analysis page"""
        try:
            # Import the analyzer
            from whale_analyzer import WhaleAnalyzer
            
            # Create analyzer and run analysis
            analyzer = WhaleAnalyzer()
            analyses = analyzer.analyze_all_whales()
            
            # Generate summary stats
            total_whales = len(analyses)
            excellent_count = len([w for w in analyses if w.recommendation == 'EXCELLENT'])
            good_count = len([w for w in analyses if w.recommendation == 'GOOD'])
            fair_count = len([w for w in analyses if w.recommendation == 'FAIR'])
            poor_count = len([w for w in analyses if w.recommendation in ['POOR', 'AVOID']])
            
            return render_template_string(ANALYSIS_TEMPLATE, 
                                       analyses=analyses,
                                       total_whales=total_whales,
                                       excellent_count=excellent_count,
                                       good_count=good_count,
                                       fair_count=fair_count,
                                       poor_count=poor_count,
                                       mode=mode,
                                       moment=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        except Exception as e:
            logger.error(f"Error in whale analysis: {e}")
            return f"Analysis error: {e}", 500
    
    # Add catch-all route for debugging  
    @app.route("/<path:path>")
    def catch_all(path):
        print(f"Unexpected route requested: {path}")
        return f"Path {path} not found", 404
    
    return app
