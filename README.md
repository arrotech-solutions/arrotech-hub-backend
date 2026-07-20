# Arrotech Hub — Backend

> **The AI operations and workflow automation engine powering Arrotech Hub.**

This document is the canonical technical reference for the `arrotech-hub-backend` codebase. It is written in the spirit of Google's internal g3doc documentation philosophy: **docs-as-code**, colocated with the source, version-controlled, and maintained by the same engineers who maintain the platform.

---

## Table of Contents

- [Platform Overview](#platform-overview)
- [Architecture](#architecture)
  - [High-Level System Diagram](#high-level-system-diagram)
  - [Request Lifecycle](#request-lifecycle)
  - [Dual Runtime Modes](#dual-runtime-modes)
- [Core Abstractions](#core-abstractions)
  - [Execution Orchestrator](#1-execution-orchestrator)
  - [Tool Executor](#2-tool-executor)
  - [Dynamic Tool Registry](#3-dynamic-tool-registry)
  - [Conversational Agent Service](#4-conversational-agent-service)
  - [RAG Pipeline Service](#5-rag-pipeline-service)
  - [Conversation Context Manager (CCM)](#6-conversation-context-manager-ccm)
- [Code Mode v2](#code-mode-v2)
- [Harness Engineering](#harness-engineering)
- [Service Catalog](#service-catalog)
- [Data Model & Persistence](#data-model--persistence)
- [Observability](#observability)
- [Security & Authentication](#security--authentication)
- [API Surface](#api-surface)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
- [Testing](#testing)
- [Deployment](#deployment)
- [Glossary](#glossary)

---

## Platform Overview

Arrotech Hub is a **multi-tenant, MCP-native AI operations platform**. It allows businesses to:

1. **Chat with AI** that autonomously selects and executes tools (CRM, email, payments, file ops, etc.)
2. **Design visual workflows** (Zapier/Make-style) triggered by webhooks from WhatsApp, Telegram, Slack, Gmail, etc.
3. **Deploy conversational agents** on WhatsApp/Telegram that handle ordering, customer service, and payments using an inner tool-calling loop.
4. **Build knowledge bases** via a RAG pipeline that ingests content from 10+ sources into vector databases.
5. **Manage integrations** across 30+ third-party platforms with OAuth and BYOK credential resolution.

### Why MCP?

The backend implements the **Model Context Protocol (MCP)** — an open standard by Anthropic for connecting LLMs to external tools. When `RUN_MODE=mcp`, the server exposes tools via `stdio` for direct integration with Claude Desktop. In `web` mode (default), the same tool infrastructure powers the FastAPI HTTP API.

### Design Principles

| Principle | Implementation |
|---|---|
| **Provider-Agnostic AI** | `LLMService` abstracts OpenAI, Anthropic, Gemini, Ollama, HuggingFace, Together AI behind a unified interface. |
| **Dynamic Tool Discovery** | `DynamicToolRegistry` generates tool manifests at runtime based on user connections, subscription tier, and platform registry. |
| **Multi-Tenant Isolation** | Every data query, vector namespace, and webhook session is scoped to `user_id` or `organization_id`. |
| **BYOK (Bring Your Own Key)** | Users can supply their own API keys (OpenAI, Pinecone, Firecrawl, etc.) stored encrypted in `UserSettings`. Platform keys are used as fallback. |
| **Observability-First** | Structured JSON logging, distributed tracing (`trace_id`/`span_id`), and a Dead Letter Queue (DLQ) are built into the middleware and tool wrapper layers. |

---

## Architecture

### High-Level System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                             │
│  React Frontend  │  WhatsApp Webhook  │  Telegram Bot  │  MCP   │
└────────┬─────────┴────────┬───────────┴───────┬────────┴───┬────┘
         │                  │                   │            │
         ▼                  ▼                   ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EDGE & MIDDLEWARE                            │
│  Nginx → GZip → RateLimit → CacheControl → CORS → Observability│
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASTAPI APPLICATION                           │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   ROUTER LAYER (63 routers)               │   │
│  │  /auth  /chat  /workflows  /agents  /connections  /mcp   │   │
│  │  /payments  /whatsapp  /telegram  /slack  /hubspot  ...  │   │
│  │  /_internal/harness/* (guardrails, quality, metrics)     │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                             │                                   │
│  ┌──────────────────────────▼───────────────────────────────┐   │
│  │              SERVICE ORCHESTRATION LAYER                  │   │
│  │                                                          │   │
│  │  ExecutionOrchestrator ──→ IntentProcessor                │   │
│  │         │                                                │   │
│  │         ├──→ ToolRouter (semantic tool selection)         │   │
│  │         │                                                │   │
│  │         ├──→ ToolExecutor (105+ service dispatchers)     │   │
│  │         │         │                                      │   │
│  │         │    CodeSandboxService (Code Mode v2)           │   │
│  │         │         │                                      │   │
│  │         │    ToolAPIGenerator + ToolDiscoveryService      │   │
│  │         │                                                │   │
│  │         └──→ HarnessEngine (guardrails + feedback + QA)  │   │
│  │                    │                                     │   │
│  │         DynamicToolRegistry ←── PlatformRegistry          │   │
│  │                                                          │   │
│  │  ConversationalAgentService (WhatsApp/Telegram agents)   │   │
│  │  RAGPipelineService (ingest → chunk → embed → store)     │   │
│  │  WorkflowBuilderService (visual DAG execution)           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   PERSISTENCE LAYER                       │   │
│  │  PostgreSQL (asyncpg + SQLAlchemy 2.0 + Alembic)         │   │
│  │  Redis (session state, CCM memory, rate limiting)        │   │
│  │  Vector DBs (Pinecone / Qdrant / Weaviate)               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 OBSERVABILITY LAYER                        │   │
│  │  JSONFormatter → stdout + async DB log worker             │   │
│  │  ObservabilityMiddleware (trace injection per request)    │   │
│  │  Tool wrapper (auto-retry + DLQ on failure)              │   │
│  │  ELK Stack (Elasticsearch/Logstash/Kibana)               │   │
│  │  Prometheus + Grafana (metrics)                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Request Lifecycle

A typical AI chat request flows through these stages:

```
1. HTTP POST /chat/{conversation_id}
       │
2. ObservabilityMiddleware: inject trace_id, log HTTP_REQUEST
       │
3. RateLimitMiddleware: sliding-window check (5 req/min auth, 60 req/min API)
       │
4. AuthRouter: JWT verification → resolve User + Organization
       │
5. ChatRouter: load conversation, build optimized context window
       │
6. ExecutionOrchestrator.process_message()
       ├── IntentProcessor.classify_intent()     → tool-required or direct-response?
       ├── ToolRouter.get_relevant_tools()       → semantic matching from 200+ tools
       ├── DynamicToolRegistry.convert_to_openai_format()
       ├── LLM call with function-calling (OpenAI/Anthropic/Gemini/Ollama)
       │      │
       │      └── If tool_calls returned:
       │              ├── ToolArgumentValidator.validate()
       │              ├── ToolExecutor.execute_tool()     → dispatches to service
       │              │      └── observability_execute_tool() wraps with tracing + retry
       │              └── Loop back to LLM with tool results (max 5 iterations)
       │
7. Save assistant message to DB, return SSE stream or JSON
       │
8. ObservabilityMiddleware: log HTTP_RESPONSE with duration_ms
```

### Dual Runtime Modes

The application supports two distinct runtime modes controlled by `RUN_MODE`:

| Mode | Trigger | Transport | Use Case |
|---|---|---|---|
| `web` (default) | `RUN_MODE=web` | HTTP/REST via FastAPI + Uvicorn | Production deployment, frontend API |
| `mcp` | `RUN_MODE=mcp` | stdio via MCP SDK | Claude Desktop integration, local dev |

In MCP mode, tools are exposed directly to the MCP client. In web mode, the same tool definitions power the `/chat` endpoint's function-calling loop.

---

## Core Abstractions

These are the six architectural pillars that every developer must understand.

### 1. Execution Orchestrator

**File:** `src/services/execution_orchestrator.py`

The central coordinator for all AI chat interactions. It:
- Classifies user intent via `IntentProcessor`
- Selects relevant tools via `ToolRouter` (semantic matching)
- Runs the **function-calling loop** (up to 5 LLM ↔ tool iterations)
- Handles **BYOK fallback** — tries user's own API keys if the platform key fails
- Tracks AI action usage per subscription tier
- Counts tokens via `tiktoken` for billing

**Key method:** `process_message(content, provider) → (response, tools_called, tokens_used)`

### 2. Tool Executor

**File:** `src/services/tool_executor.py` (7,200 lines)

The dispatch layer that routes tool calls to their corresponding service. It:
- Maps 100+ tool names to service methods via prefix matching (e.g., `slack_*` → `SlackService`)
- Enforces **connection access** by subscription tier via `FeatureGate`
- Blocks **write operations** for free-tier users (read-only mode)
- Wraps every execution with observability tracing and auto-retry
- Supports a **Code Mode** sandbox (`execute_python_code`) where LLM-generated Python can call other tools

**Architecture pattern:**
```
tool_name="slack_send_message"
    → _get_platform_from_tool() → "slack"
    → FeatureGate.has_connection_access(user, "slack")
    → _check_write_operation_access() → allowed/blocked
    → _execute_slack_tool() → SlackService.send_message()
    → observability_execute_tool() wraps with trace + retry
```

### 3. Dynamic Tool Registry

**File:** `src/services/dynamic_tool_registry.py`

Generates the available tool manifest at runtime. It:
- Maintains **base tools** (always available): web search, file management, content creation, maps, M-Pesa, orders, code execution, etc.
- Discovers **connection-based tools** by querying the user's active `Connection` records in the database
- Merges tool definitions from `PlatformRegistry` (187KB of platform-specific tool schemas)
- Converts all tools to OpenAI function-calling format for the LLM
- Supports `always_available` vs connection-gated tools

### 4. Conversational Agent Service

**File:** `src/services/conversational_agent_service.py`

Powers autonomous WhatsApp/Telegram ordering agents. Unlike the general chat, this service:
- Operates in **single-turn mode** (one LLM call per incoming message)
- Uses **CCM** (Conversation Context Manager) for multi-turn memory via Redis
- Has its own **inner tool-calling loop** with sub-tools: `search_products`, `create_order`, `calculate_total`, `initiate_mpesa_payment`, `display_product_cards`
- Builds **industry-specific system prompts** (food, clothing, retail, general)
- Injects **business-specific config** from workflow variables (KB ID, currency, delivery methods)
- Supports **dynamic MCP tool injection** — external enterprise tools can be added via workflow config
- Handles **image extraction** from AI responses and dispatches them as native WhatsApp/Telegram media

### 5. RAG Pipeline Service

**File:** `src/services/rag_pipeline_service.py`

A **zero-file-storage RAG orchestrator** that dynamically routes to the correct vector DB, embedding model, and parser based on each `KnowledgeBase`'s stored configuration.

**Pipeline stages:**
```
1. Source Fetch   → MCP tool call (Drive, Notion, Slack, Gmail, HubSpot, website, etc.)
2. Parse          → LlamaParse (PDFs) / Unstructured (DOCX/PPTX) / Firecrawl (websites)
3. Chunk          → Native recursive token splitter (tiktoken-based, configurable size/overlap)
4. Embed          → OpenAI / Cohere / HuggingFace (routed by KB config)
5. Store          → Pinecone / Qdrant / Weaviate (routed by KB config)
```

**Key features:**
- **Hybrid credential resolution**: User BYOK keys → Platform env vars
- **Multi-tenant namespacing**: `user_{id}_kb_{id}` per vector namespace
- **Smart text extraction**: Handles Google Docs, Zoho articles, Slack messages, HubSpot records, Airtable records, and generic JSON
- **Folder ingestion**: Recursively processes Google Drive folders

### 6. Conversation Context Manager (CCM)

**File:** `src/services/conversation_context_manager.py`

Manages multi-turn conversation memory for WhatsApp/Telegram agents via Redis.

| Setting | Default | Description |
|---|---|---|
| `CCM_MAX_MESSAGES` | 20 | Sliding window of messages to retain |
| `CCM_MAX_TOKENS` | 2000 | Token budget for context sent to LLM |
| `CCM_SESSION_TTL` | 7200s | Redis key expiry (2 hours) |
| `CCM_ENABLE_SUMMARIZATION` | false | Auto-summarize old messages via LLM |

---

## Code Mode v2

Code Mode is a paradigm shift inspired by **Cloudflare**, **FastMCP**, and **Anthropic's Programmatic Tool Calling**. Instead of presenting 200+ tools as individual function-calling schemas (consuming massive context tokens), the LLM **writes Python code** against a typed API.

### Why Code Mode?

| Dimension | Standard Function-Calling | Code Mode v2 |
|---|---|---|
| **Multi-step ops** | 5 LLM ↔ tool round-trips | 1 code block, zero re-entry |
| **Token usage** | ~25,000 tokens for 200 tools | ~1,000 tokens (search → execute) |
| **Reliability** | LLMs trained on synthetic tool-call examples | LLMs trained on billions of real code tokens |
| **Intermediate state** | Re-enters context window each iteration | Stays in sandbox memory |

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Code Mode v2                       │
│                                                     │
│  ToolDiscoveryService                               │
│    ├── search_tools(query) → matching tools          │
│    ├── get_tool_schema(name) → full inputSchema      │
│    └── list_categories() → [messaging, crm, ...]     │
│                                                     │
│  ToolAPIGenerator                                    │
│    └── generate_api(tools) → typed Python classes    │
│        class slack:                                  │
│            async def send_message(channel, text)     │
│            async def list_channels()                 │
│        class hubspot:                                │
│            async def search_contacts(query)          │
│                                                     │
│  CodeSandboxService (security-hardened)               │
│    ├── AST validation (blocked: os, sys, subprocess) │
│    ├── Resource limits (30s timeout, 50MB, 20 calls) │
│    ├── Typed API injection into sandbox globals       │
│    └── Structured result capture                     │
└─────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|---|---|
| `tool_api_generator.py` | Converts `DynamicToolRegistry` tool defs into typed Python class stubs |
| `tool_discovery_service.py` | On-demand tool search (BM25 keyword matching) + schema inspection |
| `sandbox_service.py` | Secure `exec()` sandbox with AST validation, resource limits, tool call tracking |

### Activation Heuristics

Code Mode activates automatically when:
- User has **15+ relevant tools** (context pressure)
- User intent contains multi-step keywords ("then", "for each", "combine")
- User explicitly requests code execution
- Configurable per-user/per-org setting

---

## Harness Engineering

Implements **OpenAI's Harness Engineering** framework — the execution environment infrastructure that makes AI agents reliable, self-correcting, and observable at scale.

### Four Pillars

```
┌──────────────────────────────────────────────────────────┐
│                  Harness Engineering                      │
│                                                          │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │  Guardrails   │  │ Feedback Loops │  │ Quality Gates │  │
│  │  (preventive) │  │ (corrective)  │  │ (evaluative)  │  │
│  │              │  │               │  │               │  │
│  │ • Tool ACL   │  │ • Error class │  │ • Completeness│  │
│  │ • Injection  │  │ • Auto-retry  │  │ • Accuracy    │  │
│  │ • Rate limit │  │ • Fix suggest │  │ • Efficiency  │  │
│  │ • Code safety│  │ • Max retries │  │ • Safety      │  │
│  └──────────────┘  └───────────────┘  └───────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              Agent Context (AGENTS.md)                │ │
│  │  Living docs injected per session: tier info, tool   │ │
│  │  quirks, error patterns, learned lessons             │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|---|---|
| `harness/guardrails.py` | Pre-execution validation: tool ACL, injection detection, rate limiting, code safety |
| `harness/feedback_loops.py` | Error classification + corrective instruction generation + retry management |
| `harness/quality_gates.py` | Post-execution scoring: completeness, accuracy, efficiency, safety |
| `harness/agent_context.py` | AGENTS.md-style living documentation assembled per session |
| `routers/harness_router.py` | Internal monitoring API (`/_internal/harness/*`) |

### Integration with Orchestrator

The harness wraps the execution orchestrator loop:

```
1. Load AgentContext → inject into system prompt
2. Pre-execution: AgentGuardrails.validate_tool_call()
3. If blocked → FeedbackLoop generates corrective instruction
4. Execute tool → observe result
5. Post-execution: QualityGate.evaluate_response()
6. Log quality scores to ObservabilityLog
```

---

## Service Catalog

The backend contains **105+ service files** organized by domain:

### AI & LLM Services
| Service | File | Purpose |
|---|---|---|
| `LLMService` | `llm_service.py` | Provider-agnostic LLM abstraction (OpenAI, Anthropic, Gemini, Ollama, HuggingFace, Together) |
| `ToolSelector` | `tool_selector.py` | Semantic tool routing — matches user intent to relevant tools |
| `IntentProcessor` | `intent_processor.py` | Classifies intent type and determines if tools are needed |
| `ToolContextEngine` | `tool_context_engine.py` | Builds rich context for tool execution |

### Messaging & Channels
| Service | File | Purpose |
|---|---|---|
| `WhatsAppService` | `whatsapp_service.py` | Send messages, media, product cards, templates via Meta API |
| `TelegramService` | `telegram_service.py` | Send messages, photos, register webhooks |
| `SlackService` | `slack_service.py` | Full Slack integration (messages, channels, reports, events) |
| `TeamsService` | `teams_service.py` | Microsoft Teams messaging and adaptive cards |
| `EmailService` | `email_service.py` | SMTP + Resend transactional email |

### CRM & Productivity
| Service | File | Purpose |
|---|---|---|
| `HubSpotService` | `hubspot_service.py` | Contacts, deals, notes |
| `SalesforceService` | `salesforce_service.py` | SOQL queries, record CRUD |
| `ZohoService` | `zoho_service.py` | CRM + Desk + Books |
| `GoogleWorkspace` | `google_workspace/` | Gmail, Calendar, Drive, Sheets, Docs, Analytics (6 sub-services) |
| `AsanaService` | `asana_service.py` | Tasks, projects, workspaces |
| `JiraService`, `TrelloService`, `ClickUpService`, `NotionService` | Various | Project management integrations |

### Payments & Finance
| Service | File | Purpose |
|---|---|---|
| `PaymentService` | `payment_service.py` | Stripe + Paystack checkout, subscriptions |
| `MpesaReconciliationService` | `mpesa_reconciliation_service.py` | M-Pesa STK push, payment matching, fraud detection |
| `DarajaService` | `daraja_service.py` | Safaricom Daraja API (B2C, C2B, STK) |
| `QuickBooksService` | `quickbooks_service.py` | Accounting integration |
| `XeroService` | `xero_service.py` | Accounting integration |

### Workflow & Automation
| Service | File | Purpose |
|---|---|---|
| `WorkflowBuilderService` | `workflow_builder_service.py` | Visual DAG workflow design and execution |
| `WorkflowSchedulerService` | `workflow_scheduler.py` | APScheduler-based cron/interval triggers |
| `ExecutionOrchestrator` | `execution_orchestrator.py` | AI chat function-calling loop + Code Mode + Harness |
| `AutonomousAgentService` | `autonomous_agent_service.py` | Scheduled autonomous agents |

### Code Mode & Harness Engineering
| Service | File | Purpose |
|---|---|---|
| `ToolAPIGenerator` | `tool_api_generator.py` | Generates typed Python API stubs from tool registry |
| `ToolDiscoveryService` | `tool_discovery_service.py` | On-demand tool search + schema inspection |
| `CodeSandboxService` | `sandbox_service.py` | Security-hardened Python execution with AST validation |
| `AgentGuardrails` | `harness/guardrails.py` | Pre-execution validation (ACL, injection, rate limits) |
| `FeedbackLoop` | `harness/feedback_loops.py` | Error classification + auto-correction |
| `QualityGate` | `harness/quality_gates.py` | Post-execution response evaluation |
| `AgentContext` | `harness/agent_context.py` | AGENTS.md-style living documentation |

### Autonomous Agents (`src/services/agents/`)
| Agent | Purpose |
|---|---|
| `InboxZeroCoachAgent` | Analyzes incoming email, suggests categorization, drafts responses |
| `MeetingPrepAgent` | Gathers context and docs before scheduled meetings |
| `DeadlineGuardianAgent` | Monitors task deadlines across connected platforms |
| `FollowUpAgent` | Tracks and reminds about pending follow-ups |
| `WeeklyDigestAgent` | Generates weekly summary reports |
| `MpesaAgent` | Automated payment reconciliation |

### Maps & Location
| Service | File | Purpose |
|---|---|---|
| `MapsService` | `maps_service.py` | Geocoding, routing, distance matrix, geofencing, static maps, rider assignment, delivery zone validation |

---

## Data Model & Persistence

### Database Stack
- **PostgreSQL 15** via `asyncpg` (non-blocking)
- **SQLAlchemy 2.0** async ORM
- **Alembic** for schema migrations (auto-run by `migrator` Docker service on startup)
- **Redis 7** for session state, CCM memory, rate limiting, and caching

### Core Entity Groups

**Identity & Multi-Tenancy:** `User`, `Organization`, `OrganizationMember`, `OrganizationInvitation`, `Department`, `Role`, `UserSettings`

**AI & Conversations:** `Conversation`, `Message` (with `MessageRole` enum: USER/ASSISTANT/SYSTEM/TOOL), `KnowledgeBase`

**Automation:** `Workflow`, `WorkflowStep`, `WorkflowExecution`, `WorkflowTemplate`

**Integrations:** `Connection` (stores OAuth tokens per platform), `ConnectionStatus` enum

**Finance:** `Payment`, `Subscription`, `Invoice`, `UsageLog`

**Observability:** `ObservabilityLog`, `ObservabilityTrace`, `FailedEvent` (DLQ)

### Running Migrations

```bash
# Auto-generated migration
alembic revision --autogenerate -m "add new column"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

> **Note:** In Docker Compose, migrations run automatically via the `migrator` service before the app starts.

---

## Observability

The observability system is structured into four layers:

### 1. Structured JSON Logging (`observability/logger.py`)
Every log line is emitted as a JSON object with: `timestamp`, `level`, `trace_id`, `span_id`, `customer_id`, `logger`, `message`, and optional `event_type`, `duration_ms`, `status`, `error_type`.

### 2. Distributed Tracing (`observability/tracer.py`)
- Each HTTP request gets a `trace_id` (from `X-Trace-ID` header or auto-generated UUID)
- Context is stored in `contextvars` for async safety
- `set_customer_id()` is called by `ToolExecutor` to correlate traces to users

### 3. Request Middleware (`observability/middleware.py`)
- Injects `trace_id` into every request/response cycle
- Logs `HTTP_REQUEST` (incoming) and `HTTP_RESPONSE` (outgoing with duration)
- Catches unhandled exceptions and logs `HTTP_ERROR` with classified error types
- Returns `X-Trace-ID` header in response for client-side correlation

### 4. Tool Wrapper with Auto-Retry (`observability/tool_wrapper.py`)
- Wraps every `ToolExecutor.execute_tool()` call
- Logs `TOOL_EXECUTION` events with timing
- On failure: classifies error type (transient vs permanent)
- Transient failures get automatic retry (configurable)
- Permanent failures go to the **Dead Letter Queue** (`FailedEvent` table)

### 5. Async DB Log Persistence (`observability/logger.py`)
- Background `asyncio` worker batches log entries (up to 50) and persists to `observability_logs` table
- Cleanup job deletes logs older than 14 days
- Falls back to `stderr` if DB persistence fails

### 6. Harness Engineering Events

The harness framework emits structured events to the observability pipeline:

| Event Type | Source | Description |
|---|---|---|
| `GUARDRAIL_CHECK` | `guardrails.py` | Pre-execution validation result (passed/blocked) |
| `FEEDBACK_LOOP` | `feedback_loops.py` | Error classification + corrective action taken |
| `QUALITY_GATE_PASS` | `quality_gates.py` | Response met quality threshold |
| `QUALITY_GATE_FAIL` | `quality_gates.py` | Response below threshold (logged, not blocked) |
| `CODE_MODE_EXECUTION` | `sandbox_service.py` | Code Mode run with tool calls, timing, errors |
| `AGENT_CONTEXT_UPDATE` | `agent_context.py` | Living documentation updated with new lesson |

### Error Classification (`observability/errors.py`)
```
USER_ERROR         → 400 (bad input)
VALIDATION_ERROR   → 422 (schema mismatch)
SYSTEM_ERROR       → 500 (internal failure)
EXTERNAL_API_ERROR → 502 (third-party failure)
TIMEOUT            → 504 (deadline exceeded)
RATE_LIMIT         → 429 (throttled)
```

---

## Security & Authentication

| Layer | Implementation |
|---|---|
| **Authentication** | Stateless JWT (`HS256`, 30-min expiry). Refresh token rotation. |
| **MFA** | TOTP (`pyotp`), backup codes, email OTP |
| **Passkeys** | WebAuthn via `webauthn` library |
| **OAuth** | Google, Microsoft login. OAuth flows for 20+ integrations. |
| **RBAC** | Route-level dependency injection. `FeatureGate` controls feature access by subscription tier. |
| **Encryption** | Sensitive fields encrypted at rest via `src/utils/encryption.py` |
| **Rate Limiting** | In-memory sliding window (5 req/min auth, 60 req/min API). Redis-backed for production. |
| **Secret Management** | Integration tokens stored encrypted in `Connection.config`. Never hardcoded. |

### Subscription Tiers & Feature Gating

The `FeatureGate` class (`src/services/feature_flags.py`) controls access:

| Feature | Free | Pro | Enterprise |
|---|---|---|---|
| AI messages/day | 50 | 1,000 | Unlimited |
| Connections | 3 | 15 | Unlimited |
| Write operations (send email, create event) | ❌ | ✅ | ✅ |
| Code Mode (execute_python_code) | ❌ | ✅ | ✅ |
| White-label | ❌ | ❌ | ✅ |

---

## API Surface

63 routers organized by domain. Key namespaces:

| Prefix | Purpose |
|---|---|
| `/auth/*` | Registration, login, OAuth, password reset, passkeys, MFA |
| `/chat/*` | Conversations, streaming messages, tool discovery |
| `/workflows/*` | CRUD, execution, history, templates |
| `/agents/*` | Autonomous agent lifecycle, scheduling |
| `/connections/*` | Integration OAuth flows, config management |
| `/payments/*` | M-Pesa callbacks, Stripe webhooks, checkout |
| `/api/v1/*` | System status, usage, organization management |
| `/mcp/*` | MCP protocol endpoints |
| `/templates/*` | Workflow template library |
| `/whatsapp/*` | Webhooks, contacts, broadcasts, auto-reply |
| `/_internal/*` | Debug APIs (logs, traces, DLQ, health) |
| `/_internal/harness/*` | Harness monitoring (guardrails, feedback, quality, Code Mode metrics) |

**Auto-generated docs:** Swagger at `/docs`, ReDoc at `/redoc`.

---

## Configuration

Configuration uses `pydantic-settings` with environment-specific classes:

| Class | Env File | Use Case |
|---|---|---|
| `DevelopmentConfig` | `.env.development` | Local dev (debug=true, reload=true) |
| `TestingConfig` | `.env.testing` | pytest (in-memory DB, test secrets) |
| `StagingConfig` | `.env.staging` | Pre-production |
| `ProductionConfig` | `.env.production` | Railway/Docker (debug=false, 2 workers) |

### Critical Environment Variables

```bash
# Core
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://localhost:6379
SECRET_KEY=<32-byte-random>
ENVIRONMENT=development|staging|production

# LLM Providers (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434

# LLM Settings
DEFAULT_LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4o
OLLAMA_MODEL=qwen3

# Runtime
RUN_MODE=web|mcp
PORT=8000
```

See `env.example` for the complete list of 100+ variables.

---

## Getting Started

### Prerequisites
- Python 3.11+
- Docker Desktop (recommended) or PostgreSQL 15 + Redis 7
- Git

### Option A: Docker Compose (Recommended)

```bash
git clone <repository-url>
cd arrotech-hub-backend

# Configure environment
cp env.example .env
# Edit .env with your API keys

# Start full stack (app + postgres + redis + ELK + prometheus + grafana + nginx)
docker-compose up -d

# Verify
curl http://localhost:8000/health
```

**Services started:**

| Service | Port | Purpose |
|---|---|---|
| `app` | 8000 | FastAPI application |
| `postgres` | 5434 | PostgreSQL 15 |
| `redis` | 6379 | Redis 7 |
| `elasticsearch` | 9200 | Log storage |
| `kibana` | 5601 | Log visualization |
| `prometheus` | 9090 | Metrics collection |
| `grafana` | 3001 | Metrics dashboards |
| `nginx` | 80 | Edge proxy |

### Option B: Local Python

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Start server
python -m src.main
```

### Accessing the Application

- **API Root:** `http://localhost:8000`
- **Swagger Docs:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **Health Check:** `http://localhost:8000/health`

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing

# Run specific test file
pytest tests/test_auth_router.py -v
```

Tests use `pytest-asyncio` with an in-memory SQLite database (`aiosqlite`). The `TESTING=true` environment variable disables rate limiting and external service calls.

---

## Deployment

### Production (Railway)

The application is deployed to Railway via GitHub Actions. Configuration in `railway.toml`:

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "python -m src.main"
```

### CI/CD Pipeline (`.github/workflows/`)

1. **PR Checks:** Linting (`flake8`/`black`), type checking, automated tests
2. **Main Branch Push:** Docker build → Railway deployment

### Docker Image

The `Dockerfile` uses a multi-stage build:
- Stage 1: Install Python dependencies
- Stage 2: Copy source code, expose port, run via `python -m src.main`

---

## Glossary

| Term | Definition |
|---|---|
| **MCP** | Model Context Protocol — open standard for LLM ↔ tool communication |
| **CCM** | Conversation Context Manager — Redis-backed multi-turn memory for WhatsApp/Telegram |
| **BYOK** | Bring Your Own Key — users supply their own LLM/service API keys |
| **DLQ** | Dead Letter Queue — failed events stored for retry in `failed_events` table |
| **RAG** | Retrieval-Augmented Generation — augmenting LLM context with vector search |
| **STK Push** | Safaricom M-Pesa prompt sent to customer's phone for payment |
| **Tool** | An MCP-compatible function the LLM can autonomously invoke |
| **Workflow** | A visual DAG of trigger → steps → actions, similar to Zapier/Make |
| **Agent** | An autonomous scheduled service that runs without user input |
| **Connection** | An OAuth-authenticated link to a third-party platform |
| **Code Mode** | Execution paradigm where the LLM writes Python code against a typed API instead of making individual tool calls |
| **Harness Engineering** | OpenAI's framework for reliable autonomous agents — guardrails, feedback loops, quality gates |
| **Guardrail** | A preventive control that validates agent actions before execution |
| **Quality Gate** | A post-execution evaluation checkpoint that scores agent output |
| **AGENTS.md** | Living documentation injected into agent context per session |
