"""Unit tests for SmartThings REST client and rotation engine."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from rotator.browser import SmartThingsBrowserRotator
from rotator.rest import (
    RestAuthExpiredError,
    SmartThingsRestClient,
    extract_cookies_and_xsrf,
)
from rotator.storage import TokenStorage


def test_extract_cookies_and_xsrf_header_format() -> None:
    """Test extracting cookies and XSRF from Cookie header string."""
    raw = "XSRF-TOKEN=test-xsrf-123; JSESSIONID=sess-456; _JTKN=token-789"
    header, xsrf = extract_cookies_and_xsrf(raw)
    assert xsrf == "test-xsrf-123"
    assert "XSRF-TOKEN=test-xsrf-123" in header
    assert "JSESSIONID=sess-456" in header


def test_extract_cookies_and_xsrf_json_format() -> None:
    """Test extracting cookies and XSRF from Cookie-Editor JSON format."""
    raw = json.dumps([
        {"name": "XSRF-TOKEN", "value": "json-xsrf-abc"},
        {"name": "session", "value": "val-def"},
    ])
    header, xsrf = extract_cookies_and_xsrf(raw)
    assert xsrf == "json-xsrf-abc"
    assert "XSRF-TOKEN=json-xsrf-abc" in header
    assert "session=val-def" in header


def test_extract_cookies_from_file(tmp_path) -> None:
    """Test reading cookies from a file path."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("XSRF-TOKEN=from-file; test=123", encoding="utf-8")
    header, xsrf = extract_cookies_and_xsrf(str(cookie_file))
    assert xsrf == "from-file"
    assert "test=123" in header


@pytest.mark.asyncio
async def test_rest_create_and_rotate(aiohttp_client, tmp_path) -> None:
    """Test creating and rotating token via simulated SmartThings account API."""
    created_tokens = []
    deleted_keys = []

    async def handle_tokens(request: web.Request) -> web.Response:
        if request.headers.get("X-XSRF-TOKEN") != "valid-xsrf":
            return web.Response(status=403, text="Forbidden")

        if request.method == "POST":
            data = await request.json()
            created_tokens.append(data)
            return web.json_response(
                {
                    "accessToken": "new-access-token-9999",
                    "sanitizedToken": {
                        "authKey": "new-auth-key-8888",
                        "deviceName": data["deviceName"],
                    },
                },
                status=201,
            )
        elif request.method == "GET":
            return web.json_response([
                {"deviceName": "HA_AutoPAT_old", "authKey": "old-auth-key-1111"},
                {"deviceName": "HomeAssistant_Permanent", "authKey": "perm-auth-key"},
            ])
        return web.Response(status=405)

    async def handle_delete(request: web.Request) -> web.Response:
        auth_key = request.match_info["authKey"]
        deleted_keys.append(auth_key)
        return web.Response(status=204)

    app = web.Application()
    app.router.add_route("*", "/api/tokens", handle_tokens)
    app.router.add_delete("/api/tokens/{authKey}", handle_delete)

    client = await aiohttp_client(app)
    api_url = f"{client.make_url('/api/tokens')}"

    storage = TokenStorage(
        token_file=tmp_path / "smartthings_pat.txt",
        metadata_file=tmp_path / "pat_metadata.json",
    )
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("XSRF-TOKEN=valid-xsrf; user=123\n")

    rest_client = SmartThingsRestClient(storage=storage, cookies_file=cookies_file)

    with patch("rotator.rest.SMARTTHINGS_ACCOUNT_API", api_url):
        token = await rest_client.async_rotate(token_name="HA_AutoPAT_new")
        assert token == "new-access-token-9999"
        assert storage.get_token() == "new-access-token-9999"
        # Old auto-generated token should be cleaned up
        assert "old-auth-key-1111" in deleted_keys
        # Permanent user token should NOT be cleaned up
        assert "perm-auth-key" not in deleted_keys


@pytest.mark.asyncio
async def test_rest_expired_auth(aiohttp_client, tmp_path) -> None:
    """Test handling of 401/403 session expiration."""
    async def handle_forbidden(request: web.Request) -> web.Response:
        return web.Response(status=401, text="Unauthorized")

    app = web.Application()
    app.router.add_route("*", "/api/tokens", handle_forbidden)

    client = await aiohttp_client(app)
    api_url = f"{client.make_url('/api/tokens')}"

    storage = TokenStorage(
        token_file=tmp_path / "smartthings_pat.txt",
        metadata_file=tmp_path / "pat_metadata.json",
    )
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("XSRF-TOKEN=expired; user=123\n")

    rest_client = SmartThingsRestClient(storage=storage, cookies_file=cookies_file)

    with patch("rotator.rest.SMARTTHINGS_ACCOUNT_API", api_url):
        with pytest.raises(RestAuthExpiredError):
            await rest_client.async_rotate()


@pytest.mark.asyncio
async def test_browser_rotator_prefers_rest(tmp_path) -> None:
    """Test that SmartThingsBrowserRotator uses fast REST first."""
    storage = TokenStorage(
        token_file=tmp_path / "smartthings_pat.txt",
        metadata_file=tmp_path / "pat_metadata.json",
    )
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("XSRF-TOKEN=abc; sess=123\n")

    rotator = SmartThingsBrowserRotator(
        session_dir=tmp_path / "session",
        cookies_file=cookies_file,
        storage=storage,
    )

    with patch.object(
        rotator.rest_client, "async_rotate", new_callable=AsyncMock
    ) as mock_rest:
        mock_rest.return_value = "rest-token-instant"

        token = await rotator.async_rotate()
        assert token == "rest-token-instant"
        mock_rest.assert_called_once()
