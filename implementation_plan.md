# RLS System Bypass Implementation Plan

## Goal
Restore functionality to background tasks (like the WhatsApp conversational agent) which were broken by the Row-Level Security (RLS) rollout. Because webhooks arrive unauthenticated, the Celery workers do not have a `user_id` to set the tenant context, causing RLS to block all database queries and inserts.

## User Review Required
> [!WARNING]
> This plan will implement a `system_session` context manager that explicitly bypasses RLS using a custom PostgreSQL setting (`app.bypass_rls`). This is the industry-standard way to handle background tasks and webhook processing in multi-tenant systems.

## Proposed Changes

### Database Layer
#### [NEW] `alembic/versions/p9q0r1s2t3u6_add_rls_bypass.py`
Create a new migration to update all RLS policies to include a bypass check:
```sql
USING (
    current_setting('app.bypass_rls', true) = 'true' 
    OR user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
)
```

#### [MODIFY] `src/database.py`
Add a new context manager `system_session` that sets the bypass configuration:
```python
@asynccontextmanager
async def system_session() -> AsyncGenerator[AsyncSession, None]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        await session.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
        try:
            yield session
        finally:
            await session.close()
```

### Application Layer
#### [MODIFY] `src/tasks/webhook_tasks.py`
Change the webhook processor to use the `system_session` so it can query across all tenants to route incoming messages:
```diff
-        session_maker = get_session_maker()
-        async with session_maker() as db:
+        from src.database import system_session
+        async with system_session() as db:
             try:
                 await process_incoming_messages(payload, db, background_tasks=None)
```

#### [MODIFY] `src/tasks/maintenance_tasks.py` (if applicable)
Update any other critical background tasks (like billing/usage sweeps) to use `system_session`.

## Verification Plan
1. Apply the new migration.
2. Trigger the WhatsApp webhook and verify the conversational agent can insert messages and respond.
3. Confirm standard API requests still correctly enforce RLS.
