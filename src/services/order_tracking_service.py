"""
Automated order tracking notifications for WhatsApp ordering agents.

Sends customer-facing updates: order confirmation, digital receipts,
and status/shipping alerts when order status changes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Connection, ConnectionStatus, User
from .cache_service import cache_service
from .order_service import ORDER_STATUSES, OrderService

logger = logging.getLogger(__name__)

TRACKING_TTL_SECONDS = 60 * 60 * 24 * 45  # 45 days

# Statuses that trigger a proactive customer WhatsApp alert
NOTIFY_STATUSES = {
    "confirmed",
    "preparing",
    "ready",
    "shipped",
    "out_for_delivery",
    "delivered",
    "cancelled",
    "refunded",
}

STATUS_CUSTOMER_COPY = {
    "pending": ("🕐", "Order received", "We've received your order and will confirm it shortly."),
    "confirmed": ("✅", "Order confirmed", "Your order is confirmed! We're getting it ready."),
    "preparing": ("👨‍🍳", "Being prepared", "Our team is preparing your order now."),
    "ready": ("📦", "Ready", "Your order is ready! We'll dispatch it soon."),
    "shipped": ("🚚", "Shipped", "Your order is on the way."),
    "out_for_delivery": ("🏍️", "Out for delivery", "Your order is out for delivery — almost there!"),
    "delivered": ("✅", "Delivered", "Your order has been delivered. Enjoy!"),
    "cancelled": ("❌", "Cancelled", "Your order has been cancelled."),
    "refunded": ("💰", "Refunded", "A refund has been processed for your order."),
}


class OrderTrackingService:
    """Customer notifications and order tracking registry."""

    def __init__(self):
        self.order_service = OrderService()

    def _tracking_key(self, owner_user_id: str, order_id: str) -> str:
        return f"wa_order_track:{owner_user_id}:{order_id}"

    def register_order(
        self,
        owner_user_id: str,
        order_id: str,
        customer_phone: str,
        order_snapshot: Dict[str, Any],
        business_name: str = "",
        business_phone: str = "",
        currency: str = "KES",
    ) -> None:
        """Store order → customer mapping for later status push notifications."""
        if not order_id or not customer_phone:
            return
        payload = {
            "order_id": order_id,
            "customer_phone": customer_phone,
            "business_name": business_name,
            "business_phone": business_phone,
            "currency": currency,
            "status": (order_snapshot.get("status") or "pending"),
            "order": order_snapshot,
            "registered_at": datetime.utcnow().isoformat(),
            "placement_notified": False,
        }
        cache_service.set(
            self._tracking_key(owner_user_id, order_id),
            payload,
            expire_seconds=TRACKING_TTL_SECONDS,
        )

    def get_registered_order(
        self, owner_user_id: str, order_id: str
    ) -> Optional[Dict[str, Any]]:
        return cache_service.get(self._tracking_key(owner_user_id, order_id))

    async def notify_order_placed(
        self,
        *,
        user: User,
        db: AsyncSession,
        customer_phone: str,
        order_data: Dict[str, Any],
        business_name: str,
        business_phone: str = "",
        currency: str = "KES",
    ) -> Dict[str, Any]:
        """
        Send confirmation + digital receipt when an order is created.
        """
        order = order_data.get("order") if isinstance(order_data.get("order"), dict) else order_data
        order_id = order.get("order_id") or order_data.get("order_id", "")
        if not order_id or not customer_phone:
            return {"success": False, "error": "order_id and customer_phone required"}

        existing = self.get_registered_order(str(user.id), order_id) or {}
        if existing.get("placement_notified"):
            return {
                "success": True,
                "order_id": order_id,
                "skipped": True,
                "reason": "placement_already_notified",
            }

        self.register_order(
            str(user.id),
            order_id,
            customer_phone,
            order,
            business_name=business_name,
            business_phone=business_phone,
            currency=currency,
        )

        receipt_result = await self.order_service.format_order_receipt(
            order_data=order,
            format_type="whatsapp",
            business_name=business_name,
            business_phone=business_phone,
            currency=currency,
        )
        receipt_text = receipt_result.get("message", "") if receipt_result.get("success") else ""

        confirmation = (
            f"✅ *Order received!*\n\n"
            f"Thanks for ordering from *{business_name}*. "
            f"Your order *{order_id}* is in our queue.\n\n"
            f"We'll message you here when the status changes. 🔔"
        )

        sent = []
        wa_config = await self._get_whatsapp_config(user, db)
        if not wa_config:
            return {"success": False, "error": "WhatsApp not connected"}

        from .whatsapp_service import WhatsAppService

        wa = WhatsAppService()
        r1 = await wa.send_message(customer_phone, confirmation, config=wa_config)
        sent.append("confirmation" if r1.get("success") else "confirmation_failed")

        if receipt_text:
            r2 = await wa.send_message(customer_phone, receipt_text, config=wa_config)
            sent.append("receipt" if r2.get("success") else "receipt_failed")

        maps_link = self._delivery_maps_link(order)
        if maps_link and order.get("delivery_method") == "delivery":
            r3 = await wa.send_message(
                customer_phone,
                f"📍 *Delivery location saved*\n{maps_link}",
                config=wa_config,
            )
            sent.append("location_link" if r3.get("success") else "location_link_failed")

        # Send payment options
        payment_buttons = [
            {"id": f"pay_mpesa:{order_id}", "title": "Pay with Mpesa"}
        ]
        r4 = await wa.send_quick_reply_buttons(
            to_number=customer_phone,
            body_text="How would you like to pay for your order?",
            buttons=payment_buttons,
            config=wa_config
        )
        sent.append("payment_prompt" if r4.get("success") else "payment_prompt_failed")

        registry = self.get_registered_order(str(user.id), order_id) or {}
        registry["placement_notified"] = True
        registry["status"] = registry.get("status") or "pending"
        cache_service.set(
            self._tracking_key(str(user.id), order_id),
            registry,
            expire_seconds=TRACKING_TTL_SECONDS,
        )

        return {"success": True, "order_id": order_id, "sent": sent}

    async def notify_status_change(
        self,
        *,
        user: User,
        db: AsyncSession,
        order_id: str,
        new_status: str,
        customer_phone: str = "",
        business_name: str = "",
        currency: str = "KES",
        notes: str = "",
        previous_status: str = "",
    ) -> Dict[str, Any]:
        """Send a shipping/status alert to the customer."""
        new_status = (new_status or "").lower().replace(" ", "_")
        if new_status not in ORDER_STATUSES:
            return {"success": False, "error": f"Invalid status: {new_status}"}

        registry = self.get_registered_order(str(user.id), order_id) or {}
        phone = customer_phone or registry.get("customer_phone", "")
        if not phone:
            return {"success": False, "error": "Customer phone not found for this order"}

        business_name = business_name or registry.get("business_name", "Our Business")
        currency = currency or registry.get("currency", "KES")
        order = dict(registry.get("order") or {})
        order["status"] = new_status
        order["order_id"] = order_id

        prev = (previous_status or registry.get("status") or "pending").lower().replace(" ", "_")
        if prev == new_status:
            return {"success": True, "skipped": True, "reason": "status_unchanged"}

        if new_status == "confirmed" and registry.get("placement_notified"):
            return {
                "success": True,
                "skipped": True,
                "reason": "already_notified_on_placement",
            }

        if new_status not in NOTIFY_STATUSES:
            return {"success": True, "skipped": True, "reason": "status_not_notifiable"}

        icon, title, body = STATUS_CUSTOMER_COPY.get(
            new_status, ("📋", new_status.replace("_", " ").title(), "")
        )
        items_summary = self._summarize_items(order.get("items") or [])
        total = order.get("subtotal", 0)

        message = (
            f"{icon} *{title}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏪 {business_name}\n"
            f"📋 Order: *{order_id}*\n"
            f"📦 {body}\n"
        )
        if items_summary:
            message += f"\n🛒 {items_summary}\n"
        if total:
            message += f"💰 Total: *{currency} {float(total):,.0f}*\n"
        if notes:
            message += f"\n📝 {notes}\n"
        if new_status in ("shipped", "out_for_delivery", "delivered"):
            maps_link = self._delivery_maps_link(order)
            if maps_link:
                message += f"\n📍 Track delivery area:\n{maps_link}\n"
        message += f"\n_Updated {datetime.utcnow().strftime('%d %b, %H:%M')}_"

        wa_config = await self._get_whatsapp_config(user, db)
        if not wa_config:
            return {"success": False, "error": "WhatsApp not connected"}

        from .whatsapp_service import WhatsAppService

        wa = WhatsAppService()
        result = await wa.send_message(phone, message, config=wa_config)

        if result.get("success"):
            registry["status"] = new_status
            registry["order"] = order
            cache_service.set(
                self._tracking_key(str(user.id), order_id),
                registry,
                expire_seconds=TRACKING_TTL_SECONDS,
            )

        return {
            "success": result.get("success", False),
            "order_id": order_id,
            "new_status": new_status,
            "customer_phone": phone,
            "error": result.get("error"),
        }

    async def notify_payment_received(
        self,
        *,
        user: User,
        db: AsyncSession,
        order_id: str,
        mpesa_receipt: str = "",
        amount_paid: float = 0.0,
        currency: str = "KES",
    ) -> Dict[str, Any]:
        """
        Generate a downloadable PDF receipt on confirmed payment and send it
        to BOTH the customer and the business as a WhatsApp document.
        Idempotent per order (guarded by `payment_notified`).
        """
        registry = self.get_registered_order(str(user.id), order_id) or {}
        if registry.get("payment_notified"):
            return {"success": True, "order_id": order_id, "skipped": True, "reason": "already_notified"}

        order = dict(registry.get("order") or {})
        order["order_id"] = order_id
        customer_phone = registry.get("customer_phone") or order.get("customer_phone", "")
        business_name = registry.get("business_name", "Our Business")
        business_phone = registry.get("business_phone", "")
        currency = currency or registry.get("currency", "KES")
        if not amount_paid:
            amount_paid = float(order.get("subtotal") or order.get("grand_total") or 0)

        html = self._build_receipt_html(
            order=order,
            order_id=order_id,
            business_name=business_name,
            business_phone=business_phone,
            mpesa_receipt=mpesa_receipt,
            amount_paid=amount_paid,
            currency=currency,
        )

        # Generate the PDF (base64) then decode to bytes for upload
        import base64
        pdf_bytes = None
        try:
            from .file_management_service import FileManagementService
            fms = FileManagementService()
            pdf_res = await fms.generate_pdf_from_html(html, filename=f"receipt_{order_id}.pdf")
            if pdf_res.get("success") and pdf_res.get("content"):
                pdf_bytes = base64.b64decode(pdf_res["content"])
        except Exception as pdf_err:
            logger.warning(f"[ORDER_TRACK] Receipt PDF generation failed: {pdf_err}")

        wa_config = await self._get_whatsapp_config(user, db)
        if not wa_config:
            return {"success": False, "error": "WhatsApp not connected"}

        from .whatsapp_service import WhatsAppService

        wa = WhatsAppService()
        filename = f"Receipt-{order_id}.pdf"
        sent: List[str] = []

        if pdf_bytes:
            if customer_phone:
                r = await wa.upload_and_send_document(
                    to_number=customer_phone,
                    file_bytes=pdf_bytes,
                    filename=filename,
                    caption=f"🧾 Thank you! Here's your receipt for order {order_id}.",
                    config=wa_config,
                )
                sent.append("customer_receipt" if r.get("success") else "customer_receipt_failed")
            if business_phone:
                r = await wa.upload_and_send_document(
                    to_number=business_phone,
                    file_bytes=pdf_bytes,
                    filename=filename,
                    caption=f"💰 Payment received for order {order_id} ({currency} {amount_paid:,.0f}).",
                    config=wa_config,
                )
                sent.append("business_receipt" if r.get("success") else "business_receipt_failed")
        else:
            # PDF unavailable — fall back to a text receipt so the customer is still served
            text_receipt = await self.order_service.format_order_receipt(
                order_data=order,
                format_type="whatsapp",
                business_name=business_name,
                business_phone=business_phone,
                currency=currency,
            )
            body = text_receipt.get("message", "") if text_receipt.get("success") else ""
            paid_line = f"\n✅ *PAID* via M-Pesa{(' · ' + mpesa_receipt) if mpesa_receipt else ''}"
            if customer_phone and body:
                await wa.send_message(customer_phone, body + paid_line, config=wa_config)
                sent.append("customer_text_receipt")
            if business_phone and body:
                await wa.send_message(business_phone, body + paid_line, config=wa_config)
                sent.append("business_text_receipt")

        registry["status"] = "paid"
        registry["payment_notified"] = True
        registry["mpesa_receipt"] = mpesa_receipt
        registry["amount_paid"] = amount_paid
        cache_service.set(
            self._tracking_key(str(user.id), order_id),
            registry,
            expire_seconds=TRACKING_TTL_SECONDS,
        )

        return {"success": True, "order_id": order_id, "sent": sent}

    def _build_receipt_html(
        self,
        *,
        order: Dict[str, Any],
        order_id: str,
        business_name: str,
        business_phone: str,
        mpesa_receipt: str,
        amount_paid: float,
        currency: str,
    ) -> str:
        """Build a clean, printable HTML receipt for PDF rendering."""
        from html import escape

        items = order.get("items") or []
        rows = ""
        for item in items:
            name = escape(str(item.get("name", "Item")))
            qty = item.get("quantity", 1)
            unit = float(item.get("unit_price", 0) or item.get("price", 0) or 0)
            line_total = float(item.get("total", 0) or (float(qty) * unit))
            rows += (
                f"<tr><td>{name}</td><td style='text-align:center'>{qty}</td>"
                f"<td style='text-align:right'>{currency} {unit:,.0f}</td>"
                f"<td style='text-align:right'>{currency} {line_total:,.0f}</td></tr>"
            )

        customer_name = escape(str(order.get("customer_name", "")))
        customer_phone = escape(str(order.get("customer_phone", "")))
        delivery_method = escape(str(order.get("delivery_method", "")))
        delivery_address = escape(str(order.get("delivery_address", "")))
        paid_at = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

        return f"""
        <!DOCTYPE html>
        <html><head><meta charset="utf-8"><style>
            body {{ font-family: Arial, Helvetica, sans-serif; color: #1a1a1a; margin: 32px; }}
            .header {{ text-align: center; border-bottom: 2px solid #16a34a; padding-bottom: 12px; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .paid {{ display: inline-block; background: #16a34a; color: #fff;
                     padding: 4px 12px; border-radius: 6px; font-weight: bold; margin-top: 8px; }}
            .meta {{ margin: 16px 0; font-size: 13px; line-height: 1.6; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
            th, td {{ padding: 8px; border-bottom: 1px solid #e5e5e5; }}
            th {{ text-align: left; background: #f5f5f5; }}
            .total {{ text-align: right; font-size: 16px; font-weight: bold; margin-top: 14px; }}
            .footer {{ margin-top: 24px; text-align: center; font-size: 12px; color: #666; }}
        </style></head><body>
            <div class="header">
                <h1>{escape(business_name)}</h1>
                <div class="paid">PAID</div>
            </div>
            <div class="meta">
                <strong>Receipt</strong><br/>
                Order: <strong>{escape(order_id)}</strong><br/>
                Date: {paid_at}<br/>
                {f"M-Pesa Receipt: <strong>{escape(str(mpesa_receipt))}</strong><br/>" if mpesa_receipt else ""}
                {f"Customer: {customer_name}<br/>" if customer_name else ""}
                {f"Phone: {customer_phone}<br/>" if customer_phone else ""}
                {f"Delivery: {delivery_method}<br/>" if delivery_method else ""}
                {f"Address: {delivery_address}<br/>" if delivery_address else ""}
                {f"Business contact: {escape(str(business_phone))}<br/>" if business_phone else ""}
            </div>
            <table>
                <thead><tr><th>Item</th><th style="text-align:center">Qty</th>
                    <th style="text-align:right">Unit</th><th style="text-align:right">Total</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
            <div class="total">Total Paid: {currency} {amount_paid:,.0f}</div>
            <div class="footer">Thank you for your business! 🙏<br/>This is a computer-generated receipt.</div>
        </body></html>
        """

    @staticmethod
    def _summarize_items(items: List[Dict[str, Any]]) -> str:
        parts = []
        for item in items[:4]:
            name = item.get("name", "Item")
            qty = item.get("quantity", 1)
            parts.append(f"{name} ×{qty}")
        if len(items) > 4:
            parts.append(f"+{len(items) - 4} more")
        return ", ".join(parts)

    @staticmethod
    def _delivery_maps_link(order: Dict[str, Any]) -> str:
        loc = order.get("delivery_location") or {}
        lat = loc.get("latitude") or order.get("delivery_latitude")
        lng = loc.get("longitude") or order.get("delivery_longitude")
        if lat is not None and lng is not None:
            return f"https://maps.google.com/?q={lat},{lng}"
        address = order.get("delivery_address") or loc.get("formatted_address")
        if address:
            from urllib.parse import quote_plus
            return f"https://maps.google.com/?q={quote_plus(address)}"
        return ""

    async def _get_whatsapp_config(
        self, user: User, db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            select(Connection).where(
                Connection.user_id == user.id,
                Connection.platform == "whatsapp",
                Connection.status == ConnectionStatus.ACTIVE,
            )
        )
        connection = result.scalar_one_or_none()
        if not connection or not connection.config:
            return None
        cfg = connection.config
        if not cfg.get("access_token") or not cfg.get("phone_number_id"):
            return None
        return {
            "access_token": cfg.get("access_token"),
            "phone_number_id": cfg.get("phone_number_id"),
        }


order_tracking_service = OrderTrackingService()
