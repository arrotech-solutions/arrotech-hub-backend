"""
Salesforce Service for CRM operations and integrations.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus, User

logger = logging.getLogger(__name__)


class SalesforceService:
    """Salesforce CRM service for contact, lead, and opportunity management."""
    
    def __init__(self):
        self.base_url = "https://api.salesforce.com/services/data/v58.0"
        self.access_token = None
        self.instance_url = None
    
    async def initialize(self, connection: Connection):
        """Initialize Salesforce service with connection."""
        self.connection = connection
        await self._authenticate()
    
    async def _authenticate(self):
        """Authenticate with Salesforce using OAuth 2.0 Password Grant flow."""
        try:
            config = self.connection.config
            
            # Validate required fields
            client_id = config.get("client_id")
            client_secret = config.get("client_secret")
            username = config.get("username")
            password = config.get("password")
            security_token = config.get("security_token", "")
            
            if not all([client_id, client_secret, username, password]):
                raise Exception("Missing required authentication fields: client_id, client_secret, username, password")
            
            # Determine the correct token endpoint (production vs sandbox)
            # Check if username contains 'sandbox' or if we should try both
            auth_urls = []
            if "sandbox" in username.lower() or "test" in username.lower():
                auth_urls = ["https://test.salesforce.com/services/oauth2/token"]
            else:
                auth_urls = ["https://login.salesforce.com/services/oauth2/token"]
            
            # Prepare authentication data according to Salesforce OAuth 2.0 Password Grant specification
            data = {
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
                "username": username,
                "password": password + security_token  # Concatenate password + security token
            }
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }
            
            # Log request details for debugging (without sensitive data)
            logger.info(f"Attempting Salesforce OAuth 2.0 Password Grant authentication")
            logger.info(f"Username: {username}")
            logger.info(f"Client ID: {client_id[:10]}..." if len(client_id) > 10 else f"Client ID: {client_id}")
            logger.info(f"Password length: {len(password)}")
            logger.info(f"Security token length: {len(security_token)}")
            logger.info(f"Combined password length: {len(password + security_token)}")
            
            last_error = None
            
            for auth_url in auth_urls:
                logger.info(f"Trying authentication URL: {auth_url}")
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(auth_url, data=data, headers=headers, timeout=30) as response:
                            response_text = await response.text()
                            
                            logger.info(f"Response status: {response.status}")
                            logger.info(f"Response headers: {dict(response.headers)}")
                            
                            if response.status == 200:
                                try:
                                    auth_data = await response.json()
                                    
                                    # Validate required fields in response
                                    if "access_token" not in auth_data:
                                        raise Exception("Missing access_token in Salesforce response")
                                    if "instance_url" not in auth_data:
                                        raise Exception("Missing instance_url in Salesforce response")
                                    
                                    self.access_token = auth_data["access_token"]
                                    self.instance_url = auth_data["instance_url"]
                                    
                                    logger.info("Salesforce OAuth 2.0 authentication successful!")
                                    logger.info(f"Instance URL: {self.instance_url}")
                                    logger.info(f"Token type: {auth_data.get('token_type', 'Bearer')}")
                                    logger.info(f"Token issued at: {auth_data.get('issued_at', 'N/A')}")
                                    
                                    return  # Success, exit the method
                                    
                                except KeyError as e:
                                    error_msg = f"Missing required field in Salesforce response: {e}"
                                    logger.error(error_msg)
                                    last_error = Exception(error_msg)
                                except Exception as e:
                                    error_msg = f"Failed to parse Salesforce response: {e}"
                                    logger.error(error_msg)
                                    last_error = Exception(error_msg)
                            else:
                                # Handle error responses
                                logger.error(f"Salesforce authentication failed with status {response.status}")
                                logger.error(f"Response text: {response_text}")
                                
                                try:
                                    error_data = await response.json()
                                    error_type = error_data.get("error", "unknown_error")
                                    error_description = error_data.get("error_description", "Unknown error")
                                    
                                    # Provide specific error messages based on Salesforce error types
                                    if error_type == "invalid_grant":
                                        error_msg = f"Invalid credentials: {error_description}"
                                    elif error_type == "invalid_client":
                                        error_msg = f"Invalid client credentials: {error_description}"
                                    elif error_type == "invalid_request":
                                        error_msg = f"Invalid request: {error_description}"
                                    else:
                                        error_msg = f"Salesforce authentication failed: {error_description}"
                                    
                                    last_error = Exception(error_msg)
                                    
                                except:
                                    error_msg = f"Salesforce authentication failed: HTTP {response.status} - {response_text}"
                                    last_error = Exception(error_msg)
                
                except asyncio.TimeoutError:
                    error_msg = f"Request timeout for URL: {auth_url}"
                    logger.error(error_msg)
                    last_error = Exception(error_msg)
                except Exception as e:
                    error_msg = f"Request failed for URL {auth_url}: {str(e)}"
                    logger.error(error_msg)
                    last_error = Exception(error_msg)
            
            # If we get here, all authentication attempts failed
            if last_error:
                raise last_error
            else:
                raise Exception("All authentication attempts failed")
                
        except Exception as e:
            logger.error(f"Salesforce authentication error: {e}")
            raise
    
    async def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make authenticated request to Salesforce API."""
        if not self.access_token:
            await self._authenticate()
        
        url = f"{self.instance_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, headers=headers) as response:
                    return await response.json()
            elif method == "POST":
                async with session.post(url, headers=headers, json=data) as response:
                    return await response.json()
            elif method == "PATCH":
                async with session.patch(url, headers=headers, json=data) as response:
                    return await response.json()
            elif method == "DELETE":
                async with session.delete(url, headers=headers) as response:
                    return {"success": response.status == 204}
    
    # Contact Management
    async def create_contact(self, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new contact in Salesforce."""
        try:
            endpoint = "/sobjects/Contact"
            result = await self._make_request("POST", endpoint, contact_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "contact_id": result["id"],
                    "message": "Contact created successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error creating contact: {e}")
            return {"success": False, "error": str(e)}
    
    async def update_contact(self, contact_id: str, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing contact in Salesforce."""
        try:
            endpoint = f"/sobjects/Contact/{contact_id}"
            result = await self._make_request("PATCH", endpoint, contact_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "message": "Contact updated successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error updating contact: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        """Get a specific contact by ID."""
        try:
            endpoint = f"/sobjects/Contact/{contact_id}"
            result = await self._make_request("GET", endpoint)
            
            if "Id" in result:
                return {
                    "success": True,
                    "contact": result
                }
            else:
                return {
                    "success": False,
                    "error": "Contact not found"
                }
        except Exception as e:
            logger.error(f"Error getting contact: {e}")
            return {"success": False, "error": str(e)}
    
    async def search_contacts(self, query: str, limit: int = 50) -> Dict[str, Any]:
        """Search contacts using SOQL query."""
        try:
            soql_query = f"SELECT Id, FirstName, LastName, Email, Phone, Company FROM Contact WHERE Name LIKE '%{query}%' OR Email LIKE '%{query}%' LIMIT {limit}"
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "contacts": result.get("records", []),
                "total_size": result.get("totalSize", 0)
            }
        except Exception as e:
            logger.error(f"Error searching contacts: {e}")
            return {"success": False, "error": str(e)}
    
    # Lead Management
    async def create_lead(self, lead_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new lead in Salesforce."""
        try:
            endpoint = "/sobjects/Lead"
            result = await self._make_request("POST", endpoint, lead_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "lead_id": result["id"],
                    "message": "Lead created successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            return {"success": False, "error": str(e)}
    
    async def convert_lead(self, lead_id: str, conversion_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a lead to contact, account, and opportunity."""
        try:
            endpoint = f"/sobjects/Lead/{lead_id}/convert"
            result = await self._make_request("POST", endpoint, conversion_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "converted_objects": result,
                    "message": "Lead converted successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error converting lead: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_leads(self, status: str = None, limit: int = 50) -> Dict[str, Any]:
        """Get leads with optional status filter."""
        try:
            soql_query = "SELECT Id, FirstName, LastName, Company, Email, Status, LeadSource FROM Lead"
            if status:
                soql_query += f" WHERE Status = '{status}'"
            soql_query += f" LIMIT {limit}"
            
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "leads": result.get("records", []),
                "total_size": result.get("totalSize", 0)
            }
        except Exception as e:
            logger.error(f"Error getting leads: {e}")
            return {"success": False, "error": str(e)}
    
    # Opportunity Management
    async def create_opportunity(self, opportunity_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new opportunity in Salesforce."""
        try:
            endpoint = "/sobjects/Opportunity"
            result = await self._make_request("POST", endpoint, opportunity_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "opportunity_id": result["id"],
                    "message": "Opportunity created successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error creating opportunity: {e}")
            return {"success": False, "error": str(e)}
    
    async def update_opportunity_stage(self, opportunity_id: str, stage: str) -> Dict[str, Any]:
        """Update opportunity stage."""
        try:
            endpoint = f"/sobjects/Opportunity/{opportunity_id}"
            data = {"StageName": stage}
            result = await self._make_request("PATCH", endpoint, data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "message": f"Opportunity stage updated to {stage}"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error updating opportunity stage: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_opportunities(self, stage: str = None, limit: int = 50) -> Dict[str, Any]:
        """Get opportunities with optional stage filter."""
        try:
            soql_query = "SELECT Id, Name, Amount, StageName, CloseDate, AccountId FROM Opportunity"
            if stage:
                soql_query += f" WHERE StageName = '{stage}'"
            soql_query += f" LIMIT {limit}"
            
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "opportunities": result.get("records", []),
                "total_size": result.get("totalSize", 0)
            }
        except Exception as e:
            logger.error(f"Error getting opportunities: {e}")
            return {"success": False, "error": str(e)}
    
    # Account Management
    async def create_account(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new account in Salesforce."""
        try:
            endpoint = "/sobjects/Account"
            result = await self._make_request("POST", endpoint, account_data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "account_id": result["id"],
                    "message": "Account created successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])
                }
        except Exception as e:
            logger.error(f"Error creating account: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_accounts(self, limit: int = 50) -> Dict[str, Any]:
        """Get accounts."""
        try:
            soql_query = f"SELECT Id, Name, Industry, BillingCity, Phone FROM Account LIMIT {limit}"
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "accounts": result.get("records", []),
                "total_size": result.get("totalSize", 0)
            }
        except Exception as e:
            logger.error(f"Error getting accounts: {e}")
            return {"success": False, "error": str(e)}
    
    # Reporting and Analytics
    async def get_sales_pipeline_report(self, date_range: str = "30") -> Dict[str, Any]:
        """Get sales pipeline report."""
        try:
            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=int(date_range))
            
            soql_query = f"""
                SELECT StageName, SUM(Amount) TotalAmount, COUNT(Id) OpportunityCount
                FROM Opportunity 
                WHERE CloseDate >= {start_date.strftime('%Y-%m-%d')}
                GROUP BY StageName
                ORDER BY TotalAmount DESC
            """
            
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "pipeline_report": result.get("records", []),
                "date_range": f"Last {date_range} days"
            }
        except Exception as e:
            logger.error(f"Error getting pipeline report: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_lead_conversion_report(self, date_range: str = "30") -> Dict[str, Any]:
        """Get lead conversion report."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=int(date_range))
            
            soql_query = f"""
                SELECT LeadSource, COUNT(Id) TotalLeads, 
                       SUM(CASE WHEN IsConverted = true THEN 1 ELSE 0 END) ConvertedLeads
                FROM Lead 
                WHERE CreatedDate >= {start_date.strftime('%Y-%m-%d')}
                GROUP BY LeadSource
                ORDER BY TotalLeads DESC
            """
            
            endpoint = f"/query?q={soql_query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "conversion_report": result.get("records", []),
                "date_range": f"Last {date_range} days"
            }
        except Exception as e:
            logger.error(f"Error getting conversion report: {e}")
            return {"success": False, "error": str(e)}
    
    # Bulk Operations
    async def bulk_create_contacts(self, contacts_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk create contacts."""
        try:
            endpoint = "/composite/sobjects"
            data = {
                "allOrNone": False,
                "records": contacts_data
            }
            result = await self._make_request("POST", endpoint, data)
            
            return {
                "success": True,
                "results": result,
                "message": f"Bulk operation completed for {len(contacts_data)} contacts"
            }
        except Exception as e:
            logger.error(f"Error in bulk create contacts: {e}")
            return {"success": False, "error": str(e)}
    
    # Data Sync
    async def sync_contacts_from_hubspot(self, hubspot_contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync contacts from HubSpot to Salesforce."""
        try:
            synced_count = 0
            errors = []
            
            for contact in hubspot_contacts:
                # Map HubSpot fields to Salesforce fields
                sf_contact = {
                    "FirstName": contact.get("firstname", ""),
                    "LastName": contact.get("lastname", ""),
                    "Email": contact.get("email", ""),
                    "Phone": contact.get("phone", ""),
                    "Company": contact.get("company", ""),
                    "Description": f"Imported from HubSpot - {contact.get('hs_object_id', '')}"
                }
                
                result = await self.create_contact(sf_contact)
                if result["success"]:
                    synced_count += 1
                else:
                    errors.append(f"Failed to sync contact {contact.get('email', 'unknown')}: {result.get('error')}")
            
            return {
                "success": True,
                "synced_count": synced_count,
                "error_count": len(errors),
                "errors": errors,
                "message": f"Synced {synced_count} contacts from HubSpot"
            }
        except Exception as e:
            logger.error(f"Error syncing contacts from HubSpot: {e}")
            return {"success": False, "error": str(e)}
    
    # Utility Methods
    async def get_object_fields(self, object_name: str) -> Dict[str, Any]:
        """Get available fields for a Salesforce object."""
        try:
            endpoint = f"/sobjects/{object_name}/describe"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "fields": result.get("fields", []),
                "object_name": object_name
            }
        except Exception as e:
            logger.error(f"Error getting object fields: {e}")
            return {"success": False, "error": str(e)}
    
    async def execute_soql_query(self, query: str) -> Dict[str, Any]:
        """Execute a custom SOQL query."""
        try:
            endpoint = f"/query?q={query}"
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "records": result.get("records", []),
                "total_size": result.get("totalSize", 0),
                "done": result.get("done", True)
            }
        except Exception as e:
            logger.error(f"Error executing SOQL query: {e}")
            return {"success": False, "error": str(e)}

    async def create_record(self, object_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create any Salesforce record dynamically."""
        try:
            endpoint = f"/sobjects/{object_name}/"
            result = await self._make_request("POST", endpoint, data=data)
            
            return {
                "success": True,
                "record_id": result.get("id"),
                "status": "created",
                "object_name": object_name
            }
        except Exception as e:
            logger.error(f"Error creating {object_name} record: {e}")
            return {"success": False, "error": str(e)}

    async def update_record(self, object_name: str, record_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update any Salesforce record dynamically."""
        try:
            endpoint = f"/sobjects/{object_name}/{record_id}"
            await self._make_request("PATCH", endpoint, data=data)
            
            return {
                "success": True,
                "record_id": record_id,
                "status": "updated",
                "object_name": object_name
            }
        except Exception as e:
            logger.error(f"Error updating {object_name} record {record_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_record(self, object_name: str, record_id: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get any Salesforce record dynamically."""
        try:
            endpoint = f"/sobjects/{object_name}/{record_id}"
            if fields:
                endpoint += f"?fields={','.join(fields)}"
                
            result = await self._make_request("GET", endpoint)
            
            return {
                "success": True,
                "record": result,
                "object_name": object_name
            }
        except Exception as e:
            logger.error(f"Error getting {object_name} record {record_id}: {e}")
            return {"success": False, "error": str(e)}