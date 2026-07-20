import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from .llm_service import llm_service
from ..config import settings

logger = logging.getLogger(__name__)

class ViralEngine:
    """
    Engine for generating viral content logic, AI captions, and trends.
    """
    
    def __init__(self):
        pass

    async def generate_sheng_caption(self, topic: str, tone: str = "funny", context: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a TikTok caption in authentic Kenyan Sheng.
        """
        
        system_prompt = (
            "You are a Gen-Z Kenyan social media expert who speaks fluent Sheng (Kenyan slang) mixed with English. "
            "Your goal is to write viral TikTok captions that resonate with Nairobi youth. "
            "Use popular phrases like 'Bazenga', 'Form ni gani', 'Mabeste', 'Kuja nikusho', etc. where appropriate. "
            "Keep it short, punchy, and engaging. Always include 3-5 trending Kenyan hashtags."
        )
        
        user_prompt = f"Write a {tone} TikTok caption about: {topic}."
        if context:
            user_prompt += f"\nContext: {context}"
            
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response = await llm_service.chat_completion(
                messages=messages,
                temperature=0.8, # High creativity
                max_tokens=200,
                use_background_model=True
            )
            
            if response.error:
                raise Exception(response.error)
                
            return {
                "success": True,
                "caption": response.content.strip(),
                "tone": tone,
                "topic": topic
            }
            
        except Exception as e:
            logger.error(f"Error generating Sheng caption: {e}")
            return {
                "success": False,
                "error": str(e),
                "caption": f"Check out this cool video about {topic}! #Kenya #TikTok" # Fallback
            }

    async def analyze_video_virality(self, video_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mock analysis of a video's potential virality.
        Real implementation would use vision/audio AI models.
        """
        score = 0
        suggestions = []
        
        # Simple logical checks
        duration = video_data.get("duration", 0)
        if 15 <= duration <= 45:
            score += 30
            suggestions.append("Perfect duration for TikTok (15-45s).")
        elif duration < 10:
             score += 10
             suggestions.append("Video might be too short.")
        else:
             score += 15
             suggestions.append("Video is a bit long, ensure the hook is strong.")
             
        if video_data.get("has_music"):
            score += 20
        else:
            suggestions.append("Add trending audio to boost reach.")
            
        return {
            "score": score + 30, # Base score
            "suggestions": suggestions,
            "prediction": "High Potential" if score > 40 else "Moderate Potential"
        }

# Global instance
viral_engine = ViralEngine()
