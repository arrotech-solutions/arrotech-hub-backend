"""
RAG Pipeline API Routes
Handles UI interactions for Knowledge Bases, Data Sources, and Search.
"""
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import uuid
from datetime import datetime, timezone

from ..database import get_db
from ..models import User, KnowledgeBase, DataSource, SyncLog
from ..routers.auth_router import get_current_user
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag-pipeline"])


# ================================================================
# Request / Response Models
# ================================================================

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = None
    embedding_model: str = "text-embedding-3-small"
    vector_db: str = "pinecone"
    chunk_size: int = 512
    chunk_overlap: int = 50


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    embedding_model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None


class DataSourceCreate(BaseModel):
    source_type: str
    name: str
    config: dict
    sync_mode: str = "manual"


class RAGQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    rerank: bool = False
    rerank_top_n: int = 3


# ================================================================
# Knowledge Base CRUD
# ================================================================

@router.post("/knowledge-bases")
async def create_knowledge_base(
    kb: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        new_kb = KnowledgeBase(
            user_id=user.id,
            name=kb.name,
            description=kb.description,
            embedding_model=kb.embedding_model,
            vector_db=kb.vector_db,
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap
        )
        db.add(new_kb)
        await db.commit()
        await db.refresh(new_kb)
        return {
            "id": str(new_kb.id), 
            "name": new_kb.name,
            "vector_db": new_kb.vector_db,
            "embedding_model": new_kb.embedding_model,
            "status": "created"
        }
    except Exception as e:
        logger.error(f"Error creating Knowledge Base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.user_id == user.id))
        kbs = result.scalars().all()
        return [{
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "vector_db": kb.vector_db,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at
        } for kb in kbs]
    except Exception as e:
        logger.error(f"Error listing Knowledge Bases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}")
async def get_knowledge_base(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a single Knowledge Base with summary stats."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id)
        )
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        # Count data sources
        source_result = await db.execute(
            select(func.count(DataSource.id)).filter(DataSource.kb_id == kb_uuid)
        )
        source_count = source_result.scalar() or 0

        return {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "vector_db": kb.vector_db,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "source_count": source_count,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Knowledge Base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/knowledge-bases/{kb_id}")
async def update_knowledge_base(
    kb_id: str,
    update: KnowledgeBaseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a Knowledge Base's settings."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id)
        )
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if update.name is not None:
            kb.name = update.name
        if update.description is not None:
            kb.description = update.description
        if update.embedding_model is not None:
            kb.embedding_model = update.embedding_model
        if update.chunk_size is not None:
            kb.chunk_size = update.chunk_size
        if update.chunk_overlap is not None:
            kb.chunk_overlap = update.chunk_overlap

        await db.commit()
        return {"id": str(kb.id), "status": "updated"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating Knowledge Base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a Knowledge Base, its data sources, and its vector DB namespace."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id)
        )
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        # Delete vectors from vector DB
        from ..services.rag_pipeline_service import RAGPipelineService
        rag_service = RAGPipelineService()
        await rag_service.rag_delete_knowledge_base(
            kb_id=str(kb.id),
            user_id=str(user.id),
            vector_db=kb.vector_db
        )

        # Delete KB (cascade deletes data sources and sync logs)
        await db.delete(kb)
        await db.commit()
        
        return {"id": kb_id, "status": "deleted"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting Knowledge Base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# Knowledge Base Stats
# ================================================================

@router.get("/knowledge-bases/{kb_id}/stats")
async def get_knowledge_base_stats(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get stats for a Knowledge Base: source count, last sync, sync history."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id)
        )
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        # Count sources
        source_result = await db.execute(
            select(DataSource).filter(DataSource.kb_id == kb_uuid)
        )
        sources = source_result.scalars().all()

        # Get total chunks from sync logs
        total_chunks = 0
        last_synced = None
        for source in sources:
            log_result = await db.execute(
                select(SyncLog)
                .filter(SyncLog.data_source_id == source.id, SyncLog.status == "success")
                .order_by(SyncLog.completed_at.desc())
                .limit(1)
            )
            last_log = log_result.scalars().first()
            if last_log:
                total_chunks += last_log.chunks_added or 0
                if not last_synced or (last_log.completed_at and last_log.completed_at > last_synced):
                    last_synced = last_log.completed_at
            if source.last_synced_at:
                if not last_synced or source.last_synced_at > last_synced:
                    last_synced = source.last_synced_at

        return {
            "kb_id": kb_id,
            "name": kb.name,
            "source_count": len(sources),
            "total_chunks_indexed": total_chunks,
            "last_synced": last_synced,
            "vector_db": kb.vector_db,
            "embedding_model": kb.embedding_model,
            "sources": [{
                "id": str(s.id),
                "name": s.name,
                "source_type": s.source_type,
                "status": s.status,
                "sync_mode": s.sync_mode,
                "last_synced_at": s.last_synced_at
            } for s in sources]
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting KB stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# Knowledge Base Query (Test/Preview)
# ================================================================

@router.post("/knowledge-bases/{kb_id}/query")
async def query_knowledge_base(
    kb_id: str,
    request: RAGQueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Query a Knowledge Base — returns retrieved chunks + citations."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id)
        )
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        from ..services.rag_pipeline_service import RAGPipelineService
        rag_service = RAGPipelineService()
        
        search_res = await rag_service.rag_search_query(
            query=request.query,
            kb_id=str(kb.id),
            user_id=str(user.id),
            top_k=request.top_k,
            rerank=request.rerank,
            rerank_top_n=request.rerank_top_n,
            user=user,
            db=db
        )
        
        return search_res
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying Knowledge Base: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# Data Source CRUD + Sync
# ================================================================

@router.post("/knowledge-bases/{kb_id}/data-sources")
async def add_data_source(
    kb_id: str,
    source: DataSourceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id))
        kb = result.scalars().first()
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        new_source = DataSource(
            kb_id=kb.id,
            source_type=source.source_type,
            name=source.name,
            config=source.config,
            sync_mode=source.sync_mode
        )
        db.add(new_source)
        await db.commit()
        await db.refresh(new_source)
        return {"id": str(new_source.id), "status": "created"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding Data Source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/data-sources")
async def list_data_sources(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id))
        if not result.scalars().first():
             raise HTTPException(status_code=404, detail="Knowledge base not found")
             
        source_result = await db.execute(select(DataSource).filter(DataSource.kb_id == kb_uuid))
        sources = source_result.scalars().all()
        return [{
            "id": str(s.id),
            "name": s.name,
            "source_type": s.source_type,
            "status": s.status,
            "sync_mode": s.sync_mode,
            "config": s.config,
            "last_synced_at": s.last_synced_at
        } for s in sources]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing Data Sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/knowledge-bases/{kb_id}/data-sources/{source_id}")
async def delete_data_source(
    kb_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a data source from a Knowledge Base."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        source_uuid = uuid.UUID(source_id)
        
        # Verify KB ownership
        result = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == kb_uuid, KnowledgeBase.user_id == user.id))
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        
        # Find and delete source
        source_result = await db.execute(select(DataSource).filter(DataSource.id == source_uuid, DataSource.kb_id == kb_uuid))
        source = source_result.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Data source not found")
        
        await db.delete(source)
        await db.commit()
        return {"id": source_id, "status": "deleted"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting Data Source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/knowledge-bases/{kb_id}/validate-products")
async def validate_kb_products(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Audit catalog sheet rows for missing images, duplicates, and alt-text mismatches."""
    try:
        kb_uuid = uuid.UUID(kb_id)
        result = await db.execute(
            select(KnowledgeBase).filter(
                KnowledgeBase.id == kb_uuid,
                KnowledgeBase.user_id == user.id,
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        from ..services.product_catalog_service import ProductCatalogService

        report = await ProductCatalogService.validate_kb_catalog(
            kb_id=kb_id, user=user, db=db
        )
        return report
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid KB ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating KB products: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# Sync Trigger
# ================================================================

async def _run_sync_in_background(source_id: str, kb_id: str, user_id: str, source_type: str, source_config: dict, db_session_maker):
    """Background task to run source ingestion."""
    from ..services.rag_pipeline_service import RAGPipelineService
    from ..models import User, DataSource, SyncLog
    
    rag_service = RAGPipelineService()
    
    async with db_session_maker() as session:
        try:
            # Get user
            user_result = await session.execute(select(User).filter(User.id == uuid.UUID(user_id)))
            user = user_result.scalars().first()
            if not user:
                logger.error(f"User {user_id} not found for sync")
                return
            
            # Determine source identifier from config
            url_or_id = (
                source_config.get("url") or source_config.get("file_id") or 
                source_config.get("page_id") or source_config.get("spreadsheet_id") or
                source_config.get("channel") or source_config.get("query") or 
                source_config.get("id", "")
            )
            
            # Create sync log
            sync_log = SyncLog(
                data_source_id=uuid.UUID(source_id),
                status="in_progress",
                started_at=datetime.now(timezone.utc)
            )
            session.add(sync_log)
            await session.commit()
            
            # Run ingestion
            sync_res = await rag_service.rag_ingest_source(
                url_or_id=url_or_id,
                kb_id=kb_id,
                user_id=user_id,
                source_type=source_type,
                user=user,
                db=session
            )
            
            # Update sync log
            sync_log.status = "success" if sync_res.get("status") == "success" else "failed"
            sync_log.chunks_added = sync_res.get("chunks_added", 0)
            sync_log.error_message = sync_res.get("message") if sync_res.get("status") != "success" else None
            sync_log.completed_at = datetime.now(timezone.utc)
            
            # Update source last_synced_at
            source_result = await session.execute(select(DataSource).filter(DataSource.id == uuid.UUID(source_id)))
            source = source_result.scalars().first()
            if source:
                source.last_synced_at = datetime.now(timezone.utc)
                source.status = "active" if sync_res.get("status") == "success" else "error"
            
            await session.commit()
            logger.info(f"Background sync completed for source {source_id}: {sync_res.get('status')}")
            
        except Exception as e:
            logger.error(f"Background sync failed for source {source_id}: {e}")
            try:
                sync_log.status = "failed"
                sync_log.error_message = str(e)
                sync_log.completed_at = datetime.now(timezone.utc)
                await session.commit()
            except Exception:
                pass


@router.post("/data-sources/{source_id}/sync")
async def trigger_sync(
    source_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Triggers a sync/ingestion for a specific data source."""
    try:
        source_uuid = uuid.UUID(source_id)
        stmt = select(DataSource).join(KnowledgeBase).filter(
            DataSource.id == source_uuid,
            KnowledgeBase.user_id == user.id
        )
        result = await db.execute(stmt)
        source = result.scalars().first()
        if not source:
            raise HTTPException(status_code=404, detail="Data source not found")
        
        # Update status to indexing
        source.status = "indexing"
        await db.commit()
        
        # Determine source identifier from config
        source_config = source.config or {}
        url_or_id = (
            source_config.get("url") or source_config.get("file_id") or 
            source_config.get("page_id") or source_config.get("spreadsheet_id") or
            source_config.get("channel") or source_config.get("query") or 
            source_config.get("id", "")
        )
        
        # Enqueue the Celery Task
        from ..tasks.rag_tasks import rag_ingest_source_task
        rag_ingest_source_task.delay(
            url_or_id=url_or_id,
            kb_id=str(source.kb_id),
            user_id=str(user.id),
            source_type=source.source_type
        )
        
        return {"status": "sync_triggered", "source_id": source_id, "message": "Background ingestion started"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Source ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ================================================================
# Sync Logs
# ================================================================

@router.get("/data-sources/{source_id}/sync-logs")
async def get_sync_logs(
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get sync history for a data source."""
    try:
        source_uuid = uuid.UUID(source_id)
        
        # Verify user owns this source
        stmt = select(DataSource).join(KnowledgeBase).filter(
            DataSource.id == source_uuid,
            KnowledgeBase.user_id == user.id
        )
        result = await db.execute(stmt)
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail="Data source not found")
        
        log_result = await db.execute(
            select(SyncLog)
            .filter(SyncLog.data_source_id == source_uuid)
            .order_by(SyncLog.started_at.desc())
            .limit(20)
        )
        logs = log_result.scalars().all()
        
        return [{
            "id": str(log.id),
            "status": log.status,
            "chunks_added": log.chunks_added,
            "chunks_deleted": log.chunks_deleted,
            "error_message": log.error_message,
            "started_at": log.started_at,
            "completed_at": log.completed_at
        } for log in logs]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Source ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sync logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
