"""Tests for WhatsApp location sharing and order tracking notifications."""

import pytest

from src.services.whatsapp_location_service import (
    LOCATION_AGENT_PREFIX,
    build_location_agent_message,
    normalize_whatsapp_location_payload,
    format_location_saved_reply,
)
from src.services.order_tracking_service import OrderTrackingService


class TestWhatsAppLocationService:
    def test_normalize_location_with_name_and_address(self):
        loc = {
            "latitude": -1.2921,
            "longitude": 36.8219,
            "name": "Home",
            "address": "Nairobi, Kenya",
        }
        out = normalize_whatsapp_location_payload(loc)
        assert out["latitude"] == pytest.approx(-1.2921)
        assert out["longitude"] == pytest.approx(36.8219)
        assert "Home" in out["delivery_address"]
        assert out["source"] == "whatsapp_location"
        assert "maps.google.com" in out["maps_url"]

    def test_normalize_invalid_returns_empty(self):
        assert normalize_whatsapp_location_payload({}) == {}
        assert normalize_whatsapp_location_payload({"latitude": "x"}) == {}

    def test_build_location_agent_message(self):
        loc = normalize_whatsapp_location_payload(
            {"latitude": 1.0, "longitude": 2.0, "name": "Shop"}
        )
        msg = build_location_agent_message(loc)
        assert msg.startswith(LOCATION_AGENT_PREFIX)
        assert "Shop" in msg or "1.0" in msg

    def test_format_location_saved_reply(self):
        loc = {"delivery_address": "123 Main St"}
        reply = format_location_saved_reply(loc, "Test Biz")
        assert "Delivery location received" in reply
        assert "123 Main St" in reply
        assert "Test Biz" in reply


class TestOrderTrackingService:
    def test_register_and_get_order(self, monkeypatch):
        store = {}

        def fake_set(key, value, expire_seconds=3600):
            store[key] = value
            return True

        def fake_get(key):
            return store.get(key)

        from src.services import order_tracking_service as ots_module

        monkeypatch.setattr(ots_module.cache_service, "set", fake_set)
        monkeypatch.setattr(ots_module.cache_service, "get", fake_get)

        svc = OrderTrackingService()
        svc.register_order(
            "owner-1",
            "ORD-99",
            "254700000000",
            {"status": "pending", "items": [{"name": "Beef", "quantity": 2}]},
            business_name="Grill Co",
            currency="KES",
        )
        reg = svc.get_registered_order("owner-1", "ORD-99")
        assert reg is not None
        assert reg["customer_phone"] == "254700000000"
        assert reg["order_id"] == "ORD-99"

    def test_delivery_maps_link_from_coordinates(self):
        link = OrderTrackingService._delivery_maps_link(
            {
                "delivery_location": {"latitude": -1.28, "longitude": 36.82},
                "delivery_method": "delivery",
            }
        )
        assert "maps.google.com" in link
        assert "-1.28" in link

    def test_delivery_maps_link_from_address(self):
        link = OrderTrackingService._delivery_maps_link(
            {"delivery_address": "Westlands, Nairobi"}
        )
        assert "maps.google.com" in link
        assert "Westlands" in link

    def test_summarize_items(self):
        text = OrderTrackingService._summarize_items(
            [
                {"name": "Ribeye", "quantity": 1},
                {"name": "Fries", "quantity": 2},
            ]
        )
        assert "Ribeye" in text
        assert "Fries" in text

    def test_skip_duplicate_confirmed_status_after_placement(self, monkeypatch):
        store = {
            "wa_order_track:owner:ORD-1": {
                "order_id": "ORD-1",
                "customer_phone": "254700",
                "status": "pending",
                "placement_notified": True,
                "order": {},
            }
        }

        def fake_get(key):
            return store.get(key)

        from src.services import order_tracking_service as ots_module

        monkeypatch.setattr(ots_module.cache_service, "get", fake_get)

        svc = OrderTrackingService()
        reg = svc.get_registered_order("owner", "ORD-1")
        assert reg.get("placement_notified") is True
