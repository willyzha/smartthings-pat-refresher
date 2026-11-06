"""Tests for SmartThingsApiClient."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.smartthings_plus.api import (
    SmartThingsApiClient,
    SmartThingsAuthError,
)
from custom_components.smartthings_plus.const import (
    DEFAULT_REDIRECT_URI,
    SMARTTHINGS_OAUTH_AUTHORIZE_URL,
)
from tests.conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_CLIENT_ID,
    MOCK_CLIENT_SECRET,
    MOCK_NEW_ACCESS_TOKEN,
    MOCK_NEW_REFRESH_TOKEN,
    MOCK_REFRESH_TOKEN,
    MockAiohttpResponse,
)


def test_build_authorization_url() -> None:
    """Test generating OAuth authorization URL with query params."""
    url = SmartThingsApiClient.build_authorization_url(
        client_id=MOCK_CLIENT_ID,
        redirect_uri=DEFAULT_REDIRECT_URI,
    )
    assert url.startswith(SMARTTHINGS_OAUTH_AUTHORIZE_URL)
    assert f"client_id={MOCK_CLIENT_ID}" in url
    assert "response_type=code" in url
    assert "scope=" in url


@pytest.mark.asyncio
async def test_async_exchange_auth_code_success(mock_session: MagicMock) -> None:
    """Test exchanging auth code for access & refresh tokens."""
    mock_payload = {
        "access_token": MOCK_ACCESS_TOKEN,
        "refresh_token": MOCK_REFRESH_TOKEN,
        "expires_in": 86400,
    }
    mock_session.post.return_value = MockAiohttpResponse(status=200, json_data=mock_payload)

    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
    )

    result = await client.async_exchange_auth_code("code_12345", DEFAULT_REDIRECT_URI)

    assert result["access_token"] == MOCK_ACCESS_TOKEN
    assert client.access_token == MOCK_ACCESS_TOKEN
    assert client.refresh_token == MOCK_REFRESH_TOKEN
    assert client.expires_at > time.time()


@pytest.mark.asyncio
async def test_async_exchange_auth_code_failure(mock_session: MagicMock) -> None:
    """Test auth code exchange failure raises SmartThingsAuthError."""
    mock_session.post.return_value = MockAiohttpResponse(
        status=401, text_data="invalid_grant: Bad code"
    )

    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
    )

    with pytest.raises(SmartThingsAuthError) as exc_info:
        await client.async_exchange_auth_code("bad_code", DEFAULT_REDIRECT_URI)
    assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_refresh_token_rolling(mock_session: MagicMock) -> None:
    """Test rolling refresh token renewal updates both access and refresh tokens."""
    mock_payload = {
        "access_token": MOCK_NEW_ACCESS_TOKEN,
        "refresh_token": MOCK_NEW_REFRESH_TOKEN,
        "expires_in": 86400,
    }
    mock_session.post.return_value = MockAiohttpResponse(status=200, json_data=mock_payload)

    callback_mock = AsyncMock()

    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
        access_token=MOCK_ACCESS_TOKEN,
        refresh_token=MOCK_REFRESH_TOKEN,
        expires_at=time.time() + 100,
        on_token_refreshed=callback_mock,
    )

    await client.async_refresh_token()

    # Verify both access token and new rolling refresh token are stored
    assert client.access_token == MOCK_NEW_ACCESS_TOKEN
    assert client.refresh_token == MOCK_NEW_REFRESH_TOKEN
    assert callback_mock.called


@pytest.mark.asyncio
async def test_async_ensure_token_valid(mock_session: MagicMock) -> None:
    """Test proactive token refresh triggered when expiry is within leeway."""
    mock_payload = {
        "access_token": MOCK_NEW_ACCESS_TOKEN,
        "refresh_token": MOCK_NEW_REFRESH_TOKEN,
        "expires_in": 86400,
    }
    mock_session.post.return_value = MockAiohttpResponse(status=200, json_data=mock_payload)

    # Token expires in 1 hour (within the 2-hour leeway)
    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
        access_token=MOCK_ACCESS_TOKEN,
        refresh_token=MOCK_REFRESH_TOKEN,
        expires_at=time.time() + 3600,
    )

    await client.async_ensure_token_valid()

    assert client.access_token == MOCK_NEW_ACCESS_TOKEN
    assert mock_session.post.called


@pytest.mark.asyncio
async def test_async_get_devices_and_status(mock_session: MagicMock) -> None:
    """Test fetching device list and status."""
    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
        access_token=MOCK_ACCESS_TOKEN,
        refresh_token=MOCK_REFRESH_TOKEN,
        expires_at=time.time() + 50000,
    )

    # Mock devices list call
    mock_session.request.return_value = MockAiohttpResponse(
        status=200,
        json_data={"items": [{"deviceId": "dev1", "name": "Switch 1"}]},
    )
    devices = await client.async_get_devices()
    assert len(devices) == 1
    assert devices[0]["deviceId"] == "dev1"

    # Mock device status call
    mock_session.request.return_value = MockAiohttpResponse(
        status=200,
        json_data={"components": {"main": {"switch": {"switch": {"value": "on"}}}}},
    )
    status = await client.async_get_device_status("dev1")
    assert status["main"]["switch"]["switch"]["value"] == "on"


@pytest.mark.asyncio
async def test_async_execute_device_command(mock_session: MagicMock) -> None:
    """Test sending command payload to SmartThings API."""
    client = SmartThingsApiClient(
        session=mock_session,
        client_id=MOCK_CLIENT_ID,
        client_secret=MOCK_CLIENT_SECRET,
        access_token=MOCK_ACCESS_TOKEN,
        refresh_token=MOCK_REFRESH_TOKEN,
        expires_at=time.time() + 50000,
    )

    mock_session.request.return_value = MockAiohttpResponse(
        status=200,
        json_data={"results": [{"status": "COMPLETED"}]},
    )

    res = await client.async_execute_device_command(
        device_id="dev1",
        capability="switch",
        command="on",
    )
    assert res["results"][0]["status"] == "COMPLETED"
    mock_session.request.assert_called_with(
        "POST",
        "https://api.smartthings.com/v1/devices/dev1/commands",
        headers={
            "Authorization": f"Bearer {MOCK_ACCESS_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "commands": [
                {
                    "component": "main",
                    "capability": "switch",
                    "command": "on",
                    "arguments": [],
                }
            ]
        },
        params=None,
    )
