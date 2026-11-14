"""Scripted multi-turn commerce journeys. The model is a fixture, not OpenAI."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import select

from src.models import CommerceOrder, MpesaAgentConfig
from src.services.cache_service import cache_service
from src.services.catalog_search_service import CatalogSearchService
from src.services.conversation_context_manager import (
    ConversationSession,
    context_manager,
)
from src.services.conversational_agent_service import ConversationalAgentService
from src.services.daraja_service import DarajaService
from src.services.llm_service import LLMResponse
from src.services.order_tracking_service import OrderTrackingService, order_tracking_service
from src.services.openai_service import OpenAIEmbeddingService


class CommerceJourney:
    """One WhatsApp customer, an in-memory session, and a scripted model."""

    def __init__(self, db, user, products=None, phone="254711000701"):
        self.db = db
        self.user = user
        self.products = list(products or [])
        self.phone = phone
        self.session_key = f"ccm:whatsapp:{user.id}:{phone}"
        self.live_llm_calls = 0
        self.stk_calls = 0
        self.last_stk_amount = 0
        self.scripted_turns_used = 0
        self.session = ConversationSession(
            session_key=self.session_key,
            platform="whatsapp",
            owner_user_id=str(user.id),
            sender_id=phone,
            messages=[],
            metadata={"welcome_sent": True},
        )
        self.agent = None
        self._queue: list[dict] = []
        self._searches: list[tuple[str, list]] = []
        self._stk_amounts: list[int] = []
        self._stack = ExitStack()
        self._memory_cache: dict = {}

    async def __aenter__(self):
        for product in self.products:
            product.user_id = self.user.id
            self.db.add(product)
        self.db.add(
            MpesaAgentConfig(
                user_id=self.user.id,
                daraja_consumer_key="gate-key",
                daraja_consumer_secret="gate-secret",
                daraja_passkey="gate-passkey",
                daraja_shortcode="174379",
                webhook_secret=uuid.uuid4().hex,
                callback_url_override="https://example.test",
                daraja_environment="sandbox",
            )
        )
        await self.db.commit()
        for product in self.products:
            await self.db.refresh(product)

        self._install_guards()
        self.agent = ConversationalAgentService()
        self.agent._harness_enabled = False
        self.agent.llm_service.chat_completion = self._scripted_completion
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._stack.close()
        return False

    @property
    def rails_state(self) -> dict:
        raw = self.session.metadata.get("commerce_rails_state") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def search_hits(self, fragment: str) -> list:
        needle = (fragment or "").lower()
        hits = []
        for query, found in self._searches:
            if needle in (query or "").lower():
                hits.extend(found)
        return hits

    async def say(self, message: str, replies: list[dict]) -> dict:
        self._queue = list(replies)
        return await self.agent.execute(
            user_message=message,
            session_key=self.session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": True,
                "business_name": "Shop",
                "currency": "KES",
                "delivery_methods": ["delivery", "pickup"],
                "storage_provider": "none",
                "customer_name": "Asha",
            },
            user=self.user,
            db=self.db,
        )

    async def payment_callback(
        self,
        *,
        paid: bool,
        receipt: str = "",
        result_code: str = "",
    ) -> None:
        from src.services.order_stk_payment_service import finalize_order_stk_payment

        order_id = self.rails_state.get("order_id")
        if not order_id:
            raise AssertionError("payment callback has no rails order")
        amount = float(self.last_stk_amount or 0)
        await finalize_order_stk_payment(
            db=self.db,
            owner_user_id=str(self.user.id),
            order_id=order_id,
            whatsapp_sender=self.phone,
            mpesa_phone=self.phone,
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=paid,
            mpesa_receipt=receipt,
            amount_paid=amount,
            currency="KES",
            result_code=result_code or ("0" if paid else "1032"),
            result_desc="Success" if paid else "Request cancelled by user",
            checkout_request_id=f"chk-{self.stk_calls}-{int(paid)}-{receipt or result_code}",
            merchant_request_id=f"mr-{self.stk_calls}",
            session_key=self.session_key,
        )

    def allow_payment_retry(self) -> None:
        order_id = self.rails_state.get("order_id")
        if not order_id:
            return
        key = order_tracking_service._tracking_key(str(self.user.id), order_id)
        registry = cache_service.get(key) or {}
        registry["last_stk_at"] = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        cache_service.set(key, registry)

    async def order(self) -> CommerceOrder:
        order_id = self.rails_state.get("order_id")
        result = await self.db.execute(
            select(CommerceOrder).where(
                CommerceOrder.user_id == self.user.id,
                CommerceOrder.external_order_id == order_id,
            )
        )
        return result.scalar_one()

    async def _scripted_completion(self, messages, tools=None, **kwargs):
        system = ""
        if messages and isinstance(messages[0], dict):
            system = str(messages[0].get("content") or "")
        if "language detector" in system.lower():
            return LLMResponse(content="en")
        if not self._queue:
            return LLMResponse(content="Okay.")
        step = self._queue.pop(0)
        self.scripted_turns_used += 1
        calls = []
        for tool in step.get("tools") or []:
            calls.append(
                {
                    "name": tool["name"],
                    "arguments": dict(tool.get("arguments") or {}),
                }
            )
        return LLMResponse(
            content=step.get("content") or "",
            tools_called=calls or None,
        )

    def _install_guards(self) -> None:
        journey = self

        def cache_get(key):
            return journey._memory_cache.get(key)

        def cache_set(key, value, expire_seconds=3600):
            journey._memory_cache[key] = value
            return True

        def cache_delete(key):
            journey._memory_cache.pop(key, None)
            return True

        async def fake_get(key):
            if key == journey.session.session_key:
                return journey.session
            return None

        async def fake_save(session):
            return None

        async def fake_update(key, updates):
            if key == journey.session.session_key and isinstance(updates, dict):
                journey.session.metadata.update(updates)

        async def no_db(session):
            return None

        async def refuse_chat(self, *args, **kwargs):
            journey.live_llm_calls += 1
            raise AssertionError("commerce rails gate called a live chat model")

        async def refuse_embedding(self, *args, **kwargs):
            journey.live_llm_calls += 1
            return {"success": False, "error": "commerce rails gate blocks live embeddings"}

        async def fake_stk(self, **kwargs):
            journey.stk_calls += 1
            try:
                amount = int(float(kwargs.get("amount") or 0))
            except (TypeError, ValueError):
                amount = 0
            journey._stk_amounts.append(amount)
            journey.last_stk_amount = amount
            return {
                "success": True,
                "checkout_request_id": f"chk-{journey.stk_calls}",
                "merchant_request_id": f"mr-{journey.stk_calls}",
            }

        def no_poll(**kwargs):
            return None

        async def no_payout(**kwargs):
            journey.live_llm_calls += 1
            raise AssertionError("commerce rails gate called a live B2C payout")

        async def no_pdf(self, **kwargs):
            return None

        original_search = CatalogSearchService.search_products

        async def recording_search(self, db, user_id, query, **kwargs):
            hits = await original_search(self, db, user_id, query, **kwargs)
            journey._searches.append((query, list(hits or [])))
            return hits

        stack = self._stack
        stack.enter_context(patch.object(cache_service, "get", cache_get))
        stack.enter_context(patch.object(cache_service, "set", cache_set))
        stack.enter_context(patch.object(cache_service, "delete", cache_delete))
        stack.enter_context(patch.object(context_manager, "get_session_by_key", fake_get))
        stack.enter_context(patch.object(context_manager, "save_session", fake_save))
        stack.enter_context(
            patch.object(context_manager, "update_session_metadata", fake_update)
        )
        stack.enter_context(patch.object(context_manager, "_save_to_db", no_db))
        stack.enter_context(patch.object(context_manager, "_save_to_redis", lambda session: None))
        stack.enter_context(
            patch(
                "src.services.llm_service.OpenAIProvider.chat_completion",
                refuse_chat,
            )
        )
        stack.enter_context(
            patch.object(OpenAIEmbeddingService, "openai_create_embedding", refuse_embedding)
        )
        stack.enter_context(patch.object(DarajaService, "stk_push", fake_stk))
        stack.enter_context(
            patch(
                "src.services.order_stk_payment_service.schedule_stk_payment_poll",
                no_poll,
            )
        )
        stack.enter_context(
            patch(
                "src.services.commerce_refund_service.payout_credentials_configured",
                lambda: False,
            )
        )
        stack.enter_context(
            patch("src.services.commerce_refund_service.send_b2c_payout", no_payout)
        )
        stack.enter_context(
            patch.object(OrderTrackingService, "_generate_receipt_pdf_bytes", no_pdf)
        )
        stack.enter_context(patch.object(CatalogSearchService, "search_products", recording_search))
