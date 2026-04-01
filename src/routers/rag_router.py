"""
RAG Pipeline API Routes
Handles UI interactions for Knowledge Bases and Data Sources.
"""
import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import uuid

from ..database import get_db
from ..models import User, KnowledgeBase, DataSource, SyncLog
from ..routers.auth_router import get_current_user
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag-pipeline"])


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = None
    embedding_model: str = "text-embedding-3-small"
    vector_db: str = "pinecone"
    chunk_size: int = 512
    chunk_overlap: int = 50


class DataSourceCreate(BaseModel):
    source_type: str
    name: str
    config: dict
    sync_mode: str = "manual"


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
        return {"id": str(new_kb.id), "status": "created"}
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
            "created_at": kb.created_at
        } for kb in kbs]
    except Exception as e:
        logger.error(f"Error listing Knowledge Bases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        logger.error(f"Error listing Data Sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data-sources/{source_id}/sync")
async def trigger_sync(
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually triggers a sync/ingestion for the specific data source.
    """
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
             
        # Placeholder for RAG pipeline service ingestion call
        # from ..services.rag_pipeline_service import trigger_ingestion
        # await trigger_ingestion(str(source.id))
        
        return {"status": "sync_triggered", "message": "Background ingestion started (placeholder)"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Source ID format")
    except Exception as e:
         logger.error(f"Error triggering sync: {e}")
         raise HTTPException(status_code=500, detail=str(e))
