"""Tests for SmartThingsDataUpdateCoordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.smartthings_plus.api import SmartThingsApiClient, SmartThingsApiError
from custom_components.smartthings_plus.coordinator import (
    SmartThingsDataUpdateCoordinator,
    UpdateFailed,
)
from tests.conftest import (
    MOCK_DEVICE_ID_SWITCH,
    MOCK_DEVICE_STATUSES,
    MOCK_DEVICES_LIST,
)


@pytest.mark.asyncio
async def test_coordinator_fetch_all_devices_and_status() -> None:
    """Test coordinator concurrently fetches all devices and statuses."""
    client = MagicMock(spec=SmartThingsApiClient)
    client.async_ensure_token_valid = AsyncMock()
    client.async_get_devices = AsyncMock(return_value=MOCK_DEVICES_LIST)

    async def mock_get_status(dev_id: str):
        return MOCK_DEVICE_STATUSES.get(dev_id, {})

    client.async_get_device_status = AsyncMock(side_effect=mock_get_status)

    coordinator = SmartThingsDataUpdateCoordinator(
        hass=MagicMock(),
        client=client,
        update_interval=timedelta(seconds=30),
    )

    data = await coordinator._async_update_data()

    assert client.async_ensure_token_valid.called
    assert len(data) == len(MOCK_DEVICES_LIST)
    assert MOCK_DEVICE_ID_SWITCH in data
    assert data[MOCK_DEVICE_ID_SWITCH]["status"]["main"]["switch"]["switch"]["value"] == "on"


@pytest.mark.asyncio
async def test_coordinator_handles_api_failure() -> None:
    """Test coordinator translates API errors to UpdateFailed."""
    client = MagicMock(spec=SmartThingsApiClient)
    client.async_ensure_token_valid = AsyncMock()
    client.async_get_devices = AsyncMock(side_effect=SmartThingsApiError("SmartThings cloud down"))

    coordinator = SmartThingsDataUpdateCoordinator(
        hass=MagicMock(),
        client=client,
        update_interval=timedelta(seconds=30),
    )

    with pytest.raises(UpdateFailed) as exc_info:
        await coordinator._async_update_data()
    assert "SmartThings cloud down" in str(exc_info.value)
