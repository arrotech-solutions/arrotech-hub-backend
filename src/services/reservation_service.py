"""
Reservation Service for Arrotech Hub.

Stateless processing tools for restaurant table reservations (bookings).
No database models — reservations are persisted to the tenant's connected
storage (Google Sheets / Airtable) and the business is notified to confirm.

A reservation is intentionally cart-less: it captures a date, time, party size,
and the customer's name/phone. Availability is NOT checked automatically — the
business confirms or declines the request.
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Reservation lifecycle statuses.
RESERVATION_STATUSES = ["requested", "confirmed", "declined", "cancelled", "seated", "no_show"]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _coerce_party_size(value: Any) -> Optional[int]:
    """Extract a positive integer party size from free text or a number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        size = int(value)
        return size if size > 0 else None
    m = re.search(r"\d{1,3}", str(value))
    if not m:
        return None
    size = int(m.group(0))
    return size if size > 0 else None


class ReservationService:
    """Stateless reservation processing tools for the ordering agent."""

    async def create_reservation(
        self,
        customer_name: str = "",
        customer_phone: str = "",
        reservation_date: str = "",
        reservation_time: str = "",
        party_size: Any = None,
        notes: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Build a structured reservation record ready for storage."""
        customer_name = _clean(customer_name)
        customer_phone = _clean(customer_phone)
        reservation_date = _clean(reservation_date)
        reservation_time = _clean(reservation_time)
        notes = _clean(notes)
        size = _coerce_party_size(party_size)

        missing = []
        if not customer_name:
            missing.append("name")
        if not customer_phone:
            missing.append("phone")
        if not reservation_date:
            missing.append("date")
        if not reservation_time:
            missing.append("time")
        if not size:
            missing.append("party size")
        if missing:
            return {
                "success": False,
                "error": f"Missing reservation details: {', '.join(missing)}",
                "missing": missing,
            }

        now = datetime.now()
        reservation_id = f"RES-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        reservation = {
            "reservation_id": reservation_id,
            "status": "requested",
            "customer": {"name": customer_name, "phone": customer_phone},
            "reservation_date": reservation_date,
            "reservation_time": reservation_time,
            "party_size": size,
            "notes": notes,
            "created_at": now.isoformat(),
        }

        return {
            "success": True,
            "reservation": reservation,
            "reservation_id": reservation_id,
            "message": (
                f"Reservation {reservation_id} requested for {customer_name} — "
                f"{size} guest(s) on {reservation_date} at {reservation_time}."
            ),
        }

    @staticmethod
    def format_reservation_confirmation(
        *,
        customer_name: str,
        customer_phone: str,
        reservation_date: str,
        reservation_time: str,
        party_size: Any,
        business_name: str = "",
        notes: str = "",
        lang: str = "en",
    ) -> str:
        """Deterministic reservation summary asking the customer to reply YES."""
        size = _coerce_party_size(party_size) or party_size
        if (lang or "en").lower().startswith("sw"):
            body = (
                f"🍽️ *Uhakiki wa nafasi ya meza:*\n"
                f"👤 Jina: {customer_name}\n"
                f"📞 Simu: {customer_phone}\n"
                f"📅 Tarehe: {reservation_date}\n"
                f"🕐 Saa: {reservation_time}\n"
                f"👥 Watu: {size}\n"
            )
            if notes:
                body += f"📝 Maelezo: {notes}\n"
            body += "\nJibu *NDIO* kuomba nafasi hii. Tutakuthibitishia mara tu tutakapokubali."
            return body

        body = (
            f"🍽️ *Reservation summary:*\n"
            f"👤 Name: {customer_name}\n"
            f"📞 Phone: {customer_phone}\n"
            f"📅 Date: {reservation_date}\n"
            f"🕐 Time: {reservation_time}\n"
            f"👥 Party size: {size}\n"
        )
        if notes:
            body += f"📝 Notes: {notes}\n"
        body += "\nReply *YES* to request this booking. We'll confirm once the restaurant approves it."
        return body

    @staticmethod
    def format_reservation_business_notification(
        reservation: Dict[str, Any],
        business_name: str = "",
        lang: str = "en",
    ) -> str:
        """Business-facing alert framed as a request to confirm or decline."""
        res = reservation.get("reservation", reservation)
        customer = res.get("customer", {}) or {}
        notification = (
            f"🔔 *NEW RESERVATION REQUEST — {business_name}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Ref: {res.get('reservation_id', 'N/A')}\n"
            f"👤 Customer: {customer.get('name', 'Unknown')}\n"
            f"📱 Phone: {customer.get('phone', 'N/A')}\n"
            f"📅 Date: {res.get('reservation_date', 'N/A')}\n"
            f"🕐 Time: {res.get('reservation_time', 'N/A')}\n"
            f"👥 Party size: {res.get('party_size', 'N/A')}\n"
        )
        if res.get("notes"):
            notification += f"📝 Notes: {res.get('notes')}\n"
        notification += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"Please *confirm* or *decline* this booking with the customer.\n"
            f"⏰ {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}"
        )
        return notification


reservation_service = ReservationService()
