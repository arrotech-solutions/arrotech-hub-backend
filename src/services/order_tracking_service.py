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
