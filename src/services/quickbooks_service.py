"""
QuickBooks Online service for Arrotech Hub.
Full OAuth 2.0 integration with accounting API operations.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class QuickBooksService:
    """QuickBooks Online API service using OAuth 2.0."""

    # Intuit OAuth endpoints
    AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

    # API base URLs
    SANDBOX_API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
    PRODUCTION_API_BASE = "https://quickbooks.api.intuit.com/v3/company"

    def __init__(self):
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.redirect_uri: Optional[str] = None
        self.environment: str = "sandbox"

        # Per-request state (set from connection config before API calls)
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.realm_id: Optional[str] = None  # QuickBooks company ID

    async def initialize(self):
        """Initialize QuickBooks credentials from settings."""
        self.client_id = getattr(settings, "QUICKBOOKS_CLIENT_ID", None)
        self.client_secret = getattr(settings, "QUICKBOOKS_CLIENT_SECRET", None)
        self.redirect_uri = getattr(settings, "QUICKBOOKS_REDIRECT_URI", None)
        self.environment = getattr(settings, "QUICKBOOKS_ENVIRONMENT", "sandbox")

        if self.client_id and self.client_secret:
            logger.info("QuickBooks credentials initialized")
        else:
            logger.warning("QuickBooks credentials not fully configured")

    @property
    def api_base_url(self) -> str:
        """Get the API base URL based on environment."""
        if self.environment == "production":
            return self.PRODUCTION_API_BASE
        return self.SANDBOX_API_BASE

    # ─────────────────────────────────────────────
    # OAuth 2.0 Flow
    # ─────────────────────────────────────────────

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """
        Generate Intuit OAuth 2.0 authorization URL.
        Scope: com.intuit.quickbooks.accounting
        """
        if not self.client_id:
            raise ValueError("QuickBooks client_id must be configured")

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "com.intuit.quickbooks.accounting",
            "state": state,
        }

        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.client_id or not self.client_secret:
            raise ValueError("QuickBooks credentials must be configured")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TOKEN_URL,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to exchange token: {response.status} - {error_text}"
                    )

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("QuickBooks credentials must be configured")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TOKEN_URL,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to refresh QuickBooks token: {response.status} - {error_text}"
                    )
                    raise Exception(
                        f"Failed to refresh token: {response.status} - {error_text}"
                    )

    # ─────────────────────────────────────────────
    # API Request Helper
    # ─────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        json_data: Dict = None,
    ) -> Any:
        """Make an authenticated request to the QuickBooks API."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        if not self.realm_id:
            return {"success": False, "error": "Realm ID (company ID) required"}

        url = f"{self.api_base_url}/{self.realm_id}/{endpoint}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, params=params, json=json_data, headers=headers
            ) as response:
                if response.status in (200, 201):
                    return await response.json()
                elif response.status == 401:
                    # Token expired — try refresh
                    if self.refresh_token:
                        try:
                            new_tokens = await self.refresh_access_token(self.refresh_token)
                            self.access_token = new_tokens.get("access_token")
                            if new_tokens.get("refresh_token"):
                                self.refresh_token = new_tokens["refresh_token"]

                            # Retry the request
                            headers["Authorization"] = f"Bearer {self.access_token}"
                            async with session.request(
                                method, url, params=params, json=json_data, headers=headers
                            ) as retry_response:
                                if retry_response.status in (200, 201):
                                    return await retry_response.json()
                                else:
                                    text = await retry_response.text()
                                    return {
                                        "success": False,
                                        "error": f"QuickBooks API Error ({retry_response.status}): {text}",
                                    }
                        except Exception as e:
                            return {
                                "success": False,
                                "error": f"Token refresh failed: {str(e)}",
                            }
                    return {"success": False, "error": "Access token expired and no refresh token available"}
                else:
                    text = await response.text()
                    return {
                        "success": False,
                        "error": f"QuickBooks API Error ({response.status}): {text}",
                    }

    def _configure_from_connection(self, config: Dict[str, Any]):
        """Configure service state from a stored connection config."""
        self.access_token = config.get("access_token")
        self.refresh_token = config.get("refresh_token")
        self.realm_id = config.get("realm_id")

    # ─────────────────────────────────────────────
    # Accounting API Operations
    # ─────────────────────────────────────────────

    async def get_company_info(self) -> Dict[str, Any]:
        """Get connected company information."""
        response = await self._request("GET", "companyinfo/" + self.realm_id)

        if isinstance(response, dict) and "error" in response:
            return response

        info = response.get("CompanyInfo", {})
        return {
            "success": True,
            "company": {
                "name": info.get("CompanyName"),
                "legal_name": info.get("LegalName"),
                "address": {
                    "line1": info.get("CompanyAddr", {}).get("Line1"),
                    "city": info.get("CompanyAddr", {}).get("City"),
                    "country": info.get("CompanyAddr", {}).get("Country"),
                    "postal_code": info.get("CompanyAddr", {}).get("PostalCode"),
                },
                "email": info.get("Email", {}).get("Address") if isinstance(info.get("Email"), dict) else info.get("Email"),
                "phone": info.get("PrimaryPhone", {}).get("FreeFormNumber") if isinstance(info.get("PrimaryPhone"), dict) else None,
                "fiscal_year_start": info.get("FiscalYearStartMonth"),
                "country": info.get("Country"),
                "currency": info.get("HomeCurrency", {}).get("value") if isinstance(info.get("HomeCurrency"), dict) else None,
            },
        }

    async def get_invoices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """Get invoices with optional filters."""
        where_clauses = []

        if start_date:
            where_clauses.append(f"TxnDate >= '{start_date}'")
        if end_date:
            where_clauses.append(f"TxnDate <= '{end_date}'")
        if status:
            # Paid, Unpaid, Overdue etc
            if status.lower() == "unpaid":
                where_clauses.append("Balance > '0'")
            elif status.lower() == "paid":
                where_clauses.append("Balance = '0'")

        where = " AND ".join(where_clauses) if where_clauses else None
        query = f"SELECT * FROM Invoice"
        if where:
            query += f" WHERE {where}"
        query += f" MAXRESULTS {max_results}"

        response = await self._request("GET", "query", params={"query": query})

        if isinstance(response, dict) and "error" in response:
            return response

        query_response = response.get("QueryResponse", {})
        invoices_raw = query_response.get("Invoice", [])

        invoices = []
        for inv in invoices_raw:
            invoices.append({
                "id": inv.get("Id"),
                "doc_number": inv.get("DocNumber"),
                "customer_name": inv.get("CustomerRef", {}).get("name"),
                "customer_id": inv.get("CustomerRef", {}).get("value"),
                "date": inv.get("TxnDate"),
                "due_date": inv.get("DueDate"),
                "total": float(inv.get("TotalAmt", 0)),
                "balance": float(inv.get("Balance", 0)),
                "currency": inv.get("CurrencyRef", {}).get("value", "USD"),
                "status": "Paid" if float(inv.get("Balance", 0)) == 0 else "Unpaid",
                "email_status": inv.get("EmailStatus"),
                "line_items": [
                    {
                        "description": line.get("Description", ""),
                        "amount": float(line.get("Amount", 0)),
                        "detail_type": line.get("DetailType"),
                    }
                    for line in inv.get("Line", [])
                    if line.get("DetailType") == "SalesItemLineDetail"
                ],
            })

        return {
            "success": True,
            "invoices": invoices,
            "count": len(invoices),
            "total_value": sum(i["total"] for i in invoices),
            "total_outstanding": sum(i["balance"] for i in invoices),
        }

    async def create_invoice(
        self,
        customer_id: str,
        line_items: List[Dict[str, Any]],
        due_date: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new invoice."""
        lines = []
        for item in line_items:
            line = {
                "Amount": item.get("amount", 0),
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": item.get("item_id", "1")},
                    "Qty": item.get("quantity", 1),
                    "UnitPrice": item.get("unit_price", item.get("amount", 0)),
                },
            }
            if item.get("description"):
                line["Description"] = item["description"]
            lines.append(line)

        payload = {
            "CustomerRef": {"value": customer_id},
            "Line": lines,
        }

        if due_date:
            payload["DueDate"] = due_date
        if email:
            payload["BillEmail"] = {"Address": email}

        response = await self._request("POST", "invoice", json_data=payload)

        if isinstance(response, dict) and "error" in response:
            return response

        invoice = response.get("Invoice", {})
        return {
            "success": True,
            "message": "Invoice created successfully",
            "invoice": {
                "id": invoice.get("Id"),
                "doc_number": invoice.get("DocNumber"),
                "total": float(invoice.get("TotalAmt", 0)),
                "due_date": invoice.get("DueDate"),
                "customer": invoice.get("CustomerRef", {}).get("name"),
            },
        }

    async def get_profit_and_loss(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get Profit and Loss report."""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        response = await self._request("GET", "reports/ProfitAndLoss", params=params)

        if isinstance(response, dict) and "error" in response:
            return response

        header = response.get("Header", {})
        rows = response.get("Rows", {})

        # Parse the report rows for key figures
        income = 0
        expenses = 0
        net_income = 0

        for row in rows.get("Row", []):
            summary = row.get("Summary", {})
            group = row.get("group", "")

            if group == "Income":
                col_data = summary.get("ColData", [])
                if len(col_data) > 1:
                    try:
                        income = float(col_data[1].get("value", 0))
                    except (ValueError, TypeError):
                        pass
            elif group == "Expenses":
                col_data = summary.get("ColData", [])
                if len(col_data) > 1:
                    try:
                        expenses = float(col_data[1].get("value", 0))
                    except (ValueError, TypeError):
                        pass
            elif group == "NetIncome":
                col_data = summary.get("ColData", [])
                if len(col_data) > 1:
                    try:
                        net_income = float(col_data[1].get("value", 0))
                    except (ValueError, TypeError):
                        pass

        return {
            "success": True,
            "report": "Profit and Loss",
            "period": {
                "start": header.get("StartPeriod"),
                "end": header.get("EndPeriod"),
            },
            "currency": header.get("Currency"),
            "income": income,
            "expenses": expenses,
            "net_income": net_income,
            "profit_margin": round((net_income / income * 100), 2) if income > 0 else 0,
        }

    async def get_balance_sheet(
        self, date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get Balance Sheet report."""
        params = {}
        if date:
            params["date"] = date

        response = await self._request("GET", "reports/BalanceSheet", params=params)

        if isinstance(response, dict) and "error" in response:
            return response

        header = response.get("Header", {})

        return {
            "success": True,
            "report": "Balance Sheet",
            "as_of": header.get("EndPeriod"),
            "currency": header.get("Currency"),
            "raw_rows": response.get("Rows", {}),
        }

    async def get_accounts(
        self, account_type: Optional[str] = None, max_results: int = 100
    ) -> Dict[str, Any]:
        """Get chart of accounts."""
        query = "SELECT * FROM Account"
        if account_type:
            query += f" WHERE AccountType = '{account_type}'"
        query += f" MAXRESULTS {max_results}"

        response = await self._request("GET", "query", params={"query": query})

        if isinstance(response, dict) and "error" in response:
            return response

        query_response = response.get("QueryResponse", {})
        accounts_raw = query_response.get("Account", [])

        accounts = []
        for acct in accounts_raw:
            accounts.append({
                "id": acct.get("Id"),
                "name": acct.get("Name"),
                "full_name": acct.get("FullyQualifiedName"),
                "type": acct.get("AccountType"),
                "sub_type": acct.get("AccountSubType"),
                "balance": float(acct.get("CurrentBalance", 0)),
                "active": acct.get("Active", True),
                "currency": acct.get("CurrencyRef", {}).get("value"),
            })

        return {
            "success": True,
            "accounts": accounts,
            "count": len(accounts),
        }

    async def get_customers(self, max_results: int = 100) -> Dict[str, Any]:
        """Get customers list."""
        query = f"SELECT * FROM Customer MAXRESULTS {max_results}"

        response = await self._request("GET", "query", params={"query": query})

        if isinstance(response, dict) and "error" in response:
            return response

        query_response = response.get("QueryResponse", {})
        customers_raw = query_response.get("Customer", [])

        customers = []
        for cust in customers_raw:
            customers.append({
                "id": cust.get("Id"),
                "name": cust.get("DisplayName"),
                "company": cust.get("CompanyName"),
                "email": cust.get("PrimaryEmailAddr", {}).get("Address") if isinstance(cust.get("PrimaryEmailAddr"), dict) else None,
                "phone": cust.get("PrimaryPhone", {}).get("FreeFormNumber") if isinstance(cust.get("PrimaryPhone"), dict) else None,
                "balance": float(cust.get("Balance", 0)),
                "active": cust.get("Active", True),
            })

        return {
            "success": True,
            "customers": customers,
            "count": len(customers),
        }

    async def query_entity(
        self, entity: str, where_clause: Optional[str] = None, max_results: int = 100
    ) -> Dict[str, Any]:
        """Run a generic QBO query."""
        allowed_entities = [
            "Invoice", "Customer", "Vendor", "Account", "Bill",
            "Payment", "Purchase", "Estimate", "CreditMemo",
            "JournalEntry", "Item", "TaxCode", "Department",
            "Employee", "Transfer",
        ]

        if entity not in allowed_entities:
            return {
                "success": False,
                "error": f"Entity '{entity}' not supported. Allowed: {', '.join(allowed_entities)}",
            }

        query = f"SELECT * FROM {entity}"
        if where_clause:
            query += f" WHERE {where_clause}"
        query += f" MAXRESULTS {max_results}"

        response = await self._request("GET", "query", params={"query": query})

        if isinstance(response, dict) and "error" in response:
            return response

        query_response = response.get("QueryResponse", {})
        entities = query_response.get(entity, [])

        return {
            "success": True,
            "entity": entity,
            "results": entities,
            "count": len(entities),
        }

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test a QuickBooks connection by fetching company info."""
        try:
            self._configure_from_connection(config)

            if not self.access_token or not self.realm_id:
                return {
                    "success": False,
                    "error": "QuickBooks access_token and realm_id are required",
                }

            result = await self.get_company_info()

            if result.get("success"):
                return {
                    "success": True,
                    "message": "QuickBooks connection test successful",
                    "data": {
                        "company_name": result["company"]["name"],
                        "country": result["company"]["country"],
                    },
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to fetch company info"),
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"QuickBooks connection test failed: {str(e)}",
            }

    async def handle_operation(
        self,
        operation: str,
        config: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Handle QuickBooks operations from the workflow tool executor.
        This is the main entry point called by tool_executor.py.
        """
        try:
            # Configure from connection
            if config:
                self._configure_from_connection(config)

            if not self.access_token or not self.realm_id:
                return {
                    "success": False,
                    "error": "QuickBooks connection not configured. Please connect QuickBooks first.",
                }

            if operation == "get_company_info":
                return await self.get_company_info()

            elif operation == "get_invoices":
                return await self.get_invoices(
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                    status=kwargs.get("status"),
                    max_results=kwargs.get("max_results", 100),
                )

            elif operation == "create_invoice":
                customer_id = kwargs.get("customer_id")
                line_items = kwargs.get("line_items", [])
                if not customer_id:
                    return {"success": False, "error": "customer_id is required"}
                if not line_items:
                    return {"success": False, "error": "line_items are required"}
                return await self.create_invoice(
                    customer_id=customer_id,
                    line_items=line_items,
                    due_date=kwargs.get("due_date"),
                    email=kwargs.get("email"),
                )

            elif operation == "get_profit_loss":
                return await self.get_profit_and_loss(
                    start_date=kwargs.get("start_date"),
                    end_date=kwargs.get("end_date"),
                )

            elif operation == "get_balance_sheet":
                return await self.get_balance_sheet(
                    date=kwargs.get("date"),
                )

            elif operation == "get_accounts":
                return await self.get_accounts(
                    account_type=kwargs.get("account_type"),
                    max_results=kwargs.get("max_results", 100),
                )

            elif operation == "get_customers":
                return await self.get_customers(
                    max_results=kwargs.get("max_results", 100),
                )

            elif operation == "query":
                entity = kwargs.get("entity")
                if not entity:
                    return {"success": False, "error": "entity is required"}
                return await self.query_entity(
                    entity=entity,
                    where_clause=kwargs.get("where_clause"),
                    max_results=kwargs.get("max_results", 100),
                )

            else:
                return {
                    "success": False,
                    "error": f"Operation '{operation}' not supported. Available: get_company_info, get_invoices, create_invoice, get_profit_loss, get_balance_sheet, get_accounts, get_customers, query",
                }

        except Exception as e:
            logger.error(f"QuickBooks operation error: {str(e)}", exc_info=True)
            return {"success": False, "error": f"QuickBooks error: {str(e)}"}


# Global instance
quickbooks_service = QuickBooksService()
