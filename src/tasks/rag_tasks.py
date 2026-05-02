"""
RAG Tasks — Long-running RAG pipeline operations via Celery.

RAG ingestion is CPU-intensive (embedding generation) and I/O-bound
(vector DB calls). Running in a dedicated low-priority queue prevents
blocking real-time webhook processing.

Queue: low
"""

import logging
from typing import Dict, Any, Optional, List
from src.celery_app import app

logger = logging.getLogger(__name__)


from .utils import run_async as _run_async

@app.task(
    name="src.tasks.rag_tasks.rag_ingest_source_task",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
    time_limit=600,       # 10 minute hard limit for large documents
    soft_time_limit=540,  # 9 minute soft limit
)
def rag_ingest_source_task(
    self,
    url_or_id: str,
    kb_id: str,
    user_id: str,
    source_type: str = "website",
):
    """
    Fetch data from a source (website, Google Drive, Notion, etc.),
    parse, chunk, embed, and upsert into the vector database.

    This is the heavy-lifting RAG pipeline that can take minutes for
    large documents or multi-file Drive folders.
    """
    logger.info(
        f"[CeleryRAG] Ingesting source: type={source_type}, id={url_or_id}, kb={kb_id}"
    )

    async def _ingest():
        from src.services.rag_pipeline_service import RAGPipelineService
        from src.database import get_session_maker
        from src.models import User
        from sqlalchemy import select

        service = RAGPipelineService()
        session_maker = get_session_maker()

        async with session_maker() as db:
            # Fetch user for credential resolution
            user = None
            try:
                import uuid as uuid_mod
                result = await db.execute(
                    select(User).filter(User.id == uuid_mod.UUID(user_id))
                )
                user = result.scalars().first()
            except Exception:
                pass

            result = await service.rag_ingest_source(
                url_or_id=url_or_id,
                kb_id=kb_id,
                user_id=user_id,
                source_type=source_type,
                user=user,
                db=db,
            )
            return result

    result = _run_async(_ingest())
    logger.info(f"[CeleryRAG] Ingestion result: {result.get('status')}, chunks={result.get('chunks_added', 0)}")
    return result


@app.task(
    name="src.tasks.rag_tasks.rag_ingest_content_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
)
def rag_ingest_content_task(
    self,
    content: Any,
    kb_id: str,
    user_id: str,
    source_url: str = None,
    source_name: str = None,
    source_tool: str = "custom",
    metadata: Dict[str, Any] = None,
):
    """
    Process raw content (text, JSON objects, lists) into the vector database.

    Use this for direct content ingestion when the data is already fetched
    (e.g., from a workflow step output or a custom API call).
    """
    logger.info(f"[CeleryRAG] Ingesting content for kb={kb_id}, source={source_tool}")

    async def _ingest():
        from src.services.rag_pipeline_service import RAGPipelineService
        from src.database import get_session_maker
        from src.models import User
        from sqlalchemy import select

        service = RAGPipelineService()
        session_maker = get_session_maker()

        async with session_maker() as db:
            user = None
            try:
                import uuid as uuid_mod
                result = await db.execute(
                    select(User).filter(User.id == uuid_mod.UUID(user_id))
                )
                user = result.scalars().first()
            except Exception:
                pass

            result = await service.rag_ingest_content(
                content=content,
                kb_id=kb_id,
                user_id=user_id,
                source_url=source_url,
                source_name=source_name,
                source_tool=source_tool,
                metadata=metadata,
                user=user,
                db=db,
            )
            return result

    result = _run_async(_ingest())
    return result
