"""
test_url_safety.py - Unit tests for URL safety validation.

Tests:
  - Public URLs pass validation
  - Private/loopback IPs are blocked
  - Localhost and .local domains are blocked
  - Edge cases (IPv6, reserved ranges)
"""

import ipaddress

import httpx
import pytest

from app.core.url_safety import _get_host, _is_disallowed_ip, get_public_url, validate_public_url

# ---------------------------------------------------------------------------
# _get_host
# ---------------------------------------------------------------------------


class TestGetHost:
    def test_https_url(self):
        assert _get_host("https://example.com/path") == "example.com"

    def test_http_url(self):
        assert _get_host("http://example.com") == "example.com"

    def test_www_prefix(self):
        assert _get_host("https://www.example.com") == "www.example.com"

    def test_trailing_dot_is_normalized(self):
        assert _get_host("https://Example.COM./path") == "example.com"

    def test_ip_address(self):
        assert _get_host("http://1.2.3.4") == "1.2.3.4"

    def test_empty_string(self):
        assert _get_host("") == ""


# ---------------------------------------------------------------------------
# _is_disallowed_ip
# ---------------------------------------------------------------------------


class TestIsDisallowedIp:
    def test_loopback_ipv4(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("127.0.0.1")) is True

    def test_loopback_ipv6(self):
        assert _is_disallowed_ip(ipaddress.IPv6Address("::1")) is True

    def test_private_10(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("10.0.0.1")) is True

    def test_private_192(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("192.168.1.1")) is True

    def test_private_172(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("172.16.0.1")) is True

    def test_link_local(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("169.254.1.1")) is True

    def test_multicast(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("224.0.0.1")) is True

    def test_unspecified(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("0.0.0.0")) is True

    def test_public_ip_allowed(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("8.8.8.8")) is False

    def test_public_ip_allowed_2(self):
        assert _is_disallowed_ip(ipaddress.IPv4Address("142.250.80.46")) is False

    def test_clash_fake_ip_allowed(self):
        """198.18.0.0/15 (Clash Fake IP) should be allowed for proxy compatibility."""
        assert _is_disallowed_ip(ipaddress.IPv4Address("198.18.0.1")) is False
        assert _is_disallowed_ip(ipaddress.IPv4Address("198.19.255.255")) is False


# ---------------------------------------------------------------------------
# validate_public_url
# ---------------------------------------------------------------------------


class TestValidatePublicUrl:
    def test_valid_public_url(self):
        result = validate_public_url("https://example.com")
        assert result == "https://example.com"

    def test_valid_public_url_with_path(self):
        result = validate_public_url("https://example.com/path/to/page")
        assert result == "https://example.com/path/to/page"

    def test_localhost_blocked(self):
        with pytest.raises(ValueError, match="blocklist"):
            validate_public_url("http://localhost")

    def test_localhost_with_port_blocked(self):
        with pytest.raises(ValueError, match="blocklist"):
            validate_public_url("http://localhost:8080")

    def test_trailing_dot_localhost_blocked(self):
        with pytest.raises(ValueError, match="blocklist"):
            validate_public_url("http://localhost./admin")

    def test_dot_local_blocked(self):
        with pytest.raises(ValueError, match="blocklist"):
            validate_public_url("http://myserver.local")

    def test_trailing_dot_local_domain_blocked(self):
        with pytest.raises(ValueError, match="blocklist"):
            validate_public_url("http://myserver.local./feed")

    def test_private_ip_blocked(self):
        with pytest.raises(ValueError, match="private"):
            validate_public_url("http://192.168.1.1")

    def test_loopback_ip_blocked(self):
        with pytest.raises(ValueError, match="private"):
            validate_public_url("http://127.0.0.1")

    def test_trailing_dot_loopback_ip_blocked(self):
        with pytest.raises(ValueError, match="private"):
            validate_public_url("http://127.0.0.1./feed")

    def test_empty_host_blocked(self):
        with pytest.raises(ValueError, match="valid public URL"):
            validate_public_url("http://")


class TestGetPublicUrl:
    @pytest.mark.anyio
    async def test_redirect_to_private_host_is_blocked_before_following(self):
        calls: list[str] = []

        class RedirectClient:
            async def get(self, url: str, *, timeout: float, follow_redirects: bool):
                calls.append(url)
                assert follow_redirects is False
                return httpx.Response(
                    status_code=302,
                    headers={"location": "http://localhost/admin"},
                    request=httpx.Request("GET", url),
                )

        with pytest.raises(ValueError, match="blocklist"):
            await get_public_url(RedirectClient(), "http://93.184.216.34/feed", timeout=1.0)

        assert calls == ["http://93.184.216.34/feed"]
