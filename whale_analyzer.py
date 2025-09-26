#!/usr/bin/env python3
"""
Whale Analyzer - Automated Copy Trading Analysis

This script analyzes all tracked whales and generates a webpage with
ranked recommendations for copy trading based on multiple criteria.
"""

import sys
import os
import logging
import math
from pathlib import Path
from typing import List, Dict, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

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

@dataclass
class WhaleAnalysis:
    """Analysis results for a single whale"""
    address: str
    score_v2: float
    roi_pct: float
    profit_usd: float
    trades: int
    win_rate: float
    risk_multiplier: float
    token_count: int
    token_breakdown: List[Tuple]  # (symbol, address, pnl, trades, last_updated)
    
    # Calculated metrics
    diversification_score: float
    concentration_risk: float
    copy_trading_score: float
    risk_level: str
    recommendation: str
    reasons: List[str]

class WhaleAnalyzer:
    """Analyzes whales for copy trading suitability"""
    
    def __init__(self, db_file: str = "whales.db"):
        self.db_manager = DatabaseManager(db_file)
    
    def calculate_diversification_score(self, token_breakdown: List[Tuple]) -> float:
        """Calculate diversification score (0-100)"""
        if not token_breakdown:
            return 0.0
        
        # Filter out PROCESSED marker and calculate total PnL
        # token_breakdown format: (symbol, address, pnl, trades, last_updated)
        valid_tokens = [(row[0], row[2], row[3]) for row in token_breakdown if row[0] != "PROCESSED"]
        if not valid_tokens:
            return 0.0
        
        total_pnl = sum(pnl for _, pnl, _ in valid_tokens)
        if total_pnl <= 0:
            return 0.0
        
        # Calculate Herfindahl-Hirschman Index (HHI) for concentration
        hhi = 0
        for _, pnl, _ in valid_tokens:
            if pnl > 0:  # Only count profitable tokens
                weight = pnl / total_pnl
                hhi += weight ** 2
        
        # Convert HHI to diversification score (0-100)
        # HHI = 1 means completely concentrated, HHI = 0 means perfectly diversified
        diversification_score = (1 - hhi) * 100
        
        # Bonus for more tokens
        token_bonus = min(len(valid_tokens) * 2, 20)  # Max 20 point bonus
        
        return min(diversification_score + token_bonus, 100)
    
    def calculate_concentration_risk(self, token_breakdown: List[Tuple]) -> float:
        """Calculate concentration risk (0-100, higher = more risky)"""
        if not token_breakdown:
            return 100.0
        
        # token_breakdown format: (symbol, address, pnl, trades, last_updated)
        valid_tokens = [(row[0], row[2], row[3]) for row in token_breakdown if row[0] != "PROCESSED"]
        if not valid_tokens:
            return 100.0
        
        total_pnl = sum(pnl for _, pnl, _ in valid_tokens)
        if total_pnl <= 0:
            return 100.0
        
        # Find top token's percentage of total PnL
        top_token_pnl = max(pnl for _, pnl, _ in valid_tokens)
        top_token_percentage = (top_token_pnl / total_pnl) * 100
        
        # Calculate top 3 tokens' percentage
        sorted_tokens = sorted(valid_tokens, key=lambda x: x[1], reverse=True)
        top3_pnl = sum(pnl for _, pnl, _ in sorted_tokens[:3])
        top3_percentage = (top3_pnl / total_pnl) * 100
        
        # Risk score based on concentration
        risk_score = (top_token_percentage * 0.7) + (top3_percentage * 0.3)
        
        return min(risk_score, 100)
    
    def calculate_copy_trading_score(self, whale: WhaleAnalysis) -> float:
        """Calculate overall copy trading suitability score (0-100)"""
        
        # Base score from Score v2.0 (normalized to 0-100)
        base_score = min(whale.score_v2 / 5, 100)  # Assume max score around 500
        
        # Diversification bonus (0-30 points)
        diversification_bonus = whale.diversification_score * 0.3
        
        # Trade volume bonus (0-20 points)
        volume_bonus = min(whale.trades / 25, 20)  # Max 20 points for 500+ trades
        
        # Win rate bonus (0-15 points)
        win_rate_bonus = whale.win_rate * 15  # Max 15 points for 100% win rate
        
        # Risk penalty (0-25 points penalty)
        risk_penalty = whale.concentration_risk * 0.25
        
        # Token count bonus (0-10 points)
        token_bonus = min(whale.token_count / 2, 10)  # Max 10 points for 20+ tokens
        
        # Calculate final score
        final_score = base_score + diversification_bonus + volume_bonus + win_rate_bonus - risk_penalty + token_bonus
        
        return max(0, min(final_score, 100))
    
    def determine_risk_level(self, concentration_risk: float, risk_multiplier: float) -> str:
        """Determine risk level based on concentration and risk multiplier"""
        if concentration_risk > 80 or risk_multiplier > 1.4:
            return "VERY HIGH"
        elif concentration_risk > 60 or risk_multiplier > 1.2:
            return "HIGH"
        elif concentration_risk > 40 or risk_multiplier > 1.1:
            return "MEDIUM"
        else:
            return "LOW"
    
    def generate_recommendation(self, whale: WhaleAnalysis) -> Tuple[str, List[str]]:
        """Generate recommendation and reasons"""
        reasons = []
        
        # Determine recommendation
        if whale.copy_trading_score >= 80:
            recommendation = "EXCELLENT"
        elif whale.copy_trading_score >= 65:
            recommendation = "GOOD"
        elif whale.copy_trading_score >= 50:
            recommendation = "FAIR"
        elif whale.copy_trading_score >= 35:
            recommendation = "POOR"
        else:
            recommendation = "AVOID"
        
        # Generate reasons
        if whale.trades >= 300:
            reasons.append(f"High trade volume ({whale.trades} trades)")
        elif whale.trades >= 200:
            reasons.append(f"Good trade volume ({whale.trades} trades)")
        elif whale.trades < 100:
            reasons.append(f"Low trade volume ({whale.trades} trades)")
        
        if whale.token_count >= 15:
            reasons.append(f"Excellent diversification ({whale.token_count} tokens)")
        elif whale.token_count >= 10:
            reasons.append(f"Good diversification ({whale.token_count} tokens)")
        elif whale.token_count < 5:
            reasons.append(f"Poor diversification ({whale.token_count} tokens)")
        
        if whale.diversification_score >= 70:
            reasons.append("Well-balanced token allocation")
        elif whale.diversification_score < 30:
            reasons.append("Highly concentrated in few tokens")
        
        if whale.concentration_risk > 80:
            reasons.append("Very high concentration risk")
        elif whale.concentration_risk > 60:
            reasons.append("High concentration risk")
        
        if whale.win_rate >= 0.7:
            reasons.append(f"High win rate ({whale.win_rate*100:.1f}%)")
        elif whale.win_rate < 0.5:
            reasons.append(f"Low win rate ({whale.win_rate*100:.1f}%)")
        
        if whale.roi_pct >= 100:
            reasons.append(f"Excellent ROI ({whale.roi_pct:.1f}%)")
        elif whale.roi_pct >= 50:
            reasons.append(f"Good ROI ({whale.roi_pct:.1f}%)")
        elif whale.roi_pct < 0:
            reasons.append(f"Negative ROI ({whale.roi_pct:.1f}%)")
        
        if whale.risk_multiplier > 1.3:
            reasons.append(f"High risk multiplier ({whale.risk_multiplier:.2f})")
        elif whale.risk_multiplier < 1.1:
            reasons.append(f"Conservative risk ({whale.risk_multiplier:.2f})")
        
        return recommendation, reasons
    
    def analyze_whale(self, whale_data: Tuple) -> WhaleAnalysis:
        """Analyze a single whale"""
        # Database columns: 0=address, 1=moralis_roi_pct, 2=roi_usd, 3=trades, 4=bootstrap_time, 
        # 5=last_refresh, 6=cumulative_pnl, 7=risk_multiplier, 8=allocation_size, 9=score, 10=win_rate, 11=discarded_timestamp
        address = whale_data[0]
        roi_pct = whale_data[1] if len(whale_data) > 1 else 0
        profit_usd = whale_data[2] if len(whale_data) > 2 else 0
        trades = whale_data[3] if len(whale_data) > 3 else 0
        score_v2 = whale_data[9] if len(whale_data) > 9 else 0
        win_rate = whale_data[10] if len(whale_data) > 10 else 0
        risk_multiplier = whale_data[7] if len(whale_data) > 7 else 1.0
        
        # Get token breakdown
        token_breakdown = self.db_manager.get_whale_token_breakdown(address)
        token_count = len([t for t in token_breakdown if t[0] != "PROCESSED"])
        
        # Create analysis object
        whale = WhaleAnalysis(
            address=address,
            score_v2=score_v2,
            roi_pct=roi_pct,
            profit_usd=profit_usd,
            trades=trades,
            win_rate=win_rate,
            risk_multiplier=risk_multiplier,
            token_count=token_count,
            token_breakdown=token_breakdown,
            diversification_score=0,  # Will be calculated
            concentration_risk=0,     # Will be calculated
            copy_trading_score=0,     # Will be calculated
            risk_level="",            # Will be calculated
            recommendation="",        # Will be calculated
            reasons=[]                # Will be calculated
        )
        
        # Calculate metrics
        whale.diversification_score = self.calculate_diversification_score(token_breakdown)
        whale.concentration_risk = self.calculate_concentration_risk(token_breakdown)
        whale.copy_trading_score = self.calculate_copy_trading_score(whale)
        whale.risk_level = self.determine_risk_level(whale.concentration_risk, whale.risk_multiplier)
        whale.recommendation, whale.reasons = self.generate_recommendation(whale)
        
        return whale
    
    def analyze_all_whales(self) -> List[WhaleAnalysis]:
        """Analyze all tracked whales"""
        logger.info("Analyzing all tracked whales...")
        
        # Get all non-discarded whales
        all_whales = self.db_manager.get_all_whales_sorted_by_score()
        logger.info(f"Found {len(all_whales)} whales to analyze")
        
        analyses = []
        for i, whale_data in enumerate(all_whales, 1):
            logger.info(f"Analyzing whale {i}/{len(all_whales)}: {whale_data[0][:10]}...")
            try:
                analysis = self.analyze_whale(whale_data)
                analyses.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing whale {whale_data[0]}: {e}")
                continue
        
        # Sort by copy trading score (descending)
        analyses.sort(key=lambda x: x.copy_trading_score, reverse=True)
        
        logger.info(f"Analysis complete. Generated {len(analyses)} whale analyses.")
        return analyses
    
    def generate_html_report(self, analyses: List[WhaleAnalysis], output_file: str = "whale_analysis_report.html"):
        """Generate HTML report with whale recommendations"""
        
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Whale Copy Trading Analysis Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8f9fa;
            color: #333;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
        }}
        .header p {{
            margin: 10px 0 0 0;
            font-size: 1.2em;
            opacity: 0.9;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            color: #667eea;
        }}
        .summary-card .number {{
            font-size: 2em;
            font-weight: bold;
            color: #333;
        }}
        .whale-card {{
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            border-left: 5px solid #ddd;
        }}
        .whale-card.excellent {{ border-left-color: #28a745; }}
        .whale-card.good {{ border-left-color: #17a2b8; }}
        .whale-card.fair {{ border-left-color: #ffc107; }}
        .whale-card.poor {{ border-left-color: #fd7e14; }}
        .whale-card.avoid {{ border-left-color: #dc3545; }}
        .whale-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }}
        .whale-address {{
            font-family: 'Courier New', monospace;
            font-size: 1.1em;
            font-weight: bold;
            color: #333;
        }}
        .copy-btn {{
            background: #007bff;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
        }}
        .copy-btn:hover {{
            background: #0056b3;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .metric {{
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }}
        .metric-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 1.2em;
            font-weight: bold;
            color: #333;
        }}
        .recommendation {{
            background: #e9ecef;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
        }}
        .recommendation.excellent {{ background: #d4edda; color: #155724; }}
        .recommendation.good {{ background: #d1ecf1; color: #0c5460; }}
        .recommendation.fair {{ background: #fff3cd; color: #856404; }}
        .recommendation.poor {{ background: #f8d7da; color: #721c24; }}
        .recommendation.avoid {{ background: #f5c6cb; color: #721c24; }}
        .reasons {{
            margin-top: 15px;
        }}
        .reasons h4 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .reasons ul {{
            margin: 0;
            padding-left: 20px;
        }}
        .reasons li {{
            margin-bottom: 5px;
        }}
        .token-breakdown {{
            margin-top: 20px;
        }}
        .token-breakdown h4 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .token-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .token {{
            background: #e9ecef;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        .token.positive {{ background: #d4edda; color: #155724; }}
        .token.negative {{ background: #f8d7da; color: #721c24; }}
        .risk-indicator {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .risk-low {{ background: #d4edda; color: #155724; }}
        .risk-medium {{ background: #fff3cd; color: #856404; }}
        .risk-high {{ background: #f8d7da; color: #721c24; }}
        .risk-very-high {{ background: #f5c6cb; color: #721c24; }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #666;
            border-top: 1px solid #dee2e6;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🐋 Whale Copy Trading Analysis</h1>
        <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="summary">
        <div class="summary-card">
            <h3>Total Whales</h3>
            <div class="number">{len(analyses)}</div>
        </div>
        <div class="summary-card">
            <h3>Excellent</h3>
            <div class="number">{len([w for w in analyses if w.recommendation == 'EXCELLENT'])}</div>
        </div>
        <div class="summary-card">
            <h3>Good</h3>
            <div class="number">{len([w for w in analyses if w.recommendation == 'GOOD'])}</div>
        </div>
        <div class="summary-card">
            <h3>Fair</h3>
            <div class="number">{len([w for w in analyses if w.recommendation == 'FAIR'])}</div>
        </div>
        <div class="summary-card">
            <h3>Poor/Avoid</h3>
            <div class="number">{len([w for w in analyses if w.recommendation in ['POOR', 'AVOID']])}</div>
        </div>
    </div>
    
    <div class="whales">
"""
        
        for i, whale in enumerate(analyses, 1):
            # Get top 5 tokens for display
            # token_breakdown format: (symbol, address, pnl, trades, last_updated)
            top_tokens = sorted(whale.token_breakdown, key=lambda x: x[2], reverse=True)[:5]
            top_tokens = [(row[0], row[2], row[3]) for row in top_tokens if row[0] != "PROCESSED"]
            
            html_content += f"""
        <div class="whale-card {whale.recommendation.lower()}">
            <div class="whale-header">
                <div>
                    <div class="whale-address">{whale.address}</div>
                    <div style="font-size: 0.9em; color: #666; margin-top: 5px;">
                        Rank #{i} | Copy Trading Score: {whale.copy_trading_score:.1f}/100
                    </div>
                </div>
                <button class="copy-btn" onclick="copyAddress('{whale.address}')">Copy Address</button>
            </div>
            
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">Score v2.0</div>
                    <div class="metric-value">{whale.score_v2:.2f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">ROI</div>
                    <div class="metric-value">{whale.roi_pct:.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Profit</div>
                    <div class="metric-value">${whale.profit_usd:,.0f}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Trades</div>
                    <div class="metric-value">{whale.trades:,}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value">{whale.win_rate*100:.1f}%</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Tokens</div>
                    <div class="metric-value">{whale.token_count}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Diversification</div>
                    <div class="metric-value">{whale.diversification_score:.1f}/100</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Risk Level</div>
                    <div class="metric-value">
                        <span class="risk-indicator risk-{whale.risk_level.lower().replace(' ', '-')}">{whale.risk_level}</span>
                    </div>
                </div>
            </div>
            
            <div class="recommendation {whale.recommendation.lower()}">
                <strong>Recommendation: {whale.recommendation}</strong>
            </div>
            
            <div class="reasons">
                <h4>Analysis:</h4>
                <ul>
"""
            
            for reason in whale.reasons:
                html_content += f"                    <li>{reason}</li>\n"
            
            html_content += f"""
                </ul>
            </div>
            
            <div class="token-breakdown">
                <h4>Top Tokens:</h4>
                <div class="token-list">
"""
            
            for symbol, pnl, trades in top_tokens:
                token_class = "positive" if pnl > 0 else "negative"
                html_content += f'                    <span class="token {token_class}">{symbol}: {pnl:.2f} ETH ({trades} trades)</span>\n'
            
            html_content += """
                </div>
            </div>
        </div>
"""
        
        html_content += """
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
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML report generated: {output_file}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze whales for copy trading suitability")
    parser.add_argument("--output", "-o", default="whale_analysis_report.html",
                       help="Output HTML file (default: whale_analysis_report.html)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create analyzer and run analysis
    analyzer = WhaleAnalyzer()
    analyses = analyzer.analyze_all_whales()
    
    # Generate HTML report
    analyzer.generate_html_report(analyses, args.output)
    
    # Print summary
    print(f"\n{'='*60}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"Total whales analyzed: {len(analyses)}")
    print(f"Excellent recommendations: {len([w for w in analyses if w.recommendation == 'EXCELLENT'])}")
    print(f"Good recommendations: {len([w for w in analyses if w.recommendation == 'GOOD'])}")
    print(f"Fair recommendations: {len([w for w in analyses if w.recommendation == 'FAIR'])}")
    print(f"Poor/Avoid recommendations: {len([w for w in analyses if w.recommendation in ['POOR', 'AVOID']])}")
    print(f"\nHTML report generated: {args.output}")
    print(f"Open the file in your browser to view the full analysis!")

if __name__ == "__main__":
    main()
