"""
Invoice Service for handling invoice operations.
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Invoice, InvoiceStatus, User

logger = logging.getLogger(__name__)

class InvoiceService:
    """Service for managing invoices."""

    async def create_invoice(
        self,
        user_id: int,
        invoice_data: Dict[str, Any],
        db: AsyncSession
    ) -> Invoice:
        """Create a new invoice."""
        # Check if invoice with same number exists for user
        stmt = select(Invoice).where(
            and_(
                Invoice.user_id == user_id,
                Invoice.invoice_number == invoice_data["invoice_number"]
            )
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError(f"Invoice {invoice_data['invoice_number']} already exists")

        invoice = Invoice(
            user_id=user_id,
            invoice_number=invoice_data["invoice_number"],
            amount=Decimal(str(invoice_data["amount"])),
            due_date=invoice_data.get("due_date"),
            status=invoice_data.get("status", InvoiceStatus.SENT),
            customer_name=invoice_data.get("customer_name"),
            customer_email=invoice_data.get("customer_email"),
            customer_phone=invoice_data.get("customer_phone"),
            reference=invoice_data.get("reference"),
            description=invoice_data.get("description"),
            items=invoice_data.get("items", []),
            metadata_=invoice_data.get("metadata", {})
        )

        db.add(invoice)
        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def get_invoice(
        self,
        invoice_id: int,
        user_id: int,
        db: AsyncSession
    ) -> Optional[Invoice]:
        """Get invoice by ID."""
        stmt = select(Invoice).where(
            and_(
                Invoice.id == invoice_id,
                Invoice.user_id == user_id
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_invoice_by_number(
        self,
        invoice_number: str,
        user_id: int,
        db: AsyncSession
    ) -> Optional[Invoice]:
        """Get invoice by invoice number."""
        stmt = select(Invoice).where(
            and_(
                Invoice.invoice_number == invoice_number,
                Invoice.user_id == user_id
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_invoices(
        self,
        user_id: int,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None
    ) -> List[Invoice]:
        """Get user invoices."""
        query = select(Invoice).where(Invoice.user_id == user_id)
        
        if status:
            query = query.where(Invoice.status == status)
            
        query = query.order_by(Invoice.created_at.desc()).offset(skip).limit(limit)
        
        result = await db.execute(query)
        return list(result.scalars().all())

    async def update_invoice(
        self,
        invoice_id: int,
        user_id: int,
        updates: Dict[str, Any],
        db: AsyncSession
    ) -> Optional[Invoice]:
        """Update invoice."""
        invoice = await self.get_invoice(invoice_id, user_id, db)
        if not invoice:
            return None

        for field, value in updates.items():
            if hasattr(invoice, field):
                setattr(invoice, field, value)
        
        invoice.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(invoice)
        return invoice

    async def delete_invoice(
        self,
        invoice_id: int,
        user_id: int,
        db: AsyncSession
    ) -> bool:
        """Delete invoice."""
        invoice = await self.get_invoice(invoice_id, user_id, db)
        if not invoice:
            return False

        await db.delete(invoice)
        await db.commit()
        return True
