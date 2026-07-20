"""
Zoho integration service for Mini-Hub.
"""

from typing import Any, Dict, Optional
import logging
import requests
import os

logger = logging.getLogger(__name__)

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_ACCOUNTS_URL = "https://accounts.zoho.com"

class ZohoService:
    def __init__(self, access_token: str = None, api_domain: str = None, refresh_token: str = None):
        self.access_token = access_token
        self.api_domain = api_domain or "https://www.zohoapis.com"
        self.refresh_token = refresh_token
        
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Zoho-oauthtoken {self.access_token}",
            "Content-Type": "application/json"
        }

    async def refresh_access_token(self) -> Dict[str, Any]:
        """Refresh the Zoho access token using the refresh token."""
        if not self.refresh_token:
            return {
                "success": False,
                "error": "No refresh token available"
            }
            
        try:
            token_url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token"
            data = {
                "refresh_token": self.refresh_token,
                "client_id": ZOHO_CLIENT_ID,
                "client_secret": ZOHO_CLIENT_SECRET,
                "grant_type": "refresh_token"
            }
            
            response = requests.post(token_url, data=data)
            response_data = response.json()
            
            if response.status_code == 200 and "access_token" in response_data:
                self.access_token = response_data["access_token"]
                if "api_domain" in response_data:
                    self.api_domain = response_data["api_domain"]
                    
                return {
                    "success": True,
                    "access_token": self.access_token,
                    "api_domain": self.api_domain,
                    "expires_in": response_data.get("expires_in")
                }
            else:
                return {
                    "success": False,
                    "error": response_data.get("error", "Unknown error refreshing token")
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error refreshing token: {str(e)}"
            }

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Zoho CRM connection by fetching org info."""
        try:
            if config:
                self.access_token = config.get("access_token")
                self.api_domain = config.get("api_domain", "https://www.zohoapis.com")
                self.refresh_token = config.get("refresh_token")

            if not self.access_token:
                return {
                    "success": False,
                    "error": "Zoho access token missing"
                }

            # Test connection to Zoho CRM API org endpoint
            response = requests.get(
                f"{self.api_domain}/crm/v6/org",
                headers=self._get_headers()
            )

            # If token is invalid/expired, try to refresh
            if response.status_code == 401 and self.refresh_token:
                refresh_result = await self.refresh_access_token()
                if refresh_result["success"]:
                    # Retry with new token
                    response = requests.get(
                        f"{self.api_domain}/crm/v6/org",
                        headers=self._get_headers()
                    )

            if response.status_code == 200:
                data = response.json()
                org_info = data.get("org", [{}])[0]
                return {
                    "success": True,
                    "message": "Zoho connection successful",
                    "account_info": {
                        "org_name": org_info.get("company_name"),
                        "domain": self.api_domain
                    }
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "error": "Authentication failed. Token may be expired and refresh failed."
                }
            else:
                # Sometimes a user doesn't have CRM configured, fallback testing another API could be added here
                return {
                    "success": False,
                    "error": f"API check failed: {response.status_code} - {response.text}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}"
            }

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None, base_url: Optional[str] = None) -> Any:
        """Helper to make authenticated requests to Zoho API."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}
            
        url = f"{base_url or self.api_domain}{endpoint}"
        headers = self._get_headers()
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=json_data, params=params)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=json_data, params=params)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
                
            # Handle token expiration (401)
            if response.status_code == 401 and self.refresh_token:
                refresh_result = await self.refresh_access_token()
                if refresh_result["success"]:
                    headers = self._get_headers()
                    if method.upper() == "GET":
                        response = requests.get(url, headers=headers, params=params)
                    elif method.upper() == "POST":
                        response = requests.post(url, headers=headers, json=json_data, params=params)
                    elif method.upper() == "PUT":
                        response = requests.put(url, headers=headers, json=json_data, params=params)
                        
            if response.status_code in (200, 201):
                # Empty response handling for successful operations without content (e.g. DELETE)
                if not response.text:
                   return {"success": True}
                return response.json()
            else:
                try:
                    err_json = response.json()
                    return {"success": False, "error": f"Zoho API Error ({response.status_code}): {err_json}"}
                except:
                    return {"success": False, "error": f"Zoho API Error ({response.status_code}): {response.text}"}
        except Exception as e:
            return {"success": False, "error": f"Request failed: {str(e)}"}

    # =========================================================================
    # ZOHO CRM OPERATIONS
    # =========================================================================

    async def get_contacts(self, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        """Get contacts from Zoho CRM."""
        params = {"per_page": limit, "page": page}
        response = await self._request("GET", "/crm/v6/Contacts", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        data = response.get("data", [])
        return {
            "success": True, 
            "contacts": data, 
            "count": len(data),
            "info": response.get("info", {})
        }

    async def create_contact(self, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a contact in Zoho CRM."""
        payload = {"data": [contact_data]}
        response = await self._request("POST", "/crm/v6/Contacts", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        result_data = response.get("data", [])
        if result_data and result_data[0].get("code") == "SUCCESS":
             return {"success": True, "message": "Contact created successfully", "contact": result_data[0].get("details")}
        return {"success": False, "error": "Failed to create contact", "details": result_data}

    async def get_deals(self, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        """Get deals from Zoho CRM."""
        params = {"per_page": limit, "page": page}
        response = await self._request("GET", "/crm/v6/Deals", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        data = response.get("data", [])
        return {
            "success": True, 
            "deals": data, 
            "count": len(data)
        }

    async def create_deal(self, deal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a deal in Zoho CRM."""
        payload = {"data": [deal_data]}
        response = await self._request("POST", "/crm/v6/Deals", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        result_data = response.get("data", [])
        if result_data and result_data[0].get("code") == "SUCCESS":
             return {"success": True, "message": "Deal created successfully", "deal": result_data[0].get("details")}
        return {"success": False, "error": "Failed to create deal", "details": result_data}

    async def update_deal_stage(self, deal_id: str, stage: str) -> Dict[str, Any]:
        """Update a deal stage in Zoho CRM."""
        payload = {"data": [{"id": deal_id, "Stage": stage}]}
        response = await self._request("PUT", "/crm/v6/Deals", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        result_data = response.get("data", [])
        if result_data and result_data[0].get("code") == "SUCCESS":
             return {"success": True, "message": f"Deal updated to stage: {stage}"}
        return {"success": False, "error": "Failed to update deal", "details": result_data}

    # =========================================================================
    # ZOHO FINANCE OPERATIONS (Books, Invoice, Expense)
    # Organization ID is required for Finance API calls.
    # We will fetch it automatically if not provided.
    # =========================================================================

    async def _get_finance_org_id(self) -> Optional[str]:
        """Helper to fetch the default Zoho Finance Organization ID."""
        response = await self._request("GET", "/books/v3/organizations")
        if isinstance(response, dict) and "organizations" in response:
             orgs = response["organizations"]
             if orgs:
                 return orgs[0].get("organization_id")
        return None

    async def create_customer(self, customer_data: Dict[str, Any], org_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a customer in Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
        if not org_id:
             return {"success": False, "error": "Could not determine Finance Organization ID"}
             
        params = {"organization_id": org_id}
        response = await self._request("POST", "/books/v3/contacts", params=params, json_data=customer_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "customer": response.get("contact")}
        return {"success": False, "error": response.get("message", "Unknown error")}

    async def get_invoices(self, limit: int = 50, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch invoices from Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
             
        params = {"organization_id": org_id, "per_page": limit} if org_id else {"per_page": limit}
        response = await self._request("GET", "/books/v3/invoices", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "invoices": response.get("invoices", [])}
        return {"success": False, "error": response.get("message", "Unknown error")}

    async def create_invoice(self, invoice_data: Dict[str, Any], org_id: Optional[str] = None) -> Dict[str, Any]:
        """Create an invoice in Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
             
        params = {"organization_id": org_id} if org_id else {}
        response = await self._request("POST", "/books/v3/invoices", params=params, json_data=invoice_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "invoice": response.get("invoice")}
        return {"success": False, "error": response.get("message", "Unknown error")}

    async def record_payment(self, payment_data: Dict[str, Any], org_id: Optional[str] = None) -> Dict[str, Any]:
        """Record a customer payment applied to an invoice in Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
             
        params = {"organization_id": org_id} if org_id else {}
        response = await self._request("POST", "/books/v3/customerpayments", params=params, json_data=payment_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "payment": response.get("payment")}
        return {"success": False, "error": response.get("message", "Unknown error")}

    async def get_expenses(self, limit: int = 50, org_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch expenses from Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
             
        params = {"organization_id": org_id, "per_page": limit} if org_id else {"per_page": limit}
        response = await self._request("GET", "/books/v3/expenses", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "expenses": response.get("expenses", [])}
        return {"success": False, "error": response.get("message", "Unknown error")}

    async def create_expense(self, expense_data: Dict[str, Any], org_id: Optional[str] = None) -> Dict[str, Any]:
        """Create an expense in Zoho Finance."""
        if not org_id:
             org_id = await self._get_finance_org_id()
             
        params = {"organization_id": org_id} if org_id else {}
        response = await self._request("POST", "/books/v3/expenses", params=params, json_data=expense_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        if response.get("code") == 0:
            return {"success": True, "expense": response.get("expense")}
        return {"success": False, "error": response.get("message", "Unknown error")}

    # =========================================================================
    # ZOHO DESK OPERATIONS (Tickets, Replies)
    # Organization ID (portal) may be required.
    # =========================================================================

    async def _get_desk_org_id(self) -> Optional[str]:
        """Fetch the default Desk Organization/Portal ID."""
        # Desk API uses a different domain than CRM
        domain_parts = self.api_domain.split('.')
        tld = domain_parts[-1] if len(domain_parts) > 1 else "com"
        desk_domain = f"https://desk.zoho.{tld}"
        
        response = await self._request("GET", "/api/v1/organizations", base_url=desk_domain)
        if isinstance(response, dict) and "data" in response:
            orgs = response["data"]
            if orgs:
                return orgs[0].get("id")
        return None

    async def _get_desk_headers(self) -> Dict[str, str]:
        """Gets Desk org headers if needed."""
        headers = self._get_headers()
        org_id = await self._get_desk_org_id()
        if org_id:
             headers["orgId"] = str(org_id)
        return headers

    async def _desk_request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Any:
        """Helper to make authenticated requests to Zoho Desk API which requires the orgId header."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        # Desk API uses a different domain than CRM
        domain_parts = self.api_domain.split('.')
        tld = domain_parts[-1] if len(domain_parts) > 1 else "com"
        desk_domain = f"https://desk.zoho.{tld}"

        # Strip /desk if it's there, as we use desk_domain
        if endpoint.startswith("/desk/"):
            endpoint = endpoint[5:]
        
        # Ensure endpoint starts with /
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        url = f"{desk_domain}{endpoint}"
        headers = await self._get_desk_headers()

        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                import logging
                logging.getLogger(__name__).info(f"[DESK_REQUEST] POST {url} orgId={headers.get('orgId')} body_keys={list(json_data.keys()) if json_data else 'none'}")
                response = requests.post(url, headers=headers, json=json_data, params=params)
                logging.getLogger(__name__).info(f"[DESK_REQUEST] Response: {response.status_code} {response.text[:500] if response.text else 'empty'}")
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}

            # Token Refresh
            if response.status_code == 401 and self.refresh_token:
                refresh_result = await self.refresh_access_token()
                if refresh_result["success"]:
                    headers = await self._get_desk_headers()
                    if method.upper() == "GET":
                        response = requests.get(url, headers=headers, params=params)
                    elif method.upper() == "POST":
                        response = requests.post(url, headers=headers, json=json_data, params=params)

            if response.status_code == 204:
                # 204 No Content = success but zero results (e.g. search with no hits)
                return {"data": []}
            elif response.status_code in (200, 201):
                if not response.text:
                    return {"success": True}
                return response.json()
            else:
                try:
                    err_json = response.json()
                    return {"success": False, "error": f"Zoho Desk Error ({response.status_code}): {err_json}"}
                except:
                    return {"success": False, "error": f"Zoho Desk Error ({response.status_code}): {response.text}"}
        except Exception as e:
            return {"success": False, "error": f"Request failed: {str(e)}"}

    async def get_tickets(self, limit: int = 50, department_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch support tickets from Zoho Desk."""
        params: Dict[str, Any] = {"limit": limit}
        if department_id:
            params["departmentId"] = department_id
             
        response = await self._desk_request("GET", "/desk/api/v1/tickets", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "tickets": response.get("data", [])}

    async def create_ticket(self, ticket_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a support ticket in Zoho Desk."""
        response = await self._desk_request("POST", "/desk/api/v1/tickets", json_data=ticket_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "ticket": response}

    async def _get_support_email(self, department_id: str = None) -> Optional[str]:
        """
        Resolve the support email address to use as 'fromEmailAddress' in ticket replies.
        
        Uses official Zoho Desk API endpoints:
          1. GET /api/v1/mailReplyAddress  — the "from" address for outgoing replies
          2. GET /api/v1/supportEmailAddress — the support inbox address (fallback)
        """
        # --- Strategy 1: MailReplyAddress (the FROM address for replies) ---
        params = {}
        if department_id:
            params["departmentId"] = department_id
        
        reply_res = await self._desk_request("GET", "/desk/api/v1/mailReplyAddress", params=params)
        logger.info(f"[ZOHO DESK] mailReplyAddress response: {reply_res}")
        
        addresses = []
        if isinstance(reply_res, dict) and "data" in reply_res:
            addresses = reply_res["data"]
        elif isinstance(reply_res, list):
            addresses = reply_res
        
        for addr in addresses:
            if isinstance(addr, dict) and addr.get("address") and addr.get("isVerified", True):
                logger.info(f"[ZOHO DESK] Found fromEmailAddress via mailReplyAddress: {addr['address']}")
                return addr["address"]

        # --- Strategy 2: SupportEmailAddress (the inbox address, also valid as FROM) ---
        support_params = {}
        if department_id:
            support_params["departmentId"] = department_id
        
        support_res = await self._desk_request("GET", "/desk/api/v1/supportEmailAddress", params=support_params)
        logger.info(f"[ZOHO DESK] supportEmailAddress response: {support_res}")
        
        support_addresses = []
        if isinstance(support_res, dict) and "data" in support_res:
            support_addresses = support_res["data"]
        elif isinstance(support_res, list):
            support_addresses = support_res
        
        for addr in support_addresses:
            if isinstance(addr, dict) and addr.get("address"):
                logger.info(f"[ZOHO DESK] Found fromEmailAddress via supportEmailAddress: {addr['address']}")
                return addr["address"]

        logger.warning("[ZOHO DESK] Could not resolve a support email from mailReplyAddress or supportEmailAddress.")
        return None

    async def reply_ticket(self, ticket_id: str, reply_text: str) -> Dict[str, Any]:
        """Send a reply to an existing ticket."""

        # 1. Fetch ticket details (needed for contact email & departmentId)
        ticket_res = await self._desk_request("GET", f"/desk/api/v1/tickets/{ticket_id}")
        if isinstance(ticket_res, dict) and "error" in ticket_res:
            return ticket_res

        # 2. Determine the recipient (customer) email
        to_email = None
        contact = ticket_res.get("contact")
        if isinstance(contact, dict):
            to_email = contact.get("email")
        if not to_email:
            to_email = ticket_res.get("email")

        # 3. Determine the sender (support) email
        department_id = ticket_res.get("departmentId")
        from_email = await self._get_support_email(department_id)

        if not from_email:
            return {"success": False, "error": "Could not determine fromEmailAddress. Please verify a support email is configured in Zoho Desk → Setup → Channels → Email."}

        logger.info(f"[ZOHO DESK] Replying to ticket {ticket_id} | From: {from_email} | To: {to_email}")

        # 4. Build and send the reply
        payload = {
            "channel": "EMAIL",
            "content": reply_text,
            "fromEmailAddress": from_email,
            "contentType": "html" if "<" in reply_text else "plainText",
        }
        if to_email:
            payload["to"] = to_email

        response = await self._desk_request("POST", f"/desk/api/v1/tickets/{ticket_id}/sendReply", json_data=payload)

        if isinstance(response, dict) and "error" in response:
            logger.error(f"[ZOHO DESK] Reply failed: {response}")
            return response

        return {"success": True, "reply": response}


    async def get_articles(self, limit: int = 50, category_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch help articles from Zoho Desk Knowledge Base."""
        params: Dict[str, Any] = {"limit": limit}
        if category_id:
             params["categoryId"] = category_id
             
        response = await self._desk_request("GET", "/desk/api/v1/articles", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "articles": response.get("data", [])}

    async def get_article(self, article_id: str) -> Dict[str, Any]:
        """Fetch full content of a specific help article."""
        response = await self._desk_request("GET", f"/desk/api/v1/articles/{article_id}")
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "article": response}

    async def search_articles(self, query: str) -> Dict[str, Any]:
        """Search for Knowledge Base articles matching a query."""
        # Zoho Desk API uses '_all' for general text search, not 'searchStr'
        params = {"_all": query}
        response = await self._desk_request("GET", "/desk/api/v1/articles/search", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "articles": response.get("data", [])}

    async def create_article(self, article_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new article draft in Zoho Desk KB."""
        response = await self._desk_request("POST", "/desk/api/v1/articles", json_data=article_data)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "article": response}

    async def subscribe_desk_webhook(self, webhook_url: str, events: list = None) -> Dict[str, Any]:
        """
        Subscribe to Zoho Desk Webhooks (e.g., Ticket.Create).
        """
        if not events:
            # Default events for KB Autopilot
            events = ["Ticket.Create", "Ticket.Update"]
            
        payload = {
            "channel": "HTTP",
            "URL": webhook_url,
            "events": events,
            "isActive": True,
            "description": "Arrotech KB Autopilot Trigger"
        }
        
        response = await self._desk_request("POST", "/desk/api/v1/webhooks", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "webhook": response}

    async def list_desk_webhooks(self) -> Dict[str, Any]:
        """List active Zoho Desk Webhooks."""
        response = await self._desk_request("GET", "/desk/api/v1/webhooks")
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "webhooks": response.get("data", [])}

    # =========================================================================
    # ZOHO MAIL OPERATIONS (Send, Read)
    # Account ID is often needed for Mail endpoints.
    # =========================================================================

    async def _get_mail_account_id(self) -> Optional[str]:
        """Fetch the default Zoho Mail Account."""
        response = await self._request("GET", "/mail/api/accounts")
        if isinstance(response, dict) and "data" in response:
             accounts = response["data"]
             if accounts:
                  return accounts[0].get("accountId")
        return None

    async def get_messages(self, limit: int = 50, account_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """Fetch email messages."""
        if not account_id:
             account_id = await self._get_mail_account_id()
             
        if not account_id:
             return {"success": False, "error": "Could not locate mail account"}
             
        params: Dict[str, Any] = {"limit": limit}
        endpoint = f"/mail/api/accounts/{account_id}/messages/view"
        if folder_id:
             params["folderId"] = folder_id

        response = await self._request("GET", endpoint, params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {"success": True, "messages": response.get("data", [])}

    async def send_email(self, account_id: Optional[str], to_address: str, subject: str, content: str) -> Dict[str, Any]:
        """Send an email via Zoho Mail."""
        if not account_id:
             account_id = await self._get_mail_account_id()
             
        if not account_id:
             return {"success": False, "error": "Could not locate mail account"}
             
        payload = {
            "toAddress": to_address,
            "subject": subject,
            "content": content
        }
        
        endpoint = f"/mail/api/accounts/{account_id}/messages"
        response = await self._request("POST", endpoint, json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        data = response.get("data", {})
        if data.get("messageId"):
             return {"success": True, "message": "Email sent successfully", "message_id": data.get("messageId")}
        return {"success": False, "error": "Failed to send email", "details": response}
