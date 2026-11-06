"""Tests for SmartThings Plus config flow."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.smartthings_plus.config_flow import SmartThingsPlusConfigFlow
from custom_components.smartthings_plus.const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_CODE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REDIRECT_URI,
    CONF_REFRESH_TOKEN,
    DEFAULT_REDIRECT_URI,
)
from tests.conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_CLIENT_ID,
    MOCK_CLIENT_SECRET,
    MOCK_REFRESH_TOKEN,
)


def test_extract_code_variations() -> None:
    """Test extracting authorization code from pure code or full redirect URLs."""
    # Plain code
    assert SmartThingsPlusConfigFlow._extract_code("my_secret_code_123") == "my_secret_code_123"

    # Full localhost redirect URL
    url = "https://localhost/?code=auth_code_xyz&state=smartthings_plus"
    assert SmartThingsPlusConfigFlow._extract_code(url) == "auth_code_xyz"

    # URL with additional parameters
    url2 = "http://192.168.1.100:8123/auth/external/callback?code=code_abc999&scope=r:devices:*"
    assert SmartThingsPlusConfigFlow._extract_code(url2) == "code_abc999"


@pytest.mark.asyncio
async def test_config_flow_full_step_flow() -> None:
    """Test full interactive config flow from Step 1 to entry creation."""
    flow = SmartThingsPlusConfigFlow()
    flow.hass = MagicMock()

    # Step 1: User enters Client ID & Secret
    result = await flow.async_step_user(
        {
            CONF_CLIENT_ID: MOCK_CLIENT_ID,
            CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
            CONF_REDIRECT_URI: DEFAULT_REDIRECT_URI,
        }
    )
    assert result["type"] == "form"
    assert result["step_id"] == "auth_code"

    # Step 2: User pastes redirect URL / code
    with patch(
        "custom_components.smartthings_plus.config_flow.SmartThingsApiClient"
    ) as mock_client_cls:
        mock_instance = MagicMock()
        mock_instance.async_exchange_auth_code = AsyncMock(
            return_value={
                "access_token": MOCK_ACCESS_TOKEN,
                "refresh_token": MOCK_REFRESH_TOKEN,
            }
        )
        mock_instance.expires_at = time.time() + 86400
        mock_instance.async_get_devices = AsyncMock(return_value=[])
        mock_client_cls.return_value = mock_instance

        result2 = await flow.async_step_auth_code(
            {CONF_AUTH_CODE: "https://localhost/?code=my_auth_code"}
        )

        assert result2["type"] == "create_entry"
        assert result2["title"] == "SmartThings Plus"
        data = result2["data"]
        assert data[CONF_CLIENT_ID] == MOCK_CLIENT_ID
        assert data[CONF_CLIENT_SECRET] == MOCK_CLIENT_SECRET
        assert data[CONF_ACCESS_TOKEN] == MOCK_ACCESS_TOKEN
        assert data[CONF_REFRESH_TOKEN] == MOCK_REFRESH_TOKEN
