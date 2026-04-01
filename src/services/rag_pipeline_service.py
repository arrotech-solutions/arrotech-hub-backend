"""
RAG Pipeline Service 
Orchestrates fetching, parsing, chunking, and vector DB insertion.
"""
import logging
import uuid
from typing import Dict, Any, List

from .firecrawl_service import FirecrawlService
from .openai_service import OpenAIEmbeddingService
from .pinecone_service import PineconeService

logger = logging.getLogger(__name__)

class RAGPipelineService:
    """Zero File Storage RAG Pipeline Orchestrator."""
    
    def __init__(self):
        self.firecrawl = FirecrawlService()
        self.openai = OpenAIEmbeddingService()
        self.pinecone = PineconeService()

    def chunk_text(self, text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
        """Simple character overlap chunking algorithm."""
        if not text:
            return []
        
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = min(start + chunk_size, text_len)
            
            # If we're not at the end of the text, try to find a natural break point
            if end < text_len:
                last_newline = text.rfind('\n', start, end)
                if last_newline != -1 and last_newline > start + chunk_size // 2:
                    end = last_newline + 1
                else:
                    last_space = text.rfind(' ', start, end)
                    if last_space != -1 and last_space > start + chunk_size // 2:
                        end = last_space + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
                
            start = end - overlap
            if start >= text_len or end >= text_len:
                break
                
        return chunks

    def _smart_extract_text(self, item: Any) -> Dict[str, str]:
        """
        Intelligently extracts text and metadata from diverse platform-specific objects.
        Supports: Google Docs, Zoho Articles, Slack Messages, HubSpot Records, etc.
        """
        text = ""
        source_url = "custom_workflow"
        
        if not item:
            return {"text": "", "url": source_url}
            
        # 1. Handle simple string/text
        if isinstance(item, str):
            return {"text": item, "url": source_url}
            
        # 2. Handle Dictionary (Platform Objects)
        if isinstance(item, dict):
            # Google Workspace Docs / Drive
            if 'content' in item and 'mime_type' in item:
                text = str(item.get('content', ''))
                source_url = f"google://{item.get('file_id', 'doc')}"
            # Zoho Desk / KB
            elif 'title' in item and ('content' in item or 'body' in item):
                text = f"# {item.get('title')}\n\n{item.get('content') or item.get('body')}"
                source_url = f"zoho://{item.get('id', 'article')}"
            # Slack Messages
            elif 'text' in item and 'user' in item:
                text = f"User {item.get('user')}: {item.get('text')}"
                source_url = f"slack://{item.get('channel', 'msg')}"
            # HubSpot / CRM (Convert properties to markdown)
            elif 'properties' in item:
                props = item.get('properties', {})
                text = "\n".join([f"- **{k}**: {v}" for k, v in props.items()])
                source_url = f"hubspot://{item.get('id', 'record')}"
            # Generic JSON
            else:
                import json
                text = json.dumps(item, indent=2)
                
        # 3. Handle Lists (Recursive call for nested structures if needed)
        elif isinstance(item, list):
             import json
             text = json.dumps(item, indent=2)

        return {"text": text, "url": source_url}

    async def rag_ingest_content(
        self, 
        content: Any, 
        kb_id: str, 
        namespace: str, 
        source_url: str = None,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Universal Knowledge Sink: Handles single items or lists from any source.
        """
        items_to_process = content if isinstance(content, list) else [content]
        all_chunks = []
        all_vectors = []
        
        logger.info(f"Universal Ingestion: Processing {len(items_to_process)} items for KB {kb_id}")
        
        # 1. Batch Extraction & Chunking
        for item in items_to_process:
            extracted = self._smart_extract_text(item)
            item_text = extracted["text"]
            item_url = source_url or extracted["url"]
            
            if not item_text.strip():
                continue
                
            item_chunks = self.chunk_text(item_text, 512)
            for chunk in item_chunks:
                all_chunks.append({
                    "text": chunk,
                    "url": item_url
                })

        if not all_chunks:
             return {"status": "success", "message": "No valid text content found to ingest", "chunks_added": 0}

        # 2. Batch Embedding (OpenAI)
        texts_only = [c["text"] for c in all_chunks]
        embeddings_result = await self.openai.openai_batch_create_embeddings(texts_only)
        
        if not embeddings_result.get("success"):
            return {"status": "error", "message": f"Embedding failed: {embeddings_result.get('error')}"}
        
        embeddings_list = embeddings_result.get("embeddings", [])
        
        # 3. Batch Preparing Vectors
        for i, (chunk_data, embedding) in enumerate(zip(all_chunks, embeddings_list)):
            vector_id = f"v_{uuid.uuid4().hex[:6]}_{i}"
            meta = {
                "text": chunk_data["text"][:5000],
                "source_url": chunk_data["url"],
                "kb_id": kb_id
            }
            if metadata:
                meta.update(metadata)
                
            all_vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": meta
            })
            
        # 4. Final Bulk Upsert
        upsert_res = await self.pinecone.pinecone_upsert_vectors(
            index_host=None,
            namespace=namespace,
            vectors=all_vectors
        )
        
        return {
            "status": "success",
            "count": len(items_to_process),
            "chunks_added": upsert_res.get("upserted_count", len(all_vectors)),
            "message": f"Successfully ingested {len(items_to_process)} sources into Knowledge Base."
        }


    async def rag_ingest_source(
        self, 
        url_or_id: str, 
        kb_id: str, 
        namespace: str, 
        source_type: str = "website", 
        user: Any = None, 
        db: Any = None
    ) -> Dict[str, Any]:
        """
        Refactored: Now fetches data and passes it to rag_ingest_content.
        """
        logger.info(f"Starting MCP fetch for {source_type}: {url_or_id}")
        raw_text = ""
        source_url = url_or_id
        
        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            
            if source_type == "website":
                scrape_result = await self.firecrawl.firecrawl_scrape_url(url_or_id)
                if not scrape_result.get("success"):
                    return {"status": "error", "message": f"Scraping failed: {scrape_result.get('error')}"}
                raw_text = scrape_result.get("markdown", "")
                
            elif source_type in ["google_drive", "google_workspace_drive"]:
                res = await executor.execute_tool("google_workspace_drive", {"operation": "download_file", "file_id": url_or_id}, user, db)
                if not res.get("success"): return {"status": "error", "message": "Drive fetch failed"}
                
                from .llamaparse_service import LlamaParseService
                import asyncio
                parse_res = await LlamaParseService().llamaparse_parse_document(res.get("content"), f"{url_or_id}.pdf")
                if parse_res.get("success"):
                    job_id = parse_res.get("job_id")
                    for _ in range(6): 
                        await asyncio.sleep(10)
                        job_res = await LlamaParseService().llamaparse_get_job_result(job_id)
                        if job_res.get("status") == "SUCCESS":
                            raw_text = job_res.get("markdown", "")
                            break
                source_url = f"https://drive.google.com/file/d/{url_or_id}/view"
                
            elif source_type == "notion":
                res = await executor.execute_tool("notion_pages", {"operation": "read", "page_id": url_or_id}, user, db)
                if not res.get("success"): return {"status": "error", "message": "Notion fetch failed"}
                raw_text = str(res.get("data", ""))
                source_url = f"notion://{url_or_id}"
                
            # Finalize via generic ingestion
            return await self.rag_ingest_content(raw_text, kb_id, namespace, source_url)
                 
        except Exception as e:
             logger.error(f"Error in dynamic source fetch: {e}")
             return {"status": "error", "message": str(e)}


    async def rag_search_query(self, query: str, namespace: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Retrieval flow for a given query against a Knowledge Base namespace.
        """
        logger.info(f"Searching namespace {namespace} for query: {query}")
        
        # Embed query
        embed_res = await self.openai.openai_create_embedding(query)
        if not embed_res.get("success"):
            return {"success": False, "error": embed_res.get("error")}
            
        query_vector = embed_res.get("embedding")
        
        # Vector search
        search_res = await self.pinecone.pinecone_query(
            index_host=None,
            namespace=namespace,
            vector=query_vector,
            top_k=top_k
        )
        
        if not search_res.get("success"):
             return {"success": False, "error": search_res.get("error")}
             
        matches = search_res.get("matches", [])
        results = [
            {
                "score": match.get("score"),
                "text": match.get("metadata", {}).get("text", ""),
                "source": match.get("metadata", {}).get("source_url", "")
            }
            for match in matches
        ]
             
        return {"success": True, "results": results}

        
    async def rag_sync_schedule(self):
        """
        Background task to sync all Data Sources. Pulls actual User context for True MCP execution.
        """
        logger.info("Running RAG scheduled sync task via ToolExecutor abstraction")
        from ..database import get_session_maker
        from ..models import DataSource, KnowledgeBase, User
        from sqlalchemy import select
        
        session_maker = get_session_maker()
        async with session_maker() as session:
            try:
                stmt = select(DataSource).filter(
                    DataSource.sync_mode == "scheduled",
                    DataSource.status == "active"
                )
                result = await session.execute(stmt)
                sources = result.scalars().all()
                
                for source in sources:
                    kb_stmt = select(KnowledgeBase).filter(KnowledgeBase.id == source.kb_id)
                    kb_result = await session.execute(kb_stmt)
                    kb = kb_result.scalars().first()
                    
                    if not kb:
                        continue
                        
                    namespace = f"user_{kb.user_id}_kb_{kb.id}"
                    
                    # Native User Extractor
                    user_stmt = select(User).filter(User.id == kb.user_id)
                    user_res = await session.execute(user_stmt)
                    actual_user = user_res.scalars().first()
                    
                    if not actual_user:
                        logger.warning(f"User {kb.user_id} not found for Knowledge Base {kb.id}")
                        continue
                            
                    url_or_id = None
                    if source.source_type == "website":
                        url_or_id = source.config.get("url")
                    elif source.source_type in ["google_drive", "google_workspace_drive"]:
                        url_or_id = source.config.get("file_id")
                    elif source.source_type == "notion":
                        url_or_id = source.config.get("page_id")
                        
                    if url_or_id:
                        sync_res = await self.rag_ingest_source(
                            url_or_id=url_or_id,
                            kb_id=str(kb.id),
                            namespace=namespace,
                            source_type=source.source_type,
                            user=actual_user,
                            db=session
                        )
                        logger.info(f"Scheduled sync result for source {source.id} ({source.source_type}): {sync_res}")
                            
            except Exception as e:
                logger.error(f"Error in RAG sync scheduler: {e}")


def get_rag_pipeline_service() -> RAGPipelineService:
    return RAGPipelineService()
