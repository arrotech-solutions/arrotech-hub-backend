# Arrotech Hub Backend

Production backend for Arrotech Hub: a multi-tenant AI operations platform that combines:

- conversational AI (`/chat`) with tool execution and streaming responses,
- workflow creation/execution (`/workflows`, `/agents`, templates, scheduling),
- business integrations (CRM, social, productivity, communication, accounting),
- payments and reconciliation (M-Pesa, Stripe, Paystack),
- creator/marketplace primitives for reusable automations,
- organization onboarding and team access control,
- public web forms, support routing, and blog APIs.

The service runs as a FastAPI app and can also run in MCP stdio mode for tool-serving workflows.

## What This Service Is

Arrotech Hub backend is the orchestration layer between:

- identity and tenant context,
- integrations and credentials,
- LLM provider abstraction,
- automation execution engines,
- analytics/monitoring and billing.

It exposes HTTP APIs consumed by the frontend and provides MCP tools when launched in MCP mode.

## System Architecture

### Runtime Composition

- **API runtime**: FastAPI with async routing and lifecycle startup/shutdown hooks.
- **Persistence**: PostgreSQL via SQLAlchemy async engine (`asyncpg`) and Alembic migrations.
- **Cache + ephemeral state**: Redis (used by cache/session context paths such as messaging memory).
- **Schedulers/orchestrators**: workflow scheduler + execution orchestration services.
- **Observability stack (local compose)**: Prometheus, Grafana, Elasticsearch, Logstash, Kibana, Node Exporter.

### Request Lifecycle (high-level)

1. Request enters FastAPI app.
2. Middleware chain applies GZip, in-memory rate limiting, cache-control headers, CORS, proxy header adaptation.
3. Auth context and org/user context are resolved in route-level dependencies.
4. Router delegates to domain service(s) and persistence layer.
5. Response is returned; selected GET endpoints receive cache-control headers.

### MCP Mode

When `RUN_MODE=mcp`, the server runs an MCP stdio server and exposes tools such as:

- HubSpot operations,
- Slack messaging/reporting,
- file management utilities,
- web tools/scraping helpers,
- content creation operations.

## Domain Modules

The backend is broad and modularized into routers + services.

### Core platform modules

- Authentication, authorization, user lifecycle
- User settings and preferences
- Security controls (2FA/OTP/passkey related flows)
- Connection registry and integration configuration
- Chat conversations, message history, provider/tool discovery
- Workflow design, versioning, execution tracking, retries
- Agent lifecycle and scheduling abstractions

### Business and vertical modules

- Marketplace + creator profiles + favorites + followers + activity
- Notification center and analytics feeds
- Public forms (contact/newsletter) and support ticket routing
- Blog API (public/admin paths)
- Organization onboarding and membership management
- M-Pesa reconciliation, invoice matching, fraud signal tracking
- TikTok creator utilities, premium links, fan commerce records
- Productivity dashboards and unified-workspace support endpoints
- RAG knowledge base/data source/sync pipeline modules

### Integrations surfaced in routers/services

- CRM/accounting: HubSpot, Salesforce, Zoho, QuickBooks, Xero, Airtable
- Communication: Slack, WhatsApp, Telegram, Teams, Zoom, Outlook, Gmail webhooks
- Social: Facebook, Instagram, LinkedIn, Twitter/X, TikTok
- Productivity/work: Notion, Trello, Jira, ClickUp, Asana, Google Workspace
- Payments: M-Pesa, Stripe, Paystack
- AI providers and vector/data tooling services (OpenAI, Anthropic, Gemini, Ollama, and related helper services)

## API Surface (grouped)

The app includes many router groups. Primary path families include:

- `/auth` - registration, login, social auth, account management, password reset
- `/chat` - conversations, message streaming, provider/tool capability discovery
- `/connections` - integration CRUD, validation, platform discovery
- `/workflows` - create/update/list/execute/test/execution history
- `/agents` - create/manage/execute/schedule automation agents
- `/payments` - M-Pesa/Stripe/Paystack pricing/payment/subscription/history flows
- `/api/v1` - status/pricing/usage and additional API namespace features
- `/api/v1/security` - security endpoints
- `/api/v1/organizations` - org/team lifecycle endpoints
- marketplace/creator/analytics/notifications/favorites/preferences namespaces
- integration-specific OAuth/webhook namespaces (e.g. WhatsApp, Slack, Google Workspace, etc.)
- public endpoints for forms/blog/support where applicable

For precise operations and schemas, use generated docs:

- local: `http://localhost:8000/docs`
- alternate: `http://localhost:8000/redoc`

## Data Model Overview

`src/models.py` contains an extensive model graph. Key entities:

- **Identity + access**: `User`, roles, passkeys, settings, preferences
- **Messaging + AI**: `Conversation`, `Message`, messaging conversation memory
- **Automation**: `Workflow`, `WorkflowStep`, `WorkflowExecution`, `WorkflowStepExecution`, versions/templates
- **Marketplace/social**: creator profiles, reviews, downloads, favorites, followers, notifications, activity feed
- **Payments/finance**: `Payment`, `Subscription`, M-Pesa payment records, invoice, fraud signals
- **Integrations**: `Connection` plus platform-specific data models
- **Organizations**: orgs, members, invites, departments, audit log
- **Content/public**: blog categories/posts, contact submissions, newsletter subscribers
- **RAG**: knowledge bases, data sources, sync logs

This schema indicates the platform currently supports both SMB workflows and larger multi-team operations.

## Configuration and Environments

Configuration is managed via `src/config.py` with environment-specific classes:

- development
- testing
- staging
- production
- release

Important environment categories:

- app/runtime (`ENVIRONMENT`, `LOG_LEVEL`, `SECRET_KEY`)
- database and redis
- auth/security keys
- payment providers
- LLM/provider keys
- integration credentials and OAuth callback settings
- feature flags
- email/smtp routing

Use `env.example` as the baseline template.

## Local Development

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- PostgreSQL/Redis (if not using compose-managed versions)

### Quick start (recommended)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy env.example .env
docker-compose up -d
```

App endpoints:

- API root: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### Direct run (without full compose)

```bash
python -m src.main
```

Set dependencies (DB/Redis) and environment variables before running directly.

## Docker Compose Topology

`docker-compose.yml` provisions:

- `app` (FastAPI)
- `migrator` (Alembic migrations)
- `postgres`
- `redis`
- observability: `elasticsearch`, `logstash`, `kibana`, `prometheus`, `grafana`, `node-exporter`
- `nginx` (local edge proxy)

This mirrors a production-like developer environment and allows full-stack diagnostics.

## Security Model

- JWT-based auth flows with additional security endpoints
- support for OTP/TOTP/passkey-style login paths in the auth/security layer
- route-level protection and role/permission checks
- CORS allow-list control
- middleware rate limiting for auth/API path classes
- secret-driven provider credentials (no hardcoded secret usage in deployment)

## Repository Structure

```text
arrotech-hub-backend/
├── src/
│   ├── main.py                  # App bootstrap, middleware, router registration, MCP mode
│   ├── config.py                # Environment-backed settings
│   ├── database.py              # SQLAlchemy async engine/session setup
│   ├── models.py                # Platform data model graph
│   ├── routers/                 # Feature and integration API routers
│   └── services/                # Domain/service orchestration layer
├── alembic/                     # DB migrations
├── docker-compose.yml           # Local full-stack runtime
├── requirements.txt             # Python dependencies
├── env.example                  # Environment variable template
└── README.md
```

## Operational Notes

- Startup performs DB init hooks, service initialization, cache init, and workflow scheduler start.
- In production mode, logging is emitted in structured JSON format.
- Health endpoint reports dependency and pool state, not just process liveness.
- Alembic controls schema evolution; the runtime does not auto-create all tables.

## Platform Scope (Current State)

This backend is not a minimal API service. It is currently a broad platform backend that supports:

- customer-facing web app APIs,
- operations automation engines,
- creator marketplace and monetization primitives,
- team/organization access patterns,
- messaging and social channel automations,
- RAG-ready knowledge base building blocks,
- observability and deployment pathways for production operation.

If you are onboarding engineers, start with:

1. `src/main.py` (runtime and API composition)
2. `src/models.py` (domain mental model)
3. `src/routers/` + `src/services/` (feature implementation paths)
4. `docker-compose.yml` (operational topology)
