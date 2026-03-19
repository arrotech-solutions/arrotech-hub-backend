"""
Xero accounting service for Arrotech Hub.
OAuth 2.0 integration with Xero Accounting API.
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


# Xero OAuth 2.0 and API endpoints
AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"
API_BASE = "https://api.xero.com/api.xro/2.0"

# Scopes for accounting operations.
# Use granular scopes (required for apps created on or after 2 March 2026).
# Broad scopes like accounting.transactions cause "Invalid scope for client" on new apps.
DEFAULT_SCOPES = (
    "openid profile email offline_access "
    "accounting.invoices accounting.contacts.read accounting.settings.read "
    "accounting.reports.profitandloss.read accounting.reports.balancesheet.read"
)


class XeroService:
    """Xero Accounting API service using OAuth 2.0."""

    def __init__(self):
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.redirect_uri: Optional[str] = None

        # Per-request state (set from connection config before API calls)
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.tenant_id: Optional[str] = None

    async def initialize(self):
        """Initialize Xero credentials from settings."""
        self.client_id = getattr(settings, "XERO_CLIENT_ID", None)
        self.client_secret = getattr(settings, "XERO_CLIENT_SECRET", None)
        self.redirect_uri = getattr(settings, "XERO_REDIRECT_URI", None)
        if self.client_id and self.client_secret:
            logger.info("Xero credentials initialized")
        else:
            logger.warning("Xero credentials not fully configured")

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Generate Xero OAuth 2.0 authorization URL."""
        if not self.client_id:
            raise ValueError("Xero client_id must be configured")
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": DEFAULT_SCOPES,
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Xero credentials must be configured")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_URL,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    return await response.json()
                error_text = await response.text()
                raise Exception(f"Failed to exchange token: {response.status} - {error_text}")

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token. Xero returns a new refresh token; caller should persist it."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Xero credentials must be configured")
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_URL,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    return await response.json()
                error_text = await response.text()
                logger.error(f"Xero token refresh failed: {response.status} - {error_text}")
                raise Exception(f"Failed to refresh token: {response.status} - {error_text}")

    async def get_connections(self) -> List[Dict[str, Any]]:
        """Get tenant (organisation) connections for the authenticated user."""
        if not self.access_token:
            return []
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(CONNECTIONS_URL, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"Failed to get connections: {response.status} - {text}")
                data = await response.json()
                return data if isinstance(data, list) else []

    def _configure_from_connection(self, config: Dict[str, Any]):
        """Configure service state from a stored connection config."""
        self.access_token = config.get("access_token")
        self.refresh_token = config.get("refresh_token")
        self.tenant_id = config.get("tenant_id")

        # Ensure app-level credentials are available for token refresh
        if not self.client_id or not self.client_secret:
            self.client_id = getattr(settings, "XERO_CLIENT_ID", None)
            self.client_secret = getattr(settings, "XERO_CLIENT_SECRET", None)

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Any:
        """Make an authenticated request to the Xero Accounting API."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}
        if not self.tenant_id:
            return {"success": False, "error": "Tenant ID required"}

        url = f"{API_BASE}/{endpoint}" if not endpoint.startswith("http") else endpoint
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Xero-tenant-id": self.tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, params=params, json=json_data, headers=headers
            ) as response:
                if response.status in (200, 201):
                    return await response.json()
                if response.status == 401 and self.refresh_token:
                    try:
                        new_tokens = await self.refresh_access_token(self.refresh_token)
                        self.access_token = new_tokens.get("access_token")
                        if new_tokens.get("refresh_token"):
                            self.refresh_token = new_tokens["refresh_token"]
                        headers["Authorization"] = f"Bearer {self.access_token}"
                        async with session.request(
                            method, url, params=params, json=json_data, headers=headers
                        ) as retry_response:
                            if retry_response.status in (200, 201):
                                return await retry_response.json()
                            text = await retry_response.text()
                            return {"success": False, "error": f"Xero API ({retry_response.status}): {text}"}
                    except Exception as e:
                        return {"success": False, "error": f"Token refresh failed: {str(e)}"}
                text = await response.text()
                return {"success": False, "error": f"Xero API ({response.status}): {text}"}

    async def get_organisation(self) -> Dict[str, Any]:
        """Get connected organisation (company) info."""
        response = await self._request("GET", "Organisation")
        if isinstance(response, dict) and response.get("error"):
            return response
        orgs = response.get("Organisations", [])
        if not orgs:
            return {"success": False, "error": "No organisation found"}
        org = orgs[0]
        return {
            "success": True,
            "company": {
                "name": org.get("Name"),
                "legal_name": org.get("LegalName"),
                "country": org.get("CountryCode"),
                "base_currency": org.get("BaseCurrency"),
                "organisation_id": org.get("OrganisationID"),
                "tax_number": org.get("TaxNumber"),
            },
        }

    async def get_invoices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        contact_id: Optional[str] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Get invoices with optional filters."""
        params: Dict[str, Any] = {}
        if status:
            params["Statuses"] = status  # DRAFT, SUBMITTED, AUTHORISED, etc.
        if contact_id:
            params["ContactIDs"] = contact_id
        # Xero uses where clause for dates: e.g. Date >= DateTime(2024-01-01)
        if start_date:
            params["where"] = params.get("where", "") + f"Date >= DateTime({start_date})"
        if end_date:
            where = params.get("where", "")
            params["where"] = (where + " AND " if where else "") + f"Date <= DateTime({end_date})"
        if max_results:
            params["page"] = 1
            params["pageSize"] = min(max_results, 100)

        response = await self._request("GET", "Invoices", params=params if params else None)
        if isinstance(response, dict) and response.get("error"):
            return response

        invoices_raw = response.get("Invoices", [])
        invoices = []
        for inv in invoices_raw:
            invoices.append({
                "id": inv.get("InvoiceID"),
                "invoice_number": inv.get("InvoiceNumber"),
                "contact_id": inv.get("Contact", {}).get("ContactID") if isinstance(inv.get("Contact"), dict) else None,
                "contact_name": inv.get("Contact", {}).get("Name") if isinstance(inv.get("Contact"), dict) else None,
                "date": inv.get("Date"),
                "due_date": inv.get("DueDate"),
                "total": float(inv.get("Total", 0)),
                "amount_due": float(inv.get("AmountDue", 0)),
                "status": inv.get("Status"),
                "currency": inv.get("CurrencyCode"),
            })
        return {
            "success": True,
            "invoices": invoices,
            "count": len(invoices),
            "total_value": sum(i["total"] for i in invoices),
            "total_outstanding": sum(i["amount_due"] for i in invoices),
        }

    async def create_invoice(
        self,
        contact_id: str,
        line_items: List[Dict[str, Any]],
        due_date: Optional[str] = None,
        reference: Optional[str] = None,
        type: str = "ACCREC",
    ) -> Dict[str, Any]:
        """Create a new invoice."""
        lines = []
        for item in line_items:
            line = {
                "Description": item.get("description", "Item"),
                "Quantity": item.get("quantity", 1),
                "UnitAmount": item.get("unit_price", item.get("amount", 0)),
                "AccountCode": item.get("account_code", "200"),
            }
            if item.get("tax_type"):
                line["TaxType"] = item["tax_type"]
            lines.append(line)

        payload = {
            "Type": type,
            "Contact": {"ContactID": contact_id},
            "LineItems": lines,
        }
        if due_date:
            payload["DueDate"] = due_date
        if reference:
            payload["Reference"] = reference

        response = await self._request("POST", "Invoices", json_data=payload)
        if isinstance(response, dict) and response.get("error"):
            return response
        invs = response.get("Invoices", [])
        if not invs:
            return {"success": False, "error": "No invoice returned"}
        inv = invs[0]
        return {
            "success": True,
            "message": "Invoice created successfully",
            "invoice": {
                "id": inv.get("InvoiceID"),
                "invoice_number": inv.get("InvoiceNumber"),
                "total": float(inv.get("Total", 0)),
                "due_date": inv.get("DueDate"),
                "contact": inv.get("Contact", {}).get("Name") if isinstance(inv.get("Contact"), dict) else None,
            },
        }

    async def create_payment(
        self,
        invoice_id: str,
        account_id: str,
        amount: float,
        date: str,
        reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record a payment against a Xero invoice."""
        payload = {
            "Invoice": {"InvoiceID": invoice_id},
            "Account": {"AccountID": account_id},
            "Amount": amount,
            "Date": date
        }
        if reference:
            payload["Reference"] = reference
            
        response = await self._request("POST", "Payments", json_data=payload)
        if isinstance(response, dict) and response.get("error"):
            return response
            
        payments = response.get("Payments", [])
        if not payments:
            return {"success": False, "error": "No payment returned from Xero"}
            
        return {
            "success": True,
            "message": "Payment recorded successfully",
            "payment": {
                "id": payments[0].get("PaymentID"),
                "status": payments[0].get("Status")
            }
        }

    async def get_contacts(self, max_results: int = 100) -> Dict[str, Any]:
        """Get contacts list."""
        params = {"page": 1, "pageSize": min(max_results, 100)}
        response = await self._request("GET", "Contacts", params=params)
        if isinstance(response, dict) and response.get("error"):
            return response
        contacts_raw = response.get("Contacts", [])
        contacts = []
        for c in contacts_raw:
            contacts.append({
                "id": c.get("ContactID"),
                "name": c.get("Name"),
                "first_name": c.get("FirstName"),
                "last_name": c.get("LastName"),
                "email": c.get("EmailAddress"),
                "phones": c.get("Phones"),
                "is_customer": c.get("IsCustomer", True),
                "is_supplier": c.get("IsSupplier", False),
            })
        return {"success": True, "contacts": contacts, "count": len(contacts)}

    async def get_accounts(self, account_type: Optional[str] = None, max_results: int = 100) -> Dict[str, Any]:
        """Get chart of accounts."""
        params: Dict[str, Any] = {"page": 1, "pageSize": min(max_results, 100)}
        if account_type:
            params["where"] = f'Type=="{account_type}"'
        response = await self._request("GET", "Accounts", params=params)
        if isinstance(response, dict) and response.get("error"):
            return response
        accounts_raw = response.get("Accounts", [])
        accounts = []
        for a in accounts_raw:
            accounts.append({
                "id": a.get("AccountID"),
                "name": a.get("Name"),
                "code": a.get("Code"),
                "type": a.get("Type"),
                "status": a.get("Status"),
                "class": a.get("Class"),
            })
        return {"success": True, "accounts": accounts, "count": len(accounts)}

    async def get_profit_and_loss(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get Profit and Loss report."""
        params: Dict[str, Any] = {}
        if start_date:
            params["fromDate"] = start_date
        if end_date:
            params["toDate"] = end_date
        response = await self._request("GET", "Reports/ProfitAndLoss", params=params if params else None)
        if isinstance(response, dict) and response.get("error"):
            return response
        return {
            "success": True,
            "report": "Profit and Loss",
            "raw": response,
        }

    async def get_balance_sheet(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get Balance Sheet report."""
        params = {"date": date} if date else {}
        response = await self._request("GET", "Reports/BalanceSheet", params=params if params else None)
        if isinstance(response, dict) and response.get("error"):
            return response
        return {"success": True, "report": "Balance Sheet", "raw": response}

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test a Xero connection by fetching organisation info."""
        try:
            self._configure_from_connection(config)
            if not self.access_token or not self.tenant_id:
                return {
                    "success": False,
                    "error": "Xero access_token and tenant_id are required",
                }
            result = await self.get_organisation()
            if result.get("success"):
                return {
                    "success": True,
                    "message": "Xero connection test successful",
                    "data": {
                        "company_name": result.get("company", {}).get("name"),
                        "country": result.get("company", {}).get("country"),
                    },
                }
            return {
                "success": False,
                "error": result.get("error", "Failed to fetch organisation"),
            }
        except Exception as e:
            return {"success": False, "error": f"Xero connection test failed: {str(e)}"}

    async def handle_operation(
        self,
        operation: str,
        config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Handle Xero operations from the tool executor."""
        try:
            if config:
                self._configure_from_connection(config)
            if not self.access_token or not self.tenant_id:
                return {
                    "success": False,
                    "error": "Xero connection not configured. Please connect Xero first.",
                }

            result = None
            if operation == "get_company_info":
                result = await self.get_organisation()
            elif operation == "get_invoices":
                result = await self.get_invoices(
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                    status=kwargs.get("status"),
                    contact_id=kwargs.get("contact_id"),
                    max_results=kwargs.get("max_results", 100),
                )
            elif operation == "create_invoice":
                contact_id = kwargs.get("customer_id") or kwargs.get("contact_id")
                line_items = kwargs.get("line_items", [])
                if not contact_id:
                    return {"success": False, "error": "customer_id or contact_id is required"}
                if not line_items:
                    return {"success": False, "error": "line_items are required"}
                result = await self.create_invoice(
                    contact_id=contact_id,
                    line_items=line_items,
                    due_date=kwargs.get("due_date"),
                    reference=kwargs.get("reference"),
                )
            elif operation == "get_profit_loss":
                result = await self.get_profit_and_loss(
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                )
            elif operation == "get_balance_sheet":
                result = await self.get_balance_sheet(date=kwargs.get("date"))
            elif operation == "get_accounts":
                result = await self.get_accounts(
                    account_type=kwargs.get("account_type"),
                    max_results=kwargs.get("max_results", 100),
                )
            elif operation == "create_payment":
                invoice_id = kwargs.get("invoice_id")
                account_id = kwargs.get("account_id")
                amount = kwargs.get("amount")
                date_str = kwargs.get("date")
                
                if not invoice_id or not account_id or amount is None or not date_str:
                    return {"success": False, "error": "invoice_id, account_id, amount, and date are required"}
                    
                result = await self.create_payment(
                    invoice_id=str(invoice_id),
                    account_id=str(account_id),
                    amount=float(amount),
                    date=str(date_str),
                    reference=str(kwargs.get("reference")) if kwargs.get("reference") else None
                )
            elif operation == "get_customers" or operation == "get_contacts":
                result = await self.get_contacts(max_results=kwargs.get("max_results", 100))
            else:
                result = {
                    "success": False,
                    "error": f"Operation '{operation}' not supported. Available: get_company_info, get_invoices, create_invoice, get_profit_loss, get_balance_sheet, get_accounts, create_payment, get_customers, get_contacts",
                }

            # Return new tokens to caller if a refresh happened
            if result and isinstance(result, dict) and config:
                initial_access = config.get("access_token")
                initial_refresh = config.get("refresh_token")
                if self.access_token != initial_access or self.refresh_token != initial_refresh:
                    result["_new_tokens"] = {
                        "access_token": self.access_token,
                        "refresh_token": self.refresh_token,
                    }
                    
            return result
        except Exception as e:
            logger.error(f"Xero operation error: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}


xero_service = XeroService()
