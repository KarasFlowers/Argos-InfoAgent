"""
Track background asyncio tasks so they can be cancelled gracefully on shutdown.

Usage:
    from app.core.background import register_background_task
    register_background_task(asyncio.create_task(some_coro()))
"""

from __future__ import annotations

import asyncio

_background_tasks: set[asyncio.Task] = set()


def register_background_task(task: asyncio.Task) -> None:
    """Register a fire-and-forget task for shutdown tracking.

    The task is automatically removed from the set when it completes.
    """
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def cancel_all_background_tasks() -> None:
    """Cancel all registered background tasks and wait for them to finish."""
    for task in list(_background_tasks):
        if not task.done():
            task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
