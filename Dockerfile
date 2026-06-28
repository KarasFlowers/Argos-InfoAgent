# --- Stage 1: Build dependencies ---
FROM python:3.13-slim AS builder

WORKDIR /app

# Install system dependencies for packages that may need native builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    gcc \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-core.txt requirements-rag.txt requirements-mcp.txt ./

ARG RAG_ENABLED=false
ARG MCP_ENABLED=false

# Install dependencies into a separate directory to keep image clean
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && if [ "$RAG_ENABLED" = "true" ]; then pip install --no-cache-dir --prefix=/install -r requirements-rag.txt; fi \
    && if [ "$MCP_ENABLED" = "true" ]; then pip install --no-cache-dir --prefix=/install -r requirements-mcp.txt; fi

# --- Stage 2: Final Image ---
FROM python:3.13-slim

WORKDIR /app

# Install only runtime system deps (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copy only the installed dependencies from builder
COPY --from=builder /install /usr/local

# Optionally pre-warm sentence-transformers weights so the first RAG request is fast.
# Disabled by default to keep the standard image lightweight.
ARG RAG_ENABLED=false
ARG PREWARM_RAG_MODELS=false
ENV HF_HOME=/opt/hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache \
    TRANSFORMERS_OFFLINE=0
RUN if [ "$RAG_ENABLED" = "true" ] && [ "$PREWARM_RAG_MODELS" = "true" ]; then \
        python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('BAAI/bge-m3'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')" \
        && mkdir -p /opt/hf-cache && chown -R appuser:appuser /opt/hf-cache; \
    else \
        mkdir -p /opt/hf-cache && chown -R appuser:appuser /opt/hf-cache; \
    fi

# Copy the rest of the application
COPY --chown=appuser:appuser . .

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Create data directory for SQLite
RUN mkdir -p /app/data && chown appuser:appuser /app/data
VOLUME /app/data

# We use 0.0.0.0 so the app can be accessed from outside the container
EXPOSE 8000

# Health check against the /api/v1/ping endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/ping')" || exit 1

# Run as non-root user
USER appuser

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
