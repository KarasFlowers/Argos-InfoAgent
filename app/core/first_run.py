"""
First-run bootstrap — invoked once at import time (before FastAPI starts).

Responsibilities:
1. If ``.env`` does not exist, copy from ``.env.template`` and (in an
   interactive terminal) prompt for the LLM API key.
2. Ensure ``data/`` subdirectories exist.
"""

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_TEMPLATE = PROJECT_ROOT / ".env.template"
DATA_DIRS = [
    PROJECT_ROOT / "data" / "sqlite",
    PROJECT_ROOT / "data" / "chroma",
    PROJECT_ROOT / "data" / "weekly_reports",
    PROJECT_ROOT / "logs",
]


def _write_llm_api_key(env_file: Path, api_key: str) -> None:
    """Persist the first-run key in the generic LLM config field."""
    text = env_file.read_text(encoding="utf-8")
    placeholder = '# LLM_API_KEY="sk-your-api-key-here"'
    if placeholder in text:
        text = text.replace(placeholder, f'LLM_API_KEY="{api_key}"')
    elif "LLM_API_KEY=" not in text:
        text += f'\nLLM_API_KEY="{api_key}"\n'
    env_file.write_text(text, encoding="utf-8")


def ensure_env() -> None:
    """Create ``.env`` from template if it doesn't exist."""
    if ENV_FILE.exists():
        return

    if not ENV_TEMPLATE.exists():
        return

    # Interactive prompt when running in a terminal
    if sys.stdin.isatty():
        print()
        print("=" * 50)
        print("  Argos — First-Time Setup")
        print("=" * 50)
        print()
        print("  .env file not found. Creating from template...")
        print()

        api_key = input("  LLM_API_KEY (press Enter to skip): ").strip()

        shutil.copy2(ENV_TEMPLATE, ENV_FILE)

        if api_key:
            _write_llm_api_key(ENV_FILE, api_key)
            print("  ✓ .env created with your LLM_API_KEY.")
        else:
            print("  ✓ .env created from template.")
            print(f"  ⚠ Please edit {ENV_FILE} and set LLM_API_KEY before using LLM features.")
        print()
    else:
        # Non-interactive (e.g. Docker, systemd) — silent copy
        shutil.copy2(ENV_TEMPLATE, ENV_FILE)


def ensure_data_dirs() -> None:
    """Create data directories if they don't exist."""
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def run_first_time_checks() -> None:
    """Entry point called from main.py."""
    ensure_env()
    ensure_data_dirs()
