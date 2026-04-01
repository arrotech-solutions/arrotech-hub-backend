"""
OpenAI Embeddings Service
"""
import logging
import os
from typing import Dict, Any, List
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class OpenAIEmbeddingService:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=self.api_key) if self.api_key else None

    async def openai_create_embedding(self, input_text: str, model: str = "text-embedding-3-small") -> Dict[str, Any]:
        """Creates an embedding vector representing the input text."""
        if not self.client:
             return {"error": "OPENAI_API_KEY not configured", "success": False}
        try:
            # Handle empty text to avoid API errors
            if not input_text or not input_text.strip():
                 return {"embedding": [], "model": model, "success": True}
                 
            response = await self.client.embeddings.create(
                input=input_text,
                model=model
            )
            return {"embedding": response.data[0].embedding, "model": model, "success": True}
        except Exception as e:
            logger.error(f"Error creating embedding: {e}")
            return {"error": str(e), "success": False}

    async def openai_batch_create_embeddings(self, input_texts: List[str], model: str = "text-embedding-3-small") -> Dict[str, Any]:
        """Creates embeddings for a batch of text."""
        if not self.client:
             return {"error": "OPENAI_API_KEY not configured", "success": False}
        try:
            # Filter out empty strings
            valid_texts = [t for t in input_texts if t and t.strip()]
            if not valid_texts:
                return {"embeddings": [], "model": model, "success": True}

            response = await self.client.embeddings.create(
                input=valid_texts,
                model=model
            )
            embeddings = [data.embedding for data in response.data]
            return {"embeddings": embeddings, "model": model, "success": True}
        except Exception as e:
            logger.error(f"Error in batch embedding: {e}")
            return {"error": str(e), "success": False}

