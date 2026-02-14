from PIL import Image, ImageDraw, ImageFont
import io
import base64
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class ViralCardGenerator:
    """Generates shareable viral score cards/images."""

    def __init__(self):
        # We could load brand assets here if available
        pass

    def generate_score_card(self, username: str, views: str, followers: str, avatar_url: str = None) -> Dict[str, Any]:
        """
        Generate a "Viral Status" image for sharing on WhatsApp/IG Stories.
        
        Design:
        - Dark/Premium background
        - Large stat numbers
        - "Powered by Arrotech" branding
        """
        try:
            # 1. Base Canvas (1080x1920 for Stories)
            width, height = 1080, 1920
            img = Image.new('RGB', (width, height), color='#000000')
            draw = ImageDraw.Draw(img)
            
            # 2. Gradient or Pattern (Simple circles for now)
            draw.ellipse([-200, -200, 600, 600], fill='#FF0050', outline=None) # TikTok Pink ish
            draw.ellipse([500, 1500, 1400, 2400], fill='#00F2EA', outline=None) # TikTok Cyan ish
            
            # Overlay a semi-transparent black layer for readability
            overlay = Image.new('RGBA', (width, height), (0, 0, 0, 200))
            img.paste(overlay, (0, 0), overlay)
            
            draw = ImageDraw.Draw(img)

            # 3. Text Configuration (Fallback to default font if ttf missing)
            try:
                # Attempt to load a system font or common font
                title_font = ImageFont.truetype("arial.ttf", 120)
                stat_font = ImageFont.truetype("arial.ttf", 200)
                label_font = ImageFont.truetype("arial.ttf", 60)
                brand_font = ImageFont.truetype("arial.ttf", 40)
            except:
                title_font = ImageFont.load_default()
                stat_font = ImageFont.load_default()
                label_font = ImageFont.load_default()
                brand_font = ImageFont.load_default()

            # 4. Draw Content
            # Header
            draw.text((width//2, 300), "VIRAL STATUS", font=title_font, fill='white', anchor="mm")
            draw.text((width//2, 450), f"@{username}", font=label_font, fill='#CCCCCC', anchor="mm")
            
            # Stats Block 1: Views
            draw.text((width//2, 800), views, font=stat_font, fill='#00F2EA', anchor="mm")
            draw.text((width//2, 950), "TOTAL VIEWS", font=label_font, fill='white', anchor="mm")
            
            # Stats Block 2: Followers
            draw.text((width//2, 1200), followers, font=stat_font, fill='#FF0050', anchor="mm")
            draw.text((width//2, 1350), "FOLLOWERS", font=label_font, fill='white', anchor="mm")
            
            # Footer Branding
            draw.text((width//2, 1800), "Powered by Arrotech Hub", font=brand_font, fill='#888888', anchor="mm")
            
            # 5. Convert to Base64
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_data = buffer.getvalue()
            
            return {
                "success": True,
                "image_base64": base64.b64encode(img_data).decode(),
                "format": "png",
                "width": width,
                "height": height
            }

        except Exception as e:
            logger.error(f"Error generating viral card: {e}")
            return {"success": False, "error": str(e)}

# Global Instance
viral_card_generator = ViralCardGenerator()
