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
        """Test HubSpot connection with both Private App tokens and legacy API keys."""
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

            # Determine authentication method based on key format
            if api_key.startswith(('pat-', 'eu1-', 'na1-')):
                # Private App Access Token - use Bearer authentication
                return await self._test_private_app_connection(api_key)
            else:
                # Legacy API Key - use hapikey parameter
                return await self._test_legacy_api_connection(api_key)

        except Exception as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}"
            }

    async def _test_private_app_connection(self, access_token: str) -> Dict[str, Any]:
        """Test connection using Private App access token."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # Test with account info endpoint first
        response = requests.get(
            f"{self.base_url}/account-info/v3/details",
            headers=headers
        )

        if response.status_code == 200:
            account_data = response.json()
            return {
                "success": True,
                "message": "HubSpot connection successful",
                "method": "Private App Access Token",
                "account_info": {
                    "portalId": account_data.get("portalId"),
                    "accountType": account_data.get("accountType"),
                    "timeZone": account_data.get("timeZone")
                }
            }
        else:
            # Try contacts endpoint as fallback
            response = requests.get(
                f"{self.base_url}/crm/v3/objects/contacts",
                headers=headers,
                params={"limit": 1}
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "HubSpot connection successful",
                    "method": "Private App Access Token",
                    "account_info": "Limited access"
                }
            else:
                return {
                    "success": False,
                    "error": f"Private App authentication failed: {response.status_code} - {response.text}",
                    "help": "Ensure your Private App has required scopes or use legacy API key for developer accounts"
                }

    async def _test_legacy_api_connection(self, api_key: str) -> Dict[str, Any]:
        """Test connection using legacy API key (for developer accounts)."""
        # Test with legacy contacts endpoint
        response = requests.get(
            f"{self.base_url}/contacts/v1/lists/all/contacts/all",
            params={"count": 1, "hapikey": api_key}
        )

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "message": "HubSpot connection successful",
                "method": "Legacy API Key (Developer Account)",
                "account_info": {
                    "contacts_found": len(data.get("contacts", [])),
                    "has_more": data.get("has-more", False)
                }
            }
        else:
            return {
                "success": False,
                "error": f"Legacy API authentication failed: {response.status_code} - {response.text}",
                "help": "Verify your API key is correct. Get it from Settings → Integrations → API Key"
            }

    async def get_contacts(self, limit: int = 10, properties: List[str] = None) -> Dict[str, Any]:
        """Get contacts from HubSpot using appropriate authentication method."""
        try:
            if properties is None:
                properties = ["email", "firstname", "lastname", "company"]

            # Determine authentication method based on API key format
            if self.api_key and self.api_key.startswith(('pat-', 'eu1-', 'na1-')):
                # Private App Access Token - use v3 API
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
                # Legacy API Key - use v1 API
                params = {
                    "count": limit,
                    "property": properties,
                    "hapikey": self.api_key
                }

                response = requests.get(
                    f"{self.base_url}/contacts/v1/lists/all/contacts/all",
                    params=params
                )

                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "data": {
                            "contacts": data.get("contacts", []),
                            "total": len(data.get("contacts", [])),
                            "has_more": data.get("has-more", False)
                        }
                    }

            return {
                "success": False,
                "error": f"Failed to fetch contacts: {response.status_code} - {response.text}"
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

    async def get_company(self, company_id: str) -> Dict[str, Any]:
        """Get details for a specific company."""
        url = f"{self.base_url}/crm/v3/objects/companies/{company_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code in [200, 201]:
            return {"success": True, "company": response.json()}
        return {"success": False, "error": response.text}

    async def create_engagement(self, engagement_data: Dict[str, Any], associations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a generic engagement (note, task, call, email, meeting)."""
        url = f"{self.base_url}/engagements/v1/engagements"
        payload = {
            "engagement": engagement_data,
            "associations": associations or {}
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code in [200, 201]:
            return {"success": True, "engagement": response.json()}
        return {"success": False, "error": response.text}

    async def associate_contact(self, contact_id: str, to_object_type: str, to_object_id: str, association_type: str) -> Dict[str, Any]:
        """Associate a contact with another object."""
        url = f"{self.base_url}/crm/v3/objects/contacts/{contact_id}/associations/{to_object_type}/{to_object_id}/{association_type}"
        response = requests.put(url, headers=self.headers)
        if response.status_code in [200, 201, 204]:
            return {"success": True, "association": response.json() if response.status_code != 204 else {}}
        return {"success": False, "error": response.text}

    async def create_email_template(self, template_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an email template."""
        url = f"{self.base_url}/email/public/v1/templates"
        response = requests.post(url, headers=self.headers, json=template_data)
        if response.status_code in [200, 201]:
            return {"success": True, "template": response.json()}
        return {"success": False, "error": response.text}

    async def enroll_sequence(self, contact_id: str, sequence_id: str, sender_email: str) -> Dict[str, Any]:
        """Enroll a contact in a sequence."""
        url = f"{self.base_url}/automation/v2/sequences/enrollments"
        payload = {
            "contactId": contact_id,
            "sequenceId": sequence_id,
            "senderEmail": sender_email
        }
        response = requests.post(url, headers=self.headers, json=payload)
        if response.status_code in [200, 201]:
            return {"success": True, "enrollment": response.json()}
        return {"success": False, "error": response.text}

    async def get_sequence_enrollment(self, enrollment_id: str) -> Dict[str, Any]:
        """Get details of a sequence enrollment."""
        url = f"{self.base_url}/automation/v2/sequences/enrollments/{enrollment_id}"
        response = requests.get(url, headers=self.headers)
        if response.status_code in [200, 201]:
            return {"success": True, "enrollment": response.json()}
        return {"success": False, "error": response.text}
