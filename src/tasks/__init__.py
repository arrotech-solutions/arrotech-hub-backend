"""
Celery Tasks Package for Arrotech Hub.

All task modules are auto-discovered by the Celery app via
celery_app.autodiscover_tasks(). Each module defines @app.task
decorated functions organized by domain.

Queues:
  high    — Webhooks (WhatsApp, Telegram, Slack, Gmail)
  default — Email, workflow execution, broadcasts
  low     — RAG ingestion, maintenance, log cleanup
"""
