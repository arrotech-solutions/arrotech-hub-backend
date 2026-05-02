"""
Celery Application Configuration for Arrotech Hub.

This module defines the Celery app instance, broker/backend configuration,
task auto-discovery, and the Celery Beat periodic task schedule.

Architecture:
  - Broker:  Redis DB 1  (task message queue)
  - Backend: Redis DB 2  (task result storage)
  - Cache:   Redis DB 0  (application cache — untouched)

Usage:
  Worker:  celery -A src.celery_app worker --loglevel=info -Q high,default,low
  Beat:    celery -A src.celery_app beat --loglevel=info
  Flower:  celery -A src.celery_app flower --port=5555
"""

import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

# Load .env before reading any env vars
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Celery App Instance ──────────────────────────────────────────────────────

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery("arrotech_hub")

app.config_from_object({
    # ── Broker & Backend ──
    "broker_url": broker_url,
    "result_backend": result_backend,
    "broker_connection_retry_on_startup": True,

    # ── Serialization ──
    "accept_content": ["json"],
    "task_serializer": "json",
    "result_serializer": "json",

    # ── Timezone ──
    "timezone": "UTC",
    "enable_utc": True,

    # ── Reliability ──
    "task_acks_late": True,                      # ACK after execution, not before
    "task_reject_on_worker_lost": True,           # Re-queue if worker dies mid-task
    "worker_prefetch_multiplier": 1,              # Fetch one task at a time (fair scheduling)
    "worker_max_tasks_per_child": int(os.getenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", "100")),

    # ── Timeouts ──
    "task_time_limit": int(os.getenv("CELERY_TASK_TIME_LIMIT", "300")),          # Hard kill after 5 min
    "task_soft_time_limit": int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "240")),  # SoftTimeLimitExceeded after 4 min

    # ── Result Expiry ──
    "result_expires": 3600,  # Results expire after 1 hour

    # ── Beat Settings ──
    "beat_schedule_filename": "/tmp/celerybeat-schedule",  # Write to /tmp to avoid permission errors

    # ── Queue Routing ──
    "task_default_queue": "default",
    "task_routes": {
        # High priority — real-time webhook processing
        "src.tasks.webhook_tasks.*": {"queue": "high"},

        # Default — email, workflow execution
        "src.tasks.email_tasks.*": {"queue": "default"},
        "src.tasks.workflow_tasks.*": {"queue": "default"},
        "src.tasks.broadcast_tasks.*": {"queue": "default"},

        # Low priority — background maintenance, RAG ingestion
        "src.tasks.maintenance_tasks.*": {"queue": "low"},
        "src.tasks.rag_tasks.*": {"queue": "low"},
    },

    # ── Retry Defaults ──
    "task_default_retry_delay": 60,        # 1 minute initial retry delay
    "task_max_retries": 3,
})

# ── Auto-discover tasks ──────────────────────────────────────────────────────

app.autodiscover_tasks([
    "src.tasks.email_tasks",
    "src.tasks.webhook_tasks",
    "src.tasks.workflow_tasks",
    "src.tasks.maintenance_tasks",
    "src.tasks.rag_tasks",
    "src.tasks.broadcast_tasks",
])


# ── Celery Beat Schedule ─────────────────────────────────────────────────────
# Replaces APScheduler's in-process cron jobs with a distributed,
# persistent scheduler that survives restarts.

app.conf.beat_schedule = {
    # ── Workflow Sync (every 60s) ──
    # Syncs active scheduled workflows from DB → Beat dynamic schedule
    "sync-workflows-every-60s": {
        "task": "src.tasks.workflow_tasks.sync_workflows_task",
        "schedule": 60.0,
        "options": {"queue": "default"},
    },

    # ── TikTok Schedule Checker (every 60s) ──
    "check-tiktok-schedules-every-60s": {
        "task": "src.tasks.maintenance_tasks.check_tiktok_schedules_task",
        "schedule": 60.0,
        "options": {"queue": "low"},
    },

    # ── WhatsApp Token Refresh (daily at 03:00 UTC) ──
    "refresh-whatsapp-tokens-daily": {
        "task": "src.tasks.maintenance_tasks.refresh_whatsapp_tokens_task",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "low"},
    },

    # ── Log Cleanup (daily at 04:00 UTC) ──
    "log-cleanup-daily": {
        "task": "src.tasks.maintenance_tasks.log_cleanup_task",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "low"},
    },

    # ── DB Log Flush (every 30s) ──
    "flush-db-logs-every-30s": {
        "task": "src.tasks.maintenance_tasks.db_log_flush_task",
        "schedule": 30.0,
        "options": {"queue": "low"},
    },
}
