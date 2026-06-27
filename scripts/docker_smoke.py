"""Docker Compose smoke test for a private Argos deployment.

This script is intentionally small and dependency-free so it can run on a
fresh host with only Python and Docker installed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT_URL = "http://127.0.0.1:8000"
API_KEY = "argos-smoke-key"


def run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def run_best_effort(cmd: list[str], *, env: dict[str, str]) -> None:
    """Run a diagnostic/cleanup command without masking the original failure."""
    try:
        run(cmd, env=env)
    except Exception as error:
        print(f"Best-effort command failed: {' '.join(cmd)} ({error})", file=sys.stderr)


def request_status(path: str, *, api_key: str | None = None, timeout: float = 3.0) -> int:
    req = urllib.request.Request(f"{ROOT_URL}{path}")
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def wait_for_ping(deadline_seconds: int) -> None:
    deadline = time.monotonic() + deadline_seconds
    last_status: int | str = "not attempted"
    while time.monotonic() < deadline:
        try:
            last_status = request_status("/api/v1/ping")
            if last_status == 200:
                return
        except Exception as error:
            last_status = f"{type(error).__name__}: {error}"
        time.sleep(2)
    raise RuntimeError(f"/api/v1/ping did not become healthy; last status: {last_status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Docker Compose smoke checks for Argos.")
    parser.add_argument(
        "--no-build", action="store_true", help="Use existing images instead of docker compose up --build."
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="Run docker compose down after the smoke check. Disabled by default to avoid stopping an existing stack.",
    )
    parser.add_argument("--timeout", type=int, default=120, help="Seconds to wait for /api/v1/ping.")
    args = parser.parse_args()

    env = os.environ.copy()
    env.update(
        {
            "RAG_ENABLED": "false",
            "API_KEY": API_KEY,
            "PUBLIC_BASE_URL": ROOT_URL,
        }
    )

    try:
        run(["docker", "info"], env=env)
        up_cmd = ["docker", "compose", "up", "-d"]
        if not args.no_build:
            up_cmd.append("--build")
        run(up_cmd, env=env)
        wait_for_ping(args.timeout)

        checks = {
            "public ping": request_status("/api/v1/ping"),
            "private without key": request_status("/api/v1/admin/tasks"),
            "private wrong key": request_status("/api/v1/admin/tasks", api_key="wrong-key"),
            "private correct key": request_status("/api/v1/admin/tasks", api_key=API_KEY),
            "status without key": request_status("/api/v1/status"),
            "status wrong key": request_status("/api/v1/status", api_key="wrong-key"),
            "status correct key": request_status("/api/v1/status", api_key=API_KEY),
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
            raise RuntimeError(f"Unexpected Docker smoke status matrix: {checks}")

        print("Docker smoke passed: ping is public and private routes require X-API-Key.")
        return 0
    except Exception:
        run_best_effort(["docker", "compose", "logs", "--tail", "80", "app"], env=env)
        raise
    finally:
        if args.teardown:
            run_best_effort(["docker", "compose", "down"], env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {' '.join(error.cmd)}", file=sys.stderr)
        raise SystemExit(error.returncode) from None
    except Exception as error:
        print(f"Docker smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
