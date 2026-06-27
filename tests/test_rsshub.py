"""Unit tests for the RSSHub route catalog (pure data + functions)."""

from unittest.mock import patch

from app.services import rsshub


class TestBuildRsshubUrl:
    def test_builds_known_route(self):
        with patch("app.services.rsshub._base_url", return_value="https://rsshub.app"):
            url = rsshub.build_rsshub_url("bilibili_user_video", uid="2267573")
        assert url == "https://rsshub.app/bilibili/user/video/2267573"

    def test_unknown_platform_returns_none(self):
        assert rsshub.build_rsshub_url("nonexistent", id="x") is None

    def test_missing_required_param_returns_none(self):
        assert rsshub.build_rsshub_url("zhihu_people") is None

    def test_empty_param_returns_none(self):
        assert rsshub.build_rsshub_url("zhihu_people", id="   ") is None

    def test_strips_whitespace_in_param(self):
        with patch("app.services.rsshub._base_url", return_value="https://rsshub.app"):
            url = rsshub.build_rsshub_url("jike_user", id="  ABCD  ")
        assert url == "https://rsshub.app/jike/user/ABCD"

    def test_respects_custom_base_url(self):
        with patch("app.services.rsshub._base_url", return_value="https://my.rsshub.io"):
            url = rsshub.build_rsshub_url("weibo_user", uid="123")
        assert url == "https://my.rsshub.io/weibo/user/123"


class TestListRoutes:
    def test_returns_all_routes_with_shape(self):
        routes = rsshub.list_routes()
        assert len(routes) == len(rsshub.ROUTES)
        for r in routes:
            assert set(r.keys()) == {"platform", "label", "params", "example"}
            assert isinstance(r["params"], list)

    def test_every_route_template_is_buildable(self):
        # Each catalog route, given dummy values for its params, must produce a URL.
        with patch("app.services.rsshub._base_url", return_value="https://rsshub.app"):
            for entry in rsshub.list_routes():
                params = {p: "x" for p in entry["params"]}
                assert rsshub.build_rsshub_url(entry["platform"], **params) is not None


class TestBaseUrl:
    def test_strips_trailing_slash(self):
        from types import SimpleNamespace

        fake_settings = SimpleNamespace(RSSHUB_BASE_URL="https://rsshub.app/")
        with patch("app.services.rsshub.settings", fake_settings, create=True):
            assert rsshub._base_url() == "https://rsshub.app"

    def test_falls_back_to_default_when_unset(self):
        from types import SimpleNamespace

        fake_settings = SimpleNamespace(RSSHUB_BASE_URL=None)
        with patch("app.services.rsshub.settings", fake_settings, create=True):
            assert rsshub._base_url() == rsshub.DEFAULT_BASE_URL
