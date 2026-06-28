#!/usr/bin/env python3
"""Print the effective RAG_ENABLED value for local launcher scripts."""

from __future__ import annotations

import os
import re
from pathlib import Path

TRUE_VALUES = {"true", "1", "yes", "on"}


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().strip('"').strip("'").strip().lower()


def _read_env_file(path: Path) -> str:
    if not path.exists():
        return ""
    value = ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^\s*RAG_ENABLED\s*=\s*(.*)\s*$", line)
        if match:
            value = match.group(1)
    return value


def main() -> int:
    value = os.environ.get("RAG_ENABLED") or _read_env_file(Path(".env"))
    print("true" if _normalize(value) in TRUE_VALUES else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
