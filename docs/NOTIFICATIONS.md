# Notification event catalog

Single entry point: `NotificationService.notify(db, user_id, event_key, title, body, ...)`.

Preferences: category × channel matrix on `user_settings.notification_rules`, gated by channel masters (`email_notifications`, `slack_notifications`, `webhook_notifications` + URL). Quiet hours suppress email/Slack/webhook for non-critical events. **Critical** severity always keeps `in_app` on.

## Categories

| Category | Examples |
|----------|----------|
| billing | payment_*, subscription_*, withdrawal_*, invoice_available |
| security | password_changed, email_changed, new_login, 2fa_changed, api_key_changed, suspicious_activity |
| workflows | workflow_run_failed, workflow_run_completed, workflow_schedule_disabled, quota_exceeded |
| agents | agent_escalation, agent_error, agent_action_completed |
| messaging | conversation_assigned, sla_breach, connection_disconnected, connection_token_expired |
| commerce | order_received, stk_result, order_cancelled, payment_failure_burst |
| marketplace | workflow_imported, earnings_received, new_follower, workflow_reviewed, milestone_reached |
| system | system_announcement, maintenance |

Full registry: `src/services/notification_events.py`.

## Channels

1. **in-app** — `notifications` table + WebSocket `notification.created`
2. **email** — Celery `deliver_notification_channels`
3. **Slack** — user’s connected Slack default channel
4. **webhook** — signed POST (`X-Hub-Signature-256`) to `notification_webhook_url`

## Ops notes

- Dedupe: `user_id + event_key + entity_id` TTL ~120s (in-process).
- Do not insert `Notification(...)` outside `NotificationService`.
- Alembic: `j4e5f6g7h8c0_notification_rules` adds rules / quiet hours / digest + index.
- Settings UI: Settings → Notifications (matrix + quiet hours). Bell links to `/settings?tab=notifications`.
