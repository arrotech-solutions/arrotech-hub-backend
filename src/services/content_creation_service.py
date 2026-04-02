"""
Content Creation Service for generating images, templates, and bulk content.
"""

import asyncio
import base64
import io
import json
import logging
import random
import string
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp
import qrcode
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


class ContentCreationService:
    """Service for content creation, image generation, and templates."""
    
    def __init__(self):
        self.templates = self._load_templates()
        self.image_cache = {}
    
    def _load_templates(self) -> Dict[str, Any]:
        """Load content templates."""
        return {
            "email_welcome": {
                "subject": "Welcome to {company_name}!",
                "body": """
                Hi {first_name},
                
                Welcome to {company_name}! We're excited to have you on board.
                
                Here are some next steps to get started:
                {next_steps}
                
                If you have any questions, feel free to reach out to our support team.
                
                Best regards,
                The {company_name} Team
                """,
                "variables": ["company_name", "first_name", "next_steps"]
            },
            "social_post": {
                "text": """
                🎉 {announcement}
                
                {description}
                
                {call_to_action}
                
                #{hashtags}
                """,
                "variables": ["announcement", "description", "call_to_action", "hashtags"]
            },
            "blog_post": {
                "title": "{title}",
                "content": """
                # {title}
                
                ## Introduction
                {introduction}
                
                ## Main Content
                {main_content}
                
                ## Conclusion
                {conclusion}
                
                ---
                *Published on {date}*
                """,
                "variables": ["title", "introduction", "main_content", "conclusion", "date"]
            },
            "product_description": {
                "title": "{product_name}",
                "description": """
                ## {product_name}
                
                {short_description}
                
                ### Key Features:
                {features}
                
                ### Benefits:
                {benefits}
                
                ### Pricing:
                {pricing}
                
                [Learn More](#)
                """,
                "variables": ["product_name", "short_description", "features", "benefits", "pricing"]
            },
            "newsletter": {
                "subject": "{newsletter_title} - {date}",
                "body": """
                # {newsletter_title}
                
                ## Featured Story
                {featured_story}
                
                ## Latest Updates
                {updates}
                
                ## Upcoming Events
                {events}
                
                ## Quick Links
                {quick_links}
                
                ---
                *Unsubscribe | View in browser*
                """,
                "variables": ["newsletter_title", "date", "featured_story", "updates", "events", "quick_links"]
            }
        }
    
    async def generate_image_from_text(self, text: str, style: str = "modern", size: tuple = (800, 600)) -> Dict[str, Any]:
        """Generate an image from text with various styles."""
        try:
            # Create image
            img = Image.new('RGB', size, color='white')
            draw = ImageDraw.Draw(img)
            
            # Try to load a font, fall back to default if not available
            try:
                font_size = min(size) // 20
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                font = ImageFont.load_default()
            
            # Apply style
            if style == "modern":
                background_color = (240, 248, 255)  # Light blue
                text_color = (51, 51, 51)  # Dark gray
                accent_color = (70, 130, 180)  # Steel blue
            elif style == "minimal":
                background_color = (255, 255, 255)  # White
                text_color = (0, 0, 0)  # Black
                accent_color = (128, 128, 128)  # Gray
            elif style == "vintage":
                background_color = (245, 245, 220)  # Beige
                text_color = (139, 69, 19)  # Saddle brown
                accent_color = (160, 82, 45)  # Sienna
            else:
                background_color = (255, 255, 255)
                text_color = (0, 0, 0)
                accent_color = (128, 128, 128)
            
            # Fill background
            draw.rectangle([0, 0, size[0], size[1]], fill=background_color)
            
            # Add accent border
            border_width = 10
            draw.rectangle([border_width, border_width, size[0]-border_width, size[1]-border_width], 
                         outline=accent_color, width=3)
            
            # Calculate text position
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            x = (size[0] - text_width) // 2
            y = (size[1] - text_height) // 2
            
            # Draw text
            draw.text((x, y), text, fill=text_color, font=font)
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_data = buffer.getvalue()
            
            return {
                "success": True,
                "image": base64.b64encode(img_data).decode(),
                "size": len(img_data),
                "dimensions": size,
                "style": style
            }
        except Exception as e:
            logger.error(f"Error generating image from text: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_qr_code_image(self, data: str, style: str = "default", size: int = 10) -> Dict[str, Any]:
        """Generate QR code image with custom styling."""
        try:
            qr = qrcode.QRCode(version=1, box_size=size, border=5)
            qr.add_data(data)
            qr.make(fit=True)
            
            # Apply style
            if style == "colorful":
                fill_color = (70, 130, 180)  # Steel blue
                back_color = (255, 255, 255)  # White
            elif style == "dark":
                fill_color = (0, 0, 0)  # Black
                back_color = (255, 255, 255)  # White
            elif style == "inverted":
                fill_color = (255, 255, 255)  # White
                back_color = (0, 0, 0)  # Black
            else:
                fill_color = (0, 0, 0)  # Black
                back_color = (255, 255, 255)  # White
            
            img = qr.make_image(fill_color=fill_color, back_color=back_color)
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_data = buffer.getvalue()
            
            return {
                "success": True,
                "image": base64.b64encode(img_data).decode(),
                "size": len(img_data),
                "qr_data": data,
                "style": style
            }
        except Exception as e:
            logger.error(f"Error generating QR code image: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_content_from_template(self, template_name: str, variables: Dict[str, str]) -> Dict[str, Any]:
        """Create content using a predefined template."""
        try:
            if template_name not in self.templates:
                return {"success": False, "error": f"Template '{template_name}' not found"}
            
            template = self.templates[template_name]
            content = template.get("body", template.get("text", ""))
            
            # Replace variables
            for var_name, var_value in variables.items():
                placeholder = "{" + var_name + "}"
                content = content.replace(placeholder, str(var_value))
            
            # Handle missing variables
            import re
            missing_vars = re.findall(r'\{([^}]+)\}', content)
            if missing_vars:
                content += f"\n\n*Note: Missing variables: {', '.join(missing_vars)}*"
            
            return {
                "success": True,
                "template": template_name,
                "content": content,
                "variables_used": list(variables.keys()),
                "missing_variables": missing_vars
            }
        except Exception as e:
            logger.error(f"Error creating content from template: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_bulk_content(self, base_content: str, variations: int = 5, 
                                  content_type: str = "social_post") -> Dict[str, Any]:
        """Generate multiple variations of content."""
        try:
            variations_list = []
            
            for i in range(variations):
                variation = base_content
                
                # Apply different variations based on content type
                if content_type == "social_post":
                    variation = await self._variation_social_post(base_content, i)
                elif content_type == "email":
                    variation = await self._variation_email(base_content, i)
                elif content_type == "blog":
                    variation = await self._variation_blog(base_content, i)
                else:
                    # Generic variation
                    variation = await self._variation_generic(base_content, i)
                
                variations_list.append({
                    "id": i + 1,
                    "content": variation,
                    "type": content_type
                })
            
            return {
                "success": True,
                "original_content": base_content,
                "variations": variations_list,
                "count": len(variations_list)
            }
        except Exception as e:
            logger.error(f"Error generating bulk content: {e}")
            return {"success": False, "error": str(e)}
    
    async def _variation_social_post(self, content: str, index: int) -> str:
        """Generate social post variation."""
        variations = [
            f"🔥 {content}",
            f"💡 {content}",
            f"🎯 {content}",
            f"🚀 {content}",
            f"✨ {content}"
        ]
        
        hashtags = [
            "#innovation #growth #success",
            "#business #strategy #leadership",
            "#marketing #digital #trends",
            "#startup #entrepreneur #motivation",
            "#technology #future #opportunity"
        ]
        
        base_variation = variations[index % len(variations)]
        hashtag = hashtags[index % len(hashtags)]
        
        return f"{base_variation}\n\n{hashtag}"
    
    async def _variation_email(self, content: str, index: int) -> str:
        """Generate email variation."""
        greetings = [
            "Hi there,",
            "Hello,",
            "Greetings,",
            "Good day,",
            "Hi everyone,"
        ]
        
        closings = [
            "Best regards,",
            "Cheers,",
            "Thanks,",
            "Sincerely,",
            "Kind regards,"
        ]
        
        greeting = greetings[index % len(greetings)]
        closing = closings[index % len(closings)]
        
        return f"{greeting}\n\n{content}\n\n{closing}"
    
    async def _variation_blog(self, content: str, index: int) -> str:
        """Generate blog post variation."""
        intros = [
            "In today's fast-paced world,",
            "As we navigate the digital landscape,",
            "With technology evolving rapidly,",
            "In the era of digital transformation,",
            "As businesses adapt to change,"
        ]
        
        intro = intros[index % len(intros)]
        return f"{intro} {content}"
    
    async def _variation_generic(self, content: str, index: int) -> str:
        """Generate generic content variation."""
        prefixes = [
            "Important: ",
            "Note: ",
            "Key point: ",
            "Highlight: ",
            "Remember: "
        ]
        
        prefix = prefixes[index % len(prefixes)]
        return f"{prefix}{content}"
    
    async def optimize_content_for_seo(self, content: str, keywords: List[str] = None) -> Dict[str, Any]:
        """Optimize content for SEO."""
        try:
            # Basic SEO optimization
            optimized_content = content
            suggestions = []
            
            # Check content length
            word_count = len(content.split())
            if word_count < 300:
                suggestions.append("Consider adding more content (aim for 300+ words)")
            elif word_count > 2000:
                suggestions.append("Content might be too long for some readers")
            
            # Check for keywords if provided
            if keywords:
                content_lower = content.lower()
                keyword_usage = {}
                
                for keyword in keywords:
                    count = content_lower.count(keyword.lower())
                    keyword_usage[keyword] = count
                    
                    if count == 0:
                        suggestions.append(f"Consider including the keyword '{keyword}'")
                    elif count > 5:
                        suggestions.append(f"Keyword '{keyword}' might be overused")
                
                # Add keyword density info
                keyword_density = {k: (v / word_count) * 100 for k, v in keyword_usage.items()}
            else:
                keyword_usage = {}
                keyword_density = {}
            
            # Check for headings
            if "#" not in content and "##" not in content:
                suggestions.append("Consider adding headings for better structure")
            
            # Check for links
            if "http" not in content:
                suggestions.append("Consider adding relevant links")
            
            return {
                "success": True,
                "original_content": content,
                "word_count": word_count,
                "keyword_usage": keyword_usage,
                "keyword_density": keyword_density,
                "suggestions": suggestions,
                "seo_score": max(0, 100 - len(suggestions) * 10)
            }
        except Exception as e:
            logger.error(f"Error optimizing content for SEO: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_content_calendar(self, start_date: str, end_date: str, 
                                     content_types: List[str] = None) -> Dict[str, Any]:
        """Generate a content calendar."""
        try:
            from datetime import datetime, timedelta
            
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            if not content_types:
                content_types = ["social_post", "blog", "email", "newsletter"]
            
            calendar = []
            current_date = start
            
            while current_date <= end:
                # Skip weekends for business content
                if current_date.weekday() < 5:  # Monday to Friday
                    content_type = random.choice(content_types)
                    
                    calendar.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "content_type": content_type,
                        "suggested_topics": await self._generate_topics_for_date(current_date, content_type)
                    })
                
                current_date += timedelta(days=1)
            
            return {
                "success": True,
                "start_date": start_date,
                "end_date": end_date,
                "calendar": calendar,
                "total_posts": len(calendar)
            }
        except Exception as e:
            logger.error(f"Error generating content calendar: {e}")
            return {"success": False, "error": str(e)}
    
    async def _generate_topics_for_date(self, date: datetime, content_type: str) -> List[str]:
        """Generate suggested topics for a specific date and content type."""
        topics = {
            "social_post": [
                "Industry insights and trends",
                "Behind-the-scenes content",
                "Customer success stories",
                "Product tips and tricks",
                "Team highlights"
            ],
            "blog": [
                "How-to guides and tutorials",
                "Industry analysis and insights",
                "Case studies and success stories",
                "Expert interviews and Q&A",
                "Trend analysis and predictions"
            ],
            "email": [
                "Weekly newsletter updates",
                "Product announcements",
                "Customer onboarding series",
                "Industry news and insights",
                "Exclusive offers and promotions"
            ],
            "newsletter": [
                "Monthly company updates",
                "Industry roundup and insights",
                "Team and culture highlights",
                "Product roadmap updates",
                "Customer community spotlights"
            ]
        }
        
        return topics.get(content_type, ["General content"])
    
    async def generate_text(
        self,
        prompt: str,
        context: str = "",
        max_tokens: int = 500,
        system_prompt: str = "",
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Generate text content using the LLM service.

        Used by RAG pipelines to produce grounded answers from retrieved context,
        and by general content-creation workflows that need free-form text generation.

        Args:
            prompt: The user's question or instruction.
            context: Optional retrieved context (KB chunks, docs, etc.).
            max_tokens: Maximum tokens for the response.
            system_prompt: Optional system-level instruction override.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            Dict with ``success``, ``content``, and metadata keys.
        """
        try:
            from .llm_service import llm_service

            # Build the system message
            if not system_prompt:
                if context:
                    system_prompt = (
                        "You are a helpful AI assistant. Answer the user's question "
                        "accurately and concisely using ONLY the provided context. "
                        "If the context does not contain enough information, say so. "
                        "Do not make up information."
                    )
                else:
                    system_prompt = (
                        "You are a helpful AI assistant. Provide a clear, "
                        "accurate, and concise response."
                    )

            # Build the user message
            if context:
                user_message = (
                    f"Context:\n{context}\n\n"
                    f"Question: {prompt}\n\n"
                    "Answer:"
                )
            else:
                user_message = prompt

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            response = await llm_service.chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                use_background_model=True,
            )

            if response.error:
                return {
                    "success": False,
                    "error": f"LLM generation failed: {response.error}",
                }

            return {
                "success": True,
                "content": response.content,
                "result": response.content,
                "tokens_used": response.tokens_used,
                "prompt": prompt,
            }

        except Exception as e:
            logger.error(f"Error generating text content: {e}")
            return {"success": False, "error": str(e)}

    def get_available_templates(self) -> Dict[str, Any]:
        """Get list of available templates."""
        return {
            "success": True,
            "templates": list(self.templates.keys()),
            "template_details": {
                name: {
                    "variables": template.get("variables", []),
                    "description": f"Template for {name.replace('_', ' ')}"
                }
                for name, template in self.templates.items()
            }
        }


# Global content creation service instance
content_creation_service = ContentCreationService() 