"""Tests for SmartThings Plus config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.smartthings_plus.api import SmartThingsAuthError
from custom_components.smartthings_plus.config_flow import SmartThingsPlusConfigFlow
from custom_components.smartthings_plus.const import (
    CONF_ACCESS_TOKEN,
    CONF_ROTATOR_URL,
    DEFAULT_ROTATOR_URL,
)
from tests.conftest import MOCK_ACCESS_TOKEN


@pytest.mark.asyncio
async def test_config_flow_user_form() -> None:
    """Test initial user step displays the rotator URL input form."""
    flow = SmartThingsPlusConfigFlow()
    flow.hass = MagicMock()

    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_config_flow_success() -> None:
    """Test successful connection creates config entry."""
    flow = SmartThingsPlusConfigFlow()
    flow.hass = MagicMock()

    with patch(
        "custom_components.smartthings_plus.config_flow.SmartThingsApiClient"
    ) as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.async_fetch_token_from_rotator = AsyncMock(
            return_value={"token": MOCK_ACCESS_TOKEN}
        )
        mock_instance.access_token = MOCK_ACCESS_TOKEN
        mock_instance.async_get_devices = AsyncMock(return_value=[])
        mock_client_cls.return_value = mock_instance

        result = await flow.async_step_user(
            {CONF_ROTATOR_URL: DEFAULT_ROTATOR_URL}
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "SmartThings Plus"
        assert result["data"][CONF_ROTATOR_URL] == DEFAULT_ROTATOR_URL
        assert result["data"][CONF_ACCESS_TOKEN] == MOCK_ACCESS_TOKEN


@pytest.mark.asyncio
async def test_config_flow_no_token() -> None:
    """Test rotator reachable but no active token displays no_token error."""
    flow = SmartThingsPlusConfigFlow()
    flow.hass = MagicMock()

    with patch(
        "custom_components.smartthings_plus.config_flow.SmartThingsApiClient"
    ) as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.async_fetch_token_from_rotator = AsyncMock(
            side_effect=SmartThingsAuthError("no active token")
        )
        mock_client_cls.return_value = mock_instance

        result = await flow.async_step_user(
            {CONF_ROTATOR_URL: DEFAULT_ROTATOR_URL}
        )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "no_token"


@pytest.mark.asyncio
async def test_config_flow_cannot_connect() -> None:
    """Test connection failure displays cannot_connect error."""
    flow = SmartThingsPlusConfigFlow()
    flow.hass = MagicMock()

    with patch(
        "custom_components.smartthings_plus.config_flow.SmartThingsApiClient"
    ) as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.async_fetch_token_from_rotator = AsyncMock(
            side_effect=SmartThingsAuthError("Connection refused")
        )
        mock_client_cls.return_value = mock_instance

        result = await flow.async_step_user(
            {CONF_ROTATOR_URL: "http://non-existent-host:8765"}
        )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"
