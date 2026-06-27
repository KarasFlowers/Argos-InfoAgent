import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.core.auth import APIKeyMiddleware, _api_key_matches


def test_api_key_match_uses_constant_time_compare(monkeypatch):
    calls: list[tuple[bytes, bytes]] = []

    def fake_compare_digest(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setattr("app.core.auth.hmac.compare_digest", fake_compare_digest)

    assert _api_key_matches("secret", "secret") is True
    assert _api_key_matches("wrong", "secret") is False
    assert calls == [(b"secret", b"secret"), (b"wrong", b"secret")]


def _make_auth_app(api_key: str | None = "secret") -> FastAPI:
    app = FastAPI()
    if api_key:
        app.add_middleware(APIKeyMiddleware, api_key=api_key)

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/feed")
    async def feed():
        return {"ok": True}

    @app.get("/feed/archive")
    async def feed_archive():
        return {"ok": True}

    @app.get("/feedback")
    async def feedback():
        return {"ok": True}

    @app.get("/static/app.js")
    async def static_asset():
        return {"ok": True}

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    @app.get("/api/v1/feed")
    async def api_feed():
        return {"ok": True}

    @app.get("/api/v1/private")
    async def private():
        return {"ok": True}

    @app.options("/api/v1/private")
    async def private_options():
        return {"ok": True}

    @app.get("/api/v1/admin/tasks")
    async def admin_tasks():
        return {"ok": True}

    @app.post("/api/v1/rag/ingest")
    async def rag_ingest():
        return {"ok": True}

    @app.get("/api/v1/boards")
    async def boards():
        return {"ok": True}

    return app


def _make_auth_cors_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://ui.example"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(APIKeyMiddleware, api_key="secret")

    @app.get("/api/v1/private")
    async def private():
        return {"ok": True}

    return app


@pytest.mark.anyio
async def test_api_key_disabled_allows_private_route():
    transport = ASGITransport(app=_make_auth_app(api_key=None))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/private")

    assert response.status_code == 200


@pytest.mark.anyio
async def test_api_key_required_for_private_route():
    transport = ASGITransport(app=_make_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/v1/private")
        wrong = await client.get("/api/v1/private", headers={"X-API-Key": "wrong"})
        correct = await client.get("/api/v1/private", headers={"X-API-Key": "secret"})

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert correct.status_code == 200


@pytest.mark.anyio
async def test_public_paths_bypass_api_key():
    transport = ASGITransport(app=_make_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.get("/"),
            await client.get("/feed"),
            await client.get("/feed/archive"),
            await client.get("/static/app.js"),
            await client.get("/api/v1/ping"),
        ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200, 200]


@pytest.mark.anyio
async def test_root_public_rule_does_not_make_every_route_public():
    transport = ASGITransport(app=_make_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/private")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_feed_public_rule_does_not_match_similar_private_paths():
    transport = ASGITransport(app=_make_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/feedback")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_sensitive_surfaces_require_api_key():
    transport = ASGITransport(app=_make_auth_app())
    paths = [
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
        ("GET", "/api/v1/feed"),
        ("GET", "/api/v1/admin/tasks"),
        ("POST", "/api/v1/rag/ingest"),
        ("GET", "/api/v1/boards"),
    ]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for method, path in paths:
            missing = await client.request(method, path)
            wrong = await client.request(method, path, headers={"X-API-Key": "wrong"})
            correct = await client.request(method, path, headers={"X-API-Key": "secret"})

            assert missing.status_code == 403, path
            assert wrong.status_code == 403, path
            assert correct.status_code == 200, path


@pytest.mark.anyio
async def test_cors_preflight_is_not_blocked_by_api_key():
    transport = ASGITransport(app=_make_auth_cors_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        preflight = await client.options(
            "/api/v1/private",
            headers={
                "Origin": "https://ui.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        private_without_key = await client.get("/api/v1/private")

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://ui.example"
    assert private_without_key.status_code == 403


@pytest.mark.anyio
async def test_non_cors_options_request_still_requires_api_key():
    transport = ASGITransport(app=_make_auth_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.options("/api/v1/private")
        correct = await client.options("/api/v1/private", headers={"X-API-Key": "secret"})

    assert missing.status_code == 403
    assert correct.status_code == 200
