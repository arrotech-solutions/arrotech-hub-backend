"""
ERP Service (Connector)
Simulates integration with external ERP systems (SAP, QuickBooks, Xero).
Decouples internal matching from external reporting.
"""
import logging
from typing import Dict, Any, Optional
import asyncio
import random

logger = logging.getLogger(__name__)

class ERPService:
    """Service for connecting to ERP systems."""
    
    SUPPORTED_ERPS = ["sap", "quickbooks", "xero", "sage"]

    async def sync_invoice(self, invoice_id: int, invoice_number: str, status: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sync an invoice status update to the configured ERP.
        """
        erp_type = config.get("erp_type", "generic").lower()
        
        if erp_type not in self.SUPPORTED_ERPS:
            logger.warning(f"Unsupported ERP type: {erp_type}. Using generic mock.")
            
        logger.info(f"Syncing Invoice #{invoice_number} (ID: {invoice_id}) to {erp_type.upper()}... Status: {status}")
        
        # SIMULATION LATENCY
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # SIMULATE SUCCESS/FAILURE
        if random.random() < 0.05: # 5% chance of network error
            return {
                "success": False,
                "error": f"Connection timeout to {erp_type.upper()} API",
                "retryable": True
            }
            
        return {
            "success": True,
            "external_id": f"{erp_type}_{invoice_number}_123",
            "timestamp": "2026-01-01T12:00:00Z",
            "message": f"Invoice updated to {status} in {erp_type.upper()}"
        }

    async def create_suspense_entry(self, transaction: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post an unidentified payment to the 'Suspense Account' (General Ledger).
        """
        erp_type = config.get("erp_type", "generic").lower()
        logger.info(f"Posting Unidentified Transaction {transaction.get('transaction_id')} to {erp_type.upper()} Suspense Account")
        
        return {
            "success": True,
            "journal_entry_id": f"JE_{random.randint(1000,9999)}"
        }
