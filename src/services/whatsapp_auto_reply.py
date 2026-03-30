"""
WhatsApp Auto-Reply Processing Engine.
This is the core of the "viral" feature - automatic responses to incoming messages.
"""

import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from ..models import (
    WhatsAppContact, WhatsAppMessage, WhatsAppAutoReply,
    WhatsAppBusinessProfile, WhatsAppMessageDirection,
    WhatsAppMessageStatus, WhatsAppAutoReplyTrigger, Connection
)
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class AutoReplyEngine:
    """
    Engine for processing incoming WhatsApp messages and sending auto-replies.
    
    Trigger Priority (highest first):
    1. Check if contact is blocked -> skip
    2. Check keyword triggers -> immediate response
    3. Check business hours -> away message
    4. Check first_message trigger -> welcome message
    5. Check "all" trigger (AI mode) -> generate AI response
    """
    
    def __init__(self):
        self.whatsapp_service = WhatsAppService()
    
    async def process_incoming_message(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        contact: WhatsAppContact,
        message: WhatsAppMessage
    ) -> Optional[WhatsAppMessage]:
        """
        Process an incoming message and send auto-reply if applicable.
        Returns the sent reply message, or None if no reply was sent.
        """
        try:
            logger.info(f"[AUTO-REPLY] Processing message from {contact.phone_number}")
            
            # Skip if contact is blocked
            if contact.is_blocked:
                logger.info(f"[AUTO-REPLY] Skipping blocked contact {contact.phone_number}")
                return None
            
            # Get active auto-reply rules for this user, ordered by priority
            result = await db.execute(
                select(WhatsAppAutoReply).filter(
                    WhatsAppAutoReply.user_id == user_id,
                    WhatsAppAutoReply.is_active == True
                ).order_by(desc(WhatsAppAutoReply.priority))
            )
            rules = result.scalars().all()
            
            if not rules:
                logger.info(f"[AUTO-REPLY] No active rules for user {user_id}")
                return None
            
            # Get business profile for context
            profile_result = await db.execute(
                select(WhatsAppBusinessProfile).filter(
                    WhatsAppBusinessProfile.user_id == user_id
                )
            )
            profile = profile_result.scalar_one_or_none()
            
            # Check each rule in priority order
            for rule in rules:
                matched = await self._check_rule_match(rule, contact, message, profile)
                
                if matched:
                    logger.info(f"[AUTO-REPLY] Rule '{rule.name}' matched!")
                    
                    # Generate response based on rule type
                    response_text = await self._generate_response(
                        db, rule, contact, message, profile
                    )
                    
                    if response_text:
                        # Send the reply
                        reply_msg = await self._send_reply(
                            db, user_id, contact, response_text, rule
                        )
                        
                        # Update rule stats
                        rule.times_triggered = (rule.times_triggered or 0) + 1
                        rule.last_triggered_at = datetime.utcnow()
                        await db.commit()
                        
                        return reply_msg
            
            logger.info(f"[AUTO-REPLY] No rules matched for message")
            return None
            
        except Exception as e:
            logger.error(f"[AUTO-REPLY] Error processing message: {e}")
            return None
    
    async def _check_rule_match(
        self,
        rule: WhatsAppAutoReply,
        contact: WhatsAppContact,
        message: WhatsAppMessage,
        profile: Optional[WhatsAppBusinessProfile]
    ) -> bool:
        """Check if a rule matches the incoming message."""
        
        trigger_type = rule.trigger_type
        
        if trigger_type == WhatsAppAutoReplyTrigger.KEYWORD.value:
            # Check if message contains any of the keywords
            keywords = (rule.trigger_value or "").lower().split("|")
            message_text = (message.content or "").lower()
            
            for keyword in keywords:
                if keyword.strip() and keyword.strip() in message_text:
                    logger.info(f"[AUTO-REPLY] Keyword '{keyword}' matched")
                    return True
            return False
            
        elif trigger_type == WhatsAppAutoReplyTrigger.FIRST_MESSAGE.value:
            # Check if this is the contact's first message
            # (message_count was 0 before this message)
            if contact.message_count <= 1:
                logger.info(f"[AUTO-REPLY] First message trigger matched")
                return True
            return False
            
        elif trigger_type == WhatsAppAutoReplyTrigger.BUSINESS_HOURS.value:
            # Check if current time is outside business hours
            if profile and profile.business_hours:
                is_open = self._is_within_business_hours(
                    profile.business_hours,
                    profile.timezone or "Africa/Nairobi"
                )
                if not is_open:
                    logger.info(f"[AUTO-REPLY] Outside business hours")
                    return True
            return False
            
        elif trigger_type == WhatsAppAutoReplyTrigger.ALL.value:
            # Match all messages (AI mode)
            logger.info(f"[AUTO-REPLY] 'All' trigger matched")
            return True
        
        return False
    
    async def _generate_response(
        self,
        db: AsyncSession,
        rule: WhatsAppAutoReply,
        contact: WhatsAppContact,
        message: WhatsAppMessage,
        profile: Optional[WhatsAppBusinessProfile]
    ) -> Optional[str]:
        """Generate the response text based on rule type."""
        
        response_type = rule.response_type
        
        if response_type == "text":
            # Simple text response with variable substitution
            text = rule.response_content or ""
            text = self._substitute_variables(text, contact, message, profile)
            return text
            
        elif response_type == "template":
            # Template-based response (would need to use WhatsApp template API)
            # For now, just return the template name as text
            return f"[Template: {rule.response_content}]"
            
        elif response_type == "ai":
            # AI-generated response
            return await self._generate_ai_response(
                db, rule, contact, message, profile
            )
        
        return None
    
    def _substitute_variables(
        self,
        text: str,
        contact: WhatsAppContact,
        message: WhatsAppMessage,
        profile: Optional[WhatsAppBusinessProfile]
    ) -> str:
        """Replace template variables in text."""
        
        # Contact variables
        text = text.replace("{{name}}", contact.name or contact.profile_name or "there")
        text = text.replace("{{phone}}", contact.phone_number or "")
        
        # Business variables
        if profile:
            text = text.replace("{{business_name}}", profile.business_name or "our business")
        else:
            text = text.replace("{{business_name}}", "our business")
        
        # Time variables
        now = datetime.now()
        text = text.replace("{{time}}", now.strftime("%H:%M"))
        text = text.replace("{{date}}", now.strftime("%d/%m/%Y"))
        
        # Greeting based on time
        hour = now.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"
        text = text.replace("{{greeting}}", greeting)
        
        return text
    
    async def _generate_ai_response(
        self,
        db: AsyncSession,
        rule: WhatsAppAutoReply,
        contact: WhatsAppContact,
        message: WhatsAppMessage,
        profile: Optional[WhatsAppBusinessProfile]
    ) -> str:
        """Generate an AI response using the existing chat infrastructure."""
        try:
            # Build context for AI
            context_parts = []
            
            if profile:
                if profile.business_name:
                    context_parts.append(f"Business: {profile.business_name}")
                if profile.description:
                    context_parts.append(f"About: {profile.description}")
                if profile.products:
                    products = ", ".join([p.get("name", "") for p in profile.products[:5]])
                    context_parts.append(f"Products: {products}")
                if profile.faqs:
                    faq_text = "\n".join([
                        f"Q: {f.get('question', '')} A: {f.get('answer', '')}"
                        for f in profile.faqs[:5]
                    ])
                    context_parts.append(f"FAQs:\n{faq_text}")
            
            if rule.ai_context:
                context_parts.append(f"Additional context: {rule.ai_context}")
            
            context = "\n".join(context_parts)
            
            # Build the prompt
            system_prompt = f"""You are a helpful WhatsApp assistant for a business.
{context}

Instructions:
- Keep responses brief (under 150 words)
- Be friendly and professional
- Use simple language
- If you can't answer, say "Let me connect you with our team"
- Don't make up information not provided in the context
- Respond in the same language as the customer message
"""
            
            user_message = message.content or ""
            
            # Use existing AI service (simplified - you can integrate with your chat service)
            # For now, return a placeholder that would be replaced with actual AI call
            try:
                from ..services.ai_service import generate_response
                response = await generate_response(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    max_tokens=rule.ai_max_tokens or 150
                )
                return response
            except ImportError:
                # Fallback if AI service not available
                logger.warning("[AUTO-REPLY] AI service not available, using fallback")
                return f"Thanks for your message! Our team will respond shortly. 🙏"
                
        except Exception as e:
            logger.error(f"[AUTO-REPLY] AI generation error: {e}")
            return "Thanks for reaching out! We'll get back to you soon."
    
    async def _send_reply(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        contact: WhatsAppContact,
        text: str,
        rule: WhatsAppAutoReply
    ) -> Optional[WhatsAppMessage]:
        """Send the auto-reply via WhatsApp API."""
        try:
            # Get user's WhatsApp connection config
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user_id,
                    Connection.platform == "whatsapp",
                    Connection.status == "active"
                )
            )
            connection = result.scalar_one_or_none()
            
            if not connection:
                logger.error(f"[AUTO-REPLY] No active WhatsApp connection for user {user_id}")
                return None
            
            config = connection.config or {}
            
            # Send message
            result = await self.whatsapp_service.send_message(
                to_number=contact.phone_number,
                message=text,
                config=config
            )
            
            if not result.get("success"):
                logger.error(f"[AUTO-REPLY] Failed to send: {result.get('error')}")
                return None
            
            # Save outgoing message
            reply_message = WhatsAppMessage(
                user_id=user_id,
                contact_id=contact.id,
                direction=WhatsAppMessageDirection.OUTGOING,
                message_type="text",
                content=text,
                whatsapp_message_id=result.get("message_id"),
                status=WhatsAppMessageStatus.SENT,
                is_auto_reply=True,
                auto_reply_rule_id=rule.id
            )
            db.add(reply_message)
            
            # Update contact's last message time
            contact.last_message_at = datetime.utcnow()
            contact.message_count = (contact.message_count or 0) + 1
            
            await db.commit()
            await db.refresh(reply_message)
            
            logger.info(f"[AUTO-REPLY] Sent reply to {contact.phone_number}: {text[:50]}...")
            
            return reply_message
            
        except Exception as e:
            logger.error(f"[AUTO-REPLY] Error sending reply: {e}")
            return None
    
    def _is_within_business_hours(
        self,
        business_hours: Dict[str, Any],
        timezone: str = "Africa/Nairobi"
    ) -> bool:
        """Check if current time is within business hours."""
        try:
            from zoneinfo import ZoneInfo
            
            now = datetime.now(ZoneInfo(timezone))
            day_name = now.strftime("%A").lower()
            
            day_hours = business_hours.get(day_name)
            if not day_hours:
                # No hours set for this day = closed
                return False
            
            open_time = day_hours.get("open")
            close_time = day_hours.get("close")
            
            if not open_time or not close_time:
                return False
            
            # Parse times
            open_hour, open_min = map(int, open_time.split(":"))
            close_hour, close_min = map(int, close_time.split(":"))
            
            current_minutes = now.hour * 60 + now.minute
            open_minutes = open_hour * 60 + open_min
            close_minutes = close_hour * 60 + close_min
            
            return open_minutes <= current_minutes <= close_minutes
            
        except Exception as e:
            logger.error(f"[AUTO-REPLY] Error checking business hours: {e}")
            return True  # Default to open if we can't determine


# Singleton instance
auto_reply_engine = AutoReplyEngine()
