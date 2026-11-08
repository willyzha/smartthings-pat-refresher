"""Tests for SmartThingsApiClient."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.smartthings_plus.api import (
    SmartThingsApiClient,
    SmartThingsAuthError,
)
from tests.conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_NEW_ACCESS_TOKEN,
    MockAiohttpResponse,
)

MOCK_ROTATOR_URL = "http://smartthings-pat-rotator:8765"


@pytest.mark.asyncio
async def test_async_fetch_token_from_rotator_success(mock_session: MagicMock) -> None:
    """Test fetching active token from the rotator server."""
    mock_payload = {
        "token": MOCK_ACCESS_TOKEN,
        "expires_at": time.time() + 86400,
    }
    mock_session.get.return_value = MockAiohttpResponse(status=200, json_data=mock_payload)

    client = SmartThingsApiClient(
        session=mock_session,
        rotator_url=MOCK_ROTATOR_URL,
    )

    result = await client.async_fetch_token_from_rotator()

    assert result["token"] == MOCK_ACCESS_TOKEN
    assert client.access_token == MOCK_ACCESS_TOKEN
    assert client.expires_at > time.time()


@pytest.mark.asyncio
async def test_async_fetch_token_from_rotator_404(mock_session: MagicMock) -> None:
    """Test rotator returning 404 raises SmartThingsAuthError."""
    mock_session.get.return_value = MockAiohttpResponse(status=404, text_data="No token available")

    client = SmartThingsApiClient(
        session=mock_session,
        rotator_url=MOCK_ROTATOR_URL,
    )

    with pytest.raises(SmartThingsAuthError) as exc_info:
        await client.async_fetch_token_from_rotator()
    assert "no active token" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_async_ensure_token_valid(mock_session: MagicMock) -> None:
    """Test proactive token refresh triggered when expiry is within leeway."""
    mock_payload = {
        "token": MOCK_NEW_ACCESS_TOKEN,
        "expires_at": time.time() + 86400,
    }
    mock_session.get.return_value = MockAiohttpResponse(status=200, json_data=mock_payload)

    # Token expires in 1 hour (within the 2-hour leeway)
    client = SmartThingsApiClient(
        session=mock_session,
        rotator_url=MOCK_ROTATOR_URL,
        access_token=MOCK_ACCESS_TOKEN,
        expires_at=time.time() + 3600,
    )

    await client.async_ensure_token_valid()

    assert client.access_token == MOCK_NEW_ACCESS_TOKEN
    assert mock_session.get.called


@pytest.mark.asyncio
async def test_async_get_devices_and_status(mock_session: MagicMock) -> None:
    """Test fetching device list and status."""
    client = SmartThingsApiClient(
        session=mock_session,
        rotator_url=MOCK_ROTATOR_URL,
        access_token=MOCK_ACCESS_TOKEN,
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
        rotator_url=MOCK_ROTATOR_URL,
        access_token=MOCK_ACCESS_TOKEN,
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


@pytest.mark.asyncio
async def test_401_retry_logic(mock_session: MagicMock) -> None:
    """Test that a 401 response triggers token refetch and retries once."""
    client = SmartThingsApiClient(
        session=mock_session,
        rotator_url=MOCK_ROTATOR_URL,
        access_token=MOCK_ACCESS_TOKEN,
        expires_at=time.time() + 50000,
    )

    client.async_fetch_token_from_rotator = AsyncMock(return_value={"token": MOCK_NEW_ACCESS_TOKEN})

    resp_401 = MockAiohttpResponse(status=401, text_data="Unauthorized")
    resp_200 = MockAiohttpResponse(status=200, json_data={"items": []})
    mock_session.request.side_effect = [resp_401, resp_200]

    devices = await client.async_get_devices()
    assert devices == []
    assert client.async_fetch_token_from_rotator.called
