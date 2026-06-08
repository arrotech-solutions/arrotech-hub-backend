"""
Google Drive Auto-Sync — Celery Beat polling.

Periodically polls Google Drive folders linked to:
  (a) RAG DataSource rows configured for auto-sync (sync_mode scheduled/realtime
      or config.auto_sync), re-ingesting them when files change, and
  (b) active EVENT workflows listening for Google Drive changes, executing the
      workflow (scoped to its owner) when the watched folder changes.

Change detection uses the folder's latest file modifiedTime compared against a
stored watermark (DataSource.last_synced_at for RAG; Redis cache for workflows).
This reuses the existing Celery Beat infrastructure rather than Drive push
notifications, which would require public webhook watch registration + renewal.

Queue: low
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


async def _latest_modified_time(executor, folder_id: str, user, db) -> Optional[datetime]:
    """Return the newest file modifiedTime in a Drive folder, or None."""
    try:
        res = await executor.execute_tool(
            "google_workspace_drive",
            {"operation": "list_files", "folder_id": folder_id, "max_results": 100,
             "order_by": "modifiedTime desc"},
            user, db,
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
    (``url_or_id``), not in ``trigger_config`` — so we fall back to steps
    when the trigger block has no folder id.
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


async def _poll_rag_sources(db) -> int:
    """Re-ingest RAG Drive sources whose folders changed since last sync."""
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
        user_res = await db.execute(select(User).where(User.id == kb.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            continue

        latest = await _latest_modified_time(executor, folder_id, user, db)
        if latest is None:
            continue
        last_synced = _parse_iso(src.last_synced_at)
        if last_synced is not None and latest <= last_synced:
            continue  # no change since last sync

        logger.info(f"[DRIVE_SYNC] RAG source {src.id} changed → re-ingesting folder {folder_id}")
        try:
            rag_ingest_source_task.delay(
                url_or_id=folder_id,
                kb_id=str(src.kb_id),
                user_id=str(kb.user_id),
                source_type=src.source_type,
            )
            src.last_synced_at = latest
            triggered += 1
        except Exception as e:
            logger.error(f"[DRIVE_SYNC] Failed to enqueue ingest for source {src.id}: {e}")

    if triggered:
        await db.commit()
    return triggered


async def _poll_drive_workflows(db) -> int:
    """Fire active workflows listening for Drive changes on their watched folder."""
    from sqlalchemy import select, and_
    from sqlalchemy.orm import selectinload
    from src.models import Workflow, WorkflowStatus, WorkflowTriggerType
    from src.services.tool_executor import ToolExecutor
    from src.services.workflow_builder_service import WorkflowBuilderService
    from src.services.cache_service import cache_service
    from src.models import User

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
                f"[DRIVE_SYNC] Workflow '{wf.name}' ({wf.id}) is a Drive event workflow "
                "but has no folder id on trigger_config or rag_ingest_source step — skipping"
            )
            continue

        user_res = await db.execute(select(User).where(User.id == wf.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            continue

        latest = await _latest_modified_time(executor, folder_id, user, db)
        if latest is None:
            logger.info(
                f"[DRIVE_SYNC] Workflow {wf.id}: could not read folder {folder_id} "
                "(check Google connection / folder access)"
            )
            continue

        watermark_key = f"drive_wf_watermark:{wf.id}:{folder_id}"
        prev = _parse_iso(cache_service.get(watermark_key))
        should_fire = False

        if prev is None:
            # First poll after deploy/enable: fire if the folder changed AFTER the
            # workflow was last saved (catches edits made right after activation).
            wf_updated = _parse_iso(wf.updated_at)
            if wf_updated and latest > wf_updated:
                should_fire = True
                logger.info(
                    f"[DRIVE_SYNC] Workflow {wf.id}: first poll, folder changed "
                    f"since workflow update ({latest.isoformat()} > {wf_updated.isoformat()})"
                )
            else:
                cache_service.set(
                    watermark_key, latest.isoformat(), expire_seconds=60 * 60 * 24 * 60
                )
                logger.info(
                    f"[DRIVE_SYNC] Workflow {wf.id}: baseline watermark set for folder {folder_id}"
                )
        elif latest > prev:
            should_fire = True

        if not should_fire:
            continue

        logger.info(f"[DRIVE_SYNC] Workflow {wf.id} folder {folder_id} changed → executing")
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
            cache_service.set(watermark_key, latest.isoformat(), expire_seconds=60 * 60 * 24 * 60)
            triggered += 1
        except Exception as e:
            logger.error(f"[DRIVE_SYNC] Failed to execute workflow {wf.id}: {e}")

    return triggered


@app.task(
    name="src.tasks.drive_sync_tasks.poll_drive_sources_task",
    bind=True,
    acks_late=True,
    time_limit=240,
    soft_time_limit=200,
)
def poll_drive_sources_task(self):
    """Beat entrypoint: poll Drive-linked RAG sources and workflows for changes."""

    async def _poll():
        from src.database import get_session_maker

        session_maker = get_session_maker()
        async with session_maker() as db:
            rag_n = 0
            wf_n = 0
            try:
                rag_n = await _poll_rag_sources(db)
            except Exception as e:
                logger.error(f"[DRIVE_SYNC] RAG poll error: {e}", exc_info=True)
            try:
                wf_n = await _poll_drive_workflows(db)
            except Exception as e:
                logger.error(f"[DRIVE_SYNC] Workflow poll error: {e}", exc_info=True)
            return {"rag_synced": rag_n, "workflows_fired": wf_n}

    result = _run_async(_poll())
    logger.info(f"[DRIVE_SYNC] Poll complete: {result}")
    return result
