"""
Email Template Service for the Email Auto-Responder Workflow.
Provides customizable email reply templates by category, supporting variable substitution.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .cache_service import cache_service

logger = logging.getLogger(__name__)


# Default templates for common email categories
DEFAULT_TEMPLATES = {
    "support": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

Thank you for reaching out to our support team. We have received your message regarding "{original_subject}" and a team member will get back to you within 24 hours.

Your ticket reference is: {ticket_id}

In the meantime, you may find helpful resources at our help center.

Best regards,
{company_name} Support Team""",
        "priority": "high"
    },
    "sales": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

Thank you for your interest in {company_name}! We received your inquiry about "{original_subject}" and would love to help.

A member of our sales team will reach out to you within the next business day to discuss your needs in detail.

Best regards,
{company_name} Sales Team""",
        "priority": "high"
    },
    "billing": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

We have received your billing inquiry regarding "{original_subject}". Our finance team is reviewing your request.

You can expect a response within 48 hours. If this is urgent, please reply with "URGENT" in the subject line.

Best regards,
{company_name} Billing Department""",
        "priority": "medium"
    },
    "general": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

Thank you for contacting {company_name}. We have received your email and will respond as soon as possible.

Best regards,
{company_name}""",
        "priority": "low"
    },
    "partnership": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

Thank you for your partnership inquiry. We appreciate your interest in collaborating with {company_name}.

Our business development team will review your proposal and get back to you within 3-5 business days.

Best regards,
{company_name} Partnerships Team""",
        "priority": "medium"
    },
    "feedback": {
        "subject_prefix": "Re: ",
        "body": """Hi {sender_name},

Thank you for sharing your feedback about "{original_subject}". We truly value input from our community.

Your feedback has been forwarded to the relevant team for review.

Best regards,
{company_name}""",
        "priority": "low"
    }
}


class EmailTemplateService:
    """Service for managing and rendering email auto-reply templates."""

    def __init__(self):
        self.cache_key_prefix = "email_template:"
        self._load_defaults_if_missing()

    def _load_defaults_if_missing(self):
        """Load default templates into cache if they don't exist."""
        for category, template in DEFAULT_TEMPLATES.items():
            cache_key = f"{self.cache_key_prefix}{category}"
            # Only set default if nothing exists
            if not cache_service.get(cache_key):
                tpl = {
                    "id": str(uuid4()),
                    "category": category,
                    "subject_prefix": template["subject_prefix"],
                    "body": template["body"],
                    "priority": template["priority"],
                    "is_default": True,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                }
                # Cache defaults indefinitely (or a very long time, e.g., 30 days)
                cache_service.set(cache_key, tpl, expire_seconds=2592000)

    async def get_template(self, category: str) -> Dict[str, Any]:
        """
        Get a template by category.
        Falls back to 'general' if category not found.
        """
        cache_key = f"{self.cache_key_prefix}{category}"
        template = cache_service.get(cache_key)
        
        if not template:
            # Try loading directly from default dict if missing in cache
            if category in DEFAULT_TEMPLATES:
                template = {
                    "id": f"default-{category}",
                    "category": category,
                    "subject_prefix": DEFAULT_TEMPLATES[category]["subject_prefix"],
                    "body": DEFAULT_TEMPLATES[category]["body"],
                    "priority": DEFAULT_TEMPLATES[category]["priority"],
                    "is_default": True
                }
                cache_service.set(cache_key, template, expire_seconds=2592000)
            else:
                # Fallback to general
                fallback_key = f"{self.cache_key_prefix}general"
                template = cache_service.get(fallback_key)
                if not template and "general" in DEFAULT_TEMPLATES:
                    template = {
                        "id": "default-general",
                        "category": "general",
                        "subject_prefix": DEFAULT_TEMPLATES["general"]["subject_prefix"],
                        "body": DEFAULT_TEMPLATES["general"]["body"],
                        "priority": DEFAULT_TEMPLATES["general"]["priority"],
                        "is_default": True
                    }
                    cache_service.set(fallback_key, template, expire_seconds=2592000)
            
        if template:
            return {"success": True, "template": template}
        return {"success": False, "error": f"No template found for category: {category}"}

    async def list_templates(self) -> Dict[str, Any]:
        """List all available templates."""
        # Find all keys matching the prefix
        keys = cache_service.keys(f"{self.cache_key_prefix}*")
        templates = []
        for key in keys:
            tpl = cache_service.get(key)
            if tpl:
                templates.append(tpl)
                
        return {
            "success": True,
            "templates": templates,
            "total": len(templates)
        }

    async def create_template(
        self,
        category: str,
        body: str,
        subject_prefix: str = "Re: ",
        priority: str = "medium"
    ) -> Dict[str, Any]:
        """
        Create or update a custom template for a category.

        Args:
            category: Template category (e.g., 'support', 'sales', 'custom_vip')
            body: Template body with {variable} placeholders
            subject_prefix: Prefix added to reply subject
            priority: Template priority ('high', 'medium', 'low')
        """
        cache_key = f"{self.cache_key_prefix}{category}"
        existing = cache_service.get(cache_key)
        
        template_id = existing.get("id") if existing else str(uuid4())
        created_at = existing.get("created_at") if existing else datetime.utcnow().isoformat()
        
        template_data = {
            "id": template_id,
            "category": category,
            "subject_prefix": subject_prefix,
            "body": body,
            "priority": priority,
            "is_default": False,
            "created_at": created_at,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Cache for 30 days
        cache_service.set(cache_key, template_data, expire_seconds=2592000)
        
        return {
            "success": True,
            "template": template_data,
            "message": f"Template for '{category}' saved successfully."
        }

    async def delete_template(self, category: str) -> Dict[str, Any]:
        """Delete a custom template. Cannot delete default templates."""
        cache_key = f"{self.cache_key_prefix}{category}"
        template = cache_service.get(cache_key)
        
        if not template:
            return {"success": False, "error": f"Template '{category}' not found."}
        if template.get("is_default"):
            return {"success": False, "error": f"Cannot delete default template '{category}'. Update it instead."}
            
        cache_service.delete(cache_key)
        return {"success": True, "message": f"Template '{category}' deleted."}

    async def render_template(
        self,
        category: str,
        variables: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Render a template with variable substitution.

        Args:
            category: Template category to render
            variables: Dict of variable names to values for substitution.
                       Common variables: sender_name, original_subject, ticket_id, company_name
        """
        result = await self.get_template(category)
        if not result["success"]:
            return result

        template = result["template"]
        body = template["body"]
        subject_prefix = template["subject_prefix"]

        # Apply variable substitution
        if variables:
            for key, value in variables.items():
                body = body.replace(f"{{{key}}}", str(value))
                subject_prefix = subject_prefix.replace(f"{{{key}}}", str(value))

        # Fill any remaining placeholders with defaults
        defaults = {
            "sender_name": "there",
            "company_name": "Our Team",
            "ticket_id": f"TKT-{uuid4().hex[:8].upper()}",
            "original_subject": "your inquiry"
        }
        for key, value in defaults.items():
            body = body.replace(f"{{{key}}}", value)
            subject_prefix = subject_prefix.replace(f"{{{key}}}", value)

        return {
            "success": True,
            "rendered_body": body,
            "subject_prefix": subject_prefix,
            "category": category,
            "priority": template["priority"]
        }


# Global singleton instance
email_template_service = EmailTemplateService()
