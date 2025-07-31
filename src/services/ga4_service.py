"""
Google Analytics 4 service for Mini-Hub MCP Server.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                RunReportRequest)
from google.auth import default
from google.auth.exceptions import DefaultCredentialsError

from ..config import settings

logger = logging.getLogger(__name__)


class GA4Service:
    """Google Analytics 4 API service."""

    def __init__(self):
        self.client: Optional[BetaAnalyticsDataClient] = None
        self.property_id: Optional[str] = None
        self.initialized: bool = False

    async def initialize(self):
        """Initialize GA4 client."""
        try:
            if not settings.GA4_PROPERTY_ID:
                logger.warning(
                    "GA4 property ID not configured - GA4 service will be disabled")
                return

            # Set up credentials
            if settings.GA4_CREDENTIALS_FILE and os.path.exists(settings.GA4_CREDENTIALS_FILE):
                # Use service account file
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = settings.GA4_CREDENTIALS_FILE
                logger.info(
                    f"Using GA4 credentials from file: {settings.GA4_CREDENTIALS_FILE}")
            else:
                # Try to use default credentials
                try:
                    credentials, project = default()
                    logger.info("Using default Google Cloud credentials")
                except DefaultCredentialsError:
                    logger.warning(
                        "No GA4 credentials found - GA4 service will be disabled")
                    return

            self.property_id = settings.GA4_PROPERTY_ID
            self.client = BetaAnalyticsDataClient()
            self.initialized = True
            logger.info("GA4 client initialized successfully")

        except Exception as e:
            logger.warning(f"Failed to initialize GA4 service: {e}")
            self.initialized = False

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test GA4 connection by verifying property access."""
        try:
            # Use config property ID if provided, otherwise use settings
            property_id = config.get("property_id") if config else self.property_id
            
            if not property_id:
                return {
                    "success": False,
                    "error": "No GA4 property ID provided"
                }

            # If we have a config, create a temporary client for testing
            if config and config.get("credentials_file"):
                import os

                # Set the credentials file path temporarily
                credentials_file = config["credentials_file"]
                if os.path.exists(credentials_file):
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_file
                    # Create temporary client
                    from google.analytics.data_v1beta import \
                        BetaAnalyticsDataClient
                    test_client = BetaAnalyticsDataClient()
                else:
                    return {
                        "success": False,
                        "error": f"Credentials file not found: {credentials_file}"
                    }
            else:
                # Use the existing initialized client
                if not self.initialized or not self.client:
                    return {
                        "success": False,
                        "error": "GA4 service not initialized - check credentials and property ID"
                    }
                test_client = self.client

            # Test by making a simple request
            from google.analytics.data_v1beta.types import (DateRange, Metric,
                                                            RunReportRequest)

            request = RunReportRequest(
                property=f"properties/{property_id}",
                date_ranges=[
                    DateRange(
                        start_date="2024-01-01",
                        end_date="2024-01-01"
                    )
                ],
                metrics=[
                    Metric(name="sessions")
                ]
            )

            # Run test report
            response = test_client.run_report(request)

            return {
                "success": True,
                "message": "GA4 connection successful",
                "property_id": property_id,
                "test_response": {
                    "row_count": len(response.rows),
                    "metadata": {
                        "dimension_headers": [h.name for h in response.dimension_headers],
                        "metric_headers": [h.name for h in response.metric_headers]
                    }
                }
            }

        except Exception as e:
            logger.error(f"GA4 connection test failed: {e}")
            return {
                "success": False,
                "error": f"GA4 connection test failed: {str(e)}"
            }

    async def get_traffic(self, hours: int = 24) -> Dict[str, Any]:
        """Get traffic data from GA4 for the specified hours."""
        if not self.initialized or not self.client or not self.property_id:
            return {
                "success": False,
                "error": "GA4 service not initialized - check credentials and property ID"
            }

        try:
            # Convert hours to integer if it's a string
            if isinstance(hours, str):
                try:
                    hours = int(hours)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid hours value: {hours}. Must be a valid integer."
                    }
            
            # Validate hours parameter
            if not isinstance(hours, int) or hours <= 0:
                return {
                    "success": False,
                    "error": f"Hours must be a positive integer, got: {hours}"
                }

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)

            # Create request
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
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

            # Run report
            response = self.client.run_report(request)

            # Process results
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

                # Update summary
                traffic_data["summary"]["total_sessions"] += sessions
                traffic_data["summary"]["total_users"] += new_users

                # Group by date
                if date not in traffic_data["by_date"]:
                    traffic_data["by_date"][date] = {
                        "sessions": 0,
                        "users": 0
                    }
                traffic_data["by_date"][date]["sessions"] += sessions
                traffic_data["by_date"][date]["users"] += new_users

            return {
                "success": True,
                "traffic_data": traffic_data,
                "period_hours": hours
            }

        except Exception as e:
            logger.error(f"Error getting GA4 traffic data: {e}")
            return {
                "success": False,
                "error": str(e),
                "traffic_data": {}
            }

    async def get_conversions(self, hours: int = 24,
                              conversion_events: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get conversion data from GA4."""
        if not self.initialized or not self.client or not self.property_id:
            return {
                "success": False,
                "error": "GA4 service not initialized - check credentials and property ID"
            }

        try:
            # Convert hours to integer if it's a string
            if isinstance(hours, str):
                try:
                    hours = int(hours)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid hours value: {hours}. Must be a valid integer."
                    }
            
            # Validate hours parameter
            if not isinstance(hours, int) or hours <= 0:
                return {
                    "success": False,
                    "error": f"Hours must be a positive integer, got: {hours}"
                }

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)

            # Default conversion events
            if not conversion_events:
                conversion_events = ["purchase", "sign_up", "contact_form"]

            # Create request
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
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

            # Run report
            response = self.client.run_report(request)

            # Process results
            conversion_data = {
                "summary": {
                    "total_conversions": 0,
                    "total_value": 0.0,
                    "conversion_rate": 0.0
                },
                "by_event": {},
                "by_date": {}
            }

            for row in response.rows:
                date = row.dimension_values[0].value
                event_name = row.dimension_values[1].value

                event_count = int(row.metric_values[0].value)
                event_value = float(row.metric_values[1].value)
                conversions = int(row.metric_values[2].value)

                # Update summary
                conversion_data["summary"]["total_conversions"] += conversions
                conversion_data["summary"]["total_value"] += event_value

                # Group by event
                if event_name not in conversion_data["by_event"]:
                    conversion_data["by_event"][event_name] = {
                        "count": 0,
                        "value": 0.0,
                        "conversions": 0
                    }
                conversion_data["by_event"][event_name]["count"] += event_count
                conversion_data["by_event"][event_name]["value"] += event_value
                conversion_data["by_event"][event_name]["conversions"] += conversions

                # Group by date
                if date not in conversion_data["by_date"]:
                    conversion_data["by_date"][date] = {
                        "count": 0,
                        "value": 0.0,
                        "conversions": 0
                    }
                conversion_data["by_date"][date]["count"] += event_count
                conversion_data["by_date"][date]["value"] += event_value
                conversion_data["by_date"][date]["conversions"] += conversions

            return {
                "success": True,
                "conversion_data": conversion_data,
                "period_hours": hours
            }

        except Exception as e:
            logger.error(f"Error getting GA4 conversion data: {e}")
            return {
                "success": False,
                "error": str(e),
                "conversion_data": {}
            }

    async def get_user_behavior(self, hours: int = 24,
                                user_segments: Optional[List[str]] = None,
                                engagement_metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        """Analyze user behavior patterns and engagement metrics."""
        if not self.initialized or not self.client or not self.property_id:
            return {
                "success": False,
                "error": "GA4 service not initialized - check credentials and property ID"
            }

        try:
            # Convert hours to integer if it's a string
            if isinstance(hours, str):
                try:
                    hours = int(hours)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid hours value: {hours}. Must be a valid integer."
                    }
            
            # Validate hours parameter
            if not isinstance(hours, int) or hours <= 0:
                return {
                    "success": False,
                    "error": f"Hours must be a positive integer, got: {hours}"
                }

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)

            # Default metrics if not provided
            if not engagement_metrics:
                engagement_metrics = [
                    "sessionsPerUser",
                    "screenPageViewsPerSession",
                    "averageSessionDuration",
                    "bounceRate",
                    "engagementRate"
                ]

            # Create request
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
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

            # Run report
            response = self.client.run_report(request)

            # Process results
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

                # Process metrics
                metrics = [float(val.value) for val in row.metric_values]

                # Update by user gender
                if user_gender not in behavior_data["by_user_type"]:
                    behavior_data["by_user_type"][user_gender] = {
                        "sessions": 0,
                        "avg_duration": 0,
                        "avg_pages": 0
                    }

                # Update by device
                if device not in behavior_data["by_device"]:
                    behavior_data["by_device"][device] = {
                        "sessions": 0,
                        "avg_duration": 0,
                        "avg_pages": 0
                    }

                # Update by date
                if date not in behavior_data["by_date"]:
                    behavior_data["by_date"][date] = {
                        "sessions": 0,
                        "avg_duration": 0,
                        "avg_pages": 0
                    }

            return {
                "success": True,
                "behavior_data": behavior_data,
                "period_hours": hours,
                "user_segments": user_segments or []
            }

        except Exception as e:
            logger.error(f"Error getting GA4 user behavior: {e}")
            return {
                "success": False,
                "error": str(e),
                "behavior_data": {}
            }

    async def get_custom_report(self, metrics: List[str], dimensions: List[str],
                                filters: Dict[str, Any]) -> Dict[str, Any]:
        """Get custom GA4 report with specified metrics and dimensions."""
        if not self.initialized or not self.client or not self.property_id:
            return {
                "success": False,
                "error": "GA4 service not initialized - check credentials and property ID"
            }

        try:
            # Calculate date range (default to last 30 days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

            # Create request
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
                date_ranges=[
                    DateRange(
                        start_date=start_date.strftime("%Y-%m-%d"),
                        end_date=end_date.strftime("%Y-%m-%d")
                    )
                ],
                metrics=[Metric(name=metric) for metric in metrics],
                dimensions=[Dimension(name=dim) for dim in dimensions]
            )

            # Add filters if provided
            if filters:
                # Convert filters to GA4 format
                # This is a simplified implementation
                pass

            # Run report
            response = self.client.run_report(request)

            # Process results
            custom_data = {
                "metrics": metrics,
                "dimensions": dimensions,
                "rows": [],
                "summary": {}
            }

            for row in response.rows:
                row_data = {
                    "dimensions": [dim.value for dim in row.dimension_values],
                    "metrics": [float(metric.value) for metric in row.metric_values]
                }
                custom_data["rows"].append(row_data)

            return {
                "success": True,
                "custom_report": custom_data
            }

        except Exception as e:
            logger.error(f"Error getting GA4 custom report: {e}")
            return {
                "success": False,
                "error": str(e),
                "custom_report": {}
            }

    async def get_ecommerce_data(self, hours: int = 24) -> Dict[str, Any]:
        """Get ecommerce data from GA4."""
        if not self.initialized or not self.client or not self.property_id:
            return {
                "success": False,
                "error": "GA4 service not initialized - check credentials and property ID"
            }

        try:
            # Convert hours to integer if it's a string
            if isinstance(hours, str):
                try:
                    hours = int(hours)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid hours value: {hours}. Must be a valid integer."
                    }
            
            # Validate hours parameter
            if not isinstance(hours, int) or hours <= 0:
                return {
                    "success": False,
                    "error": f"Hours must be a positive integer, got: {hours}"
                }

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(hours=hours)

            # Create request
            request = RunReportRequest(
                property=f"properties/{self.property_id}",
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

            # Run report
            response = self.client.run_report(request)

            # Process results
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
                avg_order = float(row.metric_values[2].value)
                items_per_purchase = float(row.metric_values[3].value)

                # Update summary
                ecommerce_data["summary"]["total_transactions"] += transactions
                ecommerce_data["summary"]["total_revenue"] += revenue

                # Update by product
                if product not in ecommerce_data["by_product"]:
                    ecommerce_data["by_product"][product] = {
                        "transactions": 0,
                        "revenue": 0
                    }
                ecommerce_data["by_product"][product]["transactions"] += transactions
                ecommerce_data["by_product"][product]["revenue"] += revenue

                # Update by category
                if category not in ecommerce_data["by_category"]:
                    ecommerce_data["by_category"][category] = {
                        "transactions": 0,
                        "revenue": 0
                    }
                ecommerce_data["by_category"][category]["transactions"] += transactions
                ecommerce_data["by_category"][category]["revenue"] += revenue

                # Update by date
                if date not in ecommerce_data["by_date"]:
                    ecommerce_data["by_date"][date] = {
                        "transactions": 0,
                        "revenue": 0
                    }
                ecommerce_data["by_date"][date]["transactions"] += transactions
                ecommerce_data["by_date"][date]["revenue"] += revenue

            # Calculate averages
            if ecommerce_data["summary"]["total_transactions"] > 0:
                ecommerce_data["summary"]["avg_order_value"] = (
                    ecommerce_data["summary"]["total_revenue"] /
                    ecommerce_data["summary"]["total_transactions"]
                )

            return {
                "success": True,
                "ecommerce_data": ecommerce_data,
                "period_hours": hours
            }

        except Exception as e:
            logger.error(f"Error getting GA4 ecommerce data: {e}")
            return {
                "success": False,
                "error": str(e),
                "ecommerce_data": {}
            }
