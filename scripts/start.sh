#!/usr/bin/env bash
# =========================================
#   Argos - One-Click Launcher
#   Supports macOS and Linux
# =========================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/venv"
PYTHON="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"
UVICORN="${VENV_DIR}/bin/uvicorn"
PORT=8000
URL="http://127.0.0.1:${PORT}"

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }

# ---- 0) Check Python ----
SYSTEM_PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        SYSTEM_PYTHON="$candidate"
        break
    fi
done
if [ -z "$SYSTEM_PYTHON" ]; then
    error "Python 3 not found. Please install Python 3.11+ first."
    exit 1
fi
PY_VERSION=$("$SYSTEM_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Found $SYSTEM_PYTHON ($PY_VERSION)"

# ---- 1) Create venv if missing ----
if [ ! -f "$PYTHON" ]; then
    info "Creating virtual environment..."
    "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
fi

# ---- 2) Install / update dependencies ----
if [ ! -f "$UVICORN" ]; then
    info "Installing dependencies (this may take a few minutes on first run)..."
    "$PIP" install --upgrade pip -q
    "$PIP" install -r requirements.txt -q
    ok "Dependencies installed."
else
    info "Dependencies already installed. Skipping pip install."
fi

# ---- 3) Auto-generate .env if missing ----
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    warn ".env file not found."
    if [ -t 0 ]; then
        # Interactive terminal — prompt for API key
        echo ""
        echo -e "${CYAN}First-time setup: please enter your OpenAI-compatible LLM API key.${NC}"
        echo -e "  Default model is DeepSeek-compatible; OpenAI-compatible providers also work."
        echo -n "  LLM_API_KEY: "
        read -r api_key
        if [ -n "$api_key" ]; then
            cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
            ARGOS_FIRST_RUN_LLM_API_KEY="$api_key" "$SYSTEM_PYTHON" - <<'PY'
from pathlib import Path
import os

env_path = Path(".env")
api_key = os.environ["ARGOS_FIRST_RUN_LLM_API_KEY"]
text = env_path.read_text(encoding="utf-8")
placeholder = '# LLM_API_KEY="sk-your-api-key-here"'
if placeholder in text:
    text = text.replace(placeholder, f'LLM_API_KEY="{api_key}"')
elif "LLM_API_KEY=" not in text:
    text += f'\nLLM_API_KEY="{api_key}"\n'
env_path.write_text(text, encoding="utf-8")
PY
            ok ".env created with your API key."
        else
            cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
            warn ".env created from template. Please edit it to add your API key."
        fi
    else
        cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
        warn ".env created from template. Please edit it to add your LLM_API_KEY."
    fi
fi

RAG_ENABLED_RAW="${RAG_ENABLED:-}"
if [ -z "$RAG_ENABLED_RAW" ] && [ -f "$PROJECT_ROOT/.env" ]; then
    RAG_ENABLED_RAW="$(grep -E '^[[:space:]]*RAG_ENABLED=' "$PROJECT_ROOT/.env" | tail -n 1 | cut -d= -f2- | tr -d "\"'[:space:]" || true)"
fi
case "${RAG_ENABLED_RAW,,}" in
    false|0|no|off)
        RAG_ENABLED_EFFECTIVE=false
        ;;
    *)
        RAG_ENABLED_EFFECTIVE=true
        ;;
esac

if [ "$RAG_ENABLED_EFFECTIVE" = "true" ]; then
    if ! "$PYTHON" -c "import sentence_transformers" >/dev/null 2>&1; then
        info "Installing RAG dependencies..."
        "$PIP" install -r requirements-rag.txt -q
        ok "RAG dependencies installed."
    fi
else
    info "RAG_ENABLED=false; skipping RAG dependencies and embedding model download."
fi

# ---- 4) Ensure data directories exist ----
mkdir -p "$PROJECT_ROOT/data/sqlite" "$PROJECT_ROOT/data/chroma" "$PROJECT_ROOT/logs"

# ---- 5) Check if port is already in use ----
if command -v lsof &>/dev/null && lsof -iTCP:$PORT -sTCP:LISTEN &>/dev/null; then
    info "Port $PORT is already in use. Opening the existing dashboard..."
    if command -v xdg-open &>/dev/null; then
        xdg-open "$URL"
    elif command -v open &>/dev/null; then
        open "$URL"
    else
        info "Open $URL in your browser."
    fi
    exit 0
fi

# ---- 6) Check Redis (optional, non-fatal) ----
if command -v redis-cli &>/dev/null; then
    if redis-cli ping &>/dev/null; then
        ok "Redis is running."
    else
        warn "Redis is installed but not running. Caching will be disabled."
        warn "Start Redis with: redis-server --daemonize yes"
    fi
else
    warn "Redis not found. Caching will be disabled. Install with: sudo apt install redis-server / brew install redis"
fi

# ---- 7) Pre-download models if RAG is enabled and not cached ----
if [ "$RAG_ENABLED_EFFECTIVE" = "true" ] && [ ! -d "${HF_HOME:-$HOME/.cache/huggingface}/hub/models--BAAI--bge-m3" ]; then
    info "Pre-downloading embedding models (first run only, ~500MB)..."
    "$PYTHON" scripts/download_models.py && ok "Models cached." || warn "Model download failed. They will be downloaded on first use."
fi

# ---- 8) Start backend ----
info "Starting Argos backend on $URL ..."
"$UVICORN" main:app --host 127.0.0.1 --port "$PORT" --reload &
SERVER_PID=$!

# ---- 9) Wait for healthy ----
info "Waiting for server..."
for i in $(seq 1 30); do
    if curl -sf "$URL/api/v1/ping" >/dev/null 2>&1; then
        ok "Server is ready!"
        # Open browser
        if command -v xdg-open &>/dev/null; then
            xdg-open "$URL"
        elif command -v open &>/dev/null; then
            open "$URL"
        else
            info "Open $URL in your browser."
        fi
        break
    fi
    sleep 1
done

echo ""
echo "==========================================="
echo "  Dashboard: $URL"
echo "  Press Ctrl+C to stop the server."
echo "==========================================="
wait $SERVER_PID
