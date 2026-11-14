"""Mocked-LLM journeys. No live OpenAI. Marker: commerce_rails_gate."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models import CatalogProduct, CommerceComplaint, CommerceOrder, CommerceReturn
from src.services.commerce_policy import upsert_policy
from tests.commerce_rails_journey_harness import CommerceJourney

pytestmark = [pytest.mark.commerce_rails_gate, pytest.mark.asyncio]


def _product(name: str, price: str, sku: str, search_text: str) -> CatalogProduct:
    return CatalogProduct(
        name=name,
        price=Decimal(price),
        description=name,
        category="grocery",
        sku=sku,
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text=search_text,
    )


def _tools(*calls: tuple[str, dict], closing: str):
    steps = [
        {"content": "", "tools": [{"name": name, "arguments": arguments}]}
        for name, arguments in calls
    ]
    steps.append({"content": closing})
    return steps


async def test_browse_to_pay_uses_catalog_price_and_marks_paid(db_session, test_user):
    tea = _product("Tea", "100.00", "TEA", "tea chai")
    async with CommerceJourney(db_session, test_user, products=[tea]) as journey:
        searched = await journey.say(
            "Do you have tea",
            _tools(("search_products", {"query": "tea"}), closing="We have Tea."),
        )
        assert any(step["tool"] == "search_products" for step in searched["actions_taken"])
        assert any(hit["name"] == "Tea" for hit in journey.search_hits("tea"))

        await journey.say(
            "Add one tea please",
            _tools(
                (
                    "manage_cart",
                    {
                        "action": "add",
                        "product_name": "Tea",
                        "quantity": 1,
                        "unit_price": 1,
                    },
                ),
                closing="Added Tea.",
            ),
        )
        journey.session.metadata["commerce_phase"] = "awaiting_yes"
        placed = await journey.say(
            "Thanks, continue",
            _tools(
                (
                    "create_order",
                    {
                        "customer_name": "Asha",
                        "items": [{"name": "Tea", "quantity": 1, "unit_price": 1}],
                        "delivery_method": "pickup",
                    },
                ),
                closing="Order placed.",
            ),
        )
        assert placed["order_created"] is True
        assert placed["order_data"]["total"] == 100
        prompted = await journey.say(
            "Please send the M-Pesa prompt",
            _tools(
                (
                    "initiate_mpesa_payment",
                    {
                        "order_id": placed["order_data"]["order_id"],
                        "phone_number": journey.phone,
                        "amount": 1,
                        "description": "Tea",
                    },
                ),
                closing="Check your phone.",
            ),
        )
        assert prompted["actions_taken"][-1]["tool"] == "initiate_mpesa_payment"
        assert journey.stk_calls == 1
        assert journey.last_stk_amount == 100
        await journey.payment_callback(paid=True, receipt="QK123TEA")

        order = await journey.order()
        assert order.payment_status == "paid"
        assert order.mpesa_receipt == "QK123TEA"
        assert order.total == Decimal("100.00")
        assert journey.rails_state["payment_status"] == "paid"
        await db_session.refresh(tea)
        assert int(tea.quantity) == 4
        assert journey.live_llm_calls == 0


async def test_pay_fail_then_retry_marks_the_same_order_paid(db_session, test_user):
    tea = _product("Tea", "100.00", "TEA2", "tea")
    async with CommerceJourney(db_session, test_user, products=[tea]) as journey:
        await journey.say(
            "Add one tea please",
            _tools(
                (
                    "manage_cart",
                    {"action": "add", "product_name": "Tea", "quantity": 1, "unit_price": 1},
                ),
                closing="Added.",
            ),
        )
        journey.session.metadata["commerce_phase"] = "awaiting_yes"
        placed = await journey.say(
            "Thanks, continue",
            _tools(
                (
                    "create_order",
                    {
                        "customer_name": "Asha",
                        "items": [{"name": "Tea", "quantity": 1, "unit_price": 9}],
                        "delivery_method": "pickup",
                    },
                ),
                closing="Placed.",
            ),
        )
        order_id = placed["order_data"]["order_id"]
        await journey.say(
            "Please send the M-Pesa prompt",
            _tools(
                (
                    "initiate_mpesa_payment",
                    {
                        "order_id": order_id,
                        "phone_number": journey.phone,
                        "amount": 100,
                        "description": "Tea",
                    },
                ),
                closing="Prompt sent.",
            ),
        )
        await journey.payment_callback(paid=False, result_code="1032")
        failed = await journey.order()
        assert failed.payment_status == "failed"
        assert failed.external_order_id == order_id
        assert journey.rails_state["order_id"] == order_id
        assert journey.rails_state["payment_status"] == "failed"

        journey.allow_payment_retry()
        retried = await journey.say(
            "Please send the M-Pesa prompt again",
            _tools(
                (
                    "initiate_mpesa_payment",
                    {
                        "order_id": order_id,
                        "phone_number": journey.phone,
                        "amount": 100,
                        "description": "Tea",
                    },
                ),
                closing="Prompt sent again.",
            ),
        )
        assert any(
            step["tool"] == "initiate_mpesa_payment" and "BLOCKED" not in step["result_summary"]
            for step in retried["actions_taken"]
        )
        assert journey.stk_calls == 2
        await journey.payment_callback(paid=True, receipt="QKRETRY1")

        paid = await journey.order()
        assert paid.payment_status == "paid"
        assert paid.mpesa_receipt == "QKRETRY1"
        assert paid.external_order_id == order_id
        stored = await db_session.execute(
            select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
        )
        assert len(list(stored.scalars().all())) == 1
        await db_session.refresh(tea)
        assert int(tea.quantity) == 4
        assert journey.rails_state["payment_status"] == "paid"
        assert journey.live_llm_calls == 0


async def test_return_under_cap_auto_approves_without_claiming_refunded(
    db_session, test_user
):
    await upsert_policy(
        db_session,
        test_user.id,
        {"auto_approve_enabled": True, "auto_approve_max_amount_kes": 500},
    )
    now = datetime.now(timezone.utc)
    db_session.add(
        CommerceOrder(
            user_id=test_user.id,
            external_order_id="ORD-UNDER",
            customer_name="Asha",
            customer_phone="254711000703",
            status="delivered",
            payment_status="paid",
            currency="KES",
            total=Decimal("100.00"),
            line_items=[{"name": "Tea", "qty": 1, "unit_price": "100.00"}],
            delivery_method="pickup",
            created_at=now,
        )
    )
    await db_session.commit()

    async with CommerceJourney(db_session, test_user, phone="254711000703") as journey:
        await journey.say(
            "The tea arrived damaged",
            [{"content": "I can start a return. What amount should I request?"}],
        )
        result = await journey.say(
            "Please return 100 shillings",
            _tools(
                (
                    "request_return",
                    {
                        "order_external_id": "ORD-UNDER",
                        "reason_code": "damaged",
                        "amount": "100",
                        "phone": "254799999999",
                    },
                ),
                closing="You have been refunded.",
            ),
        )
        text = result["response_text"]
        assert "refunded" not in text.lower()
        assert "not complete" in text.lower()
        row = (
            await db_session.execute(
                select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
            )
        ).scalar_one()
        assert row.auto_approved is True
        assert row.status == "refund_pending"
        assert row.customer_phone == "254711000703"
        assert journey.live_llm_calls == 0


async def test_return_over_cap_stays_pending_for_the_hub(db_session, test_user):
    await upsert_policy(
        db_session,
        test_user.id,
        {"auto_approve_enabled": True, "auto_approve_max_amount_kes": 50},
    )
    db_session.add(
        CommerceOrder(
            user_id=test_user.id,
            external_order_id="ORD-OVER",
            customer_name="Asha",
            customer_phone="254711000704",
            status="delivered",
            payment_status="paid",
            currency="KES",
            total=Decimal("100.00"),
            line_items=[{"name": "Tea", "qty": 1, "unit_price": "100.00"}],
            delivery_method="pickup",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    async with CommerceJourney(db_session, test_user, phone="254711000704") as journey:
        result = await journey.say(
            "Please return the full 100",
            _tools(
                (
                    "request_return",
                    {
                        "order_external_id": "ORD-OVER",
                        "reason_code": "changed_mind",
                        "amount": "100",
                    },
                ),
                closing="Refund completed.",
            ),
        )
        assert "refunded" not in result["response_text"].lower()
        row = (
            await db_session.execute(
                select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
            )
        ).scalar_one()
        assert row.auto_approved is False
        assert row.status == "pending_approval"
        assert journey.live_llm_calls == 0


async def test_payment_dispute_complaint_hands_off(db_session, test_user):
    async with CommerceJourney(db_session, test_user, phone="254711000705") as journey:
        await journey.say(
            "I was charged twice",
            [{"content": "I can record that for the shop."}],
        )
        result = await journey.say(
            "It is a payment dispute on my last order",
            _tools(
                (
                    "request_complaint",
                    {
                        "category": "payment_dispute",
                        "detail": "Charged twice",
                        "phone": "254700000000",
                    },
                ),
                closing="You are refunded already.",
            ),
        )
        assert result["human_handoff"] is True
        assert journey.session.metadata.get("human_handoff") is True
        row = (
            await db_session.execute(
                select(CommerceComplaint).where(CommerceComplaint.user_id == test_user.id)
            )
        ).scalar_one()
        assert row.status == "handed_off"
        assert row.category == "payment_dispute"
        assert row.customer_phone == "254711000705"
        assert "refunded" not in result["response_text"].lower()
        assert journey.live_llm_calls == 0


async def test_hours_away_replies_without_calling_the_model(db_session, test_user):
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Nairobi"))
    closed_minute = (now.hour * 60 + now.minute + 180) % (24 * 60)
    hour, minute = divmod(closed_minute, 60)
    slot = f"{hour:02d}:{minute:02d}"
    hours = {
        day: {"open": slot, "close": slot}
        for day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    }
    await upsert_policy(
        db_session,
        test_user.id,
        {
            "business_hours": hours,
            "away_message": "Shop is away until morning.",
        },
    )
    async with CommerceJourney(db_session, test_user, phone="254711000706") as journey:
        result = await journey.say("Hello", [{"content": "The model should not speak."}])
        assert result["response_text"] == "Shop is away until morning."
        assert result["actions_taken"] == [{"tool": "hours", "result_summary": "away"}]
        assert journey.scripted_turns_used == 0
        assert journey.live_llm_calls == 0


async def test_mixed_en_sw_search_adds_the_catalog_item(db_session, test_user):
    milk = _product("Milk", "80.00", "MILK", "fresh milk")
    async with CommerceJourney(db_session, test_user, products=[milk], phone="254711000707") as journey:
        found = await journey.say(
            "Nataka maziwa one",
            _tools(
                ("search_products", {"query": "nataka maziwa one"}),
                closing="Nimepata maziwa.",
            ),
        )
        assert any(hit["name"] == "Milk" for hit in journey.search_hits("maziwa"))
        assert any(step["tool"] == "search_products" for step in found["actions_taken"])
        added = await journey.say(
            "Add that milk",
            _tools(
                (
                    "manage_cart",
                    {
                        "action": "add",
                        "product_name": "Milk",
                        "quantity": 1,
                        "unit_price": 5,
                    },
                ),
                closing="Imeongezwa.",
            ),
        )
        assert any(step["tool"] == "manage_cart" for step in added["actions_taken"])
        names = [line.get("name") for line in journey.session.metadata.get("cart") or []]
        assert names == ["Milk"]
        assert journey.rails_state["cart_lines"]
        assert journey.live_llm_calls == 0


async def test_pay_then_cancel_opens_a_refund_pipeline(db_session, test_user):
    """A paid order cancelled before preparing keeps a Hub return and does not say refunded."""
    tea = _product("Tea", "100.00", "TEA-CANCEL", "tea")
    async with CommerceJourney(db_session, test_user, products=[tea]) as journey:
        await journey.say(
            "Add one tea please",
            _tools(
                (
                    "manage_cart",
                    {"action": "add", "product_name": "Tea", "quantity": 1, "unit_price": 1},
                ),
                closing="Added.",
            ),
        )
        journey.session.metadata["commerce_phase"] = "awaiting_yes"
        placed = await journey.say(
            "Thanks, continue",
            _tools(
                (
                    "create_order",
                    {
                        "customer_name": "Asha",
                        "items": [{"name": "Tea", "quantity": 1, "unit_price": 1}],
                        "delivery_method": "pickup",
                    },
                ),
                closing="Placed.",
            ),
        )
        order_id = placed["order_data"]["order_id"]
        await journey.say(
            "Please send the M-Pesa prompt",
            _tools(
                (
                    "initiate_mpesa_payment",
                    {
                        "order_id": order_id,
                        "phone_number": journey.phone,
                        "amount": 1,
                        "description": "Tea",
                    },
                ),
                closing="Prompt sent.",
            ),
        )
        await journey.payment_callback(paid=True, receipt="QKCANCEL1")
        cancelled = await journey.say(
            "Please cancel that order",
            _tools(
                ("cancel_order", {"order_id": order_id}),
                closing="You have been refunded.",
            ),
        )

    text = cancelled["response_text"]
    assert "refunded" not in text.lower()
    assert "not complete" in text.lower()
    order = await journey.order()
    assert order.status == "cancelled"
    assert order.payment_status == "paid"
    row = (
        await db_session.execute(
            select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
        )
    ).scalar_one()
    assert row.status != "refunded"
    assert row.order_external_id == order_id
    assert row.amount == Decimal("100.00")
    await db_session.refresh(tea)
    assert int(tea.quantity) == 5
    assert journey.live_llm_calls == 0
