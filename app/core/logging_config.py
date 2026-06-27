"""
Structured logging configuration using *structlog*.

Usage
-----
Call ``setup_logging()`` once at application startup (before any logger is
created).  Every log line will include:

- ``timestamp`` – ISO-8601
- ``level``     – uppercase log level
- ``logger``    – dotted module path
- ``trace_id``  – per-request UUID (set by the ASGI middleware)

In development the output is coloured key=value; in Docker /
``LOG_FORMAT=json`` it switches to one JSON object per line.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar, Token
from typing import Any

import structlog

# ContextVar holding the current request's trace id.
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

SECRET_FIELD_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|cookie)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(?P<prefix>\b(?:sk|ghp|tvly)-)[A-Za-z0-9_\-]{8,}|" r"(?P<header>\b(?:Bearer|token)\s+)[A-Za-z0-9._\-]{8,}",
    re.IGNORECASE,
)


def _redact_text(value: str) -> str:
    return SECRET_VALUE_RE.sub(lambda match: f"{match.group('prefix') or match.group('header')}***", value)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {key: "***" if SECRET_FIELD_RE.search(str(key)) else _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def _add_trace_id(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject the current request trace_id into every log event."""
    event_dict["trace_id"] = trace_id_ctx.get("-")
    return event_dict


def redact_secrets(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Mask common secret fields and token-looking values before rendering logs."""
    return {
        key: "***" if SECRET_FIELD_RE.search(str(key)) else _redact_value(value) for key, value in event_dict.items()
    }


def setup_logging(*, json_output: bool | None = None) -> None:
    """
    Configure structlog + stdlib logging in one shot.

    Parameters
    ----------
    json_output:
        ``True``  → JSON lines (for Docker / log aggregators).
        ``False`` → coloured key=value (for local dev).
        ``None``  → auto-detect from ``LOG_FORMAT`` env var.
    """
    if json_output is None:
        json_output = os.getenv("LOG_FORMAT", "").lower() == "json"

    # Shared processors applied to EVERY log event.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_trace_id,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        redact_secrets,
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(
            ensure_ascii=False,
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
            pad_level=False,
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quieten noisy third-party loggers.
    for name in ("httpx", "httpcore", "chromadb", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def bind_new_trace_id() -> tuple[str, Token[str]]:
    """Generate a short trace-id, bind it, and return its reset token."""
    tid = uuid.uuid4().hex[:12]
    token = trace_id_ctx.set(tid)
    return tid, token


def new_trace_id() -> str:
    """Generate a short trace-id and store it in the context var."""
    tid, _ = bind_new_trace_id()
    return tid


def reset_trace_id(token: Token[str]) -> None:
    """Restore the trace-id context that was active before a request."""
    trace_id_ctx.reset(token)
