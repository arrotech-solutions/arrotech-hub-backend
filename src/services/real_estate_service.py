"""
Real Estate Processing Tools for Arrotech Hub.

Stateless processing tools for real estate workflow automation.
No database models — data flows through workflow variables.
Designed for Kenyan real estate agencies (WhatsApp + M-Pesa focused).
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RealEstateService:
    """Stateless real estate processing tools for workflow building blocks."""

    def __init__(self):
        # Property inquiry keywords in English and Swahili
        self.INQUIRY_KEYWORDS = {
            "rent": ["rent", "kodi", "rental", "bedsitter", "bedsitta", "single", "studio"],
            "buy": ["buy", "purchase", "nunua", "kununua", "sale", "selling", "for sale"],
            "plot": ["plot", "shamba", "land", "acre", "hectare", "quarter"],
            "apartment": ["apartment", "flat", "fleti", "2br", "3br", "1br", "one bedroom",
                          "two bedroom", "three bedroom", "2 bedroom", "3 bedroom", "1 bedroom"],
            "house": ["house", "nyumba", "bungalow", "maisonette", "mansion", "villa", "townhouse"],
            "commercial": ["office", "shop", "duka", "godown", "warehouse", "commercial"],
            "viewing": ["view", "visit", "see", "tazama", "viewing", "angalia", "come see"],
            "maintenance": ["broken", "leak", "repair", "fix", "maintenance", "plumbing",
                           "electrical", "water", "maji", "stima", "haribika", "vunja"],
        }

        # M-Pesa payment confirmation pattern
        self.MPESA_PATTERN = re.compile(
            r'([A-Z0-9]{10})\s+Confirmed.*?Ksh([\d,]+\.?\d*)\s+.*?on\s+(\d{1,2}/\d{1,2}/\d{2,4})',
            re.IGNORECASE | re.DOTALL
        )

    async def handle_operation(
        self,
        operation: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Route to the appropriate real estate tool."""
        try:
            # Type coercion — workflow variables arrive as strings
            kwargs = self._coerce_types(kwargs)

            if operation == "classify_inquiry":
                return await self.classify_inquiry(**kwargs)
            elif operation == "format_rent_reminder":
                return await self.format_rent_reminder(**kwargs)
            elif operation == "format_payment_receipt":
                return await self.format_payment_receipt(**kwargs)
            elif operation == "format_listing":
                return await self.format_listing(**kwargs)
            elif operation == "classify_maintenance":
                return await self.classify_maintenance(**kwargs)
            elif operation == "format_maintenance_response":
                return await self.format_maintenance_response(**kwargs)
            elif operation == "format_viewing_slots":
                return await self.format_viewing_slots(**kwargs)
            elif operation == "generate_rent_statement":
                return await self.generate_rent_statement(**kwargs)
            elif operation == "generate_landlord_report":
                return await self.generate_landlord_report(**kwargs)
            elif operation == "format_tenant_welcome":
                return await self.format_tenant_welcome(**kwargs)
            elif operation == "format_lease_reminder":
                return await self.format_lease_reminder(**kwargs)
            elif operation == "parse_mpesa_confirmation":
                return await self.parse_mpesa_confirmation(**kwargs)
            elif operation == "format_broadcast_listing":
                return await self.format_broadcast_listing(**kwargs)
            elif operation == "format_viewing_confirmation":
                return await self.format_viewing_confirmation(**kwargs)
            elif operation == "format_escalation_notice":
                return await self.format_escalation_notice(**kwargs)
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except Exception as e:
            logger.error(f"Real estate tool error ({operation}): {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _coerce_types(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce string values from workflow variables to proper types."""
        # Fields that should be float
        float_fields = {
            "amount", "price", "rent_amount", "monthly_rent", "balance",
            "total_rent_expected", "total_rent_collected", "maintenance_cost",
            "current_rent", "new_rent"
        }
        # Fields that should be int
        int_fields = {
            "bedrooms", "total_units", "occupied_units",
            "maintenance_count", "days_until_expiry"
        }

        coerced = {}
        for key, value in kwargs.items():
            if value is None or value == "":
                coerced[key] = value
                continue

            if key in float_fields and isinstance(value, str):
                try:
                    coerced[key] = float(value.replace(",", ""))
                except (ValueError, AttributeError):
                    coerced[key] = 0.0
            elif key in int_fields and isinstance(value, str):
                try:
                    coerced[key] = int(float(value.replace(",", "")))
                except (ValueError, AttributeError):
                    coerced[key] = 0
            else:
                coerced[key] = value

        return coerced

    # ──────────────────────────────────────────────────────────────
    # 1. INQUIRY CLASSIFICATION
    # ──────────────────────────────────────────────────────────────

    async def classify_inquiry(
        self,
        message: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Classify an incoming WhatsApp message into real estate inquiry types.
        Extracts: intent, property type, bedrooms, budget, location.
        """
        if not message:
            return {"success": False, "error": "Message text is required"}

        msg_lower = message.lower().strip()
        detected_intents = []
        detected_property_type = None

        # Detect intents
        for intent, keywords in self.INQUIRY_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    detected_intents.append(intent)
                    if intent in ["apartment", "house", "plot", "commercial"]:
                        detected_property_type = intent
                    break

        # Extract bedrooms
        bedrooms = None
        br_match = re.search(r'(\d)\s*(?:br|bed(?:room)?s?)', msg_lower)
        if br_match:
            bedrooms = int(br_match.group(1))
        elif "bedsitter" in msg_lower or "bedsitta" in msg_lower:
            bedrooms = 0  # Bedsitter
        elif "single" in msg_lower and "room" in msg_lower:
            bedrooms = 0
        elif "studio" in msg_lower:
            bedrooms = 0

        # Extract budget/price mentions
        budget = None
        price_match = re.search(r'(?:ksh|kes|kes\.?|sh)\s*([\d,]+)', msg_lower)
        if not price_match:
            price_match = re.search(r'([\d,]+)\s*(?:k|K|ksh|kes|sh|bob)', msg_lower)
        if price_match:
            budget_str = price_match.group(1).replace(",", "")
            budget = int(budget_str)
            # Handle "k" shorthand (e.g. "15k")
            if budget < 1000 and ("k" in msg_lower[price_match.end():price_match.end()+2].lower()):
                budget *= 1000

        # Extract location
        location = None
        thika_areas = [
            "thika town", "makongeni", "landless", "ngoingwa", "section 9",
            "kisii", "juja", "ruiru", "gatundu", "kiambu", "gatuanyaga",
            "munyu", "witeithie", "mangu", "hospital", "blue post",
            "garissa road", "kenyatta highway", "commercial street"
        ]
        for area in thika_areas:
            if area in msg_lower:
                location = area.title()
                break

        # Determine primary intent
        primary_intent = "general_inquiry"
        if "viewing" in detected_intents:
            primary_intent = "viewing_request"
        elif "maintenance" in detected_intents:
            primary_intent = "maintenance_request"
        elif "buy" in detected_intents:
            primary_intent = "purchase_inquiry"
        elif "rent" in detected_intents:
            primary_intent = "rental_inquiry"
        elif "plot" in detected_intents:
            primary_intent = "plot_inquiry"
        elif detected_property_type:
            primary_intent = "property_inquiry"

        # Urgency detection
        urgency = "normal"
        urgent_words = ["urgent", "asap", "immediately", "now", "haraka", "sasa", "emergency"]
        if any(w in msg_lower for w in urgent_words):
            urgency = "high"

        return {
            "success": True,
            "primary_intent": primary_intent,
            "all_intents": list(set(detected_intents)),
            "property_type": detected_property_type,
            "bedrooms": bedrooms,
            "budget": budget,
            "location": location,
            "urgency": urgency,
            "original_message": message,
            "suggested_tags": [primary_intent] + (["hot_lead"] if urgency == "high" else []),
            "message": f"Classified as '{primary_intent}'" + (f" for {detected_property_type}" if detected_property_type else "")
        }

    # ──────────────────────────────────────────────────────────────
    # 2. RENT REMINDERS
    # ──────────────────────────────────────────────────────────────

    async def format_rent_reminder(
        self,
        tenant_name: str = "Tenant",
        amount: float = 0,
        due_date: str = "",
        unit: str = "",
        paybill: str = "",
        account_number: str = "",
        reminder_level: str = "first",  # first, second, final
        landlord_name: str = "",
        property_name: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a rent payment reminder message for WhatsApp."""
        if not amount:
            return {"success": False, "error": "Amount is required"}

        amount_formatted = f"KES {amount:,.0f}"

        if not due_date:
            due_date = datetime.now().strftime("%d/%m/%Y")

        # Payment instructions
        payment_info = ""
        if paybill and account_number:
            payment_info = (
                f"\n\n💳 *Payment Details:*\n"
                f"• Paybill: {paybill}\n"
                f"• Account: {account_number}\n"
                f"• Amount: {amount_formatted}"
            )
        elif paybill:
            payment_info = f"\n\n💳 *Paybill:* {paybill} | *Amount:* {amount_formatted}"

        unit_info = f" for *{unit}*" if unit else ""
        property_info = f" at *{property_name}*" if property_name else ""
        sign_off = f"\n\n_{landlord_name or 'Property Management'}_" if landlord_name else ""

        if reminder_level == "first":
            message = (
                f"🏠 *Rent Reminder*\n\n"
                f"Dear *{tenant_name}*,\n\n"
                f"This is a friendly reminder that your rent payment of *{amount_formatted}*{unit_info}{property_info} "
                f"is due on *{due_date}*.\n\n"
                f"Please make your payment on time to avoid any inconvenience.{payment_info}"
                f"\n\nThank you! 🙏{sign_off}"
            )
        elif reminder_level == "second":
            message = (
                f"⚠️ *Rent Payment Overdue*\n\n"
                f"Dear *{tenant_name}*,\n\n"
                f"Your rent of *{amount_formatted}*{unit_info}{property_info} was due on *{due_date}* "
                f"and remains unpaid.\n\n"
                f"Please make your payment as soon as possible to avoid penalties.{payment_info}"
                f"\n\nKindly contact us if you have any issues.{sign_off}"
            )
        elif reminder_level == "final":
            message = (
                f"🚨 *FINAL RENT NOTICE*\n\n"
                f"Dear *{tenant_name}*,\n\n"
                f"This is a *final notice* regarding your overdue rent of *{amount_formatted}*{unit_info}{property_info}.\n\n"
                f"Original due date: *{due_date}*\n\n"
                f"Failure to pay within *48 hours* may result in further action "
                f"as per your lease agreement.{payment_info}"
                f"\n\nPlease contact us immediately to resolve this matter.{sign_off}"
            )
        else:
            message = (
                f"🏠 *Rent Payment Reminder*\n\n"
                f"Dear *{tenant_name}*, your rent of *{amount_formatted}*{unit_info} "
                f"is due on *{due_date}*.{payment_info}{sign_off}"
            )

        return {
            "success": True,
            "message": message,
            "formatted_amount": amount_formatted,
            "reminder_level": reminder_level,
            "tenant_name": tenant_name,
            "is_overdue": reminder_level in ("second", "final")
        }

    # ──────────────────────────────────────────────────────────────
    # 3. PAYMENT RECEIPT
    # ──────────────────────────────────────────────────────────────

    async def format_payment_receipt(
        self,
        tenant_name: str = "Tenant",
        amount: float = 0,
        payment_method: str = "M-Pesa",
        transaction_id: str = "",
        period: str = "",
        unit: str = "",
        property_name: str = "",
        balance: float = 0,
        **kwargs
    ) -> Dict[str, Any]:
        """Format a payment receipt message for WhatsApp."""
        if not amount:
            return {"success": False, "error": "Amount is required"}

        amount_formatted = f"KES {amount:,.0f}"
        now = datetime.now()
        receipt_no = f"RCP-{now.strftime('%Y%m%d%H%M%S')}"

        if not period:
            period = now.strftime("%B %Y")

        unit_info = f"\n📍 Unit: {unit}" if unit else ""
        property_info = f"\n🏢 Property: {property_name}" if property_name else ""
        tx_info = f"\n🆔 Transaction: {transaction_id}" if transaction_id else ""

        balance_info = ""
        if balance > 0:
            balance_info = f"\n\n⚠️ *Outstanding Balance:* KES {balance:,.0f}"
        elif balance == 0:
            balance_info = "\n\n✅ *Fully Paid* — No outstanding balance"

        message = (
            f"✅ *PAYMENT RECEIPT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Receipt No: *{receipt_no}*\n"
            f"👤 Tenant: *{tenant_name}*{unit_info}{property_info}\n"
            f"📅 Period: *{period}*\n\n"
            f"💰 Amount Paid: *{amount_formatted}*\n"
            f"💳 Method: {payment_method}{tx_info}\n"
            f"🕐 Date: {now.strftime('%d %b %Y, %I:%M %p')}"
            f"{balance_info}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Thank you for your payment!_ 🙏"
        )

        return {
            "success": True,
            "message": message,
            "receipt_number": receipt_no,
            "formatted_amount": amount_formatted,
            "period": period,
            "has_balance": balance > 0
        }

    # ──────────────────────────────────────────────────────────────
    # 4. PROPERTY LISTING FORMATTER
    # ──────────────────────────────────────────────────────────────

    async def format_listing(
        self,
        property_type: str = "Apartment",
        bedrooms: int = 0,
        price: float = 0,
        location: str = "",
        amenities: List[str] = None,
        description: str = "",
        listing_type: str = "rent",  # rent or sale
        contact_phone: str = "",
        contact_name: str = "",
        available_from: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a property listing for WhatsApp broadcast."""
        if not price:
            return {"success": False, "error": "Price is required"}

        price_formatted = f"KES {price:,.0f}"
        price_label = "/month" if listing_type == "rent" else ""

        br_text = ""
        if bedrooms == 0:
            br_text = "Bedsitter"
        elif bedrooms > 0:
            br_text = f"{bedrooms} Bedroom{'s' if bedrooms > 1 else ''}"

        amenities_text = ""
        if amenities:
            amenities_text = "\n\n✨ *Amenities:*\n" + "\n".join(f"  • {a}" for a in amenities)

        desc_text = f"\n\n{description}" if description else ""
        avail_text = f"\n📅 Available: {available_from}" if available_from else ""

        icon = "🏠" if listing_type == "rent" else "🏡"
        action = "FOR RENT" if listing_type == "rent" else "FOR SALE"

        contact_text = ""
        if contact_phone:
            contact_text = f"\n\n📞 Contact: {contact_name + ' — ' if contact_name else ''}{contact_phone}"
        elif contact_name:
            contact_text = f"\n\n📞 Contact: {contact_name}"

        message = (
            f"{icon} *{action}: {br_text} {property_type.title()}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📍 Location: *{location or 'Thika'}*\n"
            f"💰 Price: *{price_formatted}{price_label}*"
            f"{avail_text}"
            f"{desc_text}"
            f"{amenities_text}"
            f"{contact_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Reply 'VIEW' to schedule a viewing_ 👀"
        )

        return {
            "success": True,
            "message": message,
            "formatted_price": price_formatted,
            "property_summary": f"{br_text} {property_type.title()} in {location or 'Thika'}",
            "listing_type": listing_type
        }

    # ──────────────────────────────────────────────────────────────
    # 5. MAINTENANCE REQUEST CLASSIFIER
    # ──────────────────────────────────────────────────────────────

    async def classify_maintenance(
        self,
        message: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Classify a maintenance request by category and priority."""
        if not message:
            return {"success": False, "error": "Message text is required"}

        msg_lower = message.lower()

        # Category detection
        categories = {
            "plumbing": ["leak", "water", "pipe", "tap", "drain", "toilet", "sink",
                        "maji", "bomba", "choo", "drainage", "sewer", "blocked"],
            "electrical": ["power", "light", "socket", "switch", "bulb", "wire",
                          "stima", "electrical", "blackout", "sparking", "tripping"],
            "structural": ["wall", "ceiling", "floor", "door", "window", "roof",
                          "crack", "broken", "ukuta", "mlango", "dari"],
            "appliance": ["fridge", "cooker", "washing", "heater", "oven", "microwave",
                         "machine", "appliance", "boiler"],
            "pest_control": ["cockroach", "rat", "mice", "ant", "termite", "bug",
                           "pest", "mdudu", "panya"],
            "security": ["lock", "key", "gate", "cctv", "camera", "alarm",
                        "kufuli", "ufunguo"],
            "general": ["paint", "clean", "garbage", "noise", "smell", "mold"]
        }

        detected_category = "general"
        for cat, keywords in categories.items():
            if any(kw in msg_lower for kw in keywords):
                detected_category = cat
                break

        # Priority detection
        emergency_words = ["flood", "fire", "gas", "spark", "collapse", "emergency",
                          "danger", "hatari", "moto", "immediately", "urgent"]
        high_words = ["leak", "no water", "no power", "broken lock", "blocked",
                     "overflow", "vunja"]
        
        priority = "normal"
        if any(w in msg_lower for w in emergency_words):
            priority = "emergency"
        elif any(w in msg_lower for w in high_words):
            priority = "high"

        # Extract unit/room mention
        unit = None
        unit_match = re.search(r'(?:unit|room|house|flat|apt|#)\s*(\w+)', msg_lower)
        if unit_match:
            unit = unit_match.group(1).upper()

        return {
            "success": True,
            "category": detected_category,
            "priority": priority,
            "unit": unit,
            "original_message": message,
            "requires_immediate_action": priority == "emergency",
            "suggested_response_time": {
                "emergency": "30 minutes",
                "high": "4 hours",
                "normal": "24-48 hours"
            }.get(priority, "24-48 hours"),
            "message": f"Maintenance request classified: {detected_category} ({priority} priority)"
        }

    # ──────────────────────────────────────────────────────────────
    # 6. MAINTENANCE RESPONSE FORMATTER
    # ──────────────────────────────────────────────────────────────

    async def format_maintenance_response(
        self,
        tenant_name: str = "Tenant",
        category: str = "general",
        priority: str = "normal",
        ticket_id: str = "",
        estimated_time: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a maintenance acknowledgment message."""
        if not ticket_id:
            ticket_id = f"MNT-{datetime.now().strftime('%d%m%H%M')}"

        if not estimated_time:
            estimated_time = {
                "emergency": "30 minutes",
                "high": "4 hours",
                "normal": "24-48 hours"
            }.get(priority, "24-48 hours")

        priority_icon = {"emergency": "🚨", "high": "⚠️", "normal": "🔧"}.get(priority, "🔧")

        message = (
            f"{priority_icon} *Maintenance Request Received*\n\n"
            f"Dear *{tenant_name}*,\n\n"
            f"We have received your maintenance request.\n\n"
            f"📋 *Ticket:* {ticket_id}\n"
            f"🏷️ *Category:* {category.replace('_', ' ').title()}\n"
            f"📊 *Priority:* {priority.upper()}\n"
            f"⏱️ *Estimated Response:* {estimated_time}\n\n"
            f"{'⚡ Our team is being dispatched immediately.' if priority == 'emergency' else 'Our maintenance team will attend to this as soon as possible.'}\n\n"
            f"_Reply to this message with any additional details or photos._"
        )

        return {
            "success": True,
            "message": message,
            "ticket_id": ticket_id,
            "priority": priority,
            "category": category,
            "estimated_time": estimated_time
        }

    # ──────────────────────────────────────────────────────────────
    # 7. VIEWING SLOTS FORMATTER
    # ──────────────────────────────────────────────────────────────

    async def format_viewing_slots(
        self,
        property_description: str = "the property",
        slots: List[str] = None,
        location: str = "",
        agent_name: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format available viewing time slots for WhatsApp."""
        if not slots:
            # Generate default slots for next 3 days
            base = datetime.now()
            slots = []
            for i in range(1, 4):
                day = base + timedelta(days=i)
                if day.weekday() < 6:  # Mon-Sat
                    slots.append(f"{day.strftime('%A %d %b')} — 10:00 AM")
                    slots.append(f"{day.strftime('%A %d %b')} — 2:00 PM")

        slots_text = "\n".join(f"  {i+1}️⃣ {slot}" for i, slot in enumerate(slots[:6]))
        location_text = f"\n📍 *Location:* {location}" if location else ""
        agent_text = f"\n👤 *Agent:* {agent_name}" if agent_name else ""

        message = (
            f"🏠 *Property Viewing — {property_description}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{location_text}{agent_text}\n\n"
            f"📅 *Available Slots:*\n\n"
            f"{slots_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Reply with the *number* of your preferred slot to book._ ✅"
        )

        return {
            "success": True,
            "message": message,
            "available_slots": slots[:6],
            "slot_count": len(slots[:6])
        }

    # ──────────────────────────────────────────────────────────────
    # 8. VIEWING CONFIRMATION
    # ──────────────────────────────────────────────────────────────

    async def format_viewing_confirmation(
        self,
        tenant_name: str = "Client",
        property_description: str = "the property",
        date_time: str = "",
        location: str = "",
        agent_name: str = "",
        agent_phone: str = "",
        latitude: str = "",
        longitude: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a viewing booking confirmation."""
        location_text = f"\n📍 *Address:* {location}" if location else ""
        agent_info = ""
        if agent_name:
            agent_info = f"\n👤 *Agent:* {agent_name}"
            if agent_phone:
                agent_info += f" ({agent_phone})"

        message = (
            f"✅ *Viewing Confirmed!*\n\n"
            f"Dear *{tenant_name}*,\n\n"
            f"Your viewing for *{property_description}* has been confirmed.\n\n"
            f"📅 *When:* {date_time}"
            f"{location_text}"
            f"{agent_info}\n\n"
            f"📌 *Please bring:*\n"
            f"  • Valid ID (National ID/Passport)\n"
            f"  • Proof of income (if renting)\n\n"
            f"_We'll send you a reminder 24 hours before. See you there!_ 🏠"
        )

        result = {
            "success": True,
            "message": message,
            "date_time": date_time,
            "location": location
        }

        # Include location data for WhatsApp location message
        if latitude and longitude:
            result["send_location"] = True
            result["latitude"] = latitude
            result["longitude"] = longitude

        return result

    # ──────────────────────────────────────────────────────────────
    # 9. RENT STATEMENT GENERATOR
    # ──────────────────────────────────────────────────────────────

    async def generate_rent_statement(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        monthly_rent: float = 0,
        payments: List[Dict[str, Any]] = None,
        period: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a rent statement summary message."""
        if not monthly_rent:
            return {"success": False, "error": "Monthly rent amount is required"}

        if not payments:
            payments = []

        if not period:
            period = datetime.now().strftime("%B %Y")

        total_paid = sum(p.get("amount", 0) for p in payments)
        total_expected = monthly_rent
        balance = total_expected - total_paid

        payments_text = ""
        if payments:
            for p in payments:
                date = p.get("date", "N/A")
                amt = p.get("amount", 0)
                method = p.get("method", "M-Pesa")
                ref = p.get("reference", "")
                payments_text += f"\n  ✅ {date} — KES {amt:,.0f} ({method}){' [' + ref + ']' if ref else ''}"
        else:
            payments_text = "\n  ❌ No payments recorded"

        unit_text = f" — Unit {unit}" if unit else ""
        status_icon = "✅" if balance <= 0 else "⚠️"
        status_text = "PAID" if balance <= 0 else f"BALANCE DUE: KES {balance:,.0f}"

        message = (
            f"📊 *RENT STATEMENT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Tenant: *{tenant_name}*{unit_text}\n"
            f"📅 Period: *{period}*\n"
            f"💰 Monthly Rent: *KES {monthly_rent:,.0f}*\n\n"
            f"📝 *Payments:*{payments_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Total Paid: KES {total_paid:,.0f}\n"
            f"{status_icon} Status: *{status_text}*\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return {
            "success": True,
            "message": message,
            "total_paid": total_paid,
            "total_expected": total_expected,
            "balance": balance,
            "is_fully_paid": balance <= 0,
            "payment_count": len(payments)
        }

    # ──────────────────────────────────────────────────────────────
    # 10. LANDLORD REPORT GENERATOR
    # ──────────────────────────────────────────────────────────────

    async def generate_landlord_report(
        self,
        landlord_name: str = "Landlord",
        property_name: str = "Property",
        total_units: int = 0,
        occupied_units: int = 0,
        total_rent_expected: float = 0,
        total_rent_collected: float = 0,
        maintenance_count: int = 0,
        maintenance_cost: float = 0,
        period: str = "",
        unpaid_tenants: List[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a monthly landlord summary report."""
        if not period:
            period = datetime.now().strftime("%B %Y")

        occupancy_rate = (occupied_units / total_units * 100) if total_units > 0 else 0
        collection_rate = (total_rent_collected / total_rent_expected * 100) if total_rent_expected > 0 else 0
        net_income = total_rent_collected - maintenance_cost
        outstanding = total_rent_expected - total_rent_collected

        unpaid_text = ""
        if unpaid_tenants:
            unpaid_list = "\n".join(f"  • {t}" for t in unpaid_tenants[:10])
            unpaid_text = f"\n\n👥 *Unpaid Tenants:*\n{unpaid_list}"
            if len(unpaid_tenants) > 10:
                unpaid_text += f"\n  ... and {len(unpaid_tenants) - 10} more"

        message = (
            f"📊 *MONTHLY PROPERTY REPORT*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *{landlord_name}*\n"
            f"🏢 *{property_name}*\n"
            f"📅 *{period}*\n\n"
            f"🏠 *Occupancy:*\n"
            f"  • Units: {occupied_units}/{total_units} ({occupancy_rate:.0f}%)\n"
            f"  • Vacant: {total_units - occupied_units}\n\n"
            f"💰 *Financials:*\n"
            f"  • Expected: KES {total_rent_expected:,.0f}\n"
            f"  • Collected: KES {total_rent_collected:,.0f} ({collection_rate:.0f}%)\n"
            f"  • Outstanding: KES {outstanding:,.0f}\n\n"
            f"🔧 *Maintenance:*\n"
            f"  • Requests: {maintenance_count}\n"
            f"  • Cost: KES {maintenance_cost:,.0f}\n\n"
            f"📈 *Net Income: KES {net_income:,.0f}*"
            f"{unpaid_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )

        return {
            "success": True,
            "message": message,
            "occupancy_rate": round(occupancy_rate, 1),
            "collection_rate": round(collection_rate, 1),
            "net_income": net_income,
            "outstanding": outstanding,
            "period": period
        }

    # ──────────────────────────────────────────────────────────────
    # 11. TENANT WELCOME MESSAGE
    # ──────────────────────────────────────────────────────────────

    async def format_tenant_welcome(
        self,
        tenant_name: str = "Tenant",
        unit: str = "",
        property_name: str = "",
        landlord_name: str = "",
        rent_amount: float = 0,
        due_date: str = "5th of every month",
        rules: List[str] = None,
        paybill: str = "",
        account_number: str = "",
        caretaker_phone: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format a tenant onboarding welcome message."""
        unit_text = f" to *{unit}*" if unit else ""
        property_text = f" at *{property_name}*" if property_name else ""

        rules_text = ""
        if rules:
            rules_list = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(rules))
            rules_text = f"\n\n📋 *House Rules:*\n{rules_list}"

        payment_text = ""
        if rent_amount:
            payment_text = f"\n\n💰 *Rent Details:*\n  • Amount: KES {rent_amount:,.0f}\n  • Due: {due_date}"
            if paybill:
                payment_text += f"\n  • Paybill: {paybill}"
            if account_number:
                payment_text += f"\n  • Account: {account_number}"

        caretaker_text = f"\n\n🔑 *Caretaker:* {caretaker_phone}" if caretaker_phone else ""

        message = (
            f"🏠 *Welcome{unit_text}{property_text}!*\n\n"
            f"Dear *{tenant_name}*,\n\n"
            f"Welcome to your new home! We're glad to have you as a tenant."
            f"{payment_text}"
            f"{rules_text}"
            f"{caretaker_text}\n\n"
            f"For any maintenance issues, simply send a message here describing the problem "
            f"and our team will respond promptly.\n\n"
            f"_We wish you a pleasant stay!_ 🙏\n"
            f"_{landlord_name or 'Management'}_"
        )

        return {
            "success": True,
            "message": message,
            "tenant_name": tenant_name,
            "unit": unit
        }

    # ──────────────────────────────────────────────────────────────
    # 12. LEASE RENEWAL REMINDER
    # ──────────────────────────────────────────────────────────────

    async def format_lease_reminder(
        self,
        tenant_name: str = "Tenant",
        expiry_date: str = "",
        unit: str = "",
        new_rent: float = 0,
        current_rent: float = 0,
        days_until_expiry: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """Format a lease renewal reminder."""
        unit_text = f" for *Unit {unit}*" if unit else ""

        rent_change_text = ""
        if new_rent and current_rent and new_rent != current_rent:
            diff = new_rent - current_rent
            direction = "increase" if diff > 0 else "decrease"
            rent_change_text = (
                f"\n\n💰 *Rent Update:*\n"
                f"  • Current: KES {current_rent:,.0f}\n"
                f"  • New: KES {new_rent:,.0f} ({direction} of KES {abs(diff):,.0f})"
            )

        urgency = ""
        if days_until_expiry <= 7:
            urgency = "🚨 *URGENT — Expires in less than 1 week!*\n\n"
        elif days_until_expiry <= 14:
            urgency = "⚠️ *Expiring Soon!*\n\n"

        message = (
            f"📋 *Lease Renewal Notice*\n\n"
            f"{urgency}"
            f"Dear *{tenant_name}*,\n\n"
            f"Your lease{unit_text} expires on *{expiry_date}* "
            f"(*{days_until_expiry} days* from today).\n\n"
            f"Please confirm if you wish to:\n"
            f"  1️⃣ Renew your lease\n"
            f"  2️⃣ Vacate the premises"
            f"{rent_change_text}\n\n"
            f"_Reply with 1 or 2 to confirm._ ✅"
        )

        return {
            "success": True,
            "message": message,
            "days_until_expiry": days_until_expiry,
            "is_urgent": days_until_expiry <= 14
        }

    # ──────────────────────────────────────────────────────────────
    # 13. M-PESA CONFIRMATION PARSER
    # ──────────────────────────────────────────────────────────────

    async def parse_mpesa_confirmation(
        self,
        message: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Parse M-Pesa SMS confirmation text to extract payment details."""
        if not message:
            return {"success": False, "error": "M-Pesa confirmation message is required"}

        match = self.MPESA_PATTERN.search(message)
        if match:
            transaction_id = match.group(1)
            amount = float(match.group(2).replace(",", ""))
            date = match.group(3)

            return {
                "success": True,
                "transaction_id": transaction_id,
                "amount": amount,
                "date": date,
                "is_valid_mpesa": True,
                "message": f"Parsed M-Pesa payment: KES {amount:,.0f} (Ref: {transaction_id})"
            }
        else:
            # Try simpler extraction
            tx_match = re.search(r'([A-Z0-9]{10})', message)
            amt_match = re.search(r'[Kk][Ss]h?\s*([\d,]+)', message)

            return {
                "success": True,
                "transaction_id": tx_match.group(1) if tx_match else None,
                "amount": float(amt_match.group(1).replace(",", "")) if amt_match else None,
                "date": None,
                "is_valid_mpesa": False,
                "message": "Could not fully parse M-Pesa message — partial data extracted"
            }

    # ──────────────────────────────────────────────────────────────
    # 14. BROADCAST LISTING FORMATTER
    # ──────────────────────────────────────────────────────────────

    async def format_broadcast_listing(
        self,
        listings: List[Dict[str, Any]] = None,
        agency_name: str = "",
        contact_phone: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format multiple property listings for a single broadcast message."""
        if not listings:
            return {"success": False, "error": "At least one listing is required"}

        header = f"🏘️ *{agency_name or 'NEW LISTINGS'} — Available Properties*\n"
        header += "━━━━━━━━━━━━━━━━━━━━\n"

        listing_lines = []
        for i, listing in enumerate(listings[:5], 1):  # Max 5 per broadcast
            ptype = listing.get("type", "Property")
            br = listing.get("bedrooms", "")
            price = listing.get("price", 0)
            location = listing.get("location", "Thika")
            listing_type = listing.get("listing_type", "rent")

            br_text = f"{br}BR " if br else ""
            price_text = f"KES {price:,.0f}" if price else "Negotiable"
            suffix = "/mo" if listing_type == "rent" else ""

            listing_lines.append(
                f"\n{i}️⃣ *{br_text}{ptype}* — {location}\n"
                f"   💰 {price_text}{suffix}"
            )

        footer = ""
        if contact_phone:
            footer = f"\n\n📞 Call/WhatsApp: {contact_phone}"
        footer += "\n\n_Reply with the listing number for more details_ 📱"

        message = header + "".join(listing_lines) + "\n\n━━━━━━━━━━━━━━━━━━━━" + footer

        return {
            "success": True,
            "message": message,
            "listing_count": len(listings[:5]),
            "truncated": len(listings) > 5
        }

    # ──────────────────────────────────────────────────────────────
    # 15. ESCALATION NOTICE
    # ──────────────────────────────────────────────────────────────

    async def format_escalation_notice(
        self,
        tenant_name: str = "Tenant",
        issue_type: str = "rent",  # rent, maintenance, lease
        details: str = "",
        unit: str = "",
        phone: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """Format an escalation notice for the landlord/manager."""
        unit_text = f" (Unit {unit})" if unit else ""
        phone_text = f"\n📞 Phone: {phone}" if phone else ""

        icon = {"rent": "💰", "maintenance": "🔧", "lease": "📋"}.get(issue_type, "⚠️")
        title = {
            "rent": "OVERDUE RENT ESCALATION",
            "maintenance": "URGENT MAINTENANCE ESCALATION",
            "lease": "LEASE EXPIRY ESCALATION"
        }.get(issue_type, "ESCALATION NOTICE")

        message = (
            f"{icon} *{title}*\n\n"
            f"👤 Tenant: *{tenant_name}*{unit_text}"
            f"{phone_text}\n\n"
            f"📝 *Details:*\n{details}\n\n"
            f"⏰ *Time:* {datetime.now().strftime('%d %b %Y, %I:%M %p')}\n\n"
            f"_Please take action on this matter._"
        )

        return {
            "success": True,
            "message": message,
            "issue_type": issue_type,
            "tenant_name": tenant_name,
            "escalated_at": datetime.now().isoformat()
        }


# Global singleton instance
real_estate_service = RealEstateService()
