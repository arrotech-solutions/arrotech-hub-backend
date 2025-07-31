"""
HubSpot integration service for Mini-Hub.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from ..config import settings


class HubSpotService:
    def __init__(self):
        self.api_key = settings.HUBSPOT_API_KEY
        self.base_url = "https://api.hubapi.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test HubSpot connection."""
        try:
            if config:
                api_key = config.get("api_key")
            else:
                api_key = settings.HUBSPOT_API_KEY

            if not api_key:
                return {
                    "success": False,
                    "error": "HubSpot API key not configured"
                }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            response = requests.get(
                f"{self.base_url}/crm/v3/objects/contacts",
                headers=headers,
                params={"limit": 1}
            )

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "HubSpot connection successful",
                    "account_info": response.json().get("paging", {})
                }
            else:
                return {
                    "success": False,
                    "error": f"Connection failed: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}"
            }

    async def get_contacts(self, limit: int = 10, properties: List[str] = None) -> Dict[str, Any]:
        """Get contacts from HubSpot."""
        try:
            if properties is None:
                properties = ["email", "firstname", "lastname", "company"]

            params = {
                "limit": limit,
                "properties": ",".join(properties)
            }

            response = requests.get(
                f"{self.base_url}/crm/v3/objects/contacts",
                headers=self.headers,
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "contacts": data.get("results", []),
                        "total": data.get("total", 0),
                        "paging": data.get("paging", {})
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch contacts: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching contacts: {str(e)}"
            }

    async def create_contact(
        self,
        email: str,
        first_name: str = None,
        last_name: str = None,
        company: str = None,
        phone: str = None
    ) -> Dict[str, Any]:
        """Create a new contact in HubSpot."""
        try:
            properties = {
                "email": email
            }

            if first_name:
                properties["firstname"] = first_name
            if last_name:
                properties["lastname"] = last_name
            if company:
                properties["company"] = company
            if phone:
                properties["phone"] = phone

            payload = {"properties": properties}

            response = requests.post(
                f"{self.base_url}/crm/v3/objects/contacts",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "contact_id": data.get("id"),
                        "contact": data
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create contact: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating contact: {str(e)}"
            }

    async def update_contact(
        self,
        contact_id: str,
        properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update a contact in HubSpot."""
        try:
            payload = {"properties": properties}

            response = requests.patch(
                f"{self.base_url}/crm/v3/objects/contacts/{contact_id}",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "contact_id": contact_id,
                        "contact": data
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to update contact: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error updating contact: {str(e)}"
            }

    async def get_deals(self, limit: int = 10) -> Dict[str, Any]:
        """Get deals from HubSpot."""
        try:
            params = {
                "limit": limit,
                "properties": "amount,dealname,dealstage,closedate"
            }

            response = requests.get(
                f"{self.base_url}/crm/v3/objects/deals",
                headers=self.headers,
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "deals": data.get("results", []),
                        "total": data.get("total", 0)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch deals: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching deals: {str(e)}"
            }

    async def add_deal_note(self, deal_id: str, note: str) -> Dict[str, Any]:
        """Add a note to a HubSpot deal."""
        try:
            payload = {
                "properties": {
                    "hs_note_body": note,
                    "hs_timestamp": int(datetime.now().timestamp() * 1000)
                }
            }

            response = requests.post(
                f"{self.base_url}/crm/v3/objects/notes",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "note_id": data.get("id"),
                        "note": data
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add note: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error adding note: {str(e)}"
            }

    async def get_analytics(self, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        """Get HubSpot analytics data."""
        try:
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)
                              ).strftime("%Y-%m-%d")
            if not end_date:
                end_date = datetime.now().strftime("%Y-%m-%d")

            # Get analytics data
            analytics_data = {
                "contacts_created": 0,
                "deals_created": 0,
                "total_revenue": 0,
                "conversion_rate": 0
            }

            # This would typically call HubSpot's analytics API
            # For now, returning mock data
            return {
                "success": True,
                "data": {
                    "analytics": analytics_data,
                    "period": {
                        "start_date": start_date,
                        "end_date": end_date
                    }
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching analytics: {str(e)}"
            }

    async def search_contacts(self, filters: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
        """Search contacts in HubSpot with filters."""
        try:
            # Build search query
            search_query = {
                "filterGroups": [],
                "properties": ["email", "firstname", "lastname", "company"],
                "limit": limit
            }

            # Add filters to search query
            if filters:
                filter_group = {"filters": []}
                for key, value in filters.items():
                    filter_group["filters"].append({
                        "propertyName": key,
                        "operator": "EQ",
                        "value": value
                    })
                search_query["filterGroups"].append(filter_group)

            response = requests.post(
                f"{self.base_url}/crm/v3/objects/contacts/search",
                headers=self.headers,
                json=search_query
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "contacts": data.get("results", []),
                        "total": data.get("total", 0)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to search contacts: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error searching contacts: {str(e)}"
            }

    async def segment_contacts(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Segment contacts based on criteria."""
        try:
            # Get all contacts first
            all_contacts = await self.get_contacts(limit=1000)

            if not all_contacts["success"]:
                return all_contacts

            contacts = all_contacts["data"]["contacts"]
            segmented_contacts = []

            # Apply segmentation filters
            for contact in contacts:
                properties = contact.get("properties", {})
                matches_criteria = True

                for filter_key, filter_value in filters.items():
                    contact_value = properties.get(filter_key, "")
                    if str(contact_value).lower() != str(filter_value).lower():
                        matches_criteria = False
                        break

                if matches_criteria:
                    segmented_contacts.append(contact)

            return {
                "success": True,
                "data": {
                    "segmented_contacts": segmented_contacts,
                    "total_segments": len(segmented_contacts),
                    "criteria": filters
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error segmenting contacts: {str(e)}"
            }

    async def create_deal(self, **deal_data) -> Dict[str, Any]:
        """Create a new deal in HubSpot."""
        try:
            properties = {}

            # Map deal data to HubSpot properties
            if "dealname" in deal_data:
                properties["dealname"] = deal_data["dealname"]
            if "amount" in deal_data:
                properties["amount"] = deal_data["amount"]
            if "dealstage" in deal_data:
                properties["dealstage"] = deal_data["dealstage"]
            if "closedate" in deal_data:
                properties["closedate"] = deal_data["closedate"]
            if "pipeline" in deal_data:
                properties["pipeline"] = deal_data["pipeline"]

            payload = {"properties": properties}

            response = requests.post(
                f"{self.base_url}/crm/v3/objects/deals",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "deal_id": data.get("id"),
                        "deal": data
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create deal: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating deal: {str(e)}"
            }

    async def update_deal(self, deal_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Update a deal in HubSpot."""
        try:
            payload = {"properties": properties}

            response = requests.patch(
                f"{self.base_url}/crm/v3/objects/deals/{deal_id}",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "deal_id": deal_id,
                        "deal": data
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to update deal: {response.status_code}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error updating deal: {str(e)}"
            }

    async def analyze_deals(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze deals pipeline and performance."""
        try:
            # Get deals
            deals_result = await self.get_deals(limit=100)

            if not deals_result["success"]:
                return deals_result

            deals = deals_result["data"]["deals"]

            # Analyze deals
            analysis = {
                "total_deals": len(deals),
                "total_value": 0,
                "by_stage": {},
                "by_pipeline": {},
                "avg_deal_size": 0,
                "conversion_rate": 0
            }

            closed_deals = 0
            total_value = 0

            for deal in deals:
                properties = deal.get("properties", {})
                amount = float(properties.get("amount", 0))
                stage = properties.get("dealstage", "unknown")
                pipeline = properties.get("pipeline", "default")

                # Track by stage
                if stage not in analysis["by_stage"]:
                    analysis["by_stage"][stage] = {"count": 0, "value": 0}
                analysis["by_stage"][stage]["count"] += 1
                analysis["by_stage"][stage]["value"] += amount

                # Track by pipeline
                if pipeline not in analysis["by_pipeline"]:
                    analysis["by_pipeline"][pipeline] = {
                        "count": 0, "value": 0}
                analysis["by_pipeline"][pipeline]["count"] += 1
                analysis["by_pipeline"][pipeline]["value"] += amount

                # Track closed deals
                if stage in ["closedwon", "closedlost"]:
                    closed_deals += 1

                total_value += amount

            analysis["total_value"] = total_value
            analysis["avg_deal_size"] = total_value / \
                len(deals) if deals else 0
            analysis["conversion_rate"] = (
                closed_deals / len(deals)) * 100 if deals else 0

            return {
                "success": True,
                "data": {
                    "analysis": analysis,
                    "filters_applied": filters
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Error analyzing deals: {str(e)}"
            }
