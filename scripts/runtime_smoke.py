"""Local runtime smoke test for Argos without Docker.

Starts a real Uvicorn process on a temporary port with lightweight runtime
settings, then verifies health and API key behavior.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API_KEY = "argos-runtime-smoke-key"
LOG_TAIL_CHARS = 4000


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_status(root_url: str, path: str, *, api_key: str | None = None, timeout: float = 3.0) -> int:
    request = urllib.request.Request(f"{root_url}{path}")
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def wait_for_ping(root_url: str, deadline_seconds: int) -> None:
    deadline = time.monotonic() + deadline_seconds
    last_status: int | str = "not attempted"
    while time.monotonic() < deadline:
        try:
            last_status = request_status(root_url, "/api/v1/ping")
            if last_status == 200:
                return
        except Exception as error:
            last_status = f"{type(error).__name__}: {error}"
        time.sleep(1)
    raise RuntimeError(f"/api/v1/ping did not become healthy; last status: {last_status}")


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def tail_file(path: Path, limit: int = LOG_TAIL_CHARS) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def print_log_tail(log_path: Path) -> None:
    output = tail_file(log_path)
    if output:
        print(f"--- runtime smoke log tail ({log_path}) ---", file=sys.stderr)
        print(output, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local Uvicorn smoke check for Argos.")
    parser.add_argument("--port", type=int, default=0, help="Port to bind. Default: choose a free port.")
    parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for /api/v1/ping.")
    args = parser.parse_args()

    port = args.port or find_free_port()
    root_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="argos-runtime-smoke-") as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "argos.db"
        chroma_dir = tmp_path / "chroma"

        env = os.environ.copy()
        env.update(
            {
                "API_KEY": API_KEY,
                "PUBLIC_BASE_URL": root_url,
                "RAG_ENABLED": "false",
                "SQLALCHEMY_DATABASE_URI": f"sqlite+aiosqlite:///{db_path.as_posix()}",
                "CHROMA_DB_DIR": chroma_dir.as_posix(),
            }
        )

        code = (
            "import uvicorn; "
            f"uvicorn.run('main:app', host='127.0.0.1', port={port}, log_level='warning', access_log=False)"
        )
        log_path = tmp_path / "runtime-smoke.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-c", code],
                env=env,
                text=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for_ping(root_url, args.timeout)

                checks = {
                    "public ping": request_status(root_url, "/api/v1/ping"),
                    "private without key": request_status(root_url, "/api/v1/admin/tasks"),
                    "private wrong key": request_status(root_url, "/api/v1/admin/tasks", api_key="wrong-key"),
                    "private correct key": request_status(root_url, "/api/v1/admin/tasks", api_key=API_KEY),
                    "status without key": request_status(root_url, "/api/v1/status"),
                    "status wrong key": request_status(root_url, "/api/v1/status", api_key="wrong-key"),
                    "status correct key": request_status(root_url, "/api/v1/status", api_key=API_KEY),
                }
                expected = {
                    "public ping": 200,
                    "private without key": 403,
                    "private wrong key": 403,
                    "private correct key": 200,
                    "status without key": 403,
                    "status wrong key": 403,
                    "status correct key": 200,
                }
                if checks != expected:
                    raise RuntimeError(f"Unexpected smoke status matrix: {checks}")

                print(f"Runtime smoke passed on {root_url}: ping is public and private routes require X-API-Key.")
                return 0
            except Exception:
                log_file.flush()
                print_log_tail(log_path)
                raise
            finally:
                terminate(process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {' '.join(error.cmd)}", file=sys.stderr)
        raise SystemExit(error.returncode) from None
    except Exception as error:
        print(f"Runtime smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
