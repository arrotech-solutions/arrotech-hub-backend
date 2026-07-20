"""
Lead scoring and qualification service for Mini-Hub MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class LeadScoringService:
    """Lead scoring and qualification service."""

    def __init__(self):
        self.lead_scores = {}  # In-memory storage for lead scores
        self.scoring_rules = {}  # In-memory storage for scoring rules
        self.qualification_criteria = {}  # In-memory storage for qualification criteria

    async def create_scoring_rule(
        self,
        rule_name: str,
        criteria: Dict[str, Any],
        weights: Dict[str, float],
        threshold: float
    ) -> Dict[str, Any]:
        """Create a new lead scoring rule."""
        try:
            rule_id = str(uuid4())

            rule = {
                "id": rule_id,
                "name": rule_name,
                "criteria": criteria,
                "weights": weights,
                "threshold": threshold,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "active": True
            }

            self.scoring_rules[rule_id] = rule

            logger.info(f"Created scoring rule {rule_id}: {rule_name}")

            return {
                "success": True,
                "rule_id": rule_id,
                "rule": rule
            }

        except Exception as e:
            logger.error(f"Error creating scoring rule: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def score_lead(
        self,
        lead_data: Dict[str, Any],
        rule_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Score a lead based on available data and rules."""
        try:
            if rule_id and rule_id not in self.scoring_rules:
                return {
                    "success": False,
                    "error": f"Scoring rule {rule_id} not found"
                }

            # Use default rule if none specified
            if not rule_id:
                rule_id = list(self.scoring_rules.keys())[0] if self.scoring_rules else None

            if not rule_id:
                # Create default scoring logic
                score = self._calculate_default_score(lead_data)
            else:
                rule = self.scoring_rules[rule_id]
                score = self._calculate_score_with_rule(lead_data, rule)

            # Determine qualification status
            qualification = self._determine_qualification(score, lead_data)

            # Store lead score
            lead_id = lead_data.get("id", str(uuid4()))
            self.lead_scores[lead_id] = {
                "score": score,
                "qualification": qualification,
                "scored_at": datetime.now().isoformat(),
                "lead_data": lead_data
            }

            return {
                "success": True,
                "lead_id": lead_id,
                "score": score,
                "qualification": qualification,
                "recommendations": self._generate_recommendations(score, lead_data)
            }

        except Exception as e:
            logger.error(f"Error scoring lead: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_default_score(self, lead_data: Dict[str, Any]) -> float:
        """Calculate default lead score based on common criteria."""
        score = 0.0

        # Company size scoring
        company_size = lead_data.get("company_size", "")
        if company_size in ["enterprise", "large"]:
            score += 25
        elif company_size in ["medium"]:
            score += 15
        elif company_size in ["small"]:
            score += 10

        # Job title scoring
        job_title = lead_data.get("job_title", "").lower()
        if any(title in job_title for title in ["ceo", "founder", "president", "director"]):
            score += 30
        elif any(title in job_title for title in ["manager", "head", "lead"]):
            score += 20
        elif any(title in job_title for title in ["specialist", "coordinator"]):
            score += 10

        # Industry scoring
        industry = lead_data.get("industry", "").lower()
        high_value_industries = ["technology", "finance", "healthcare", "consulting"]
        if any(ind in industry for ind in high_value_industries):
            score += 15

        # Engagement scoring
        engagement_score = lead_data.get("engagement_score", 0)
        score += engagement_score * 0.5

        # Website activity
        page_views = lead_data.get("page_views", 0)
        score += min(page_views * 2, 20)

        # Email engagement
        email_opens = lead_data.get("email_opens", 0)
        email_clicks = lead_data.get("email_clicks", 0)
        score += email_opens * 0.5 + email_clicks * 2

        return min(score, 100.0)

    def _calculate_score_with_rule(
        self,
        lead_data: Dict[str, Any],
        rule: Dict[str, Any]
    ) -> float:
        """Calculate score using a specific rule."""
        score = 0.0
        criteria = rule.get("criteria", {})
        weights = rule.get("weights", {})

        for criterion, value in criteria.items():
            if criterion in lead_data:
                lead_value = lead_data[criterion]
                weight = weights.get(criterion, 1.0)

                # Simple matching logic
                if lead_value == value:
                    score += weight * 10
                elif isinstance(lead_value, (int, float)) and isinstance(value, (int, float)):
                    # Numeric comparison
                    if lead_value >= value:
                        score += weight * 10

        return min(score, 100.0)

    def _determine_qualification(self, score: float, lead_data: Dict[str, Any]) -> str:
        """Determine lead qualification status."""
        if score >= 80:
            return "hot"
        elif score >= 60:
            return "warm"
        elif score >= 40:
            return "lukewarm"
        else:
            return "cold"

    def _generate_recommendations(
        self,
        score: float,
        lead_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations based on lead score and data."""
        recommendations = []

        if score < 40:
            recommendations.append({
                "type": "engagement",
                "priority": "high",
                "title": "Increase Engagement",
                "description": "This lead needs more engagement to move up the funnel.",
                "actions": [
                    "Send personalized content",
                    "Invite to webinar",
                    "Schedule discovery call"
                ]
            })

        if score >= 60:
            recommendations.append({
                "type": "conversion",
                "priority": "high",
                "title": "Ready for Sales",
                "description": "This lead is qualified and ready for sales outreach.",
                "actions": [
                    "Schedule sales call",
                    "Send proposal",
                    "Invite to demo"
                ]
            })

        if lead_data.get("company_size") == "enterprise":
            recommendations.append({
                "type": "enterprise",
                "priority": "medium",
                "title": "Enterprise Lead",
                "description": "This is an enterprise lead requiring special attention.",
                "actions": [
                    "Assign enterprise sales rep",
                    "Create custom proposal",
                    "Schedule executive briefing"
                ]
            })

        return recommendations

    async def get_lead_analytics(self, date_range: Optional[str] = None) -> Dict[str, Any]:
        """Get lead scoring analytics and insights."""
        try:
            # Filter leads by date range
            end_date = datetime.now()
            if date_range == "last_7_days":
                start_date = end_date - timedelta(days=7)
            elif date_range == "last_30_days":
                start_date = end_date - timedelta(days=30)
            else:
                start_date = end_date - timedelta(days=30)

            # Analyze lead scores
            qualified_leads = 0
            total_leads = 0
            avg_score = 0.0
            score_distribution = {
                "hot": 0,
                "warm": 0,
                "lukewarm": 0,
                "cold": 0
            }

            for lead_id, lead_info in self.lead_scores.items():
                scored_at = datetime.fromisoformat(lead_info["scored_at"])
                if start_date <= scored_at <= end_date:
                    total_leads += 1
                    score = lead_info["score"]
                    avg_score += score

                    if lead_info["qualification"] in ["hot", "warm"]:
                        qualified_leads += 1

                    if score >= 80:
                        score_distribution["hot"] += 1
                    elif score >= 60:
                        score_distribution["warm"] += 1
                    elif score >= 40:
                        score_distribution["lukewarm"] += 1
                    else:
                        score_distribution["cold"] += 1

            if total_leads > 0:
                avg_score = avg_score / total_leads
                qualification_rate = (qualified_leads / total_leads) * 100
            else:
                qualification_rate = 0.0

            return {
                "success": True,
                "analytics": {
                    "total_leads": total_leads,
                    "qualified_leads": qualified_leads,
                    "qualification_rate": round(qualification_rate, 2),
                    "average_score": round(avg_score, 2),
                    "score_distribution": score_distribution,
                    "date_range": {
                        "start": start_date.strftime("%Y-%m-%d"),
                        "end": end_date.strftime("%Y-%m-%d")
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error getting lead analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def update_qualification_criteria(
        self,
        criteria_id: str,
        criteria: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update lead qualification criteria."""
        try:
            self.qualification_criteria[criteria_id] = {
                **criteria,
                "updated_at": datetime.now().isoformat()
            }

            return {
                "success": True,
                "criteria_id": criteria_id,
                "message": "Qualification criteria updated"
            }

        except Exception as e:
            logger.error(f"Error updating qualification criteria: {e}")
            return {
                "success": False,
                "error": str(e)
            } 