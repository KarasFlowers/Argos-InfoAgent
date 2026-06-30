from types import SimpleNamespace

import pytest

from app.api.routes import silent_mode


@pytest.mark.asyncio
async def test_run_silent_mode_passes_board_slugs(monkeypatch):
    calls = []

    async def fake_run_silent_collection(session, *, force=False, board_slugs=None):
        calls.append({"session": session, "force": force, "board_slugs": board_slugs})
        return {"ok": True, "results": []}

    monkeypatch.setattr(silent_mode, "run_silent_collection", fake_run_silent_collection)

    session = SimpleNamespace()
    payload = silent_mode.SilentModeRunRequest(force=True, board_slugs=["tech"])
    result = await silent_mode.run_silent_mode(payload, session=session)

    assert result == {"ok": True, "results": []}
    assert calls == [{"session": session, "force": True, "board_slugs": ["tech"]}]
