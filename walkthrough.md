# Background Task RLS Bypass Implementation

## Changes Made
I successfully implemented the RLS bypass architecture for background tasks. 

1. **New Migration**: Created `alembic/versions/p9q0r1s2t3u6_add_rls_bypass.py` which updates all Row-Level Security policies to include a system-level override flag. The new policy logic reads:
   ```sql
   USING (
       current_setting('app.bypass_rls', true) = 'true'
       OR user_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
   )
   ```
   This ensures that any database session with `app.bypass_rls = 'true'` can safely read and write to all tenant-scoped tables.

2. **System Session Context Manager**: Added a `system_session` asynchronous context manager in `src/database.py`. This acts similarly to `tenant_session`, but instead of setting a specific user ID, it executes `SELECT set_config('app.bypass_rls', 'true', true)` to enable global access for the duration of the transaction.

3. **Webhook Task Modification**: Updated the WhatsApp Webhook task processor in `src/tasks/webhook_tasks.py` and the inline fallback in `src/routers/whatsapp_webhook.py` to use `system_session()`. Now, when incoming webhooks arrive without a tenant context, the worker can successfully query the database to resolve the contact and insert the incoming message.

## What to Do Next

You will need to commit these changes and push them to your repository so the CI/CD pipeline deploys them and runs the database migration.

```bash
git add alembic/versions/p9q0r1s2t3u6_add_rls_bypass.py src/database.py src/tasks/webhook_tasks.py src/routers/whatsapp_webhook.py
git commit -m "fix: implement system_session RLS bypass for webhooks and background tasks"
git push origin develop
```

Once the CI/CD pipeline finishes, your WhatsApp conversational agent will instantly resume reading and writing messages!
