"""
Google Drive Auto-Sync — shared helpers + watch renewal.

Primary sync path: Google Drive Changes API push notifications (webhooks).
This module provides folder-resolution helpers, watermark deduplication, and
a Beat task to renew expiring push channels.

``poll_drive_sources_task`` is retained as a manual fallback but is not scheduled.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.celery_app import app

from .utils import run_async as _run_async

logger = logging.getLogger(__name__)

_DRIVE_SOURCE_TYPES = ("google_drive", "google_workspace_drive")
_DRIVE_STEP_SOURCE_TYPES = frozenset({"google_drive", "google_workspace_drive"})


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _folder_changed(latest: datetime, watermark: Optional[datetime]) -> bool:
    """True only when Drive's modifiedTime is strictly newer than our watermark."""
    if watermark is None:
        return False  # caller handles first-time baseline separately
    return latest > watermark


async def _latest_modified_time(executor, folder_id: str, user, db) -> Optional[datetime]:
    """Return the newest file modifiedTime in a Drive folder, or None."""
    try:
        res = await executor.execute_tool(
            "google_workspace_drive",
            {
                "operation": "list_files",
                "folder_id": folder_id,
                "max_results": 100,
                "order_by": "modifiedTime desc",
            },
            user,
            db,
        )
    except Exception as e:
        logger.warning(f"[DRIVE_SYNC] list_files failed for folder {folder_id}: {e}")
        return None
    if not res.get("success"):
        logger.warning(f"[DRIVE_SYNC] list_files error for folder {folder_id}: {res.get('error')}")
        return None
    latest: Optional[datetime] = None
    for f in res.get("files", []):
        mt = _parse_iso(f.get("modified_time"))
        if mt and (latest is None or mt > latest):
            latest = mt
    return latest


def _folder_id_from_config(config: Dict[str, Any]) -> str:
    if not isinstance(config, dict):
        return ""
    for key in ("folder_id", "drive_folder_id", "google_drive_folder_id", "url_or_id", "id", "url"):
        val = config.get(key)
        if val:
            return str(val)
    return ""


def _literal_folder_id(value: Any) -> str:
    """Return a folder ID only when it is a concrete value (not a Jinja template)."""
    s = str(value or "").strip()
    if not s or "{{" in s or "}}" in s:
        return ""
    return s


def _is_drive_folder_event_workflow(wf) -> bool:
    """True when workflow listens for Google Drive folder change events."""
    tcfg = wf.trigger_config or {}
    platform = (tcfg.get("platform") or "").lower()
    event_type = (tcfg.get("event_type") or tcfg.get("trigger") or "").lower()
    return platform == "google_drive" and event_type == "google_drive_folder_changed"


def _folder_id_from_workflow(wf) -> str:
    """
    Resolve the Drive folder to watch for a workflow.

    The frontend stores the folder on the ``rag_ingest_source`` step
    (``url_or_id``), not in ``trigger_config``.
    """
    tcfg = wf.trigger_config or {}
    fid = _literal_folder_id(_folder_id_from_config(tcfg))
    if fid:
        return fid

    steps = sorted(wf.steps or [], key=lambda s: getattr(s, "step_number", 0))
    for step in steps:
        if step.tool_name != "rag_ingest_source":
            continue
        params = step.tool_parameters or {}
        st = (params.get("source_type") or "").lower()
        if st not in _DRIVE_STEP_SOURCE_TYPES:
            continue
        fid = _literal_folder_id(_folder_id_from_config(params))
        if fid:
            return fid
    return ""


def _kb_id_from_workflow(wf) -> Optional[str]:
    """KB id from the first rag_ingest_source step, if present."""
    for step in sorted(wf.steps or [], key=lambda s: getattr(s, "step_number", 0)):
        if step.tool_name != "rag_ingest_source":
            continue
        params = step.tool_parameters or {}
        kb = str(params.get("kb_id") or "").strip()
        if kb and "{{" not in kb:
            return kb
    return None


async def _find_data_source_for_folder(db, kb_id: str, folder_id: str):
    """Find the auto-sync DataSource row for a KB + Drive folder."""
    from sqlalchemy import select
    from src.models import DataSource

    if not kb_id or not folder_id:
        return None
    try:
        import uuid as _uuid
        kb_uuid = _uuid.UUID(str(kb_id))
    except (ValueError, TypeError):
        return None

    result = await db.execute(
        select(DataSource).where(
            DataSource.kb_id == kb_uuid,
            DataSource.source_type.in_(_DRIVE_SOURCE_TYPES),
            DataSource.status == "active",
        )
    )
    for src in result.scalars().all():
        cfg = src.config or {}
        if _folder_id_from_config(cfg) == folder_id:
            return src
    return None


async def _get_watermark(db, wf=None, data_source=None) -> Optional[datetime]:
    """Read the persisted Drive watermark (DB-first, Redis cache second)."""
    from src.services.cache_service import cache_service

    if data_source and data_source.last_synced_at:
        return _parse_iso(data_source.last_synced_at)

    if wf:
        meta = wf.workflow_metadata or {}
        wm = _parse_iso(meta.get("drive_watermark"))
        if wm:
            return wm
        redis_key = f"drive_wf_watermark:{wf.id}:{_folder_id_from_workflow(wf)}"
        cached = cache_service.get(redis_key)
        if isinstance(cached, str):
            return _parse_iso(cached)

    return None


async def _set_watermark(
    db,
    latest: datetime,
    *,
    data_source=None,
    wf=None,
    folder_id: str = "",
) -> None:
    """Persist watermark after a successful sync or baseline observation."""
    from src.services.cache_service import cache_service

    iso = latest.isoformat()

    if data_source is not None:
        data_source.last_synced_at = latest

    if wf is not None:
        meta = dict(wf.workflow_metadata or {})
        meta["drive_watermark"] = iso
        wf.workflow_metadata = meta
        if folder_id:
            cache_service.set(
                f"drive_wf_watermark:{wf.id}:{folder_id}",
                iso,
                expire_seconds=60 * 60 * 24 * 90,
            )


async def _workflow_watched_folders(db) -> Set[Tuple[str, str]]:
    """Set of (user_id, folder_id) pairs already handled by active Drive workflows."""
    from sqlalchemy import select, and_
    from sqlalchemy.orm import selectinload
    from src.models import Workflow, WorkflowStatus, WorkflowTriggerType

    watched: Set[Tuple[str, str]] = set()
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(
            and_(
                Workflow.status == WorkflowStatus.ACTIVE,
                Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
            )
        )
    )
    for wf in result.scalars().all():
        if not _is_drive_folder_event_workflow(wf):
            continue
        fid = _folder_id_from_workflow(wf)
        if fid:
            watched.add((str(wf.user_id), fid))
    return watched


async def _poll_rag_sources(db, watched_folders: Set[Tuple[str, str]]) -> int:
    """
    Re-ingest RAG Drive sources whose folders changed since last sync.

    Skips folders already watched by an active Drive event workflow to avoid
    paying for duplicate embeddings / Pinecone upserts.
    """
    from sqlalchemy import select
    from src.models import DataSource, KnowledgeBase, User
    from src.services.tool_executor import ToolExecutor
    from src.tasks.rag_tasks import rag_ingest_source_task

    triggered = 0
    result = await db.execute(
        select(DataSource).where(
            DataSource.source_type.in_(_DRIVE_SOURCE_TYPES),
            DataSource.status == "active",
        )
    )
    sources = result.scalars().all()
    executor = ToolExecutor()

    for src in sources:
        config = src.config or {}
        auto = (src.sync_mode in ("scheduled", "realtime")) or bool(config.get("auto_sync"))
        if not auto:
            continue
        folder_id = _folder_id_from_config(config)
        if not folder_id:
            continue

        kb_res = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == src.kb_id))
        kb = kb_res.scalar_one_or_none()
        if not kb:
            continue

        if (str(kb.user_id), folder_id) in watched_folders:
            logger.debug(
                f"[DRIVE_SYNC] RAG source {src.id}: folder {folder_id} handled by "
                "active workflow — skipping duplicate poll"
            )
            continue

        user_res = await db.execute(select(User).where(User.id == kb.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            continue

        latest = await _latest_modified_time(executor, folder_id, user, db)
        if latest is None:
            continue

        watermark = await _get_watermark(db, data_source=src)
        if watermark is None:
            await _set_watermark(db, latest, data_source=src)
            logger.info(
                f"[DRIVE_SYNC] RAG source {src.id}: baseline watermark set "
                f"({latest.isoformat()}) — no ingest"
            )
            continue

        if not _folder_changed(latest, watermark):
            continue

        logger.info(
            f"[DRIVE_SYNC] RAG source {src.id}: folder changed "
            f"({watermark.isoformat()} → {latest.isoformat()}) → re-ingesting"
        )
        try:
            rag_ingest_source_task.delay(
                url_or_id=folder_id,
                kb_id=str(src.kb_id),
                user_id=str(kb.user_id),
                source_type=src.source_type,
            )
            await _set_watermark(db, latest, data_source=src)
            triggered += 1
        except Exception as e:
            logger.error(f"[DRIVE_SYNC] Failed to enqueue ingest for source {src.id}: {e}")

    if triggered:
        await db.commit()
    else:
        # Baseline updates may have been staged on DataSource rows
        try:
            await db.commit()
        except Exception:
            await db.rollback()
    return triggered


async def _poll_drive_workflows(db) -> int:
    """Fire active workflows when their watched Drive folder actually changed."""
    from sqlalchemy import select, and_
    from sqlalchemy.orm import selectinload
    from src.models import Workflow, WorkflowStatus, WorkflowTriggerType, User
    from src.services.tool_executor import ToolExecutor
    from src.services.workflow_builder_service import WorkflowBuilderService

    triggered = 0
    result = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(
            and_(
                Workflow.status == WorkflowStatus.ACTIVE,
                Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
            )
        )
    )
    workflows = result.scalars().all()
    executor = ToolExecutor()
    builder = WorkflowBuilderService()

    for wf in workflows:
        if not _is_drive_folder_event_workflow(wf):
            continue

        folder_id = _folder_id_from_workflow(wf)
        if not folder_id:
            logger.warning(
                f"[DRIVE_SYNC] Workflow '{wf.name}' ({wf.id}) has no folder id — skipping"
            )
            continue

        user_res = await db.execute(select(User).where(User.id == wf.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            continue

        latest = await _latest_modified_time(executor, folder_id, user, db)
        if latest is None:
            logger.info(
                f"[DRIVE_SYNC] Workflow {wf.id}: could not read folder {folder_id}"
            )
            continue

        kb_id = _kb_id_from_workflow(wf)
        data_source = await _find_data_source_for_folder(db, kb_id, folder_id) if kb_id else None
        watermark = await _get_watermark(db, wf=wf, data_source=data_source)

        if watermark is None:
            await _set_watermark(
                db, latest, wf=wf, data_source=data_source, folder_id=folder_id
            )
            logger.info(
                f"[DRIVE_SYNC] Workflow {wf.id}: baseline watermark set "
                f"({latest.isoformat()}) — no ingest"
            )
            continue

        if not _folder_changed(latest, watermark):
            continue

        logger.info(
            f"[DRIVE_SYNC] Workflow {wf.id}: folder changed "
            f"({watermark.isoformat()} → {latest.isoformat()}) → executing"
        )
        try:
            await builder.execute_workflow(
                workflow_id=wf.id,
                user_id=wf.user_id,
                db=db,
                input_data={
                    "google_drive_folder_id": folder_id,
                    "drive_folder_id": folder_id,
                    "google_drive_state": "change",
                    "google_drive_modified_time": latest.isoformat(),
                },
            )
            await _set_watermark(
                db, latest, wf=wf, data_source=data_source, folder_id=folder_id
            )
            triggered += 1
        except Exception as e:
            logger.error(f"[DRIVE_SYNC] Failed to execute workflow {wf.id}: {e}")

    if triggered:
        await db.commit()
    else:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
    return triggered


@app.task(
    name="src.tasks.drive_sync_tasks.poll_drive_sources_task",
    bind=True,
    acks_late=True,
    time_limit=240,
    soft_time_limit=200,
)
def poll_drive_sources_task(self):
    """Beat entrypoint: poll Drive-linked sources/workflows for real changes only."""

    async def _poll():
        from src.database import get_session_maker

        session_maker = get_session_maker()
        async with session_maker() as db:
            watched = await _workflow_watched_folders(db)
            rag_n = 0
            wf_n = 0
            try:
                wf_n = await _poll_drive_workflows(db)
            except Exception as e:
                logger.error(f"[DRIVE_SYNC] Workflow poll error: {e}", exc_info=True)
            try:
                rag_n = await _poll_rag_sources(db, watched)
            except Exception as e:
                logger.error(f"[DRIVE_SYNC] RAG poll error: {e}", exc_info=True)
            return {"rag_synced": rag_n, "workflows_fired": wf_n, "no_change_skips": True}

    result = _run_async(_poll())
    if result.get("rag_synced") or result.get("workflows_fired"):
        logger.info(f"[DRIVE_SYNC] Poll complete (changes detected): {result}")
    else:
        logger.debug(f"[DRIVE_SYNC] Poll complete (no changes): {result}")
    return result


@app.task(
    name="src.tasks.drive_sync_tasks.renew_drive_watches_task",
    bind=True,
    acks_late=True,
    time_limit=300,
    soft_time_limit=240,
)
def renew_drive_watches_task(self):
    """Beat entrypoint: renew Drive push channels before they expire (~7 days)."""

    async def _renew():
        from src.database import get_session_maker
        from src.services.drive_watch_service import renew_expiring_drive_watches

        session_maker = get_session_maker()
        async with session_maker() as db:
            return await renew_expiring_drive_watches(db)

    result = _run_async(_renew())
    if result.get("renewed") or result.get("failed"):
        logger.info(f"[DRIVE_WATCH] Renewal run: {result}")
    else:
        logger.debug(f"[DRIVE_WATCH] Renewal run: {result}")
    return result
