"""Run the local release-readiness checks for Argos."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

DEFAULT_COMMANDS: list[tuple[str, list[str]]] = [
    ("Ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
    ("Ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("Git diff check", ["git", "diff", "--check"]),
    ("Frontend syntax", ["node", "--check", "app/web/static/app.js"]),
    ("Frontend API key smoke", ["node", "scripts/frontend_auth_smoke.js"]),
    ("Docker Compose config", ["docker", "compose", "config", "--quiet"]),
    ("Tests", [sys.executable, "-m", "pytest"]),
    ("Runtime smoke", [sys.executable, "scripts/runtime_smoke.py", "--timeout", "90"]),
]

DOCKER_SMOKE_COMMAND = ("Docker smoke", [sys.executable, "scripts/docker_smoke.py", "--no-build", "--timeout", "120"])


def _missing_binary(command: list[str]) -> str | None:
    binary = command[0]
    if binary == sys.executable:
        return None
    return None if shutil.which(binary) else binary


def run_command(name: str, command: list[str], *, env: dict[str, str]) -> None:
    print(f"\n==> {name}", flush=True)
    print("+ " + " ".join(command), flush=True)
    missing = _missing_binary(command)
    if missing:
        raise RuntimeError(f"Required command not found: {missing}")
    subprocess.run(command, check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Argos local release-readiness checks.")
    parser.add_argument(
        "--with-docker-smoke",
        action="store_true",
        help="Also run the real Docker Compose smoke check. Requires a running Docker daemon.",
    )
    args = parser.parse_args()

    env = os.environ.copy()

    commands = list(DEFAULT_COMMANDS)
    if args.with_docker_smoke:
        commands.append(DOCKER_SMOKE_COMMAND)

    for name, command in commands:
        run_command(name, command, env=env)

    print("\nRelease checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"\nRelease check failed: {' '.join(error.cmd)} exited with {error.returncode}", file=sys.stderr)
        raise SystemExit(error.returncode) from None
    except Exception as error:
        print(f"\nRelease check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
