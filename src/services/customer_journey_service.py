"""
Customer journey mapping service for Mini-Hub MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class CustomerJourneyService:
    """Customer journey mapping and analysis service."""

    def __init__(self):
        self.journeys = {}  # In-memory storage for customer journeys
        self.touchpoints = {}  # In-memory storage for touchpoints
        self.journey_stages = {}  # In-memory storage for journey stages

    async def create_journey_map(
        self,
        journey_name: str,
        stages: List[Dict[str, Any]],
        touchpoints: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create a new customer journey map."""
        try:
            journey_id = str(uuid4())

            journey = {
                "id": journey_id,
                "name": journey_name,
                "stages": stages,
                "touchpoints": touchpoints,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "active": True
            }

            self.journeys[journey_id] = journey

            logger.info(f"Created journey map {journey_id}: {journey_name}")

            return {
                "success": True,
                "journey_id": journey_id,
                "journey": journey
            }

        except Exception as e:
            logger.error(f"Error creating journey map: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def track_customer_touchpoint(
        self,
        customer_id: str,
        touchpoint_type: str,
        channel: str,
        interaction_data: Dict[str, Any],
        journey_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Track a customer touchpoint in their journey."""
        try:
            touchpoint_id = str(uuid4())

            touchpoint = {
                "id": touchpoint_id,
                "customer_id": customer_id,
                "journey_id": journey_id,
                "type": touchpoint_type,
                "channel": channel,
                "interaction_data": interaction_data,
                "timestamp": datetime.now().isoformat(),
                "stage": self._determine_stage(touchpoint_type, interaction_data)
            }

            # Store touchpoint
            if customer_id not in self.touchpoints:
                self.touchpoints[customer_id] = []
            self.touchpoints[customer_id].append(touchpoint)

            # Update journey stage if journey_id provided
            if journey_id:
                await self._update_journey_stage(customer_id, journey_id, touchpoint)

            return {
                "success": True,
                "touchpoint_id": touchpoint_id,
                "touchpoint": touchpoint
            }

        except Exception as e:
            logger.error(f"Error tracking touchpoint: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _determine_stage(
        self,
        touchpoint_type: str,
        interaction_data: Dict[str, Any]
    ) -> str:
        """Determine the journey stage based on touchpoint type and data."""
        stage_mapping = {
            "website_visit": "awareness",
            "email_open": "awareness",
            "social_engagement": "awareness",
            "content_download": "consideration",
            "demo_request": "consideration",
            "trial_signup": "consideration",
            "pricing_inquiry": "decision",
            "proposal_request": "decision",
            "purchase": "conversion",
            "onboarding": "retention",
            "support_request": "retention",
            "upsell": "expansion"
        }

        return stage_mapping.get(touchpoint_type, "unknown")

    async def _update_journey_stage(
        self,
        customer_id: str,
        journey_id: str,
        touchpoint: Dict[str, Any]
    ):
        """Update customer's current journey stage."""
        if customer_id not in self.journey_stages:
            self.journey_stages[customer_id] = {}

        self.journey_stages[customer_id][journey_id] = {
            "current_stage": touchpoint["stage"],
            "last_touchpoint": touchpoint,
            "updated_at": datetime.now().isoformat()
        }

    async def get_customer_journey(
        self,
        customer_id: str,
        journey_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get a customer's complete journey."""
        try:
            if customer_id not in self.touchpoints:
                return {
                    "success": False,
                    "error": f"No journey data found for customer {customer_id}"
                }

            touchpoints = self.touchpoints[customer_id]

            # Filter by journey_id if provided
            if journey_id:
                touchpoints = [
                    tp for tp in touchpoints if tp.get("journey_id") == journey_id
                ]

            # Sort by timestamp
            touchpoints.sort(key=lambda x: x["timestamp"])

            # Analyze journey
            journey_analysis = self._analyze_journey(touchpoints)

            return {
                "success": True,
                "customer_id": customer_id,
                "journey_id": journey_id,
                "touchpoints": touchpoints,
                "analysis": journey_analysis
            }

        except Exception as e:
            logger.error(f"Error getting customer journey: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _analyze_journey(self, touchpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze customer journey patterns."""
        if not touchpoints:
            return {}

        # Journey duration
        first_touchpoint = touchpoints[0]
        last_touchpoint = touchpoints[-1]
        
        start_time = datetime.fromisoformat(first_touchpoint["timestamp"])
        end_time = datetime.fromisoformat(last_touchpoint["timestamp"])
        duration = (end_time - start_time).days

        # Stage progression
        stages_visited = list(set(tp["stage"] for tp in touchpoints))
        stage_progression = [tp["stage"] for tp in touchpoints]

        # Channel analysis
        channels = {}
        for tp in touchpoints:
            channel = tp["channel"]
            if channel not in channels:
                channels[channel] = 0
            channels[channel] += 1

        # Touchpoint frequency
        touchpoint_frequency = {}
        for tp in touchpoints:
            tp_type = tp["type"]
            if tp_type not in touchpoint_frequency:
                touchpoint_frequency[tp_type] = 0
            touchpoint_frequency[tp_type] += 1

        return {
            "duration_days": duration,
            "total_touchpoints": len(touchpoints),
            "stages_visited": stages_visited,
            "stage_progression": stage_progression,
            "channel_distribution": channels,
            "touchpoint_frequency": touchpoint_frequency,
            "current_stage": last_touchpoint["stage"]
        }

    async def get_journey_analytics(
        self,
        journey_id: Optional[str] = None,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get comprehensive journey analytics."""
        try:
            # Filter data by date range
            end_date = datetime.now()
            if date_range == "last_7_days":
                start_date = end_date - timedelta(days=7)
            elif date_range == "last_30_days":
                start_date = end_date - timedelta(days=30)
            else:
                start_date = end_date - timedelta(days=30)

            # Collect all touchpoints
            all_touchpoints = []
            for customer_touchpoints in self.touchpoints.values():
                for tp in customer_touchpoints:
                    tp_time = datetime.fromisoformat(tp["timestamp"])
                    if start_date <= tp_time <= end_date:
                        if not journey_id or tp.get("journey_id") == journey_id:
                            all_touchpoints.append(tp)

            # Analyze patterns
            analytics = {
                "total_customers": len(set(tp["customer_id"] for tp in all_touchpoints)),
                "total_touchpoints": len(all_touchpoints),
                "stage_distribution": {},
                "channel_distribution": {},
                "touchpoint_type_distribution": {},
                "avg_journey_duration": 0,
                "conversion_rate": 0
            }

            # Calculate distributions
            for tp in all_touchpoints:
                stage = tp["stage"]
                channel = tp["channel"]
                tp_type = tp["type"]

                analytics["stage_distribution"][stage] = \
                    analytics["stage_distribution"].get(stage, 0) + 1
                analytics["channel_distribution"][channel] = \
                    analytics["channel_distribution"].get(channel, 0) + 1
                analytics["touchpoint_type_distribution"][tp_type] = \
                    analytics["touchpoint_type_distribution"].get(tp_type, 0) + 1

            # Calculate conversion rate
            conversion_touchpoints = [
                tp for tp in all_touchpoints if tp["stage"] == "conversion"
            ]
            if all_touchpoints:
                analytics["conversion_rate"] = (
                    len(conversion_touchpoints) / len(all_touchpoints) * 100
                )

            return {
                "success": True,
                "analytics": analytics,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                }
            }

        except Exception as e:
            logger.error(f"Error getting journey analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def optimize_journey(
        self,
        journey_id: str,
        optimization_goals: List[str]
    ) -> Dict[str, Any]:
        """Generate journey optimization recommendations."""
        try:
            if journey_id not in self.journeys:
                return {
                    "success": False,
                    "error": f"Journey {journey_id} not found"
                }

            journey = self.journeys[journey_id]
            recommendations = []

            # Analyze journey stages
            stage_analysis = {}
            for stage in journey["stages"]:
                stage_name = stage["name"]
                stage_touchpoints = [
                    tp for tp in self.touchpoints.values()
                    if any(tp_item.get("stage") == stage_name for tp_item in tp)
                ]
                
                stage_analysis[stage_name] = {
                    "touchpoint_count": len(stage_touchpoints),
                    "avg_duration": self._calculate_stage_duration(stage_touchpoints)
                }

            # Generate recommendations based on goals
            for goal in optimization_goals:
                if goal == "reduce_friction":
                    recommendations.extend(
                        self._generate_friction_reduction_recommendations(stage_analysis)
                    )
                elif goal == "increase_engagement":
                    recommendations.extend(
                        self._generate_engagement_recommendations(stage_analysis)
                    )
                elif goal == "improve_conversion":
                    recommendations.extend(
                        self._generate_conversion_recommendations(stage_analysis)
                    )

            return {
                "success": True,
                "journey_id": journey_id,
                "stage_analysis": stage_analysis,
                "recommendations": recommendations
            }

        except Exception as e:
            logger.error(f"Error optimizing journey: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_stage_duration(self, touchpoints: List[Dict[str, Any]]) -> float:
        """Calculate average duration for a stage."""
        if len(touchpoints) < 2:
            return 0.0

        durations = []
        for i in range(len(touchpoints) - 1):
            current_time = datetime.fromisoformat(touchpoints[i]["timestamp"])
            next_time = datetime.fromisoformat(touchpoints[i + 1]["timestamp"])
            duration = (next_time - current_time).days
            durations.append(duration)

        return sum(durations) / len(durations) if durations else 0.0

    def _generate_friction_reduction_recommendations(
        self,
        stage_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations to reduce journey friction."""
        recommendations = []

        for stage_name, analysis in stage_analysis.items():
            if analysis["avg_duration"] > 7:  # More than a week
                recommendations.append({
                    "type": "friction_reduction",
                    "stage": stage_name,
                    "title": f"Reduce {stage_name} stage duration",
                    "description": f"Average duration of {analysis['avg_duration']:.1f} days is too long.",
                    "actions": [
                        "Simplify forms and processes",
                        "Add progress indicators",
                        "Provide immediate feedback"
                    ]
                })

        return recommendations

    def _generate_engagement_recommendations(
        self,
        stage_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations to increase engagement."""
        recommendations = []

        for stage_name, analysis in stage_analysis.items():
            if analysis["touchpoint_count"] < 3:  # Low engagement
                recommendations.append({
                    "type": "engagement",
                    "stage": stage_name,
                    "title": f"Increase engagement in {stage_name} stage",
                    "description": f"Only {analysis['touchpoint_count']} touchpoints detected.",
                    "actions": [
                        "Add personalized content",
                        "Implement retargeting campaigns",
                        "Create interactive experiences"
                    ]
                })

        return recommendations

    def _generate_conversion_recommendations(
        self,
        stage_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations to improve conversion."""
        recommendations = []

        # Look for decision stage issues
        if "decision" in stage_analysis:
            decision_analysis = stage_analysis["decision"]
            if decision_analysis["touchpoint_count"] < 2:
                recommendations.append({
                    "type": "conversion",
                    "stage": "decision",
                    "title": "Improve decision stage conversion",
                    "description": "Low engagement in decision stage.",
                    "actions": [
                        "Add social proof elements",
                        "Provide comparison tools",
                        "Offer limited-time incentives"
                    ]
                })

        return recommendations 