# Arrotech Hub Backend

> **A multi-tenant AI operations platform backend.**

Arrotech Hub Backend serves as the robust orchestration layer powering the Arrotech Hub. It elegantly bridges conversational AI capabilities with enterprise workflow execution, business integrations, and automated operational routing.

---

## 📑 Table of Contents

- [Overview](#-overview)
- [System Architecture](#-system-architecture)
- [Core Domain Modules](#-core-domain-modules)
- [Prerequisites](#-prerequisites)
- [Getting Started](#-getting-started)
- [Configuration & Environment](#-configuration--environment)
- [Data Model & Persistence](#-data-model--persistence)
- [API Surface](#-api-surface)
- [MCP Mode](#-mcp-mode)
- [Security & Authentication](#-security--authentication)
- [Testing & Quality](#-testing--quality)
- [Deployment](#-deployment)

---

## 🎯 Overview

The service functions as the central nervous system for Arrotech Hub, handling:
- **Conversational AI (`/chat`)**: Supports tool execution and real-time streaming responses.
- **Workflow Orchestration (`/workflows`, `/agents`)**: Features template management, node-based execution tracking, and scheduling.
- **Business Integrations**: Native hooks for CRM (HubSpot, Salesforce), productivity (Slack, Google Workspace), and social channels.
- **Financial Reconciliation**: Payment gateways (M-Pesa, Stripe, Paystack) with fraud signaling.
- **Identity & Organization**: Multi-tenant RBAC, onboarding, and secure access flows.

Built on **FastAPI**, it operates asynchronously and seamlessly integrates with **PostgreSQL** (via asyncpg) and **Redis** for stateful operations.

---

## 🏗 System Architecture

The application follows a modular, service-oriented monolithic architecture with strict separation of concerns.

```mermaid
graph TD
    Client[Client Apps / Frontend] --> Proxy[Nginx Edge Proxy]
    Proxy --> API[FastAPI Application]
    
    subgraph Core Runtime
        API --> AuthMiddleware[Auth & RBAC Middleware]
        AuthMiddleware --> Routers[Domain Routers]
        Routers --> Services[Service Orchestration Layer]
    end

    subgraph Persistence
        Services --> DB[(PostgreSQL)]
        Services --> Cache[(Redis Cache & Session)]
    end

    subgraph External Dependencies
        Services -.-> LLMs[LLM Providers: OpenAI/Gemini/Ollama]
        Services -.-> Integrations[SaaS Integrations: HubSpot/Slack/WhatsApp]
        Services -.-> Payments[Payment Gateways: M-Pesa/Stripe]
    end
    
    subgraph Observability
        API -.-> Logs[Logstash/Elasticsearch]
        API -.-> Metrics[Prometheus/Grafana]
    end
```

### Request Lifecycle

1. **Ingress**: Request enters the FastAPI application.
2. **Middleware Pipeline**: Applies GZip, in-memory rate limiting, Cache-Control, CORS, and proxy header adaptation.
3. **Context Resolution**: Authorization, tenant mapping, and user identity are resolved via route-level dependencies.
4. **Service Delegation**: The router parses the request and delegates business logic to specific domain services.
5. **Persistence/External Calls**: The service interacts with PostgreSQL via SQLAlchemy, Redis, or external third-party REST/GraphQL APIs.
6. **Egress**: The response is returned to the client.

---

## 🧩 Core Domain Modules

The codebase is logically grouped into discrete domain modules located under `src/routers/` and `src/services/`.

| Module Category | Responsibilities |
|-----------------|------------------|
| **Core Platform** | Auth (JWT/Passkeys), user lifecycle, RBAC, settings, integration registry (`/connections`). |
| **Conversational** | Chat history memory, provider agnostic abstraction (OpenAI, Anthropic, Gemini), RAG tooling. |
| **Automation** | Visual workflow design, execution engine, retries, agent scheduling. |
| **Business/Vertical** | Creator marketplace, support ticketing, public forms, blog API, notifications. |
| **Finance** | M-Pesa reconciliation, Stripe/Paystack subscriptions, invoicing, fraud detection. |

---

## 🛠 Prerequisites

Before setting up the project locally, ensure you have the following installed:

- **Python**: `3.11+`
- **Docker**: Desktop or Engine + Docker Compose
- **Git**: For version control

---

## 🚀 Getting Started

We utilize Docker Compose to provide a production-mirrored development environment. 

### 1. Repository Setup

```bash
git clone <repository-url>
cd arrotech-hub-backend
```

### 2. Environment Configuration

Copy the template environment file to create your local `.env`.

```bash
cp env.example .env
```

> [!IMPORTANT]
> You **must** populate the `.env` file with functional keys for external services (e.g., `OPENAI_API_KEY`, `DATABASE_URL`) before running the application. Review the `env.example` file for instructions.

### 3. Local Virtual Environment (Optional but recommended for IDEs)

```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Bootstrapping the Infrastructure

Run the full stack (Database, Redis, FastAPI, and Observability stack) via Docker Compose:

```bash
docker-compose up -d
```

### 5. Accessing the Application

- **API Root**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Swagger Documentation**: `http://localhost:8000/docs`
- **ReDoc Documentation**: `http://localhost:8000/redoc`

---

## ⚙️ Configuration & Environment

Configuration is governed by `src/config.py` utilizing `pydantic-settings`. 

### Key Environment Variables

- **`ENVIRONMENT`**: Defines the runtime context (`development`, `staging`, `production`).
- **`DATABASE_URL`**: Async PostgreSQL connection string (`postgresql://user:pass@host:port/db`).
- **`REDIS_URL`**: Redis instance URI for caching and session state.
- **`SECRET_KEY`**: Cryptographic key used for signing JWTs and encrypting sensitive fields.
- **`DEFAULT_LLM_PROVIDER`**: Fallback LLM provider (`openai`, `anthropic`, `gemini`, `ollama`).
- **`ENABLE_*`**: Feature flags controlling the activation of integrations (e.g., `ENABLE_WHATSAPP=true`).

---

## 🗄 Data Model & Persistence

The application uses **SQLAlchemy 2.0** with **asyncpg** for non-blocking database interactions. Schema evolution is tightly controlled via **Alembic**.

> [!NOTE]
> See `src/models.py` for the complete entity graph.

### Core Entities
- **Identity**: `User`, `Role`, `Organization`, `Department`.
- **AI & Memory**: `Conversation`, `Message`.
- **Automation Engine**: `Workflow`, `WorkflowStep`, `WorkflowExecution`.
- **Finance**: `Payment`, `Subscription`, `Invoice`.

### Migrations
Database migrations are executed automatically on startup by the `migrator` service in Docker Compose. To manually generate a new migration:

```bash
alembic revision --autogenerate -m "description of changes"
alembic upgrade head
```

---

## 🌐 API Surface

The API utilizes FastAPI's robust routing mechanism. Key namespaces include:

- **`/auth`**: Registration, authentication, OAuth callbacks, password resets, passkey setup.
- **`/chat`**: LLM interaction, tool capabilities discovery, message history retrieval.
- **`/workflows`**: CRUD for automation templates, execution triggers, history.
- **`/agents`**: Lifecycle management for autonomous scheduling agents.
- **`/connections`**: Third-party integration configurations and OAuth state management.
- **`/payments`**: M-Pesa callbacks, Stripe webhooks, checkout sessions.
- **`/api/v1/*`**: System status, platform usage, organization team management.

---

## 🤖 MCP Mode (Model Context Protocol)

The backend natively supports running as an **MCP stdio server**. When initiated with `RUN_MODE=mcp`, it exposes a suite of tools directly to compatible clients.

Available tools in MCP mode include:
- HubSpot data manipulation
- Slack messaging / report generation
- Web scraping utilities
- Local file management

---

## 🔐 Security & Authentication

Security is treated as a first-class citizen:

1. **Authentication**: Stateless JWT-based sessions.
2. **MFA Support**: Integrated support for OTP, TOTP, and Passkeys (WebAuthn).
3. **RBAC**: Route-level dependency injection for rigorous permission verification.
4. **Secret Management**: External integration credentials (like HubSpot or Slack tokens) are dynamically resolved and never hardcoded.
5. **Rate Limiting**: In-memory and Redis-backed throttling for critical paths (e.g., `/auth`).

---

## 🧪 Testing & Quality

We maintain a rigorous testing standard utilizing `pytest` and `pytest-asyncio`.

To run the test suite locally:

```bash
pytest tests/ -v
```

To generate a coverage report:

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

---

## 🚢 Deployment

The production application is containerized and designed to run in environments like Kubernetes, Fly.io, or Railway. 

### CI/CD Pipeline
Deployment flows are orchestrated via GitHub Actions (`.github/workflows/ci.yml`). 
- **PR Checks**: Linting (`flake8`/`black`), formatting, and automated tests.
- **Main Branch Push**: Triggers a production build, Docker image packaging, and deployment rollout.

### Observability
The Docker Compose stack natively provisions ELK (`elasticsearch`, `logstash`, `kibana`) and Prometheus/Grafana. In production, logs are emitted in JSON format for optimized ingestion by centralized logging tools.
