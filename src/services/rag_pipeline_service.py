"""
RAG Pipeline Service 
Orchestrates fetching, parsing, chunking, embedding, and vector DB insertion.
Fully dynamic — routes to the correct vector DB, embedding model, and parser
based on each KnowledgeBase's stored configuration.
"""
import logging
import uuid
import tiktoken
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from .pinecone_service import PineconeService
from .qdrant_service import QdrantService
from .weaviate_service import WeaviateService
from .firecrawl_service import FirecrawlService
from .unstructured_service import UnstructuredService
from .cohere_service import CohereService

logger = logging.getLogger(__name__)


class RAGPipelineService:
    """Zero File Storage RAG Pipeline Orchestrator.
    
    Dynamically routes to the correct vector DB (Pinecone/Qdrant/Weaviate),
    embedding model (OpenAI/Cohere/HuggingFace), and parser (LlamaParse/
    Unstructured/Firecrawl) based on each KnowledgeBase's stored config.
    
    Supports hybrid credential resolution:
    1. User-level BYOK keys (from Connection records or UserSettings)
    2. Platform-managed keys (from environment variables)
    """
    
    def __init__(self):
        # Vector DB services — lazily selected per KB config
        # Default instances use platform env vars
        self._vector_services = {
            "pinecone": PineconeService(),
            "qdrant": QdrantService(),
            "weaviate": WeaviateService(),
        }
        # Parser services (defaults from env vars)
        self.firecrawl = FirecrawlService()
        self.unstructured = UnstructuredService()
        # Reranker
        self.cohere = CohereService()
        
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = tiktoken.encoding_for_model("gpt-4o")

    # ================================================================
    # CREDENTIAL RESOLUTION — user BYOK keys → platform env vars
    # ================================================================

    async def _resolve_credentials(self, user, db) -> Dict[str, Any]:
        """Resolve API credentials with hybrid fallback.
        
        Priority: User Connection keys → UserSettings keys → Platform env vars.
        Returns a dict of resolved credentials per service.
        """
        import os
        credentials = {
            "pinecone_api_key": os.getenv("PINECONE_API_KEY"),
            "pinecone_host": os.getenv("PINECONE_INDEX_HOST"),
            "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
            "openai_api_key": os.getenv("OPENAI_API_KEY"),
            "cohere_api_key": os.getenv("COHERE_API_KEY"),
        }
        
        if not user or not db:
            return credentials
        
        try:
            from sqlalchemy import select
            from ..models import Connection, UserSettings
            
            # Check user Connections for BYOK keys
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.status == "active"
                )
            )
            connections = result.scalars().all()
            
            for conn in connections:
                config = conn.config or {}
                platform = conn.platform.lower() if conn.platform else ""
                
                if "pinecone" in platform:
                    credentials["pinecone_api_key"] = config.get("api_key") or credentials["pinecone_api_key"]
                    credentials["pinecone_host"] = config.get("index_host") or credentials["pinecone_host"]
                elif "firecrawl" in platform:
                    credentials["firecrawl_api_key"] = config.get("api_key") or credentials["firecrawl_api_key"]
                elif "openai" in platform:
                    credentials["openai_api_key"] = config.get("api_key") or credentials["openai_api_key"]
                elif "cohere" in platform:
                    credentials["cohere_api_key"] = config.get("api_key") or credentials["cohere_api_key"]
            
            # Also check UserSettings for LLM BYOK keys (existing pattern)
            settings_result = await db.execute(
                select(UserSettings).filter(UserSettings.user_id == user.id)
            )
            settings = settings_result.scalars().first()
            
            if settings:
                if settings.openai_api_key:
                    credentials["openai_api_key"] = settings.openai_api_key
                    
        except Exception as e:
            logger.warning(f"Error resolving user credentials (using platform defaults): {e}")
        
        return credentials

    def _get_vector_service_with_creds(self, vector_db: str, credentials: Dict[str, Any] = None):
        """Return the correct vector DB service, optionally with user-specific credentials."""
        if vector_db == "pinecone" and credentials:
            api_key = credentials.get("pinecone_api_key")
            host = credentials.get("pinecone_host")
            # Only create a new instance if user has BYOK keys different from default
            if api_key or host:
                return PineconeService(api_key=api_key, host=host)
        return self._get_vector_service(vector_db)

    def _get_firecrawl_with_creds(self, credentials: Dict[str, Any] = None):
        """Return Firecrawl service with user-specific or platform credentials."""
        if credentials and credentials.get("firecrawl_api_key"):
            return FirecrawlService(api_key=credentials["firecrawl_api_key"])
        return self.firecrawl

    # ================================================================
    # VECTOR DB ROUTING — dynamic based on KB config
    # ================================================================

    def _get_vector_service(self, vector_db: str):
        """Return the correct vector DB service based on KB config."""
        service = self._vector_services.get(vector_db)
        if not service:
            logger.warning(f"Unknown vector_db '{vector_db}', falling back to Pinecone")
            return self._vector_services["pinecone"]
        return service

    async def _vector_upsert(self, vector_db: str, namespace: str, vectors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Route upsert to the correct vector DB."""
        service = self._get_vector_service(vector_db)
        
        if vector_db == "pinecone":
            return await service.pinecone_upsert_vectors(
                index_host=None, namespace=namespace, vectors=vectors
            )
        elif vector_db == "qdrant":
            # Qdrant uses collection_name = namespace, points format differs
            points = [{
                "id": v["id"],
                "vector": v["values"],
                "payload": v["metadata"]
            } for v in vectors]
            return await service.qdrant_upsert_points(
                collection_name=namespace, points=points
            )
        elif vector_db == "weaviate":
            # Weaviate uses class_name + tenant
            objects = [{
                "properties": v["metadata"],
                "vector": v["values"]
            } for v in vectors]
            return await service.weaviate_add_objects(
                class_name="KnowledgeChunk", objects=objects, tenant=namespace
            )
        
        return {"success": False, "error": f"Unsupported vector_db: {vector_db}"}

    async def _vector_query(self, vector_db: str, namespace: str, query_vector: List[float], top_k: int = 5) -> Dict[str, Any]:
        """Route query to the correct vector DB."""
        service = self._get_vector_service(vector_db)
        
        if vector_db == "pinecone":
            return await service.pinecone_query(
                index_host=None, namespace=namespace,
                vector=query_vector, top_k=top_k
            )
        elif vector_db == "qdrant":
            res = await service.qdrant_search(
                collection_name=namespace, query_vector=query_vector, limit=top_k
            )
            # Normalize Qdrant response to match Pinecone format
            if res.get("success"):
                matches = [{
                    "score": r.get("score", 0),
                    "metadata": r.get("payload", {})
                } for r in res.get("result", [])]
                return {"success": True, "matches": matches}
            return res
        elif vector_db == "weaviate":
            res = await service.weaviate_hybrid_search(
                class_name="KnowledgeChunk", query="",
                vector=query_vector, tenant=namespace, limit=top_k
            )
            # Normalize Weaviate response
            if res.get("success"):
                matches = [{
                    "score": 1.0 - r.get("_additional", {}).get("distance", 0),
                    "metadata": {k: v for k, v in r.items() if k != "_additional"}
                } for r in res.get("results", [])]
                return {"success": True, "matches": matches}
            return res

        return {"success": False, "error": f"Unsupported vector_db: {vector_db}"}

    async def _vector_delete_namespace(self, vector_db: str, namespace: str) -> Dict[str, Any]:
        """Delete an entire namespace/collection/tenant from the vector DB."""
        service = self._get_vector_service(vector_db)
        
        if vector_db == "pinecone":
            return await service.pinecone_delete_namespace(index_host=None, namespace=namespace)
        elif vector_db == "qdrant":
            return await service.qdrant_delete_collection(collection_name=namespace)
        elif vector_db == "weaviate":
            return await service.weaviate_delete_tenant(class_name="KnowledgeChunk", tenant=namespace)
        
        return {"success": False, "error": f"Unsupported vector_db: {vector_db}"}

    # ================================================================
    # KB CONFIG RESOLUTION — reads settings from database
    # ================================================================

    async def _resolve_kb_config(self, kb_id: str, user_id: str, db) -> Optional[Dict[str, Any]]:
        """Look up a KnowledgeBase's config from the database."""
        try:
            from ..models import KnowledgeBase
            from sqlalchemy import select
            
            stmt = select(KnowledgeBase).filter(
                KnowledgeBase.id == uuid.UUID(kb_id),
                KnowledgeBase.user_id == uuid.UUID(user_id)
            )
            result = await db.execute(stmt)
            kb = result.scalars().first()
            
            if not kb:
                logger.warning(f"KnowledgeBase {kb_id} not found for user {user_id}")
                return None
            
            return {
                "kb_id": str(kb.id),
                "user_id": str(kb.user_id),
                "name": kb.name,
                "embedding_model": kb.embedding_model or "text-embedding-3-small",
                "vector_db": kb.vector_db or "pinecone",
                "chunk_size": kb.chunk_size or 512,
                "chunk_overlap": kb.chunk_overlap or 50,
            }
        except Exception as e:
            logger.error(f"Error resolving KB config: {e}")
            return None

    def _embedding_model_to_operation(self, model_name: str) -> str:
        """Map a KB's embedding_model string to the ai_embeddings operation name."""
        mapping = {
            "text-embedding-3-small": "openai_small",
            "text-embedding-3-large": "openai_large",
            "embed-multilingual-v3.0": "cohere_multilingual",
            "all-MiniLM-L6-v2": "huggingface_local",
            # Also accept operation names directly
            "openai_small": "openai_small",
            "openai_large": "openai_large",
            "cohere_multilingual": "cohere_multilingual",
            "huggingface_local": "huggingface_local",
        }
        return mapping.get(model_name, "openai_small")

    # ================================================================
    # CHUNKING — native recursive token splitter
    # ================================================================

    def native_recursive_token_splitter(self, text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
        """
        Native Recursive Token Splitter using tiktoken.
        Splits on paragraphs → sentences → words while staying within token limits.
        """
        if not text:
            return []

        def get_tokens(t):
            return self.tokenizer.encode(t)

        final_chunks = []
        paragraphs = text.split('\n\n')
        
        current_chunk_tokens = []
        current_chunk_text = ""
        
        for para in paragraphs:
            para_tokens = get_tokens(para)
            
            if len(current_chunk_tokens) + len(para_tokens) <= chunk_size:
                current_chunk_tokens.extend(para_tokens)
                current_chunk_text += (para + "\n\n")
            else:
                if current_chunk_text:
                    final_chunks.append(current_chunk_text.strip())
                
                if len(para_tokens) > chunk_size:
                    sentences = para.replace('\n', ' ').split('. ')
                    current_chunk_tokens = []
                    current_chunk_text = ""
                    
                    for sent in sentences:
                        sent = sent.strip() + ". "
                        sent_tokens = get_tokens(sent)
                        
                        if len(current_chunk_tokens) + len(sent_tokens) <= chunk_size:
                            current_chunk_tokens.extend(sent_tokens)
                            current_chunk_text += sent
                        else:
                            if current_chunk_text:
                                final_chunks.append(current_chunk_text.strip())
                            
                            if len(sent_tokens) > chunk_size:
                                words = sent.split(' ')
                                current_chunk_tokens = []
                                current_chunk_text = ""
                                for word in words:
                                    word = word + " "
                                    word_tokens = get_tokens(word)
                                    if len(current_chunk_tokens) + len(word_tokens) > chunk_size:
                                        final_chunks.append(current_chunk_text.strip())
                                        current_chunk_tokens = word_tokens
                                        current_chunk_text = word
                                    else:
                                        current_chunk_tokens.extend(word_tokens)
                                        current_chunk_text += word
                            else:
                                current_chunk_tokens = sent_tokens
                                current_chunk_text = sent
                else:
                    current_chunk_tokens = para_tokens
                    current_chunk_text = para + "\n\n"
                    
        if current_chunk_text:
            final_chunks.append(current_chunk_text.strip())
            
        return final_chunks

    # ================================================================
    # TEXT EXTRACTION — smart extraction from diverse platform objects
    # ================================================================

    def _smart_extract_text(self, item: Any) -> Dict[str, str]:
        """
        Intelligently extracts text and metadata from diverse platform-specific objects.
        Supports: Google Docs, Zoho Articles, Slack Messages, HubSpot Records, etc.
        """
        text = ""
        source_url = "custom_workflow"
        
        if not item:
            return {"text": "", "url": source_url}
            
        if isinstance(item, str):
            return {"text": item, "url": source_url}
            
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
            # Notion pages
            elif 'blocks' in item or 'results' in item:
                import json
                text = json.dumps(item, indent=2)
                source_url = f"notion://{item.get('id', 'page')}"
            # Airtable records
            elif 'fields' in item:
                fields = item.get('fields', {})
                text = "\n".join([f"- **{k}**: {v}" for k, v in fields.items()])
                source_url = f"airtable://{item.get('id', 'record')}"
            # Generic JSON
            else:
                import json
                text = json.dumps(item, indent=2)
                
        elif isinstance(item, list):
            import json
            text = json.dumps(item, indent=2)

        return {"text": text, "url": source_url}

    # ================================================================
    # INGESTION — universal content ingestion with dynamic routing
    # ================================================================

    async def rag_ingest_content(
        self, 
        content: Any, 
        kb_id: str, 
        user_id: str,
        source_url: str = None,
        source_name: str = None,
        source_tool: str = "custom",
        embedding_model: str = None,
        chunk_size: int = None,
        chunk_overlap: int = None,
        vector_db: str = None,
        metadata: Dict[str, Any] = None,
        user: Any = None,
        db: Any = None
    ) -> Dict[str, Any]:
        """
        Universal Knowledge Sink: Handles single items or lists from any source.
        Dynamically routes to the correct embedding model and vector DB based on
        the KnowledgeBase's stored config (with parameter overrides supported).
        """
        from .tool_executor import ToolExecutor
        executor = ToolExecutor()
        
        # Resolve hybrid credentials (user BYOK → platform env vars)
        credentials = await self._resolve_credentials(user, db)
        
        # Resolve KB config from database if available
        kb_config = None
        if db and user_id:
            kb_config = await self._resolve_kb_config(kb_id, user_id, db)
        
        # Use KB config as defaults, allow parameter overrides
        effective_embedding = embedding_model or (kb_config or {}).get("embedding_model", "text-embedding-3-small")
        effective_chunk_size = chunk_size or (kb_config or {}).get("chunk_size", 512)
        effective_chunk_overlap = chunk_overlap or (kb_config or {}).get("chunk_overlap", 50)
        effective_vector_db = vector_db or (kb_config or {}).get("vector_db", "pinecone")
        
        # Map embedding model name to operation
        embed_operation = self._embedding_model_to_operation(effective_embedding)
        
        items_to_process = content if isinstance(content, list) else [content]
        all_chunks = []
        all_vectors = []
        
        # Multi-tenant isolated namespace
        namespace = f"user_{user_id}_kb_{kb_id}"
        
        logger.info(
            f"RAG Ingestion: Processing {len(items_to_process)} items for KB {kb_id} "
            f"(Namespace: {namespace}, VectorDB: {effective_vector_db}, "
            f"Embedding: {embed_operation}, ChunkSize: {effective_chunk_size})"
        )
        
        # 1. Batch Extraction & Chunking
        for item in items_to_process:
            extracted = self._smart_extract_text(item)
            item_text = extracted["text"]
            item_url = source_url or extracted["url"]
            
            if not item_text.strip():
                continue
                
            item_chunks = self.native_recursive_token_splitter(
                item_text, chunk_size=effective_chunk_size, overlap=effective_chunk_overlap
            )
            
            for idx, chunk in enumerate(item_chunks):
                all_chunks.append({
                    "text": chunk,
                    "url": item_url,
                    "index": idx,
                    "file_name": source_name or "document"
                })

        if not all_chunks:
            return {"status": "success", "message": "No valid text content found", "chunks_added": 0}

        # 2. Batch Embedding via ToolExecutor (dynamically routes to correct provider)
        texts_only = [c["text"] for c in all_chunks]
        embed_params = {
            "operation": embed_operation,
            "input": texts_only
        }
        
        embed_res = await executor.execute_tool("ai_embeddings", embed_params, user, db)
        
        if not embed_res.get("success"):
            return {"status": "error", "message": f"Embedding Error: {embed_res.get('error')}"}
        
        embeddings_list = embed_res.get("embeddings", [])
        
        if len(embeddings_list) != len(all_chunks):
            return {"status": "error", "message": f"Embedding count mismatch: got {len(embeddings_list)}, expected {len(all_chunks)}"}
        
        # 3. Prepare vectors with metadata
        now = datetime.now(timezone.utc).isoformat()
        for i, (chunk_data, embedding) in enumerate(zip(all_chunks, embeddings_list)):
            vector_id = f"chunk_{uuid.uuid4().hex[:12]}_{i}"
            
            meta = {
                "text": chunk_data["text"][:8192],  # Protect against metadata size limits
                "source_url": chunk_data["url"],
                "source_tool": source_tool,
                "source_file_name": chunk_data["file_name"],
                "kb_id": kb_id,
                "customer_id": user_id,
                "chunk_index": chunk_data["index"],
                "last_modified": now
            }
            if metadata:
                meta.update(metadata)
                
            all_vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": meta
            })
            
        # 4. Dynamic Vector DB Upsert (with resolved credentials)
        vector_service = self._get_vector_service_with_creds(effective_vector_db, credentials)
        if effective_vector_db == "pinecone":
            upsert_res = await vector_service.pinecone_upsert_vectors(
                index_host=None, namespace=namespace, vectors=all_vectors
            )
        elif effective_vector_db == "qdrant":
            points = [{"id": v["id"], "vector": v["values"], "payload": v["metadata"]} for v in all_vectors]
            upsert_res = await vector_service.qdrant_upsert_points(collection_name=namespace, points=points)
        elif effective_vector_db == "weaviate":
            objects = [{"properties": v["metadata"], "vector": v["values"]} for v in all_vectors]
            upsert_res = await vector_service.weaviate_add_objects(class_name="KnowledgeChunk", objects=objects, tenant=namespace)
        else:
            upsert_res = await self._vector_upsert(effective_vector_db, namespace, all_vectors)
        
        if not upsert_res.get("success", False):
            return {"status": "error", "message": f"Vector DB Error: {upsert_res.get('error')}"}
        
        return {
            "status": "success",
            "count": len(items_to_process),
            "chunks_added": upsert_res.get("upserted_count", upsert_res.get("upserted", upsert_res.get("added", len(all_vectors)))),
            "namespace": namespace,
            "vector_db": effective_vector_db,
            "embedding_model": embed_operation,
            "message": f"Successfully ingested {len(items_to_process)} sources into Knowledge Base."
        }


    # ================================================================
    # SOURCE INGESTION — fetches from MCP tools, then ingests
    # ================================================================

    async def rag_ingest_source(
        self, 
        url_or_id: str, 
        kb_id: str, 
        user_id: str,
        source_type: str = "website", 
        user: Any = None, 
        db: Any = None
    ) -> Dict[str, Any]:
        """
        Fetches data from an MCP tool source, parses it, and ingests via rag_ingest_content.
        Dynamically routes to the correct MCP tool based on source_type.
        """
        logger.info(f"Starting source fetch for {source_type}: {url_or_id}")
        raw_text = ""
        source_url = url_or_id
        source_name = url_or_id  # Safe default — no NameError
        
        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            
            # Resolve hybrid credentials (user BYOK → platform env vars)
            credentials = await self._resolve_credentials(user, db)
            
            # ---- Website (Firecrawl) ----
            if source_type == "website":
                firecrawl = self._get_firecrawl_with_creds(credentials)
                scrape_result = await firecrawl.firecrawl_scrape_url(url_or_id)
                if not scrape_result.get("success"):
                    return {"status": "error", "message": f"Scraping failed: {scrape_result.get('error')}"}
                raw_text = scrape_result.get("markdown", "")
                source_name = url_or_id
                
            # ---- Google Drive ----
            elif source_type in ["google_drive", "google_workspace_drive"]:
                # Check if it's a folder first
                meta_res = await executor.execute_tool(
                    "google_workspace_drive",
                    {"operation": "get_metadata", "file_id": url_or_id},
                    user, db
                )
                
                is_folder = False
                if meta_res.get("success") and meta_res.get("file", {}).get("mimeType") == "application/vnd.google-apps.folder":
                    is_folder = True
                
                if is_folder:
                    list_res = await executor.execute_tool(
                        "google_workspace_drive",
                        {"operation": "list_files", "folder_id": url_or_id, "max_results": 100},
                        user, db
                    )
                    if not list_res.get("success"):
                        return {"status": "error", "message": f"Drive folder fetch failed: {list_res.get('error')}"}
                    
                    files = list_res.get("files", [])
                    if not files:
                        return {"status": "success", "message": "Drive folder is empty", "chunks_added": 0}
                    
                    total_chunks = 0
                    processed = 0
                    errors = []
                    
                    for f in files:
                        f_id = f.get("id")
                        f_mime = f.get("mime_type", "")
                        f_name = f.get("name", f_id)
                        
                        # Skip subfolders (prevent infinite recursion and deep nesting)
                        if f_mime == "application/vnd.google-apps.folder":
                            continue
                            
                        r = await self.rag_ingest_source(
                            url_or_id=f_id,
                            kb_id=kb_id,
                            user_id=user_id,
                            source_type=source_type,
                            user=user,
                            db=db
                        )
                        if r.get("status") == "success":
                            total_chunks += r.get("chunks_added", 0)
                            processed += 1
                        else:
                            errors.append(f"{f_name}: {r.get('message', 'Unknown error')}")
                            
                    msg = f"Successfully ingested {processed} files from Drive folder."
                    if errors:
                        msg += f" Encountered {len(errors)} errors: " + " | ".join(errors[:3])
                        if len(errors) > 3:
                            msg += "..."
                            
                    return {
                        "status": "success" if processed > 0 else "error", 
                        "chunks_added": total_chunks, 
                        "message": msg
                    }

                # If not a folder, download as file
                res = await executor.execute_tool(
                    "google_workspace_drive", 
                    {"operation": "download_file", "file_id": url_or_id}, 
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Drive fetch failed: {res.get('error')}"}
                
                content = res.get("content")
                mime_type = res.get("mime_type", "")
                source_name = res.get("name", url_or_id)
                
                # Smart parser routing based on MIME type
                if mime_type == "application/pdf":
                    from .llamaparse_service import LlamaParseService
                    import asyncio
                    parse_res = await LlamaParseService().llamaparse_parse_document(content, f"{source_name}")
                    if parse_res.get("success"):
                        job_id = parse_res.get("job_id")
                        for _ in range(6): 
                            await asyncio.sleep(10)
                            job_res = await LlamaParseService().llamaparse_get_job_result(job_id)
                            if job_res.get("status") == "SUCCESS":
                                raw_text = job_res.get("markdown", "")
                                break
                    if not raw_text:
                        error_msg = parse_res.get("error", "LlamaParse job timed out or failed")
                        return {"status": "error", "message": f"Parsing failed for {source_name}: {error_msg}"}
                else:
                    # Use Unstructured for Office Docs (DOCX, PPTX, XLSX, TXT)
                    parse_res = await self.unstructured.unstructured_partition_document(content, source_name)
                    if parse_res.get("success"):
                        elements = parse_res.get("elements", [])
                        raw_text = "\n\n".join([el.get("text", "") for el in elements if el.get("text")])
                    else:
                        return {"status": "error", "message": f"Unstructured parser failed for {source_name}: {parse_res.get('error')}"}
                
                source_url = f"https://drive.google.com/file/d/{url_or_id}/view"
                
            # ---- Notion ----
            elif source_type == "notion":
                res = await executor.execute_tool(
                    "notion_pages", 
                    {"operation": "read", "page_id": url_or_id}, 
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Notion fetch failed: {res.get('error')}"}
                raw_text = str(res.get("data", ""))
                source_url = f"notion://{url_or_id}"
                source_name = f"Notion Page {url_or_id}"
                
            # ---- Airtable ----
            elif source_type == "airtable":
                res = await executor.execute_tool(
                    "airtable_record_management",
                    {"operation": "list_records", "base_id": url_or_id.split("/")[0], "table_name": url_or_id.split("/")[1] if "/" in url_or_id else "Table"},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Airtable fetch failed: {res.get('error')}"}
                raw_text = str(res.get("data", res.get("result", "")))
                source_url = f"airtable://{url_or_id}"
                source_name = f"Airtable {url_or_id}"
                
            # ---- Google Sheets ----
            elif source_type in ["google_sheets", "google_workspace_sheets"]:
                res = await executor.execute_tool(
                    "google_workspace_sheets",
                    {"operation": "read_range", "spreadsheet_id": url_or_id, "range_name": "A:Z"},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Sheets fetch failed: {res.get('error')}"}
                raw_text = str(res.get("data", res.get("result", "")))
                source_url = f"https://docs.google.com/spreadsheets/d/{url_or_id}"
                source_name = f"Google Sheet {url_or_id}"
                
            # ---- Slack ----
            elif source_type == "slack":
                res = await executor.execute_tool(
                    "slack_search",
                    {"action": "get_channel_history", "channel": url_or_id, "limit": 100},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Slack fetch failed: {res.get('error')}"}
                messages = res.get("data", {}).get("messages", [])
                raw_text = "\n\n".join([f"[{m.get('user', 'Unknown')}]: {m.get('text', '')}" for m in messages])
                source_url = f"slack://{url_or_id}"
                source_name = f"Slack #{url_or_id}"
                
            # ---- Gmail ----
            elif source_type in ["gmail", "google_workspace_gmail"]:
                res = await executor.execute_tool(
                    "google_workspace_gmail",
                    {"operation": "search_emails", "query": url_or_id, "max_results": 50},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Gmail fetch failed: {res.get('error')}"}
                emails = res.get("data", {}).get("emails", [])
                raw_text = "\n\n---\n\n".join([
                    f"Subject: {e.get('subject', '')}\nFrom: {e.get('from', '')}\n\n{e.get('body', e.get('snippet', ''))}"
                    for e in emails
                ])
                source_url = f"gmail://search/{url_or_id}"
                source_name = f"Gmail: {url_or_id}"
                
            # ---- HubSpot ----
            elif source_type == "hubspot":
                res = await executor.execute_tool(
                    "hubspot_contact_operations",
                    {"operation": "read", "limit": 100},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"HubSpot fetch failed: {res.get('error')}"}
                raw_text = str(res.get("data", res.get("result", "")))
                source_url = f"hubspot://contacts"
                source_name = "HubSpot Contacts"
            
            # ---- Generic MCP Tool (dynamic) ----
            else:
                logger.warning(f"Source type '{source_type}' not specifically handled, attempting generic MCP fetch")
                res = await executor.execute_tool(
                    source_type,
                    {"operation": "read", "id": url_or_id},
                    user, db
                )
                if not res.get("success"):
                    return {"status": "error", "message": f"Generic fetch failed for {source_type}: {res.get('error')}"}
                raw_text = str(res.get("data", res.get("result", "")))
                source_url = f"{source_type}://{url_or_id}"
                source_name = f"{source_type}: {url_or_id}"
            
            # If no text was extracted, return error
            if not raw_text or not raw_text.strip():
                return {"status": "error", "message": f"No text content extracted from {source_type} source"}
            
            # Delegate to generic ingestion with KB-aware parameters
            return await self.rag_ingest_content(
                content=raw_text, 
                kb_id=kb_id, 
                user_id=user_id, 
                source_url=source_url,
                source_name=source_name,
                source_tool=source_type,
                user=user,
                db=db
            )
                 
        except Exception as e:
            logger.error(f"Error in source ingestion for {source_type}: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


    # ================================================================
    # RETRIEVAL — dynamic embedding + vector search + optional reranking
    # ================================================================

    async def rag_search_query(
        self, 
        query: str, 
        kb_id: str, 
        user_id: str, 
        embedding_model: str = None,
        vector_db: str = None,
        top_k: int = 5,
        rerank: bool = False,
        rerank_top_n: int = 3,
        user: Any = None,
        db: Any = None,
        session_key: str = "",
    ) -> Dict[str, Any]:
        """
        Retrieval flow: Dynamically routes to correct embedding model and vector DB
        based on KB config. Optionally reranks results using Cohere.

        When ``session_key`` is provided (messaging workflows), the raw query is
        first rewritten using conversation history so that vague follow-ups like
        "How much does each cost?" become self-contained search queries.
        """
        from .tool_executor import ToolExecutor
        executor = ToolExecutor()
        
        # ── CCM: Rewrite vague follow-up queries using conversation history ──
        effective_query = await self._rewrite_query_with_context(query, session_key)
        
        # Resolve hybrid credentials (user BYOK → platform env vars)
        credentials = await self._resolve_credentials(user, db)
        
        # Resolve KB config from database
        kb_config = None
        if db and user_id:
            kb_config = await self._resolve_kb_config(kb_id, user_id, db)
        
        effective_embedding = embedding_model or (kb_config or {}).get("embedding_model", "text-embedding-3-small")
        effective_vector_db = vector_db or (kb_config or {}).get("vector_db", "pinecone")
        embed_operation = self._embedding_model_to_operation(effective_embedding)
        
        # Multi-tenant namespace
        namespace = f"user_{user_id}_kb_{kb_id}"
        logger.info(f"RAG Search: {namespace} | VectorDB: {effective_vector_db} | Query: {effective_query[:100]}")
        
        # 1. Embed query via ToolExecutor (use rewritten query for better retrieval)
        embed_params = {
            "operation": embed_operation,
            "input": effective_query
        }
        embed_res = await executor.execute_tool("ai_embeddings", embed_params, user, db)
        
        if not embed_res.get("success"):
            return {"success": False, "error": f"Query embedding failed: {embed_res.get('error')}"}
            
        query_vector = embed_res.get("embeddings", [])[0]
        
        # 2. Dynamic Vector DB Query (with resolved credentials)
        vector_service = self._get_vector_service_with_creds(effective_vector_db, credentials)
        if effective_vector_db == "pinecone":
            search_res = await vector_service.pinecone_query(
                index_host=None, namespace=namespace,
                vector=query_vector, top_k=top_k
            )
        elif effective_vector_db == "qdrant":
            res = await vector_service.qdrant_search(
                collection_name=namespace, query_vector=query_vector, limit=top_k
            )
            if res.get("success"):
                matches = [{"score": r.get("score", 0), "metadata": r.get("payload", {})} for r in res.get("result", [])]
                search_res = {"success": True, "matches": matches}
            else:
                search_res = res
        elif effective_vector_db == "weaviate":
            res = await vector_service.weaviate_hybrid_search(
                class_name="KnowledgeChunk", query="",
                vector=query_vector, tenant=namespace, limit=top_k
            )
            if res.get("success"):
                matches = [{"score": 1.0 - r.get("_additional", {}).get("distance", 0), "metadata": {k: v for k, v in r.items() if k != "_additional"}} for r in res.get("results", [])]
                search_res = {"success": True, "matches": matches}
            else:
                search_res = res
        else:
            search_res = await self._vector_query(effective_vector_db, namespace, query_vector, top_k=top_k)
        
        if not search_res.get("success"):
            return {"success": False, "error": search_res.get("error")}
             
        matches = search_res.get("matches", [])
        results = [
            {
                "score": match.get("score"),
                "text": match.get("metadata", {}).get("text", ""),
                "source": match.get("metadata", {}).get("source_url", ""),
                "file": match.get("metadata", {}).get("source_file_name", ""),
                "tool": match.get("metadata", {}).get("source_tool", ""),
                "modified": match.get("metadata", {}).get("last_modified", "")
            }
            for match in matches
        ]
        
        # 3. Optional Cohere Reranking
        if rerank and results:
            try:
                documents = [r["text"] for r in results if r["text"]]
                if documents:
                    rerank_res = await self.cohere.cohere_rerank(
                        query=query, documents=documents, top_n=rerank_top_n
                    )
                    if rerank_res.get("success"):
                        reranked = rerank_res.get("results", [])
                        # Reorder results based on reranking scores
                        reranked_results = []
                        for rr in reranked:
                            idx = rr.get("index", 0)
                            if idx < len(results):
                                result = results[idx].copy()
                                result["rerank_score"] = rr.get("relevance_score", 0)
                                reranked_results.append(result)
                        results = reranked_results
                        logger.info(f"Reranked {len(results)} results")
            except Exception as e:
                logger.warning(f"Reranking failed (non-fatal): {e}")
             
        return {
            "success": True, 
            "results": results, 
            "namespace": namespace,
            "vector_db": effective_vector_db,
            "reranked": rerank,
            "effective_query": effective_query
        }


    # ================================================================
    # CONVERSATIONAL QUERY REWRITING — resolve vague follow-ups
    # ================================================================

    # Patterns that signal a query depends on prior conversation context.
    # If the raw query contains any of these AND is short, we rewrite it.
    _CONTEXT_DEPENDENT_SIGNALS = {
        "it", "its", "they", "them", "their", "this", "that", "these",
        "those", "each", "the same", "how much", "how many", "what about",
        "tell me more", "and the", "check again", "what is", "which one",
        "can i", "do you", "is it", "are they", "the one", "same thing",
    }

    async def _rewrite_query_with_context(
        self, query: str, session_key: str
    ) -> str:
        """Rewrite a vague follow-up query using CCM conversation history.

        When a user sends "How much does each cost?" after asking about
        "men plain tshirt", the raw query is too vague for vector search.
        This method rewrites it into a self-contained query like
        "What is the price of the men plain tshirt?" so the RAG retrieval
        returns the correct knowledge-base chunks.

        Designed for **low latency** — skips rewriting when:
        • No session_key is provided (non-messaging workflows)
        • The query already looks self-contained (long & no pronouns)
        • The CCM session has no prior history (first message)

        Returns:
            The rewritten query, or the original query if rewriting is
            not needed or fails.
        """
        if not session_key:
            return query

        # Fast-path: Skip rewriting for queries that are already specific.
        # A query with 8+ words and no context-dependent signal words is
        # likely self-contained (e.g. "How many units of men plain tshirt").
        query_lower = query.lower().strip()
        word_count = len(query_lower.split())
        has_signal = any(s in query_lower for s in self._CONTEXT_DEPENDENT_SIGNALS)

        if word_count >= 8 and not has_signal:
            logger.debug(f"[RAG] Query appears self-contained, skipping rewrite: {query[:80]}")
            return query

        # If query is long AND has no signal words, it's probably fine
        if not has_signal and word_count >= 5:
            return query

        # ── Load conversation history from CCM ──
        try:
            from .conversation_context_manager import context_manager

            session = await context_manager.get_session_by_key(session_key)
            if not session or len(session.messages) < 2:
                # No meaningful history to rewrite from (first message or empty session)
                return query

            # Build a compact history string (last 6 messages max, excluding current)
            recent = session.messages[-7:-1]  # exclude the latest (it's the current query)
            if not recent:
                return query

            history_lines = []
            for msg in recent:
                role_label = "Customer" if msg["role"] == "user" else "Assistant"
                content = msg.get("content", "")[:200]  # Truncate long messages
                history_lines.append(f"{role_label}: {content}")

            history_text = "\n".join(history_lines)

        except Exception as e:
            logger.warning(f"[RAG] CCM load failed for query rewrite (using original): {e}")
            return query

        # ── Use a fast LLM call to rewrite the query ──
        try:
            from .llm_service import llm_service

            rewrite_response = await llm_service.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a query rewriter for a knowledge-base search engine. "
                            "Given a conversation history and the user's latest message, "
                            "rewrite the latest message into a single, self-contained search query "
                            "that can be understood WITHOUT any conversation history. "
                            "Resolve all pronouns (it, they, each, etc.) and references "
                            "to specific entities mentioned earlier.\n\n"
                            "Rules:\n"
                            "- Output ONLY the rewritten query, nothing else\n"
                            "- Keep it concise (under 20 words)\n"
                            "- If the message is already self-contained, return it unchanged\n"
                            "- Do NOT answer the question, just rewrite it\n"
                            "- Preserve the user's intent exactly"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{history_text}\n\n"
                            f"Latest message: {query}\n\n"
                            f"Rewritten search query:"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=60,
                use_background_model=True,
            )

            if rewrite_response and rewrite_response.content:
                rewritten = rewrite_response.content.strip().strip('"').strip("'")
                # Sanity check: if the rewrite is empty or absurdly long, use original
                if rewritten and len(rewritten) < 200:
                    logger.info(f"[RAG] Query rewritten: '{query}' → '{rewritten}'")
                    return rewritten
                else:
                    logger.warning(f"[RAG] Rewrite produced invalid output, using original")

        except Exception as e:
            logger.warning(f"[RAG] Query rewrite LLM call failed (using original): {e}")

        return query

    # ================================================================
    # SYNC — scheduled background sync with delta tracking
    # ================================================================

    async def rag_sync_schedule(self):
        """
        Background task to sync all scheduled Data Sources. 
        Pulls actual User context for MCP execution. Creates SyncLog entries.
        """
        logger.info("Running RAG scheduled sync task")
        from ..database import get_session_maker
        from ..models import DataSource, KnowledgeBase, User, SyncLog
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
                    # Look up KB
                    kb_stmt = select(KnowledgeBase).filter(KnowledgeBase.id == source.kb_id)
                    kb_result = await session.execute(kb_stmt)
                    kb = kb_result.scalars().first()
                    
                    if not kb:
                        continue
                    
                    # Look up User
                    user_stmt = select(User).filter(User.id == kb.user_id)
                    user_res = await session.execute(user_stmt)
                    actual_user = user_res.scalars().first()
                    
                    if not actual_user:
                        logger.warning(f"User {kb.user_id} not found for KB {kb.id}")
                        continue
                    
                    # Create SyncLog entry
                    sync_log = SyncLog(
                        data_source_id=source.id,
                        status="in_progress",
                        started_at=datetime.now(timezone.utc)
                    )
                    session.add(sync_log)
                    await session.commit()
                    
                    # Determine the source identifier
                    url_or_id = None
                    if source.source_type == "website":
                        url_or_id = source.config.get("url")
                    elif source.source_type in ["google_drive", "google_workspace_drive"]:
                        url_or_id = source.config.get("file_id")
                    elif source.source_type == "notion":
                        url_or_id = source.config.get("page_id")
                    elif source.source_type == "airtable":
                        url_or_id = source.config.get("base_id")
                    elif source.source_type in ["google_sheets", "google_workspace_sheets"]:
                        url_or_id = source.config.get("spreadsheet_id")
                    elif source.source_type == "slack":
                        url_or_id = source.config.get("channel")
                    elif source.source_type in ["gmail", "google_workspace_gmail"]:
                        url_or_id = source.config.get("query", source.config.get("label"))
                    elif source.source_type == "hubspot":
                        url_or_id = source.config.get("object_type", "contacts")
                    else:
                        url_or_id = source.config.get("id", source.config.get("url"))
                        
                    if not url_or_id:
                        sync_log.status = "failed"
                        sync_log.error_message = "No source identifier found in config"
                        sync_log.completed_at = datetime.now(timezone.utc)
                        await session.commit()
                        continue
                    
                    try:
                        # Delta sync: delete old vectors for this source first
                        namespace = f"user_{kb.user_id}_kb_{kb.id}"
                        # Note: Full delta requires per-document deletion in vector DB
                        # which needs filter-based delete. For now, we re-ingest.
                        
                        sync_res = await self.rag_ingest_source(
                            url_or_id=url_or_id,
                            kb_id=str(kb.id),
                            user_id=str(kb.user_id),
                            source_type=source.source_type,
                            user=actual_user,
                            db=session
                        )
                        
                        # Update SyncLog
                        sync_log.status = "success" if sync_res.get("status") == "success" else "failed"
                        sync_log.chunks_added = sync_res.get("chunks_added", 0)
                        sync_log.error_message = sync_res.get("message") if sync_res.get("status") != "success" else None
                        sync_log.completed_at = datetime.now(timezone.utc)
                        
                        # Update DataSource last_synced_at
                        source.last_synced_at = datetime.now(timezone.utc)
                        
                        await session.commit()
                        
                        logger.info(f"Sync result for source {source.id} ({source.source_type}): {sync_res.get('status')}")
                        
                    except Exception as e:
                        sync_log.status = "failed"
                        sync_log.error_message = str(e)
                        sync_log.completed_at = datetime.now(timezone.utc)
                        await session.commit()
                        logger.error(f"Sync failed for source {source.id}: {e}")
                            
            except Exception as e:
                logger.error(f"Error in RAG sync scheduler: {e}", exc_info=True)


    # ================================================================
    # DELETE — remove KB namespace from vector DB
    # ================================================================

    async def rag_delete_knowledge_base(self, kb_id: str, user_id: str, vector_db: str = "pinecone") -> Dict[str, Any]:
        """Delete all vectors for a knowledge base from the vector DB."""
        namespace = f"user_{user_id}_kb_{kb_id}"
        logger.info(f"Deleting namespace {namespace} from {vector_db}")
        return await self._vector_delete_namespace(vector_db, namespace)


def get_rag_pipeline_service() -> RAGPipelineService:
    return RAGPipelineService()
