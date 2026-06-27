from __future__ import annotations

import html as html_mod
import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_WINDOWS_IDLE_INFO = None


def _sanitize_filename(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[^\w\-.]+", "_", value, flags=re.UNICODE)
    value = value.strip("._")
    return value or "report"


def get_idle_seconds() -> int | None:
    """Return idle seconds on Windows, or None when unavailable."""
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    last_input = LASTINPUTINFO()
    last_input.cbSize = ctypes.sizeof(LASTINPUTINFO)

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.GetLastInputInfo(ctypes.byref(last_input)):
        return None

    tick_count = getattr(kernel32, "GetTickCount64", None)
    if tick_count is None:
        now_ms = kernel32.GetTickCount()
    else:
        now_ms = int(tick_count())
    return max(0, int((now_ms - last_input.dwTime) / 1000))


def is_idle_enough(idle_seconds: int | None, threshold_seconds: int) -> bool:
    if idle_seconds is None:
        return False
    return idle_seconds >= max(0, int(threshold_seconds))


def _escape_markdown(value: str) -> str:
    return html_mod.escape((value or "").strip(), quote=False)


def _yaml_scalar(value: Any) -> str:
    text = str(value or "")
    return json.dumps(text, ensure_ascii=False)


def _yaml_list_field(name: str, values: list[Any]) -> list[str]:
    if not values:
        return [f"{name}: []"]
    return [f"{name}:", *[f"- {_yaml_scalar(value)}" for value in values]]


def _summary_article_count(summary) -> int:
    return len(summary.top_news or []) + len(summary.catchup_news or [])


def _summary_sources(summary) -> list[str]:
    sources = set()
    if summary.source_stats:
        sources.update(str(name) for name in summary.source_stats.keys() if name)
    for item in [*(summary.top_news or []), *(summary.catchup_news or [])]:
        source = getattr(item, "source", "") or ""
        if source:
            sources.add(str(source))
    return sorted(sources)


def _format_summary_item(item) -> str:
    points = item.key_points if isinstance(item.key_points, list) else []
    tags = item.tags if isinstance(item.tags, list) else []
    lines = [f"- [{_escape_markdown(item.headline)}]({item.original_link})"]
    if item.source:
        lines.append(f"  - 来源: {_escape_markdown(item.source)}")
    if item.category:
        lines.append(f"  - 分类: {_escape_markdown(item.category)}")
    if tags:
        lines.append(f"  - 标签: {', '.join(_escape_markdown(str(tag)) for tag in tags)}")
    for point in points[:5]:
        lines.append(f"  - {_escape_markdown(str(point))}")
    return "\n".join(lines)


def render_summary_markdown(summary, board, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(UTC)
    generated_iso = generated_at.astimezone().isoformat(timespec="seconds")
    sources = _summary_sources(summary)
    lines: list[str] = [
        "---",
        f"date: {_yaml_scalar(summary.date)}",
        f"board: {_yaml_scalar(board.slug)}",
        f"board_name: {_yaml_scalar(board.name)}",
        f"perspective: {_yaml_scalar(summary.perspective or 'overview')}",
        f"generated_at: {_yaml_scalar(generated_iso)}",
        f"article_count: {_summary_article_count(summary)}",
        *_yaml_list_field("sources", sources),
        *_yaml_list_field("tags", ["argos", "silent-mode"]),
        "---",
        "",
        f"# {board.name} · {summary.date}",
        "",
        f"- 生成时间: {generated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 板块: {_escape_markdown(board.slug)}",
        f"- 视角: {_escape_markdown(summary.perspective or 'overview')}",
        f"- 文章数: {_summary_article_count(summary)}",
        "",
        "## 概览",
        summary.overview.strip() or "无概览内容。",
        "",
    ]

    if summary.source_stats:
        lines += ["## 来源统计"]
        for name, count in sorted(summary.source_stats.items(), key=lambda pair: (-pair[1], pair[0])):
            lines.append(f"- {_escape_markdown(str(name))}: {count}")
        lines.append("")

    if summary.events:
        lines += ["## 事件聚合"]
        for event in summary.events[:20]:
            title = _escape_markdown(str(event.get("title") or "未命名事件"))
            lines.append(f"- {title}")
            if event.get("summary"):
                lines.append(f"  - {str(event.get('summary')).strip()}")
            sources = event.get("sources") or []
            if sources:
                lines.append(f"  - 来源: {', '.join(_escape_markdown(str(src)) for src in sources)}")
        lines.append("")

    if summary.top_news:
        lines += ["## 今日重点"]
        for item in summary.top_news:
            lines.append(_format_summary_item(item))
        lines.append("")

    if summary.catchup_news:
        lines += ["## 补读"]
        for item in summary.catchup_news:
            lines.append(_format_summary_item(item))
        lines.append("")

    if summary.recommendation_report:
        lines += ["## 推荐报告"]
        for key, value in summary.recommendation_report.items():
            lines.append(f"- {_escape_markdown(str(key))}: {_escape_markdown(str(value))}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_silent_mode_path(board_slug: str, date_str: str, perspective: str = "overview") -> Path:
    slug = _sanitize_filename(board_slug)
    perspective_slug = _sanitize_filename(perspective or "overview")
    return Path(settings.SILENT_MODE_OUTPUT_DIR) / f"{date_str}_{slug}_{perspective_slug}.md"


def export_summary_markdown(
    summary,
    board,
    output_dir: str | Path | None = None,
    generated_at: datetime | None = None,
) -> Path:
    output_root = Path(output_dir or settings.SILENT_MODE_OUTPUT_DIR)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / build_silent_mode_path(board.slug, summary.date, summary.perspective).name
    target.write_text(render_summary_markdown(summary, board, generated_at=generated_at), encoding="utf-8")
    return target


def get_manifest_path(output_dir: str | Path | None = None) -> Path:
    return Path(output_dir or settings.SILENT_MODE_OUTPUT_DIR) / "manifest.jsonl"


def append_manifest_entry(entry: dict[str, Any], output_dir: str | Path | None = None) -> Path:
    output_root = Path(output_dir or settings.SILENT_MODE_OUTPUT_DIR)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = get_manifest_path(output_root)
    with manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str))
        handle.write("\n")
    return manifest_path


def read_manifest_entries(limit: int = 20, output_dir: str | Path | None = None) -> list[dict[str, Any]]:
    manifest_path = get_manifest_path(output_dir)
    if not manifest_path.exists():
        return []

    entries: deque[dict[str, Any]] = deque(maxlen=max(1, limit))
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid silent mode manifest line: %s", line[:120])
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    return list(entries)


def get_latest_manifest_entry(output_dir: str | Path | None = None) -> dict[str, Any] | None:
    entries = read_manifest_entries(limit=1, output_dir=output_dir)
    return entries[-1] if entries else None


@dataclass
class SilentRunResult:
    board: str
    date: str
    exported_path: str | None
    status: str
    reason: str | None = None


async def run_silent_collection(
    session,
    *,
    force: bool = False,
    board_slugs: list[str] | None = None,
) -> dict[str, Any]:
    from app.services.db_service import db_service
    from app.services.source_adapters import UnknownSourceTypeError, get_adapter

    if not settings.SILENT_MODE_ENABLED and not force:
        result = {
            "ok": False,
            "reason": "silent_mode_disabled",
            "generated_at": datetime.now(UTC).isoformat(),
            "results": [],
        }
        append_manifest_entry(result)
        return result

    idle_seconds = get_idle_seconds()
    if not force and not is_idle_enough(idle_seconds, settings.SILENT_MODE_IDLE_SECONDS):
        result = {
            "ok": False,
            "reason": "pc_not_idle_enough",
            "generated_at": datetime.now(UTC).isoformat(),
            "idle_seconds": idle_seconds,
            "results": [],
        }
        append_manifest_entry(result)
        return result

    boards = await db_service.list_boards(session, active_only=True)
    if board_slugs or settings.SILENT_MODE_BOARD_SLUGS:
        wanted = {slug for slug in (board_slugs or settings.SILENT_MODE_BOARD_SLUGS) if slug}
        boards = [board for board in boards if board.slug in wanted]

    today = datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    for board in boards:
        summary = await db_service.get_summary_by_date(session, today, board_id=board.id)
        if not summary or settings.SILENT_MODE_OVERWRITE_TODAY:
            try:
                adapter = get_adapter(board.source_type)
            except UnknownSourceTypeError as error:
                results.append(
                    {
                        "board": board.slug,
                        "date": today,
                        "status": "skipped",
                        "reason": str(error),
                        "article_count": 0,
                    }
                )
                continue

            summary, _content_fallback = await adapter.produce(board=board, session=session)
            if summary:
                await db_service.save_summary(session, summary, board_id=board.id)

        if not summary:
            results.append(
                {
                    "board": board.slug,
                    "date": today,
                    "status": "skipped",
                    "reason": "no_summary",
                    "article_count": 0,
                }
            )
            continue

        exported_path = export_summary_markdown(summary, board, generated_at=generated_at)
        results.append(
            {
                "board": board.slug,
                "date": summary.date,
                "status": "exported",
                "exported_path": str(exported_path),
                "article_count": _summary_article_count(summary),
                "event_count": len(summary.events or []),
                "source_count": len(_summary_sources(summary)),
            }
        )

    result = {
        "ok": True,
        "generated_at": generated_at.isoformat(),
        "idle_seconds": idle_seconds,
        "manifest_path": str(get_manifest_path()),
        "results": results,
    }
    append_manifest_entry(result)
    return result
