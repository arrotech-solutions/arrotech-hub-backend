"""
Google Analytics 4 Service for Google Workspace Integration.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                RunReportRequest)

from .base_client import GoogleWorkspaceBaseClient

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for interacting with Google Analytics 4 via Google Workspace connection."""

    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        # Initialize GA4 client with OAuth credentials
        self.ga4_client = BetaAnalyticsDataClient(credentials=base_client.credentials)

    def _validate_hours(self, hours: Any) -> int:
        """Validate and convert hours parameter."""
        if isinstance(hours, str):
            try:
                hours = int(hours)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid hours value: {hours}. Must be a valid integer.")
        
        if not isinstance(hours, int) or hours <= 0:
            raise ValueError(f"Hours must be a positive integer, got: {hours}")
            
        return hours

    async def get_traffic(self, property_id: str, hours: int = 24) -> Dict[str, Any]:
        """Get traffic data from GA4 for the specified hours."""
        try:
            if not property_id:
                return {"success": False, "error": "Property ID is required"}
                
            hours_int = self._validate_hours(hours)

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours_int)

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[
                    Metric(name="sessions"),
                    Metric(name="newUsers")
                ],
                dimensions=[
                    Dimension(name="date")
                ]
            )

            response = self.ga4_client.run_report(request)

            traffic_data = {
                "summary": {
                    "total_sessions": 0,
                    "total_users": 0,
                    "total_pageviews": 0,
                    "avg_bounce_rate": 0.0
                },
                "by_date": {},
                "by_source": {}
            }

            for row in response.rows:
                date = row.dimension_values[0].value
                sessions = int(row.metric_values[0].value)
                new_users = int(row.metric_values[1].value)

                traffic_data["summary"]["total_sessions"] += sessions
                traffic_data["summary"]["total_users"] += new_users

                if date not in traffic_data["by_date"]:
                    traffic_data["by_date"][date] = {"sessions": 0, "users": 0}
                traffic_data["by_date"][date]["sessions"] += sessions
                traffic_data["by_date"][date]["users"] += new_users

            return {
                "success": True,
                "traffic_data": traffic_data,
                "period_hours": hours_int
            }

        except Exception as e:
            logger.error(f"Error getting GA4 traffic data: {e}")
            return {"success": False, "error": str(e), "traffic_data": {}}

    async def get_conversions(self, property_id: str, hours: int = 24, 
                              conversion_events: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get conversion data from GA4."""
        try:
            if not property_id:
                return {"success": False, "error": "Property ID is required"}

            hours_int = self._validate_hours(hours)
            
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours_int)
            
            if not conversion_events:
                conversion_events = ["purchase", "sign_up", "contact_form"]

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[
                    Metric(name="eventCount"),
                    Metric(name="eventValue"),
                    Metric(name="conversions")
                ],
                dimensions=[
                    Dimension(name="date"),
                    Dimension(name="eventName")
                ]
            )

            response = self.ga4_client.run_report(request)

            conversion_data = {
                "summary": {"total_conversions": 0, "total_value": 0.0, "conversion_rate": 0.0},
                "by_event": {},
                "by_date": {}
            }

            for row in response.rows:
                date = row.dimension_values[0].value
                event_name = row.dimension_values[1].value
                event_count = int(row.metric_values[0].value)
                event_value = float(row.metric_values[1].value)
                conversions = int(row.metric_values[2].value)

                conversion_data["summary"]["total_conversions"] += conversions
                conversion_data["summary"]["total_value"] += event_value

                if event_name not in conversion_data["by_event"]:
                    conversion_data["by_event"][event_name] = {"count": 0, "value": 0.0, "conversions": 0}
                conversion_data["by_event"][event_name]["count"] += event_count
                conversion_data["by_event"][event_name]["value"] += event_value
                conversion_data["by_event"][event_name]["conversions"] += conversions

                if date not in conversion_data["by_date"]:
                    conversion_data["by_date"][date] = {"count": 0, "value": 0.0, "conversions": 0}
                conversion_data["by_date"][date]["count"] += event_count
                conversion_data["by_date"][date]["value"] += event_value
                conversion_data["by_date"][date]["conversions"] += conversions

            return {
                "success": True,
                "conversion_data": conversion_data,
                "period_hours": hours_int
            }

        except Exception as e:
            logger.error(f"Error getting GA4 conversion data: {e}")
            return {"success": False, "error": str(e), "conversion_data": {}}

    async def get_user_behavior(self, property_id: str, hours: int = 24,
                                user_segments: Optional[List[str]] = None,
                                engagement_metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        """Analyze user behavior patterns."""
        try:
            if not property_id:
                return {"success": False, "error": "Property ID is required"}

            hours_int = self._validate_hours(hours)

            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours_int)

            if not engagement_metrics:
                engagement_metrics = [
                    "sessionsPerUser",
                    "screenPageViewsPerSession",
                    "averageSessionDuration",
                    "bounceRate",
                    "engagementRate"
                ]

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[Metric(name=metric) for metric in engagement_metrics],
                dimensions=[
                    Dimension(name="date"),
                    Dimension(name="userGender"),
                    Dimension(name="deviceCategory")
                ]
            )

            response = self.ga4_client.run_report(request)

            behavior_data = {
                "summary": {
                    "total_sessions": 0,
                    "avg_session_duration": 0,
                    "avg_pages_per_session": 0,
                    "bounce_rate": 0,
                    "engagement_rate": 0
                },
                "by_user_type": {},
                "by_device": {},
                "by_date": {}
            }

            for row in response.rows:
                date = row.dimension_values[0].value
                user_gender = row.dimension_values[1].value
                device = row.dimension_values[2].value

                # Just aggregating counts for simplicity in structure, 
                # deeper metric aggregation logic would go here
                
                if user_gender not in behavior_data["by_user_type"]:
                    behavior_data["by_user_type"][user_gender] = {"sessions": 0}
                
                if device not in behavior_data["by_device"]:
                    behavior_data["by_device"][device] = {"sessions": 0}

                if date not in behavior_data["by_date"]:
                    behavior_data["by_date"][date] = {"sessions": 0}

            return {
                "success": True,
                "behavior_data": behavior_data,
                "period_hours": hours_int
            }

        except Exception as e:
            logger.error(f"Error getting GA4 user behavior: {e}")
            return {"success": False, "error": str(e), "behavior_data": {}}

    async def get_custom_report(self, property_id: str, metrics: List[str], 
                                dimensions: List[str], filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get custom GA4 report."""
        try:
            if not property_id:
                return {"success": False, "error": "Property ID is required"}

            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[Metric(name=metric) for metric in metrics],
                dimensions=[Dimension(name=dim) for dim in dimensions]
            )

            response = self.ga4_client.run_report(request)

            custom_data = {
                "metrics": metrics,
                "dimensions": dimensions,
                "rows": []
            }

            for row in response.rows:
                row_data = {
                    "dimensions": [dim.value for dim in row.dimension_values],
                    "metrics": [float(metric.value) for metric in row.metric_values]
                }
                custom_data["rows"].append(row_data)

            return {"success": True, "custom_report": custom_data}

        except Exception as e:
            logger.error(f"Error getting GA4 custom report: {e}")
            return {"success": False, "error": str(e), "custom_report": {}}

    async def get_ecommerce_data(self, property_id: str, hours: int = 24) -> Dict[str, Any]:
        """Get ecommerce data from GA4."""
        try:
            if not property_id:
                return {"success": False, "error": "Property ID is required"}

            hours_int = self._validate_hours(hours)
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours_int)

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[
                    Metric(name="transactions"),
                    Metric(name="totalRevenue"),
                    Metric(name="averageOrderValue"),
                    Metric(name="itemsPerPurchase")
                ],
                dimensions=[
                    Dimension(name="date"),
                    Dimension(name="itemName"),
                    Dimension(name="itemCategory")
                ]
            )

            response = self.ga4_client.run_report(request)

            ecommerce_data = {
                "summary": {
                    "total_transactions": 0,
                    "total_revenue": 0,
                    "avg_order_value": 0,
                    "items_per_purchase": 0
                },
                "by_product": {},
                "by_category": {},
                "by_date": {}
            }

            for row in response.rows:
                date = row.dimension_values[0].value
                product = row.dimension_values[1].value
                category = row.dimension_values[2].value
                transactions = int(row.metric_values[0].value)
                revenue = float(row.metric_values[1].value)

                ecommerce_data["summary"]["total_transactions"] += transactions
                ecommerce_data["summary"]["total_revenue"] += revenue

                if product not in ecommerce_data["by_product"]:
                    ecommerce_data["by_product"][product] = {"transactions": 0, "revenue": 0}
                ecommerce_data["by_product"][product]["transactions"] += transactions
                ecommerce_data["by_product"][product]["revenue"] += revenue

            if ecommerce_data["summary"]["total_transactions"] > 0:
                ecommerce_data["summary"]["avg_order_value"] = (
                    ecommerce_data["summary"]["total_revenue"] / ecommerce_data["summary"]["total_transactions"]
                )

            return {
                "success": True, 
                "ecommerce_data": ecommerce_data, 
                "period_hours": hours_int
            }

        except Exception as e:
            logger.error(f"Error getting GA4 ecommerce data: {e}")
            return {"success": False, "error": str(e), "ecommerce_data": {}}
