"""Route ordering-agent mutations through CommerceRuntime and returns.

The conversational agent keeps language and WhatsApp copy. Money, cart,
checkout, place, cancel, return, complaint, and handoff changes happen
here so the model cannot write those states itself.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ...models import CommerceReturn
from ..commerce_policy import away_message_if_closed, get_policy
from ..commerce_returns_service import (
    CommerceReturnError,
    apply_aftersale_command,
    find_buyer_order,
    open_paid_cancel_return,
    payment_already_collected,
)
from ..commerce_status_notify import phones_match
from ..conversation_context_manager import context_manager
from ..whatsapp_ordering_helpers import (
    commerce_rails_intended,
    normalize_commerce_rails_enabled,
)
from .db_ports import DbCatalogPort, DbOrderPort
from .runtime import CommerceRuntime
from .state import CommerceState

logger = logging.getLogger(__name__)

SAFE_FAILURE = (
    "I couldn't complete that just now. A person from the shop will follow up."
)


class RailsPolicyUnavailable(Exception):
    """Policy could not be read for a merchant that should stay on rails."""

_HANDOFF_CODES = frozenset({"persist_failed", "unknown_command"})

_ERROR_TEXT = {
    "empty_cart": "Your cart is empty. Add a catalog item before placing the order.",
    "unknown_product": "I couldn't find that item in the catalog.",
    "out_of_stock": "That item isn't available right now.",
    "insufficient_quantity": "We don't have that many in stock.",
    "fulfillment_required": (
        "Tell me whether you want delivery or pickup before I place the order."
    ),
    "fulfillment_not_allowed": "That fulfillment option isn't offered.",
    "cancel_not_allowed": "This order can no longer be cancelled.",
    "no_order": "I couldn't find that order on your number.",
    "phone_mismatch": "I couldn't find that order on your number.",
    "already_placed": "That order is already placed.",
    "line_not_found": "I couldn't find that item in your cart.",
    "invalid_quantity": "Tell me a quantity greater than zero.",
    "invalid_checkout_field": "I need a name for that checkout detail.",
    "persist_failed": SAFE_FAILURE,
    "unknown_command": SAFE_FAILURE,
}

RAILS_MUTATION_TOOLS = frozenset(
    {
        "manage_cart",
        "create_order",
        "cancel_order",
        "validate_order",
        "request_return",
        "request_complaint",
        "escalate_to_human",
    }
)

RAILS_EXTRA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_return",
            "description": (
                "Start a return for an order the customer already placed. "
                "Uses the shop return policy. Do not tell the customer the "
                "money was refunded; repeat the tool's customer message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_external_id": {"type": "string"},
                    "reason_code": {"type": "string"},
                    "amount": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["order_external_id", "reason_code", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_complaint",
            "description": (
                "Record a complaint. Self-serve categories close in chat. "
                "Disputes hand the conversation to a person."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "order_external_id": {"type": "string"},
                    "detail": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["category"],
            },
        },
    },
]


def _message_for(code: str) -> str:
    text = _ERROR_TEXT.get(code) or SAFE_FAILURE
    return text.strip() or SAFE_FAILURE


def whatsapp_sender_phone(session_key: str) -> str:
    """Phone from a WhatsApp session key. Empty when the key is not that shape."""
    parts = str(session_key or "").split(":")
    if len(parts) >= 4 and parts[0] == "ccm" and parts[1] == "whatsapp":
        return str(parts[3] or "").strip()
    return ""


def _money_float(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    if amount < 0:
        return 0.0
    return round(amount, 2)


def _format_amount(value: Any) -> str:
    amount = _money_float(value)
    if amount == int(amount):
        return str(int(amount))
    return f"{amount:.2f}"


def _payable_snapshot(state, stored: Optional[dict], currency: str) -> dict:
    """Order dict the existing STK and tracking lookups already understand."""
    stored = stored or {}
    total = _money_float(stored.get("total"))
    items = []
    for line in stored.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        qty = line.get("quantity", line.get("qty", 1))
        unit = _money_float(line.get("unit_price") if line.get("unit_price") is not None else line.get("price"))
        items.append(
            {
                "name": line.get("name") or "",
                "product_id": line.get("product_id"),
                "quantity": qty,
                "qty": qty,
                "unit_price": unit,
                "price": unit,
            }
        )
    fields = state.checkout_fields if state is not None else {}
    customer_name = stored.get("customer_name") or fields.get("customer_name") or ""
    customer_phone = stored.get("customer_phone") or fields.get("customer_phone") or ""
    return {
        "order_id": state.order_id,
        "status": stored.get("status") or "pending",
        "payment_status": stored.get("payment_status") or state.payment_status or "pending",
        "total": total,
        "subtotal": total,
        "total_amount": total,
        "currency": currency or "KES",
        "items": items,
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "customer": {"name": customer_name, "phone": customer_phone},
        "delivery_method": stored.get("fulfillment_method") or state.fulfillment_method or "",
    }


def _customer_phone(session_key: str, arguments: dict) -> str:
    sender = whatsapp_sender_phone(session_key)
    if sender:
        return sender
    return str(arguments.get("phone") or arguments.get("customer_phone") or "").strip()


def _tool_result(ok: bool, message: str, **extra: Any) -> dict:
    text = (message or "").strip() or SAFE_FAILURE
    payload = {
        "success": bool(ok),
        "result": text,
        "verbatim_customer_message": text,
    }
    payload.update(extra)
    if not str(payload.get("verbatim_customer_message") or "").strip():
        payload["verbatim_customer_message"] = SAFE_FAILURE
        payload["result"] = SAFE_FAILURE
    return payload


def _state_from_metadata(metadata: Optional[dict]) -> CommerceState:
    raw = {}
    if isinstance(metadata, dict):
        stored = metadata.get("commerce_rails_state")
        if isinstance(stored, dict):
            raw = stored
    return CommerceState(
        cart_lines=[dict(line) for line in (raw.get("cart_lines") or []) if isinstance(line, dict)],
        fulfillment_method=raw.get("fulfillment_method"),
        checkout_fields=dict(raw.get("checkout_fields") or {}),
        order_id=raw.get("order_id"),
        payment_status=raw.get("payment_status"),
        phase=raw.get("phase") or "cart",
    )


def _state_payload(state: CommerceState) -> dict:
    return {
        "cart_lines": list(state.cart_lines),
        "fulfillment_method": state.fulfillment_method,
        "checkout_fields": dict(state.checkout_fields),
        "order_id": state.order_id,
        "payment_status": state.payment_status,
        "phase": state.phase,
    }


def _project_cart(state: CommerceState, names: dict) -> list:
    projected = []
    for line in state.cart_lines:
        product_id = str(line.get("product_id") or "")
        info = names.get(product_id) or {}
        price = info.get("price")
        try:
            unit_price = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            unit_price = 0.0
        projected.append(
            {
                "id": product_id,
                "name": info.get("name") or product_id,
                "quantity": line.get("qty") or 1,
                "unit_price": unit_price,
            }
        )
    return projected


async def away_reply_for_turn(db, user_id) -> str:
    """Away copy when rails are on and policy hours say the shop is closed."""
    if db is None or user_id is None:
        return ""
    try:
        policy = await get_policy(db, user_id)
    except Exception as exc:
        logger.warning("[COMMERCE_RAILS] hours check failed, shop stays open: %s", exc)
        return ""
    return away_message_if_closed(policy) or ""


async def rails_enabled_for_turn(
    business_config: Optional[dict],
    db,
    user_id,
    order_type: str = "",
) -> bool:
    config = dict(business_config or {})
    if order_type:
        config["order_type"] = order_type
    explicit = isinstance(business_config, dict) and "commerce_rails_enabled" in business_config
    policy = None
    if not explicit and db is not None and user_id is not None:
        try:
            loaded = await get_policy(db, user_id)
            policy = loaded if isinstance(loaded, dict) else None
        except Exception as exc:
            logger.warning("[COMMERCE_RAILS] policy load failed: %s", exc)
            if commerce_rails_intended(business_config, order_type):
                raise RailsPolicyUnavailable("policy load failed") from exc
            return False
    return normalize_commerce_rails_enabled(config, policy)


async def _load_policy(db, user_id) -> dict:
    try:
        loaded = await get_policy(db, user_id)
    except Exception as exc:
        logger.warning("[COMMERCE_RAILS] policy load failed: %s", exc)
        raise RailsPolicyUnavailable("policy load failed") from exc
    if not isinstance(loaded, dict):
        raise RailsPolicyUnavailable("policy load failed")
    return loaded


async def _save_state(session_key: str, state: CommerceState, names: dict) -> None:
    if not session_key:
        return
    await context_manager.update_session_metadata(
        session_key,
        {
            "commerce_rails_state": _state_payload(state),
            "cart": _project_cart(state, names),
        },
    )


async def _handoff(session_key: str, reason: str) -> None:
    if not session_key:
        return
    try:
        await context_manager.set_human_handoff(session_key, reason, escalated_by="commerce_rails")
    except Exception as exc:
        logger.warning("[COMMERCE_RAILS] handoff latch failed: %s", exc)


def _fail(code: str, *, handoff: bool = False, effects: Optional[list] = None) -> dict:
    message = _message_for(code)
    payload = _tool_result(False, message, error_code=code, effects=list(effects or []))
    if handoff or code in _HANDOFF_CODES:
        payload["human_handoff"] = True
        payload["effects"] = list(payload["effects"]) + [{"type": "handoff", "reason": code}]
    return payload


async def _apply(runtime: CommerceRuntime, state: CommerceState, command: dict):
    return await runtime.apply(state, command)


async def dispatch_rails_tool(
    *,
    tool_name: str,
    arguments: Optional[dict],
    business_config: Optional[dict],
    order_type: str,
    session_key: str,
    user,
    db,
    currency: str = "KES",
    escalate: Optional[Callable[[], Awaitable[dict]]] = None,
) -> Optional[dict]:
    """Run a mutation tool on the rails, or return None to keep the legacy path."""
    if tool_name not in RAILS_MUTATION_TOOLS:
        return None
    user_id = getattr(user, "id", None)
    try:
        enabled = await rails_enabled_for_turn(business_config, db, user_id, order_type)
    except RailsPolicyUnavailable:
        logger.warning("[COMMERCE_RAILS] policy unavailable, failing closed")
        await _handoff(session_key, "policy_unavailable")
        return _tool_result(
            False,
            SAFE_FAILURE,
            human_handoff=True,
            effects=[{"type": "handoff", "reason": "policy_unavailable"}],
        )
    except Exception as exc:
        logger.warning("[COMMERCE_RAILS] flag check failed: %s", exc)
        if commerce_rails_intended(business_config, order_type):
            await _handoff(session_key, "policy_unavailable")
            return _tool_result(
                False,
                SAFE_FAILURE,
                human_handoff=True,
                effects=[{"type": "handoff", "reason": "policy_unavailable"}],
            )
        return None
    if not enabled:
        return None
    if db is None or user_id is None:
        return _fail("persist_failed", handoff=True)
    try:
        return await _dispatch(
            tool_name=tool_name,
            arguments=arguments or {},
            session_key=session_key,
            user_id=user_id,
            db=db,
            currency=currency,
            escalate=escalate,
        )
    except Exception:
        logger.exception("[COMMERCE_RAILS] %s failed", tool_name)
        await _handoff(session_key, "rails_error")
        return _tool_result(
            False,
            SAFE_FAILURE,
            human_handoff=True,
            effects=[{"type": "handoff", "reason": "rails_error"}],
        )


async def _dispatch(
    *,
    tool_name: str,
    arguments: dict,
    session_key: str,
    user_id,
    db,
    currency: str,
    escalate: Optional[Callable[[], Awaitable[dict]]],
) -> dict:
    if tool_name == "escalate_to_human":
        return await _handoff_tool(session_key, escalate)
    if tool_name == "request_return":
        return await _return_tool(db, user_id, session_key, arguments)
    if tool_name == "request_complaint":
        return await _complaint_tool(db, user_id, session_key, arguments, currency)

    policy = await _load_policy(db, user_id)
    catalog = DbCatalogPort(db, user_id)
    orders = DbOrderPort(db, user_id)
    runtime = CommerceRuntime(policy, catalog, orders)
    session = None
    if session_key:
        try:
            session = await context_manager.get_session_by_key(session_key)
        except Exception as exc:
            logger.warning("[COMMERCE_RAILS] session load failed: %s", exc)
    metadata = session.metadata if session is not None else {}
    state = _state_from_metadata(metadata)
    names: dict = {}

    if tool_name == "manage_cart":
        state, result = await _cart(runtime, catalog, state, arguments, names)
    elif tool_name == "validate_order":
        state, result = await _checkout(runtime, state, arguments)
    elif tool_name == "create_order":
        state, result = await _place(
            runtime, catalog, state, arguments, metadata, names
        )
    elif tool_name == "cancel_order":
        state, result = await _cancel(runtime, orders, state, arguments)
    else:
        return _fail("unknown_command", handoff=True)

    if result.get("ok"):
        await _save_state(session_key, state, names)
    elif result.get("error_code") in _HANDOFF_CODES:
        await _handoff(session_key, result.get("error_code") or "rails_error")

    if not result.get("ok"):
        return _fail(str(result.get("error_code") or "persist_failed"))

    paid_cancel = None
    if tool_name == "cancel_order":
        paid_cancel = await _paid_cancel_refund(db, user_id, state.order_id, arguments)
        if paid_cancel is not None and not paid_cancel.get("ok"):
            await _handoff(session_key, "paid_cancel_refund")
            return _fail("persist_failed", handoff=True)
        if paid_cancel and paid_cancel.get("effects"):
            result["effects"] = list(result.get("effects") or []) + list(paid_cancel["effects"])

    effects = list(result.get("effects") or [])
    extra: dict[str, Any] = {"effects": effects, "rails": True}
    payable = None
    if state.order_id and tool_name == "create_order":
        stored = await orders.get_order(state.order_id)
        extra["order_data"] = _payable_snapshot(state, stored, currency)
        payable = extra["order_data"].get("total")
    if tool_name == "cancel_order":
        extra["cancellation_data"] = {"order_id": state.order_id, "status": "cancelled"}
    if paid_cancel and paid_cancel.get("message"):
        message = str(paid_cancel["message"])
    else:
        message = _success_text(tool_name, state, arguments, currency, effects, payable=payable)
    return _tool_result(True, message, **extra)


async def _cart(runtime, catalog, state, arguments, names):
    action = str(arguments.get("action") or "view").strip().lower()
    if action == "view":
        return state, {"ok": True, "effects": []}
    if action == "clear":
        for line in list(state.cart_lines):
            state, result = await _apply(
                runtime, state, {"type": "remove_line", "product_id": line.get("product_id")}
            )
            if not result.get("ok"):
                return state, result
        return state, {"ok": True, "effects": []}

    product = await catalog.find_product(
        str(arguments.get("product_id") or ""),
        str(arguments.get("product_name") or ""),
    )
    if product is None:
        return state, {"ok": False, "error_code": "unknown_product", "effects": []}
    names[product["id"]] = product
    if action == "remove":
        return await _apply(runtime, state, {"type": "remove_line", "product_id": product["id"]})
    qty = arguments.get("quantity") if arguments.get("quantity") is not None else 1
    command_type = "update_line" if action == "set_quantity" else "add_line"
    return await _apply(
        runtime,
        state,
        {"type": command_type, "product_id": product["id"], "qty": qty},
    )


async def _checkout(runtime, state, arguments):
    method = arguments.get("delivery_method") or arguments.get("fulfillment_method")
    if method:
        state, result = await _apply(
            runtime,
            state,
            {"type": "set_fulfillment", "fulfillment_method": method},
        )
        if not result.get("ok"):
            return state, result
    for field in ("customer_name", "customer_phone", "delivery_address", "table_number", "notes"):
        if arguments.get(field) not in (None, ""):
            state, result = await _apply(
                runtime,
                state,
                {"type": "set_checkout_field", "field": field, "value": arguments.get(field)},
            )
            if not result.get("ok"):
                return state, result
    return state, {"ok": True, "effects": []}


async def _place(runtime, catalog, state, arguments, metadata, names):
    if not state.cart_lines:
        display = metadata.get("cart") if isinstance(metadata, dict) else None
        if isinstance(display, list):
            for item in display:
                if not isinstance(item, dict):
                    continue
                product = await catalog.find_product(
                    str(item.get("id") or item.get("product_id") or ""),
                    str(item.get("name") or ""),
                )
                if product is None:
                    return state, {"ok": False, "error_code": "unknown_product", "effects": []}
                names[product["id"]] = product
                state, result = await _apply(
                    runtime,
                    state,
                    {
                        "type": "add_line",
                        "product_id": product["id"],
                        "qty": item.get("quantity") or 1,
                    },
                )
                if not result.get("ok"):
                    return state, result
    for line in state.cart_lines:
        if line.get("product_id") not in names:
            found = await catalog.get_product(str(line.get("product_id") or ""))
            if found:
                names[found["id"]] = found
    state, result = await _checkout(runtime, state, arguments)
    if not result.get("ok"):
        return state, result
    return await _apply(runtime, state, {"type": "place_order"})


async def _cancel(runtime, orders, state, arguments):
    order_id = str(arguments.get("order_id") or state.order_id or "").strip()
    if not order_id:
        return state, {"ok": False, "error_code": "no_order", "effects": []}
    phone = str(arguments.get("customer_phone") or arguments.get("phone") or "").strip()
    stored = await orders.get_order(order_id)
    if stored is None:
        return state, {"ok": False, "error_code": "no_order", "effects": []}
    if payment_already_collected(stored):
        if not phones_match(stored.get("customer_phone"), phone):
            return state, {"ok": False, "error_code": "no_order", "effects": []}
    elif phone and stored.get("customer_phone") and not phones_match(
        stored.get("customer_phone"), phone
    ):
        return state, {"ok": False, "error_code": "no_order", "effects": []}
    state.order_id = order_id
    return await _apply(runtime, state, {"type": "cancel_order"})


async def _paid_cancel_refund(db, user_id, order_id: str, arguments: dict) -> Optional[dict]:
    """Create the Hub refund path when a cancel follows collected payment."""
    if not order_id:
        return None
    from .db_ports import DbOrderPort

    stored = await DbOrderPort(db, user_id).get_order(order_id)
    if not stored or not payment_already_collected(stored):
        return None
    phone = str(
        stored.get("customer_phone")
        or arguments.get("customer_phone")
        or arguments.get("phone")
        or ""
    ).strip()
    try:
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        row = await open_paid_cancel_return(db, user_uuid, order_id, phone)
    except CommerceReturnError as exc:
        logger.warning("[COMMERCE_RAILS] paid cancel refund failed: %s", exc.code)
        return {"ok": False, "error_code": exc.code}
    except Exception:
        logger.exception("[COMMERCE_RAILS] paid cancel refund failed")
        return {"ok": False, "error_code": "persist_failed"}
    if row is None:
        return None
    snapshot = row.raw_snapshot if isinstance(row.raw_snapshot, dict) else {}
    message = str(snapshot.get("customer_message") or "").strip()
    if not message:
        message = (
            f"Order {order_id} is cancelled. Your return {row.external_return_id} "
            "is waiting for the shop to pay you. This payment is not complete."
        )
    if row.status != "refunded" and "refunded" in message.lower():
        message = (
            f"Order {order_id} is cancelled. Your return {row.external_return_id} "
            "is waiting for the shop to pay you. This payment is not complete."
        )
    return {
        "ok": True,
        "message": message,
        "effects": [
            {
                "type": "persist_return",
                "return_id": str(row.id),
                "external_return_id": row.external_return_id,
                "status": row.status,
            }
        ],
    }


async def _return_tool(db, user_id, session_key, arguments) -> dict:
    state = CommerceState(cart_lines=[])
    try:
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return _fail("persist_failed", handoff=True)
    state, result = await apply_aftersale_command(
        db,
        user_uuid,
        state,
        {
            "type": "request_return",
            "order_external_id": arguments.get("order_external_id") or arguments.get("order_id"),
            "phone": _customer_phone(session_key, arguments),
            "reason_code": arguments.get("reason_code"),
            "amount": arguments.get("amount"),
        },
    )
    if not result.get("ok"):
        failed = _fail(str(result.get("error_code") or "persist_failed"))
        return failed
    message = await _stored_return_message(db, result.get("effects") or [])
    if not message:
        message = "Your return request was received. The shop has not completed payment."
    return _tool_result(True, message, effects=result.get("effects") or [], rails=True)


async def _stored_return_message(db, effects: list) -> str:
    return_id = ""
    for effect in effects:
        if effect.get("type") == "persist_return" and effect.get("return_id"):
            return_id = str(effect["return_id"])
            break
    if not return_id:
        return ""
    try:
        found = await db.execute(
            select(CommerceReturn).where(CommerceReturn.id == uuid.UUID(return_id))
        )
        row = found.scalar_one_or_none()
    except Exception as exc:
        logger.warning("[COMMERCE_RAILS] return reload failed: %s", exc)
        return ""
    if row is None:
        return ""
    snapshot = row.raw_snapshot if isinstance(row.raw_snapshot, dict) else {}
    stored = snapshot.get("customer_message")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    if row.status == "refund_pending":
        return (
            f"Your return {row.external_return_id} is waiting for the shop to pay you. "
            "This payment is not complete."
        )
    return f"Your return {row.external_return_id} is {row.status}."


async def _complaint_tool(db, user_id, session_key, arguments, currency: str = "KES") -> dict:
    state = CommerceState(cart_lines=[])
    try:
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return _fail("persist_failed", handoff=True)
    state, result = await apply_aftersale_command(
        db,
        user_uuid,
        state,
        {
            "type": "request_complaint",
            "phone": _customer_phone(session_key, arguments),
            "category": arguments.get("category"),
            "order_external_id": arguments.get("order_external_id"),
            "detail": arguments.get("detail"),
        },
    )
    if not result.get("ok"):
        return _fail(str(result.get("error_code") or "persist_failed"))
    effects = list(result.get("effects") or [])
    handoff = any(effect.get("type") == "handoff" for effect in effects)
    if handoff:
        await _handoff(session_key, "complaint")
        message = "I've passed this to someone at the shop. They will take it from here."
        return _tool_result(True, message, effects=effects, human_handoff=True, rails=True)
    category = str(arguments.get("category") or "").strip().lower()
    phone = _customer_phone(session_key, arguments)
    message = str(result.get("customer_message") or "").strip()
    if category == "cancel":
        message = await _complaint_cancel(
            db, user_id, session_key, arguments, phone, currency
        )
    elif category == "start_return":
        message = await _complaint_start_return(db, user_id, session_key, arguments, phone)
    if not message.strip():
        message = SAFE_FAILURE
    return _tool_result(True, message, effects=effects, rails=True)


async def _complaint_cancel(db, user_id, session_key, arguments, phone, currency) -> str:
    try:
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return SAFE_FAILURE
    order = await find_buyer_order(
        db,
        user_uuid,
        phone,
        arguments.get("order_external_id"),
    )
    if order is None:
        return "I couldn't find an order on your number to cancel."
    result = await _dispatch(
        tool_name="cancel_order",
        arguments={
            "order_id": order.external_order_id,
            "customer_phone": phone,
        },
        session_key=session_key,
        user_id=user_id,
        db=db,
        currency=currency,
        escalate=None,
    )
    return str(result.get("verbatim_customer_message") or result.get("result") or SAFE_FAILURE)


async def _complaint_start_return(db, user_id, session_key, arguments, phone) -> str:
    try:
        user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return SAFE_FAILURE
    order = await find_buyer_order(
        db,
        user_uuid,
        phone,
        arguments.get("order_external_id"),
    )
    if order is None:
        return "I couldn't find an order on your number to return."
    if not payment_already_collected(order):
        return (
            f"Order {order.external_order_id} payment is {order.payment_status}. "
            "There is no collected payment to return."
        )
    policy = await _load_policy(db, user_id)
    codes = [str(code) for code in (policy.get("return_reason_codes") or [])]
    reason = "changed_mind" if "changed_mind" in codes else (codes[0] if codes else "")
    if not reason:
        return "This shop has no return reason I can start from here."
    nested = await _return_tool(
        db,
        user_id,
        session_key,
        {
            "order_external_id": order.external_order_id,
            "reason_code": reason,
            "amount": str(order.total),
            "phone": phone,
        },
    )
    return str(nested.get("verbatim_customer_message") or nested.get("result") or SAFE_FAILURE)


async def _handoff_tool(session_key, escalate) -> dict:
    if escalate is None:
        await _handoff(session_key, "customer_requested_human")
        return _tool_result(
            True,
            "A person from the shop will take it from here.",
            human_handoff=True,
            effects=[{"type": "handoff"}],
            rails=True,
        )
    result = await escalate()
    if not isinstance(result, dict):
        result = {"success": False, "result": SAFE_FAILURE}
    result.setdefault("result", SAFE_FAILURE)
    result["verbatim_customer_message"] = result.get("result") or SAFE_FAILURE
    result["human_handoff"] = True
    effects = list(result.get("effects") or [])
    effects.append({"type": "handoff"})
    result["effects"] = effects
    result["rails"] = True
    if not str(result["verbatim_customer_message"]).strip():
        result["verbatim_customer_message"] = SAFE_FAILURE
        result["result"] = SAFE_FAILURE
    return result


def _success_text(tool_name, state, arguments, currency, effects, payable=None) -> str:
    if tool_name == "create_order":
        amount = _format_amount(payable)
        return (
            f"Order {state.order_id} is placed. "
            f"Total {currency} {amount}. Payment is still pending."
        )
    if tool_name == "cancel_order":
        return f"Order {state.order_id} is cancelled."
    if tool_name == "validate_order":
        return "Checkout details are saved. Reply YES when you want me to place the order."
    action = str(arguments.get("action") or "view")
    count = len(state.cart_lines)
    if action == "clear":
        return "Your cart is cleared."
    if action == "view":
        return f"Your cart has {count} item(s)."
    return f"Cart updated. {count} item(s) in the cart. Prices come from the catalog ({currency})."


async def try_rails_fast_cart(
    *,
    command: str,
    user_message: str,
    business_config: Optional[dict],
    order_type: str,
    session_key: str,
    user,
    db,
    currency: str = "KES",
) -> Optional[str]:
    """Handle clear / remove / quantity on the rails. None keeps the legacy fast path."""
    if command not in {"clear", "remove", "set_quantity"}:
        return None
    arguments: dict[str, Any] = {"action": command}
    if command == "remove":
        from ..whatsapp_ordering_helpers import parse_remove_item_name

        arguments["product_name"] = parse_remove_item_name(user_message)
    elif command == "set_quantity":
        from ..whatsapp_ordering_helpers import parse_set_quantity_message

        name, qty = parse_set_quantity_message(user_message)
        if name is None or qty is None:
            return None
        arguments["product_name"] = name
        arguments["quantity"] = qty
    result = await dispatch_rails_tool(
        tool_name="manage_cart",
        arguments=arguments,
        business_config=business_config,
        order_type=order_type,
        session_key=session_key,
        user=user,
        db=db,
        currency=currency,
    )
    if result is None:
        return None
    return str(result.get("verbatim_customer_message") or result.get("result") or SAFE_FAILURE)
