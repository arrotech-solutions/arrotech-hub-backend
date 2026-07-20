"""
Google Drive push-notification watch management.

Uses the Drive Changes API (``changes.watch``) so edits to spreadsheets and
other files inside watched folders trigger ingestion — folder-only watches miss
in-place file edits.

One push channel is registered per user's Google Workspace connection. Incoming
webhooks are mapped back to the user via a deterministic channel id, changes
are listed incrementally, and only folders linked to active workflows or
auto-sync DataSources are re-ingested (with watermark deduplication).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models import (
    Connection,
    ConnectionStatus,
    DataSource,
    User,
    Workflow,
    WorkflowStatus,
    WorkflowTriggerType,
)
from .google_workspace.base_client import GoogleWorkspaceBaseClient
from .google_workspace.drive_service import DriveService

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "arrotech-drive-"
_WATCH_CONFIG_KEY = "drive_push_watch"
_RENEW_WITHIN_MS = 24 * 60 * 60 * 1000  # renew if expiring within 24h


def drive_webhook_url() -> str:
    """Public HTTPS URL Google will POST push notifications to."""
    override = getattr(settings, "GOOGLE_DRIVE_WEBHOOK_URL", None)
    if override:
        return str(override).rstrip("/")
    base = (settings.API_BASE_URL or "http://localhost:8000").rstrip("/")
    return f"{base}/api/google-drive/events"


def channel_id_for_user(user_id) -> str:
    return f"{_CHANNEL_PREFIX}{user_id}"


def user_id_from_channel(channel_id: Optional[str]) -> Optional[str]:
    if not channel_id or not channel_id.startswith(_CHANNEL_PREFIX):
        return None
    return channel_id[len(_CHANNEL_PREFIX) :]


def _gw_credentials(connection: Connection) -> Dict[str, Any]:
    cfg = connection.config or {}
    return {
        "client_id": cfg.get("client_id"),
        "client_secret": cfg.get("client_secret"),
        "refresh_token": cfg.get("refresh_token"),
        "access_token": cfg.get("access_token"),
        "scopes": cfg.get("scopes"),
    }


async def _get_gw_connection(db: AsyncSession, user_id) -> Optional[Connection]:
    result = await db.execute(
        select(Connection).where(
            Connection.user_id == user_id,
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    return result.scalars().first()


def _watch_state(connection: Connection) -> Dict[str, Any]:
    cfg = connection.config or {}
    state = cfg.get(_WATCH_CONFIG_KEY)
    return state if isinstance(state, dict) else {}


def _save_watch_state(connection: Connection, state: Optional[Dict[str, Any]]) -> None:
    cfg = dict(connection.config or {})
    if state:
        cfg[_WATCH_CONFIG_KEY] = state
    else:
        cfg.pop(_WATCH_CONFIG_KEY, None)
    connection.config = cfg


async def user_needs_drive_watch(db: AsyncSession, user_id) -> bool:
    """True when the user has at least one active Drive auto-sync target."""
    from ..tasks.drive_sync_tasks import (
        _DRIVE_SOURCE_TYPES,
        _folder_id_from_config,
        _folder_id_from_workflow,
        _is_drive_folder_event_workflow,
    )

    wf_res = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(
            and_(
                Workflow.user_id == user_id,
                Workflow.status == WorkflowStatus.ACTIVE,
                Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
            )
        )
    )
    for wf in wf_res.scalars().all():
        if _is_drive_folder_event_workflow(wf) and _folder_id_from_workflow(wf):
            return True

    src_res = await db.execute(
        select(DataSource).where(
            DataSource.source_type.in_(_DRIVE_SOURCE_TYPES),
            DataSource.status == "active",
        )
    )
    for src in src_res.scalars().all():
        cfg = src.config or {}
        auto = (src.sync_mode in ("scheduled", "realtime")) or bool(cfg.get("auto_sync"))
        if not auto or not _folder_id_from_config(cfg):
            continue
        from ..models import KnowledgeBase

        kb_res = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == src.kb_id)
        )
        kb = kb_res.scalar_one_or_none()
        if kb and str(kb.user_id) == str(user_id):
            return True
    return False


async def get_watched_folder_ids(db: AsyncSession, user_id) -> Set[str]:
    """Folder IDs this user wants kept in sync via Drive push."""
    from ..tasks.drive_sync_tasks import (
        _DRIVE_SOURCE_TYPES,
        _folder_id_from_config,
        _folder_id_from_workflow,
        _is_drive_folder_event_workflow,
        _workflow_watched_folders,
    )

    folders: Set[str] = set()
    wf_res = await db.execute(
        select(Workflow)
        .options(selectinload(Workflow.steps))
        .where(
            and_(
                Workflow.user_id == user_id,
                Workflow.status == WorkflowStatus.ACTIVE,
                Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
            )
        )
    )
    for wf in wf_res.scalars().all():
        if not _is_drive_folder_event_workflow(wf):
            continue
        fid = _folder_id_from_workflow(wf)
        if fid:
            folders.add(fid)

    watched_by_wf = await _workflow_watched_folders(db)
    src_res = await db.execute(
        select(DataSource).where(
            DataSource.source_type.in_(_DRIVE_SOURCE_TYPES),
            DataSource.status == "active",
        )
    )
    for src in src_res.scalars().all():
        cfg = src.config or {}
        auto = (src.sync_mode in ("scheduled", "realtime")) or bool(cfg.get("auto_sync"))
        folder_id = _folder_id_from_config(cfg)
        if not auto or not folder_id:
            continue
        from ..models import KnowledgeBase

        kb_res = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == src.kb_id)
        )
        kb = kb_res.scalar_one_or_none()
        if not kb or str(kb.user_id) != str(user_id):
            continue
        if (str(user_id), folder_id) in watched_by_wf:
            continue
        folders.add(folder_id)
    return folders


def _expiration_ms(state: Dict[str, Any]) -> Optional[int]:
    raw = state.get("expiration_ms") or state.get("expiration")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _watch_needs_renewal(state: Dict[str, Any]) -> bool:
    exp = _expiration_ms(state)
    if not exp:
        return True
    return exp <= int(time.time() * 1000) + _RENEW_WITHIN_MS


async def _build_drive_service(connection: Connection) -> DriveService:
    base = GoogleWorkspaceBaseClient(_gw_credentials(connection))
    return DriveService(base)


async def register_drive_watch(
    user: User,
    db: AsyncSession,
    *,
    connection: Optional[Connection] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Register (or renew) a Drive Changes push channel for ``user``.

    Best-effort: returns status dict; does not raise on Google API errors.
    """
    if not await user_needs_drive_watch(db, user.id):
        if connection:
            await stop_drive_watch(user, db, connection=connection)
        return {"watch_activated": False, "reason": "no_drive_sync_targets"}

    webhook = drive_webhook_url()
    if not webhook.startswith("https://"):
        logger.warning(
            f"[DRIVE_WATCH] Webhook URL is not HTTPS ({webhook}) — "
            "Google Drive push requires a public HTTPS endpoint (set API_BASE_URL)."
        )
        return {"watch_activated": False, "reason": "webhook_not_https", "url": webhook}

    conn = connection or await _get_gw_connection(db, user.id)
    if not conn:
        return {"watch_activated": False, "reason": "no_google_workspace_connection"}

    existing = _watch_state(conn)
    if existing and not force and not _watch_needs_renewal(existing):
        return {
            "watch_activated": True,
            "renewed": False,
            "channel_id": existing.get("channel_id"),
            "expiration_ms": _expiration_ms(existing),
        }

    drive = await _build_drive_service(conn)
    channel_id = channel_id_for_user(user.id)

    if existing.get("channel_id") and existing.get("resource_id"):
        try:
            await drive.stop_channel(
                str(existing["channel_id"]),
                str(existing["resource_id"]),
            )
        except Exception as stop_err:
            logger.debug(f"[DRIVE_WATCH] stop old channel (ignored): {stop_err}")

    page_token = existing.get("page_token")
    if not page_token:
        token_res = await drive.get_start_page_token()
        if not token_res.get("success"):
            return {
                "watch_activated": False,
                "reason": "start_page_token_failed",
                "error": token_res.get("error"),
            }
        page_token = token_res["page_token"]

    watch_res = await drive.watch_changes(
        channel_id=channel_id,
        webhook_url=webhook,
        page_token=str(page_token),
    )
    if not watch_res.get("success"):
        return {
            "watch_activated": False,
            "reason": "watch_registration_failed",
            "error": watch_res.get("error"),
        }

    exp_raw = watch_res.get("expiration")
    expiration_ms = int(exp_raw) if exp_raw else None
    state = {
        "channel_id": watch_res.get("channel_id", channel_id),
        "resource_id": watch_res.get("resource_id"),
        "page_token": watch_res.get("page_token", page_token),
        "expiration_ms": expiration_ms,
        "webhook_url": webhook,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_watch_state(conn, state)
    await db.commit()

    logger.info(
        f"[DRIVE_WATCH] Push channel registered for user {user.id} "
        f"(expires {expiration_ms})"
    )
    return {
        "watch_activated": True,
        "renewed": bool(existing),
        "channel_id": state["channel_id"],
        "expiration_ms": expiration_ms,
    }


async def stop_drive_watch(
    user: User,
    db: AsyncSession,
    *,
    connection: Optional[Connection] = None,
) -> Dict[str, Any]:
    """Stop the user's Drive push channel and clear stored watch state."""
    conn = connection or await _get_gw_connection(db, user.id)
    if not conn:
        return {"stopped": False, "reason": "no_connection"}

    state = _watch_state(conn)
    if not state.get("channel_id") or not state.get("resource_id"):
        _save_watch_state(conn, None)
        await db.commit()
        return {"stopped": True, "reason": "no_active_channel"}

    drive = await _build_drive_service(conn)
    stop_res = await drive.stop_channel(
        str(state["channel_id"]),
        str(state["resource_id"]),
    )
    _save_watch_state(conn, None)
    await db.commit()
    return {"stopped": stop_res.get("success", False), "details": stop_res}


async def ensure_drive_watch(user: User, db: AsyncSession) -> Dict[str, Any]:
    """Ensure a push channel exists when the user has Drive sync targets."""
    if not await user_needs_drive_watch(db, user.id):
        return {"watch_activated": False, "reason": "not_needed"}
    return await register_drive_watch(user, db)


async def renew_expiring_drive_watches(db: AsyncSession) -> Dict[str, int]:
    """Beat task helper: register missing watches and renew expiring channels."""
    result = await db.execute(
        select(Connection).where(
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    renewed = 0
    registered = 0
    skipped = 0
    failed = 0

    for conn in result.scalars().all():
        user_res = await db.execute(select(User).where(User.id == conn.user_id))
        user = user_res.scalar_one_or_none()
        if not user:
            failed += 1
            continue

        needs_watch = await user_needs_drive_watch(db, user.id)
        state = _watch_state(conn)

        if not needs_watch:
            if state:
                await stop_drive_watch(user, db, connection=conn)
            skipped += 1
            continue

        if not state:
            res = await register_drive_watch(user, db, connection=conn)
            if res.get("watch_activated"):
                registered += 1
            else:
                failed += 1
                logger.warning(
                    f"[DRIVE_WATCH] Initial registration failed for user {user.id}: {res}"
                )
            continue

        if not _watch_needs_renewal(state):
            skipped += 1
            continue

        res = await register_drive_watch(user, db, connection=conn, force=True)
        if res.get("watch_activated"):
            renewed += 1
        else:
            failed += 1
            logger.warning(
                f"[DRIVE_WATCH] Renewal failed for user {user.id}: {res}"
            )

    return {
        "renewed": renewed,
        "registered": registered,
        "skipped": skipped,
        "failed": failed,
    }


def _change_affects_folder(
    change: Dict[str, Any],
    watched_folder_ids: Set[str],
) -> Optional[str]:
    """Return the watched folder id affected by this change, if any."""
    file_id = change.get("fileId")
    if file_id and file_id in watched_folder_ids:
        return file_id

    file_obj = change.get("file") or {}
    parents = file_obj.get("parents") or []
    for parent in parents:
        if parent in watched_folder_ids:
            return parent
    return None


async def process_drive_notification(
    channel_id: Optional[str],
    resource_state: Optional[str],
) -> Dict[str, Any]:
    """
    Handle an incoming Google Drive push notification.

    Lists incremental changes, maps them to watched folders, and triggers
    workflow execution / RAG re-ingest with watermark deduplication.
    """
    if resource_state == "sync":
        logger.info(f"[DRIVE_WATCH] Sync handshake for channel {channel_id}")
        return {"status": "sync_ok"}

    if resource_state not in ("add", "update", "trash", "remove", "change", None):
        return {"status": "ignored", "state": resource_state}

    user_id_str = user_id_from_channel(channel_id)
    if not user_id_str:
        logger.warning(f"[DRIVE_WATCH] Unknown channel id: {channel_id}")
        return {"status": "unknown_channel"}

    from ..database import get_session_maker
    from ..tasks.drive_sync_tasks import (
        _find_data_source_for_folder,
        _folder_changed,
        _get_watermark,
        _kb_id_from_workflow,
        _latest_modified_time,
        _set_watermark,
        _is_drive_folder_event_workflow,
        _folder_id_from_workflow,
    )
    from ..services.tool_executor import ToolExecutor
    from ..services.workflow_builder_service import WorkflowBuilderService
    from ..tasks.rag_tasks import rag_ingest_source_task
    import uuid as _uuid

    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            user_uuid = _uuid.UUID(user_id_str)
        except ValueError:
            return {"status": "invalid_user_id"}

        user_res = await db.execute(select(User).where(User.id == user_uuid))
        user = user_res.scalar_one_or_none()
        if not user:
            return {"status": "user_not_found"}

        conn = await _get_gw_connection(db, user.id)
        if not conn:
            return {"status": "no_connection"}

        state = _watch_state(conn)
        page_token = state.get("page_token")
        if not page_token:
            logger.warning(f"[DRIVE_WATCH] No page token for user {user.id}")
            return {"status": "no_page_token"}

        watched_folders = await get_watched_folder_ids(db, user.id)
        if not watched_folders:
            return {"status": "no_watched_folders"}

        drive = await _build_drive_service(conn)
        changes_res = await drive.list_changes(str(page_token))
        if not changes_res.get("success"):
            logger.error(
                f"[DRIVE_WATCH] changes.list failed for user {user.id}: "
                f"{changes_res.get('error')}"
            )
            return {"status": "changes_list_failed", "error": changes_res.get("error")}

        new_token = changes_res.get("new_start_page_token")
        if new_token and new_token != page_token:
            state = {**state, "page_token": new_token}
            _save_watch_state(conn, state)

        affected: Set[str] = set()
        for change in changes_res.get("changes", []):
            folder = _change_affects_folder(change, watched_folders)
            if folder:
                affected.add(folder)

        if not affected:
            await db.commit()
            logger.debug(
                f"[DRIVE_WATCH] Notification for user {user.id}: "
                f"{changes_res.get('count', 0)} changes, none in watched folders"
            )
            return {"status": "no_matching_folders", "changes": changes_res.get("count", 0)}

        executor = ToolExecutor()
        builder = WorkflowBuilderService()
        workflows_fired = 0
        rag_fired = 0

        wf_res = await db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(
                and_(
                    Workflow.user_id == user.id,
                    Workflow.status == WorkflowStatus.ACTIVE,
                    Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
                )
            )
        )
        workflows = wf_res.scalars().all()

        handled_folders: Set[str] = set()

        for folder_id in affected:
            latest = await _latest_modified_time(executor, folder_id, user, db)
            if latest is None:
                continue

            for wf in workflows:
                if not _is_drive_folder_event_workflow(wf):
                    continue
                if _folder_id_from_workflow(wf) != folder_id:
                    continue

                kb_id = _kb_id_from_workflow(wf)
                data_source = (
                    await _find_data_source_for_folder(db, kb_id, folder_id)
                    if kb_id
                    else None
                )
                watermark = await _get_watermark(db, wf=wf, data_source=data_source)
                if watermark and not _folder_changed(latest, watermark):
                    continue

                logger.info(
                    f"[DRIVE_WATCH] Webhook → workflow {wf.id} "
                    f"folder {folder_id} ({watermark} → {latest.isoformat()})"
                )
                try:
                    await builder.execute_workflow(
                        workflow_id=wf.id,
                        user_id=wf.user_id,
                        db=db,
                        input_data={
                            "google_drive_folder_id": folder_id,
                            "drive_folder_id": folder_id,
                            "google_drive_state": resource_state or "change",
                            "google_drive_modified_time": latest.isoformat(),
                            "google_drive_channel_id": channel_id,
                        },
                    )
                    await _set_watermark(
                        db, latest, wf=wf, data_source=data_source, folder_id=folder_id
                    )
                    workflows_fired += 1
                    handled_folders.add(folder_id)
                except Exception as e:
                    logger.error(
                        f"[DRIVE_WATCH] Workflow {wf.id} execution failed: {e}"
                    )

        from ..tasks.drive_sync_tasks import (
            _DRIVE_SOURCE_TYPES,
            _folder_id_from_config,
            _workflow_watched_folders,
        )

        watched_by_wf = await _workflow_watched_folders(db)
        src_res = await db.execute(
            select(DataSource).where(
                DataSource.source_type.in_(_DRIVE_SOURCE_TYPES),
                DataSource.status == "active",
            )
        )
        for src in src_res.scalars().all():
            cfg = src.config or {}
            auto = (src.sync_mode in ("scheduled", "realtime")) or bool(
                cfg.get("auto_sync")
            )
            folder_id = _folder_id_from_config(cfg)
            if not auto or not folder_id or folder_id not in affected:
                continue
            from ..models import KnowledgeBase

            kb_res = await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == src.kb_id)
            )
            kb = kb_res.scalar_one_or_none()
            if not kb or str(kb.user_id) != str(user.id):
                continue
            if (str(user.id), folder_id) in watched_by_wf:
                continue
            if folder_id in handled_folders:
                continue

            latest = await _latest_modified_time(executor, folder_id, user, db)
            if latest is None:
                continue
            watermark = await _get_watermark(db, data_source=src)
            if watermark and not _folder_changed(latest, watermark):
                continue

            logger.info(
                f"[DRIVE_WATCH] Webhook → RAG source {src.id} folder {folder_id}"
            )
            try:
                rag_ingest_source_task.delay(
                    url_or_id=folder_id,
                    kb_id=str(src.kb_id),
                    user_id=str(kb.user_id),
                    source_type=src.source_type,
                )
                await _set_watermark(db, latest, data_source=src)
                rag_fired += 1
            except Exception as e:
                logger.error(f"[DRIVE_WATCH] RAG enqueue failed for {src.id}: {e}")

        await db.commit()
        return {
            "status": "processed",
            "workflows_fired": workflows_fired,
            "rag_fired": rag_fired,
            "affected_folders": list(affected),
        }
