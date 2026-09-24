# 🛍️ AIStoreAssistant

> Enterprise AI customer support and sales automation platform for online e-commerce stores. Powered by **FastAPI**, **Celery**, **PostgreSQL (`pgvector`)**, **Frappe / ERPNext Webshop**, and private **`llm-gateway`**.

---

## 🌟 Key Features

- **Omnichannel Customer Support**:
  - **Website Live Chat Widget**: Real-time token streaming via Server-Sent Events (SSE) with `localStorage` session continuity, interactive quick prompts, and lightweight markdown formatting.
  - **Meta Facebook Messenger**: Webhook ingestion with HMAC SHA-256 signature verification, <25ms event acknowledgment, and asynchronous multi-turn conversation handling via Celery.
- **Enterprise ERPNext / Frappe Webshop Integration**:
  - Automated catalog and inventory sync from `http://erppark.local.com`.
  - Real-time order lookup and status tracking.
  - Automated human escalation support ticket creation (`Issue` DocType).
- **Autonomous Multi-Turn Tool Loop**:
  - `search_products`: Semantic and keyword catalog queries.
  - `get_product_details`: Live stock, attributes, specifications, and pricing.
  - `track_order`: Multi-courier tracking and delivery timeline calculation.
  - `search_store_policies`: 1024-dim dense vector RAG (BGE-M3) cosine similarity search.
  - `request_human_handoff`: Automatic staff takeover flagging and ticket creation.
- **Grounding & Guardrails**:
  - Strict anti-hallucination system prompts preventing fabricated discounts or delivery promises.
  - Bilingual conversational fluency (English & Bengali).
  - Distributed Redis locking per customer preventing race conditions.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Omnichannel["Omnichannel Ingestion"]
        FB["Facebook Messenger\n(Webhook Events)"]
        WEB["Website Visitors\n(Vanilla JS Widget)"]
    end

    subgraph FastAPILayer["FastAPI Application (:8000)"]
        HOOK["POST /api/v1/webhooks/messenger"]
        CHAT_INIT["POST /api/v1/chat/sessions"]
        CHAT_STREAM["POST /api/v1/chat/stream\n(Direct SSE Token Stream)"]
        CHAT_HIST["GET /api/v1/chat/sessions/{id}/history"]
        DEMO["GET /demo\n(Demo Storefront)"]
    end

    subgraph AsyncPipeline["Background Workers"]
        CELERY["Celery Worker\n(Concurrent Task Processor)"]
        BEAT["Celery Beat\n(Catalog Sync Scheduler)"]
    end

    subgraph AIEngine["AI Reasoning & RAG Engine"]
        GATEWAY["llm-gateway (:8002)\n/ local Ollama (:11434)"]
        EMBED["Ollama BGE-M3 (1024-dim)\nSemantic Vector Embeddings"]
        TOOLS["Multi-Turn Tool Orchestrator\n• search_products\n• get_product_details\n• track_order\n• search_store_policies\n• request_human_handoff"]
    end

    subgraph ExternalIntegrations["External Integrations"]
        ERPNEXT["Frappe / ERPNext Webshop\n(http://erppark.local.com)"]
        META_GRAPH["Meta Graph API v21.0\n(Send API)"]
    end

    subgraph Infrastructure["Shared Infrastructure (db_services)"]
        PGVEC[("PostgreSQL 16 + pgvector (:5433)\n11 Tables + HNSW Index")]
        REDIS[("Shared Redis (:6379)\nDB 3: Cache | DB 4: Broker | DB 5: Backend")]
    end

    FB -->|HMAC Verified POST| HOOK
    HOOK -->|Enqueues Task| REDIS
    REDIS -->|Dispatches Turn| CELERY
    CELERY -->|Multi-Turn Agent| TOOLS
    CELERY -->|Send API| META_GRAPH

    WEB -->|Init / Resume| CHAT_INIT
    WEB -->|Real-Time SSE| CHAT_STREAM
    CHAT_STREAM -->|Token Stream| TOOLS

    TOOLS <-->|Tool Calling Loop| GATEWAY
    TOOLS <-->|Dense Vector Search| PGVEC
    TOOLS <-->|Live API Queries| ERPNEXT

    BEAT -->|Periodic Catalog Sync| ERPNEXT
    ERPNEXT -->|Catalog Ingestion| PGVEC
```

---

## 📁 Project Directory Structure

```text
ai-store-assistant/backend/
├── app/
│   ├── api/v1/endpoints/       # Messenger Webhooks & Webchat REST/SSE endpoints
│   ├── core/                   # Config, Database engine, Celery, Middleware
│   ├── models/                 # SQLAlchemy 2.0 ORM Models (11 tables)
│   ├── services/               # AI agent, Frappe client, RAG, Meta service, Tools
│   └── tasks/                  # Celery background tasks
├── alembic/                    # Database migrations
├── scripts/                    # Seeding, sync tests, webhook simulations
├── static/                     # Embedded chat widget & demo storefront
├── tests/                      # Automated Pytest test suite (11 tests)
└── pyproject.toml              # Dependencies managed by uv (Python 3.14)
```

---

## ⚡ Quickstart Guide

### 1. Prerequisites
- Python 3.14+ with [uv](https://github.com/astral-sh/uv)
- Docker & Docker Compose
- Shared database services running in `/home/shafayet/Workspace/db_services`
- Local Ollama running `bge-m3` or `nomic-embed-text`
- Remote or local `llm-gateway`

### 2. Environment Configuration
Copy `.env.example` to `.env` and update secrets:
```bash
cp .env.example .env
```

Ensure the connection variables match your shared database setup:
```env
DATABASE_URL="postgresql+asyncpg://postgres:postgrespassword@localhost:5433/aistore_db"
REDIS_URL="redis://localhost:6379/3"
CELERY_BROKER_URL="redis://localhost:6379/4"
CELERY_RESULT_BACKEND="redis://localhost:6379/5"
```

### 3. Database Migration & Seeding
```bash
# Apply Alembic schema migrations
uv run alembic upgrade head

# Seed initial store catalog, policies & sample orders
uv run python -m scripts.seed_mock_data
```

### 4. Sync Live ERPNext Catalog (Optional)
```bash
uv run python -m scripts.test_frappe_sync
```

### 5. Running the Application Locally
```bash
# Terminal 1: FastAPI API & SSE Streaming Server
uv run fastapi dev --port 8000

# Terminal 2: Celery Background Task Worker
uv run celery -A app.core.celery.celery_app worker --loglevel=info --concurrency=4
```

### 6. Run Automated Tests
```bash
uv run pytest -v
```

---

## 🌐 Testing the Components

### A. Website AI Chat Widget
1. Start the server: `uv run fastapi dev --port 8000`.
2. Open your browser to **`http://localhost:8000/demo`**.
3. Click the floating chat bubble in the lower right.
4. Try queries like:
   - *"Where is my order SO-2026-0042?"*
   - *"Do you have any black t-shirts in stock?"*
   - *"What are your delivery charges to Chittagong?"*
   - *"I need to speak with a human agent."*

### B. Embed into Any Website
Include this single script tag in your HTML:
```html
<script src="http://localhost:8000/static/widget/chat-widget.js" defer></script>
```

### C. Simulate Meta Messenger Webhook
Run the end-to-end simulation script:
```bash
uv run python -m scripts.simulate_messenger_webhook
```

---

## 🐳 Docker Deployment

The application runs seamlessly with the central shared `db_services`:

1. Start shared database infrastructure:
   ```bash
   docker compose -f /home/shafayet/Workspace/db_services/compose.yml up -d
   ```

2. Start AIStoreAssistant services:
   ```bash
   docker compose -f ../docker/compose.yml up -d --build
   ```

3. View live logs:
   ```bash
   docker logs -f aistore-backend
   docker logs -f aistore-celery-worker
   ```

