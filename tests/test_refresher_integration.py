"""Unit tests for the non-vendored SmartThings Refresher custom component."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from pysmartthings import SmartThings

from custom_components.smartthings_refresher import async_setup_entry, async_unload_entry
from custom_components.smartthings_refresher.config_flow import SmartThingsRefresherConfigFlow
from custom_components.smartthings_refresher.const import (
    CONF_ROTATOR_URL,
)


@pytest.mark.asyncio
async def test_config_flow_form_display() -> None:
    """Test initial config flow form display."""
    flow = SmartThingsRefresherConfigFlow()
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_config_flow_success(aiohttp_client) -> None:
    """Test successful config flow verifying rotator and SmartThings API."""

    async def handle_rotator_token(request: web.Request) -> web.Response:
        return web.Response(text="test-rotator-pat-token-1234567890abcdef")

    async def handle_locations(request: web.Request) -> web.Response:
        return web.json_response({"items": [{"name": "My Lake House"}]})

    app = web.Application()
    app.router.add_get("/token", handle_rotator_token)
    app.router.add_get("/v1/locations", handle_locations)
    client = await aiohttp_client(app)

    flow = SmartThingsRefresherConfigFlow()
    flow.hass = MagicMock()

    rotator_url = str(client.make_url(""))
    locations_url = str(client.make_url("/v1/locations"))

    with (
        patch(
            "custom_components.smartthings_refresher.config_flow.async_get_clientsession",
            return_value=client.session,
        ),
        patch(
            "custom_components.smartthings_refresher.config_flow.SMARTTHINGS_LOCATIONS_API",
            locations_url,
            create=True,
        ),
    ):
        result = await flow.async_step_user({CONF_ROTATOR_URL: rotator_url})
        assert result["type"] == "create_entry"
        assert "My Lake House" in result["title"]
        assert result["data"][CONF_ROTATOR_URL] == rotator_url.rstrip("/")


@pytest.mark.asyncio
async def test_config_flow_cannot_connect(aiohttp_client) -> None:
    """Test config flow when rotator server returns 500 or is unavailable."""

    async def handle_error(request: web.Request) -> web.Response:
        return web.Response(status=500, text="Internal Error")

    app = web.Application()
    app.router.add_get("/token", handle_error)
    client = await aiohttp_client(app)

    flow = SmartThingsRefresherConfigFlow()
    flow.hass = MagicMock()
    rotator_url = str(client.make_url(""))

    with patch(
        "custom_components.smartthings_refresher.config_flow.async_get_clientsession",
        return_value=client.session,
    ):
        result = await flow.async_step_user({CONF_ROTATOR_URL: rotator_url})
        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_async_setup_and_unload_entry(aiohttp_client) -> None:
    """Test entry setup initializing client and runtime_data."""

    async def handle_token(request: web.Request) -> web.Response:
        return web.Response(text="live-pat-from-rotator-container-999")

    rot_app = web.Application()
    rot_app.router.add_get("/token", handle_token)
    rot_client = await aiohttp_client(rot_app)
    rot_url = str(rot_client.make_url(""))

    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    entry = MagicMock()
    entry.data = {CONF_ROTATOR_URL: rot_url}
    entry.options = {}
    entry.entry_id = "test_entry_id"

    # Mock SmartThings client calls
    mock_st_client = MagicMock(spec=SmartThings)
    mock_location = MagicMock()
    mock_location.location_id = "loc_001"
    mock_st_client.get_locations = AsyncMock(return_value=[mock_location])
    mock_st_client.get_rooms = AsyncMock(return_value=[])
    mock_st_client.get_devices = AsyncMock(return_value=[])
    mock_st_client.get_scenes = AsyncMock(return_value=[])

    with (
        patch("custom_components.smartthings_refresher.SmartThings", return_value=mock_st_client),
        patch(
            "custom_components.smartthings_refresher.async_get_clientsession",
            return_value=rot_client.session,
        ),
    ):
        success = await async_setup_entry(hass, entry)
        assert success is True
        assert entry.runtime_data is not None
        assert entry.runtime_data.client == mock_st_client
        mock_st_client.authenticate.assert_called_with("live-pat-from-rotator-container-999")
        assert callable(mock_st_client.refresh_token_function)

        # Test unload
        unload_success = await async_unload_entry(hass, entry)
        assert unload_success is True
