"""
Predictive analytics service for Mini-Hub MCP Server.
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class PredictiveAnalyticsService:
    """Predictive analytics and forecasting service."""

    def __init__(self):
        self.forecasts = {}  # In-memory storage for forecasts
        self.trends = {}  # In-memory storage for trends
        self.predictions = {}  # In-memory storage for predictions

    async def generate_forecast(
        self,
        metric: str,
        historical_data: List[Dict[str, Any]],
        forecast_periods: int = 30,
        confidence_level: float = 0.95
    ) -> Dict[str, Any]:
        """Generate forecast for a specific metric."""
        try:
            forecast_id = str(uuid4())

            # Simple forecasting logic (in production, use ML models)
            forecast_data = self._calculate_forecast(
                historical_data, forecast_periods, confidence_level
            )

            forecast = {
                "id": forecast_id,
                "metric": metric,
                "forecast_periods": forecast_periods,
                "confidence_level": confidence_level,
                "forecast_data": forecast_data,
                "created_at": datetime.now().isoformat(),
                "accuracy_metrics": self._calculate_accuracy_metrics(forecast_data)
            }

            self.forecasts[forecast_id] = forecast

            return {
                "success": True,
                "forecast_id": forecast_id,
                "forecast": forecast
            }

        except Exception as e:
            logger.error(f"Error generating forecast: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_forecast(
        self,
        historical_data: List[Dict[str, Any]],
        periods: int,
        confidence_level: float
    ) -> Dict[str, Any]:
        """Calculate forecast using simple moving average and trend analysis."""
        if not historical_data:
            return {"values": [], "confidence_intervals": []}

        # Extract values and dates
        values = [point["value"] for point in historical_data]
        dates = [point["date"] for point in historical_data]

        # Calculate moving average
        window_size = min(7, len(values))
        if window_size == 0:
            return {"values": [], "confidence_intervals": []}

        moving_avg = sum(values[-window_size:]) / window_size

        # Calculate trend
        if len(values) >= 2:
            trend = (values[-1] - values[0]) / len(values)
        else:
            trend = 0

        # Generate forecast values
        forecast_values = []
        confidence_intervals = []
        current_value = moving_avg

        for i in range(periods):
            # Add trend and some randomness
            forecast_value = current_value + trend + random.uniform(-0.1, 0.1) * current_value
            forecast_values.append(max(0, forecast_value))  # Ensure non-negative

            # Calculate confidence interval
            confidence_range = current_value * (1 - confidence_level)
            confidence_intervals.append({
                "lower": max(0, forecast_value - confidence_range),
                "upper": forecast_value + confidence_range
            })

            current_value = forecast_value

        return {
            "values": forecast_values,
            "confidence_intervals": confidence_intervals,
            "trend": trend,
            "moving_average": moving_avg
        }

    def _calculate_accuracy_metrics(self, forecast_data: Dict[str, Any]) -> Dict[str, float]:
        """Calculate forecast accuracy metrics."""
        values = forecast_data.get("values", [])
        if not values:
            return {"mape": 0.0, "rmse": 0.0}

        # For demo purposes, use simple metrics
        return {
            "mape": random.uniform(5.0, 15.0),  # Mean Absolute Percentage Error
            "rmse": random.uniform(10.0, 25.0)   # Root Mean Square Error
        }

    async def analyze_trends(
        self,
        data_source: str,
        metrics: List[str],
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze trends in marketing data."""
        try:
            # Generate mock trend data
            trends = {}
            for metric in metrics:
                trends[metric] = self._generate_trend_analysis(metric, date_range)

            trend_analysis = {
                "data_source": data_source,
                "metrics": metrics,
                "trends": trends,
                "insights": self._generate_trend_insights(trends),
                "recommendations": self._generate_trend_recommendations(trends)
            }

            return {
                "success": True,
                "analysis": trend_analysis
            }

        except Exception as e:
            logger.error(f"Error analyzing trends: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _generate_trend_analysis(
        self,
        metric: str,
        date_range: Optional[str]
    ) -> Dict[str, Any]:
        """Generate trend analysis for a specific metric."""
        # Mock trend data
        trend_direction = random.choice(["increasing", "decreasing", "stable"])
        change_rate = random.uniform(0.05, 0.25)
        
        if trend_direction == "decreasing":
            change_rate = -change_rate

        return {
            "direction": trend_direction,
            "change_rate": round(change_rate * 100, 2),
            "significance": random.choice(["high", "medium", "low"]),
            "seasonality": random.choice(["yes", "no"]),
            "volatility": random.uniform(0.1, 0.5)
        }

    def _generate_trend_insights(self, trends: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate insights from trend analysis."""
        insights = []

        for metric, trend in trends.items():
            if trend["direction"] == "increasing" and trend["significance"] == "high":
                insights.append({
                    "type": "positive",
                    "metric": metric,
                    "insight": f"{metric} is showing strong positive growth",
                    "impact": "high"
                })
            elif trend["direction"] == "decreasing" and trend["significance"] == "high":
                insights.append({
                    "type": "negative",
                    "metric": metric,
                    "insight": f"{metric} is declining significantly",
                    "impact": "high"
                })

        return insights

    def _generate_trend_recommendations(
        self,
        trends: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate recommendations based on trend analysis."""
        recommendations = []

        for metric, trend in trends.items():
            if trend["direction"] == "decreasing" and trend["significance"] == "high":
                recommendations.append({
                    "metric": metric,
                    "priority": "high",
                    "title": f"Address declining {metric}",
                    "description": f"{metric} is decreasing by {trend['change_rate']}%",
                    "actions": [
                        "Investigate root causes",
                        "Implement corrective measures",
                        "Monitor closely"
                    ]
                })
            elif trend["seasonality"] == "yes":
                recommendations.append({
                    "metric": metric,
                    "priority": "medium",
                    "title": f"Plan for {metric} seasonality",
                    "description": f"{metric} shows seasonal patterns",
                    "actions": [
                        "Adjust campaigns for seasonality",
                        "Prepare seasonal content",
                        "Optimize timing"
                    ]
                })

        return recommendations

    async def predict_customer_behavior(
        self,
        customer_data: Dict[str, Any],
        prediction_type: str
    ) -> Dict[str, Any]:
        """Predict customer behavior based on historical data."""
        try:
            prediction_id = str(uuid4())

            # Generate predictions based on type
            if prediction_type == "churn":
                prediction = self._predict_churn_risk(customer_data)
            elif prediction_type == "lifetime_value":
                prediction = self._predict_lifetime_value(customer_data)
            elif prediction_type == "next_purchase":
                prediction = self._predict_next_purchase(customer_data)
            else:
                return {
                    "success": False,
                    "error": f"Unknown prediction type: {prediction_type}"
                }

            prediction_record = {
                "id": prediction_id,
                "customer_id": customer_data.get("id"),
                "prediction_type": prediction_type,
                "prediction": prediction,
                "confidence": prediction.get("confidence", 0.0),
                "created_at": datetime.now().isoformat()
            }

            self.predictions[prediction_id] = prediction_record

            return {
                "success": True,
                "prediction_id": prediction_id,
                "prediction": prediction_record
            }

        except Exception as e:
            logger.error(f"Error predicting customer behavior: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _predict_churn_risk(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict customer churn risk."""
        # Mock churn prediction logic
        engagement_score = customer_data.get("engagement_score", 0)
        days_since_last_activity = customer_data.get("days_since_last_activity", 30)
        total_purchases = customer_data.get("total_purchases", 0)

        # Calculate churn risk
        risk_factors = []
        churn_risk = 0.0

        if days_since_last_activity > 30:
            risk_factors.append("inactive_user")
            churn_risk += 0.3

        if engagement_score < 0.5:
            risk_factors.append("low_engagement")
            churn_risk += 0.2

        if total_purchases == 0:
            risk_factors.append("no_purchases")
            churn_risk += 0.4

        churn_risk = min(churn_risk, 1.0)

        return {
            "churn_risk": round(churn_risk, 3),
            "risk_level": "high" if churn_risk > 0.7 else "medium" if churn_risk > 0.4 else "low",
            "risk_factors": risk_factors,
            "confidence": random.uniform(0.7, 0.95),
            "recommendations": self._generate_churn_prevention_recommendations(churn_risk)
        }

    def _predict_lifetime_value(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict customer lifetime value."""
        # Mock LTV prediction
        avg_order_value = customer_data.get("avg_order_value", 100)
        purchase_frequency = customer_data.get("purchase_frequency", 2)
        customer_age_months = customer_data.get("customer_age_months", 6)

        # Simple LTV calculation
        monthly_value = avg_order_value * purchase_frequency
        predicted_months = min(24, customer_age_months * 2)  # Predict 2x current age
        predicted_ltv = monthly_value * predicted_months

        return {
            "predicted_ltv": round(predicted_ltv, 2),
            "monthly_value": round(monthly_value, 2),
            "predicted_months": predicted_months,
            "confidence": random.uniform(0.6, 0.9),
            "segments": self._segment_by_ltv(predicted_ltv)
        }

    def _predict_next_purchase(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict next purchase timing and value."""
        # Mock next purchase prediction
        days_since_last_purchase = customer_data.get("days_since_last_purchase", 30)
        avg_purchase_cycle = customer_data.get("avg_purchase_cycle", 45)

        # Predict next purchase
        days_until_next = max(1, avg_purchase_cycle - days_since_last_purchase)
        predicted_date = datetime.now() + timedelta(days=days_until_next)

        return {
            "predicted_date": predicted_date.strftime("%Y-%m-%d"),
            "days_until_next": days_until_next,
            "predicted_value": customer_data.get("avg_order_value", 100),
            "confidence": random.uniform(0.5, 0.8)
        }

    def _generate_churn_prevention_recommendations(
        self,
        churn_risk: float
    ) -> List[Dict[str, Any]]:
        """Generate churn prevention recommendations."""
        recommendations = []

        if churn_risk > 0.7:
            recommendations.append({
                "priority": "high",
                "title": "Immediate re-engagement needed",
                "description": "High churn risk detected",
                "actions": [
                    "Send personalized re-engagement email",
                    "Offer exclusive discount",
                    "Schedule retention call"
                ]
            })
        elif churn_risk > 0.4:
            recommendations.append({
                "priority": "medium",
                "title": "Increase engagement",
                "description": "Moderate churn risk",
                "actions": [
                    "Send relevant content",
                    "Invite to webinar",
                    "Offer loyalty program"
                ]
            })

        return recommendations

    def _segment_by_ltv(self, ltv: float) -> str:
        """Segment customers by lifetime value."""
        if ltv > 10000:
            return "enterprise"
        elif ltv > 5000:
            return "premium"
        elif ltv > 1000:
            return "standard"
        else:
            return "basic"

    async def get_prediction_analytics(
        self,
        prediction_type: Optional[str] = None,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get analytics for predictions."""
        try:
            # Filter predictions
            filtered_predictions = []
            for prediction in self.predictions.values():
                if prediction_type and prediction["prediction_type"] != prediction_type:
                    continue
                filtered_predictions.append(prediction)

            # Calculate accuracy metrics
            total_predictions = len(filtered_predictions)
            avg_confidence = sum(p["confidence"] for p in filtered_predictions) / total_predictions if total_predictions > 0 else 0

            analytics = {
                "total_predictions": total_predictions,
                "average_confidence": round(avg_confidence, 3),
                "prediction_types": list(set(p["prediction_type"] for p in filtered_predictions)),
                "recent_predictions": filtered_predictions[-10:] if filtered_predictions else []
            }

            return {
                "success": True,
                "analytics": analytics
            }

        except Exception as e:
            logger.error(f"Error getting prediction analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def forecast_lead_trends(
        self,
        historical_data: Dict[str, Any],
        forecast_periods: int = 3
    ) -> Dict[str, Any]:
        """Forecast lead trends based on historical data."""
        try:
            forecast_id = str(uuid4())
            
            # Extract lead data from historical_data
            leads_data = historical_data.get("leads", [])
            conversions_data = historical_data.get("conversions", [])
            revenue_data = historical_data.get("revenue", [])
            
            # Calculate trends
            trends = {}
            
            if leads_data:
                leads_trend = self._calculate_trend(leads_data)
                trends["leads"] = leads_trend
            
            if conversions_data:
                conversions_trend = self._calculate_trend(conversions_data)
                trends["conversions"] = conversions_trend
            
            if revenue_data:
                revenue_trend = self._calculate_trend(revenue_data)
                trends["revenue"] = revenue_trend
            
            # Generate forecasts
            forecasts = {}
            
            if leads_data:
                forecasts["leads"] = self._forecast_metric(leads_data, forecast_periods)
            
            if conversions_data:
                forecasts["conversions"] = self._forecast_metric(conversions_data, forecast_periods)
            
            if revenue_data:
                forecasts["revenue"] = self._forecast_metric(revenue_data, forecast_periods)
            
            # Calculate conversion rate trend
            if leads_data and conversions_data:
                conversion_rates = [c/l if l > 0 else 0 for c, l in zip(conversions_data, leads_data)]
                conversion_trend = self._calculate_trend(conversion_rates)
                trends["conversion_rate"] = conversion_trend
                forecasts["conversion_rate"] = self._forecast_metric(conversion_rates, forecast_periods)
            
            result = {
                "id": forecast_id,
                "forecast_periods": forecast_periods,
                "trends": trends,
                "forecasts": forecasts,
                "created_at": datetime.now().isoformat(),
                "insights": self._generate_trend_insights(trends),
                "recommendations": self._generate_trend_recommendations(trends)
            }
            
            return {
                "success": True,
                "forecast_id": forecast_id,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"Error forecasting lead trends: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_trend(self, data: List[float]) -> Dict[str, Any]:
        """Calculate trend for a metric."""
        if len(data) < 2:
            return {"direction": "stable", "change_rate": 0, "significance": "low"}
        
        # Calculate change rate
        start_value = data[0]
        end_value = data[-1]
        change_rate = ((end_value - start_value) / start_value) * 100 if start_value > 0 else 0
        
        # Determine direction
        if change_rate > 5:
            direction = "increasing"
        elif change_rate < -5:
            direction = "decreasing"
        else:
            direction = "stable"
        
        # Determine significance
        if abs(change_rate) > 20:
            significance = "high"
        elif abs(change_rate) > 10:
            significance = "medium"
        else:
            significance = "low"
        
        return {
            "direction": direction,
            "change_rate": round(change_rate, 2),
            "significance": significance,
            "start_value": start_value,
            "end_value": end_value
        }

    def _forecast_metric(self, data: List[float], periods: int) -> List[float]:
        """Generate forecast for a metric."""
        if not data:
            return []
        
        # Simple moving average forecast
        window_size = min(3, len(data))
        if window_size == 0:
            return []
        
        avg = sum(data[-window_size:]) / window_size
        trend = (data[-1] - data[0]) / len(data) if len(data) > 1 else 0
        
        forecasts = []
        current_value = avg
        
        for _ in range(periods):
            current_value += trend + random.uniform(-0.05, 0.05) * current_value
            forecasts.append(max(0, current_value))
        
        return [round(f, 2) for f in forecasts]

    async def predict_lead_behavior(
        self,
        lead_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Predict lead behavior based on lead characteristics."""
        try:
            prediction_id = str(uuid4())
            
            # Extract lead characteristics
            company_size = lead_data.get("company_size", "")
            industry = lead_data.get("industry", "")
            title = lead_data.get("title", "")
            engagement_level = lead_data.get("engagement_level", "medium")
            budget = lead_data.get("budget", "")
            
            # Calculate behavior predictions
            conversion_probability = self._calculate_conversion_probability(lead_data)
            response_time = self._predict_response_time(lead_data)
            deal_size = self._predict_deal_size(lead_data)
            sales_cycle = self._predict_sales_cycle(lead_data)
            
            # Generate insights
            insights = self._generate_lead_insights(lead_data, conversion_probability)
            recommendations = self._generate_lead_recommendations(lead_data, conversion_probability)
            
            prediction = {
                "id": prediction_id,
                "lead_id": lead_data.get("id"),
                "lead_name": lead_data.get("name"),
                "company": lead_data.get("company"),
                "predictions": {
                    "conversion_probability": conversion_probability,
                    "response_time_days": response_time,
                    "predicted_deal_size": deal_size,
                    "predicted_sales_cycle_days": sales_cycle
                },
                "insights": insights,
                "recommendations": recommendations,
                "confidence": random.uniform(0.7, 0.95),
                "created_at": datetime.now().isoformat()
            }
            
            self.predictions[prediction_id] = prediction
            
            return {
                "success": True,
                "prediction_id": prediction_id,
                "prediction": prediction
            }
            
        except Exception as e:
            logger.error(f"Error predicting lead behavior: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _calculate_conversion_probability(self, lead_data: Dict[str, Any]) -> float:
        """Calculate conversion probability based on lead characteristics."""
        probability = 0.5  # Base probability
        
        # Adjust based on company size
        company_size = lead_data.get("company_size", "")
        if "enterprise" in company_size.lower() or "500+" in company_size:
            probability += 0.2
        elif "startup" in company_size.lower() or "1-10" in company_size:
            probability -= 0.1
        
        # Adjust based on title
        title = lead_data.get("title", "").lower()
        if any(word in title for word in ["ceo", "cto", "vp", "director", "founder"]):
            probability += 0.15
        elif "manager" in title:
            probability += 0.1
        
        # Adjust based on engagement level
        engagement = lead_data.get("engagement_level", "medium").lower()
        if engagement == "high":
            probability += 0.2
        elif engagement == "low":
            probability -= 0.2
        
        # Adjust based on budget
        budget = lead_data.get("budget", "")
        if "$100K" in budget or "$500K" in budget:
            probability += 0.1
        
        return min(0.95, max(0.05, probability))

    def _predict_response_time(self, lead_data: Dict[str, Any]) -> int:
        """Predict response time in days."""
        base_time = 3
        
        # Adjust based on engagement level
        engagement = lead_data.get("engagement_level", "medium").lower()
        if engagement == "high":
            base_time -= 1
        elif engagement == "low":
            base_time += 2
        
        # Adjust based on company size
        company_size = lead_data.get("company_size", "")
        if "enterprise" in company_size.lower():
            base_time += 1
        
        return max(1, base_time)

    def _predict_deal_size(self, lead_data: Dict[str, Any]) -> float:
        """Predict deal size in thousands."""
        base_size = 50
        
        # Adjust based on company size
        company_size = lead_data.get("company_size", "")
        if "enterprise" in company_size.lower():
            base_size = 200
        elif "startup" in company_size.lower():
            base_size = 25
        
        # Adjust based on budget
        budget = lead_data.get("budget", "")
        if "$100K" in budget:
            base_size = 100
        elif "$500K" in budget:
            base_size = 250
        
        return base_size

    def _predict_sales_cycle(self, lead_data: Dict[str, Any]) -> int:
        """Predict sales cycle in days."""
        base_cycle = 45
        
        # Adjust based on company size
        company_size = lead_data.get("company_size", "")
        if "enterprise" in company_size.lower():
            base_cycle = 90
        elif "startup" in company_size.lower():
            base_cycle = 30
        
        # Adjust based on deal size
        deal_size = self._predict_deal_size(lead_data)
        if deal_size > 100:
            base_cycle += 30
        
        return base_cycle

    def _generate_lead_insights(self, lead_data: Dict[str, Any], conversion_probability: float) -> List[Dict[str, Any]]:
        """Generate insights about the lead."""
        insights = []
        
        if conversion_probability > 0.8:
            insights.append({
                "type": "positive",
                "title": "High Conversion Potential",
                "description": "This lead shows strong indicators for conversion"
            })
        elif conversion_probability < 0.3:
            insights.append({
                "type": "warning",
                "title": "Low Conversion Risk",
                "description": "This lead may require additional nurturing"
            })
        
        engagement = lead_data.get("engagement_level", "medium")
        if engagement == "high":
            insights.append({
                "type": "positive",
                "title": "High Engagement",
                "description": "Lead is actively engaging with content"
            })
        
        return insights

    def _generate_lead_recommendations(self, lead_data: Dict[str, Any], conversion_probability: float) -> List[Dict[str, Any]]:
        """Generate recommendations for the lead."""
        recommendations = []
        
        if conversion_probability > 0.8:
            recommendations.append({
                "priority": "high",
                "title": "Accelerate Sales Process",
                "description": "Lead is ready for direct sales approach",
                "actions": [
                    "Schedule demo immediately",
                    "Prepare proposal",
                    "Engage decision makers"
                ]
            })
        elif conversion_probability < 0.3:
            recommendations.append({
                "priority": "medium",
                "title": "Focus on Nurturing",
                "description": "Lead needs more education and engagement",
                "actions": [
                    "Send educational content",
                    "Invite to webinar",
                    "Provide case studies"
                ]
            })
        
        return recommendations 