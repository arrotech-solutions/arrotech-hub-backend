"""
HR Service
Handles leave management and policy search for regional businesses.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class HRService:
    """Service for HR operations."""

    async def get_leave_balance(self, user_id: uuid.UUID, employee_id: str) -> Dict[str, Any]:
        """Get leave balance for an employee."""
        # In production, this would query the leave_balances table
        # For now, return mock data to demonstrate functionality
        # Format balance string for workflow variables
        remaining = {
            "annual": 18,
            "sick": 7
        }
        balance_str = ", ".join([f"{k.capitalize()}: {v}" for k, v in remaining.items()])

        return {
            "employee_id": employee_id,
            "balance": balance_str,  # Added for workflow variable {{step_2.balance}}
            "leave_balances": {
                "annual": 21,
                "sick": 7,
                "maternity": 90,
                "paternity": 14,
                "compassionate": 5
            },
            "used_days": {
                "annual": 3,
                "sick": 0
            },
            "remaining_days": remaining
        }

    async def apply_leave(self, user_id: uuid.UUID, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply for leave."""
        employee_id = data.get("employee_id")
        leave_type = data.get("leave_type", "annual")
        days = data.get("days", 1)
        start_date = data.get("start_date")
        
        # Mock application logic
        return {
            "success": True,
            "request_id": f"LV-{datetime.now().strftime('%Y%H%M%S')}",
            "status": "pending_approval",
            "message": f"Leave application for {days} day(s) of {leave_type} leave submitted. Waiting for manager approval."
        }

    async def search_policies(self, query: str, language: str = "english") -> Dict[str, Any]:
        """Search company policies (Bilingual support)."""
        # Mock policy search results
        policies = [
            {
                "title": "Annual Leave Policy",
                "content": "Employees are entitled to 21 working days of annual leave per year after completion of 12 months of service.",
                "relevance": 0.95
            },
            {
                "title": "Sick Leave Policy",
                "content": "Employees are entitled to 7 days of full pay sick leave and 7 days of half pay sick leave per year.",
                "relevance": 0.85
            }
        ]
        
        if language.lower() == "swahili":
            return {
                "query": query,
                "policy_content": "Wafanyakazi wana haki ya siku 21 za kazi za likizo ya mwaka baada ya kukamilisha miezi 12 ya huduma.", # Added for workflow variable
                "results": [
                    {
                        "title": "Sera ya Likizo ya Mwaka",
                        "content": "Wafanyakazi wana haki ya siku 21 za kazi za likizo ya mwaka baada ya kukamilisha miezi 12 ya huduma.",
                        "relevance": 0.95
                    }
                ]
            }
        
        # Get content from first result or default message
        policy_content = policies[0]["content"] if policies else "No policy found matching your query."
            
        return {
            "query": query,
            "policy_content": policy_content, # Added for workflow variable {{step_1.policy_content}}
            "results": policies
        }

    async def get_pending_requests(self, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get pending leave requests for approval."""
        return [
            {
                "request_id": "LV-20240105001",
                "employee_name": "John Doe",
                "leave_type": "annual",
                "days": 3,
                "start_date": "2024-02-10",
                "reason": "Family vacation"
            }
        ]

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test HR Hub connection."""
        company_id = config.get("company_id")
        if not company_id:
            return {"success": False, "error": "company_id is required"}
        return {"success": True, "message": "Successfully connected to HR Hub"}

    async def handle_hr_operation(
        self,
        platform: str,
        operation: str,
        employee_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Handle HR operations for various platforms (WorkPay, SeamlessHR, etc.)."""
        
        platform_name = platform.replace("_", " ").title()
        
        if operation == "process_payroll":
            return {
                "success": True,
                "platform": platform,
                "period": "January 2024",
                "employees_processed": 15,
                "total_payout": 450000,
                "status": "Paid",
                "message": f"Payroll for January 2024 processed successfully via {platform_name}"
            }
        
        elif operation == "onboard_employee":
            name = kwargs.get("name", "New Employee")
            return {
                "success": True,
                "platform": platform,
                "employee_id": f"EMP-{datetime.now().strftime('%M%S')}",
                "status": "Active",
                "message": f"Employee {name} onboarded successfully to {platform_name}"
            }
            
        elif operation == "approve_leave":
            request_id = kwargs.get("request_id", "REQ-001")
            return {
                "success": True,
                "platform": platform,
                "request_id": request_id,
                "status": "Approved",
                "message": f"Leave request {request_id} approved on {platform_name}"
            }
            
        else:
            return {"success": False, "error": f"Operation {operation} not supported for {platform_name}"}
