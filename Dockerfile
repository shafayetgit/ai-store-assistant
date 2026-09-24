# ━━ Stage 1: Build & Dependencies ━━
FROM python:3.14-slim AS builder

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml to install dependencies
COPY backend/pyproject.toml .

# Install dependencies into /app/.venv
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

# ━━ Stage 2: Production Runtime ━━
FROM python:3.14-slim AS runner

WORKDIR /app

# Create unprivileged system user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy virtualenv from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source code
COPY backend/ /app/

# Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]