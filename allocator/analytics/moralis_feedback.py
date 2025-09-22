"""
Moralis feedback tracking and auto-adjustment system
"""

import logging
import json
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class MoralisRejection:
    """Track a Moralis rejection event"""
    address: str
    timestamp: float
    reason: str
    roi_pct: Optional[float] = None
    profit_usd: Optional[float] = None
    trades: Optional[int] = None
    discovery_mode: str = ""
    stage1_trades: int = 0
    stage1_pnl: float = 0.0


@dataclass
class MoralisAcceptance:
    """Track a Moralis acceptance event"""
    address: str
    timestamp: float
    roi_pct: float
    profit_usd: float
    trades: int
    discovery_mode: str = ""
    stage1_trades: int = 0
    stage1_pnl: float = 0.0


class MoralisFeedbackTracker:
    """Track Moralis API feedback and auto-adjust discovery thresholds"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager
        
        # In-memory tracking
        self.rejections = deque(maxlen=1000)  # Keep last 1000 rejections
        self.acceptances = deque(maxlen=1000)  # Keep last 1000 acceptances
        
        # Auto-adjustment settings
        self.min_samples_for_adjustment = 10
        self.adjustment_sensitivity = 0.1  # How aggressively to adjust (0.0-1.0)
        
        # Tracked rejection reasons
        self.rejection_categories = {
            "low_roi": "ROI below minimum threshold",
            "low_profit": "Profit USD below minimum threshold", 
            "low_trades": "Trade count below minimum threshold",
            "spam_detection": "Detected as spam/bot activity",
            "api_error": "Moralis API error",
            "data_quality": "Poor data quality",
            "duplicate": "Duplicate address"
        }
    
    def track_moralis_rejection(self, address: str, reason: str, 
                              roi_pct: Optional[float] = None,
                              profit_usd: Optional[float] = None,
                              trades: Optional[int] = None,
                              discovery_mode: str = "",
                              stage1_trades: int = 0,
                              stage1_pnl: float = 0.0) -> None:
        """Track a Moralis rejection"""
        rejection = MoralisRejection(
            address=address,
            timestamp=time.time(),
            reason=reason,
            roi_pct=roi_pct,
            profit_usd=profit_usd,
            trades=trades,
            discovery_mode=discovery_mode,
            stage1_trades=stage1_trades,
            stage1_pnl=stage1_pnl
        )
        
        self.rejections.append(rejection)
        
        # Save to database if available
        if self.db:
            try:
                self.db.save_moralis_feedback({
                    'type': 'rejection',
                    'data': asdict(rejection)
                })
            except Exception as e:
                logger.debug(f"Failed to save rejection to DB: {e}")
        
        logger.debug(f"Tracked Moralis rejection: {address[:10]}... - {reason}")
    
    def track_moralis_acceptance(self, address: str, roi_pct: float,
                               profit_usd: float, trades: int,
                               discovery_mode: str = "",
                               stage1_trades: int = 0,
                               stage1_pnl: float = 0.0) -> None:
        """Track a Moralis acceptance"""
        acceptance = MoralisAcceptance(
            address=address,
            timestamp=time.time(),
            roi_pct=roi_pct,
            profit_usd=profit_usd,
            trades=trades,
            discovery_mode=discovery_mode,
            stage1_trades=stage1_trades,
            stage1_pnl=stage1_pnl
        )
        
        self.acceptances.append(acceptance)
        
        # Save to database if available
        if self.db:
            try:
                self.db.save_moralis_feedback({
                    'type': 'acceptance',
                    'data': asdict(acceptance)
                })
            except Exception as e:
                logger.debug(f"Failed to save acceptance to DB: {e}")
        
        logger.debug(f"Tracked Moralis acceptance: {address[:10]}... - ROI: {roi_pct}%")
    
    def analyze_rejection_patterns(self, mode: str = "", hours_back: int = 24) -> Dict:
        """Analyze rejection patterns to identify adjustment opportunities"""
        cutoff_time = time.time() - (hours_back * 3600)
        
        # Filter recent rejections for this mode
        recent_rejections = [
            r for r in self.rejections 
            if r.timestamp >= cutoff_time and (not mode or r.discovery_mode == mode)
        ]
        
        recent_acceptances = [
            a for a in self.acceptances
            if a.timestamp >= cutoff_time and (not mode or a.discovery_mode == mode)
        ]
        
        if not recent_rejections and not recent_acceptances:
            return {"insufficient_data": True}
        
        total_attempts = len(recent_rejections) + len(recent_acceptances)
        acceptance_rate = len(recent_acceptances) / total_attempts if total_attempts > 0 else 0
        
        # Categorize rejections
        rejection_reasons = defaultdict(int)
        for rejection in recent_rejections:
            rejection_reasons[rejection.reason] += 1
        
        # Analyze threshold issues
        analysis = {
            "total_attempts": total_attempts,
            "acceptance_rate": acceptance_rate,
            "rejection_count": len(recent_rejections),
            "acceptance_count": len(recent_acceptances),
            "rejection_reasons": dict(rejection_reasons),
            "recommendations": self._generate_recommendations(recent_rejections, recent_acceptances),
            "mode": mode,
            "hours_analyzed": hours_back
        }
        
        return analysis
    
    def _generate_recommendations(self, rejections: List[MoralisRejection], 
                                acceptances: List[MoralisAcceptance]) -> Dict:
        """Generate threshold adjustment recommendations"""
        recommendations = {
            "stage1_adjustments": {},
            "moralis_adjustments": {},
            "confidence": 0.0
        }
        
        if len(rejections) + len(acceptances) < self.min_samples_for_adjustment:
            recommendations["confidence"] = 0.0
            return recommendations
        
        # Analyze stage-1 thresholds (pre-Moralis filtering)
        if rejections:
            # If high rejection rate due to low ROI/profit, increase stage-1 thresholds
            low_roi_rejections = [r for r in rejections if r.reason == "low_roi"]
            low_profit_rejections = [r for r in rejections if r.reason == "low_profit"]
            low_trades_rejections = [r for r in rejections if r.reason == "low_trades"]
            
            rejection_rate = len(rejections) / (len(rejections) + len(acceptances))
            
            if rejection_rate > 0.8:  # More than 80% rejection rate
                if len(low_roi_rejections) > len(rejections) * 0.5:
                    # Too many low ROI rejections - increase profit threshold
                    avg_rejected_pnl = sum(r.stage1_pnl for r in low_roi_rejections if r.stage1_pnl > 0)
                    if avg_rejected_pnl > 0:
                        avg_rejected_pnl /= len([r for r in low_roi_rejections if r.stage1_pnl > 0])
                        recommended_pnl = avg_rejected_pnl * 1.5
                        recommendations["stage1_adjustments"]["min_pnl_threshold"] = recommended_pnl
                
                if len(low_trades_rejections) > len(rejections) * 0.3:
                    # Too many low trade rejections - increase trade threshold
                    avg_rejected_trades = sum(r.stage1_trades for r in low_trades_rejections if r.stage1_trades > 0)
                    if avg_rejected_trades > 0:
                        avg_rejected_trades /= len([r for r in low_trades_rejections if r.stage1_trades > 0])
                        recommended_trades = int(avg_rejected_trades * 1.3)
                        recommendations["stage1_adjustments"]["min_trades"] = recommended_trades
            
            elif rejection_rate < 0.3:  # Less than 30% rejection rate
                # Low rejection rate - could potentially lower thresholds to find more candidates
                if acceptances:
                    avg_accepted_pnl = sum(a.stage1_pnl for a in acceptances if a.stage1_pnl > 0)
                    if avg_accepted_pnl > 0:
                        avg_accepted_pnl /= len([a for a in acceptances if a.stage1_pnl > 0])
                        recommended_pnl = avg_accepted_pnl * 0.8
                        recommendations["stage1_adjustments"]["min_pnl_threshold"] = recommended_pnl
        
        # Set confidence based on sample size
        total_samples = len(rejections) + len(acceptances)
        recommendations["confidence"] = min(1.0, total_samples / (self.min_samples_for_adjustment * 3))
        
        return recommendations
    
    def get_adjustment_suggestions(self, mode: str, current_thresholds: Dict) -> Dict:
        """Get specific adjustment suggestions for a discovery mode"""
        analysis = self.analyze_rejection_patterns(mode=mode)
        
        if analysis.get("insufficient_data"):
            return {"adjustments": {}, "confidence": 0.0, "reason": "insufficient_data"}
        
        recommendations = analysis.get("recommendations", {})
        stage1_adjustments = recommendations.get("stage1_adjustments", {})
        
        if not stage1_adjustments:
            return {"adjustments": {}, "confidence": recommendations.get("confidence", 0.0), 
                   "reason": "no_adjustments_needed"}
        
        # Apply sensitivity factor
        adjustments = {}
        for key, suggested_value in stage1_adjustments.items():
            if key in current_thresholds:
                current_value = current_thresholds[key]
                
                # Apply gradual adjustment based on sensitivity
                if isinstance(current_value, (int, float)):
                    adjustment = (suggested_value - current_value) * self.adjustment_sensitivity
                    new_value = current_value + adjustment
                    
                    # Ensure reasonable bounds
                    if key == "min_trades":
                        new_value = max(1, min(50, int(new_value)))
                    elif key == "min_pnl_threshold":
                        new_value = max(0.1, min(1000.0, new_value))
                    
                    adjustments[key] = new_value
        
        return {
            "adjustments": adjustments,
            "confidence": recommendations.get("confidence", 0.0),
            "analysis": analysis,
            "reason": "feedback_based"
        }
    
    def get_rejection_summary(self, hours_back: int = 24) -> Dict:
        """Get summary of rejections for logging/dashboard"""
        cutoff_time = time.time() - (hours_back * 3600)
        
        recent_rejections = [r for r in self.rejections if r.timestamp >= cutoff_time]
        recent_acceptances = [a for a in self.acceptances if a.timestamp >= cutoff_time]
        
        # Group by mode
        by_mode = defaultdict(lambda: {"rejections": 0, "acceptances": 0, "reasons": defaultdict(int)})
        
        for rejection in recent_rejections:
            mode = rejection.discovery_mode or "unknown"
            by_mode[mode]["rejections"] += 1
            by_mode[mode]["reasons"][rejection.reason] += 1
        
        for acceptance in recent_acceptances:
            mode = acceptance.discovery_mode or "unknown"
            by_mode[mode]["acceptances"] += 1
        
        # Calculate rates
        summary = {}
        for mode, data in by_mode.items():
            total = data["rejections"] + data["acceptances"]
            acceptance_rate = data["acceptances"] / total if total > 0 else 0
            
            summary[mode] = {
                "total_attempts": total,
                "acceptance_rate": acceptance_rate,
                "rejection_rate": 1.0 - acceptance_rate,
                "top_rejection_reasons": dict(data["reasons"].most_common(3)) if hasattr(data["reasons"], 'most_common') else dict(data["reasons"])
            }
        
        return summary
