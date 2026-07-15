"""
WhatsApp shared-location → delivery address extraction for ordering agents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

LOCATION_AGENT_PREFIX = "CUSTOMER_SHARED_WHATSAPP_LOCATION"


def normalize_whatsapp_location_payload(loc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Meta WhatsApp location message object into a structured delivery location.

    WhatsApp location fields: latitude, longitude, name, address (optional)
    """
    if not loc:
        return {}

    try:
        lat = float(loc.get("latitude"))
        lng = float(loc.get("longitude"))
    except (TypeError, ValueError):
        return {}

    name = (loc.get("name") or "").strip()
    address = (loc.get("address") or "").strip()

    parts = []
    if name:
        parts.append(name)
    if address and address not in parts:
        parts.append(address)
    
    maps_url = f"https://maps.google.com/?q={lat},{lng}"

    # Only include readable parts in the address string
    delivery_address = " — ".join(parts) if parts else "WhatsApp Location Pin"

    return {
        "latitude": lat,
        "longitude": lng,
        "name": name,
        "address": address,
        "formatted_address": delivery_address,
        "delivery_address": delivery_address,
        "maps_url": maps_url,
        "source": "whatsapp_location",
    }


async def enrich_location_with_reverse_geocode(
    location: Dict[str, Any],
) -> Dict[str, Any]:
    """Optional reverse geocode when Google Maps API is configured."""
    if not location:
        return location
    lat = location.get("latitude")
    lng = location.get("longitude")
    if lat is None or lng is None:
        return location

    try:
        from ..config import settings
        from .maps_service import MapsService

        api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", None)
        if not api_key or api_key == "MOCK_KEY":
            return location

        maps = MapsService()
        geo = await maps.reverse_geocode(float(lat), float(lng))
        if geo.get("error"):
            return location

        formatted = (geo.get("formatted_address") or "").strip()
        if formatted:
            location["formatted_address"] = formatted
            location["delivery_address"] = formatted
            if location.get("name"):
                location["delivery_address"] = f"{location['name']} — {formatted}"
    except Exception as e:
        logger.warning(f"[WA_LOCATION] Reverse geocode failed: {e}")

    return location


def build_location_agent_message(location: Dict[str, Any]) -> str:
    """Natural-language message injected into the conversational agent."""
    addr = location.get("delivery_address") or location.get("formatted_address", "")
    maps_url = location.get("maps_url", "")
    return (
        f"{LOCATION_AGENT_PREFIX}: The customer shared their delivery location on WhatsApp.\n"
        f"Saved delivery address: {addr}\n"
        f"Maps: {maps_url}\n"
        "Use this address for delivery on their order. Confirm receipt briefly."
    )


def format_location_saved_reply(location: Dict[str, Any], business_name: str = "") -> str:
    """Customer-facing acknowledgment after sharing a location pin."""
    addr = location.get("delivery_address") or location.get("formatted_address", "")
    biz = business_name or "us"
    return (
        f"📍 *Delivery location received!*\n\n"
        f"We've saved this address for your order:\n_{addr}_\n\n"
        f"Reply with your name or tap *Checkout* when you're ready to complete your order with *{biz}*."
    )
