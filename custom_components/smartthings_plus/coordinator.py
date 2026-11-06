"""DataUpdateCoordinator for SmartThings Plus."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Generic, TypeVar

from .api import SmartThingsApiClient, SmartThingsApiError, SmartThingsAuthError

_DataT = TypeVar("_DataT")

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
except ImportError:
    # Fallback / mock shim for standalone testing
    class HomeAssistant:  # type: ignore[no-redef]
        pass

    class UpdateFailed(Exception):  # type: ignore[no-redef]
        pass

    class DataUpdateCoordinator(Generic[_DataT]):  # type: ignore[no-redef]
        def __init__(self, hass: Any, logger: Any, name: str, update_interval: timedelta) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: Any = {}

        async def async_refresh(self) -> None:
            self.data = await self._async_update_data()

        async def _async_update_data(self) -> Any:
            raise NotImplementedError


_LOGGER = logging.getLogger(__name__)


class SmartThingsDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to manage polling data from the SmartThings API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SmartThingsApiClient,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="SmartThings Plus Coordinator",
            update_interval=update_interval,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch all device states from SmartThings."""
        try:
            # 1. Proactively ensure token validity
            await self.client.async_ensure_token_valid()

            # 2. Get list of devices
            devices = await self.client.async_get_devices()

            # 3. Concurrently fetch status for all devices
            async def _fetch_status(device: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                device_id = device["deviceId"]
                try:
                    status = await self.client.async_get_device_status(device_id)
                except Exception as err:
                    _LOGGER.warning("Could not fetch status for device %s: %s", device_id, err)
                    status = {}
                return device_id, {"device": device, "status": status}

            results = await asyncio.gather(*[_fetch_status(d) for d in devices])
            return dict(results)

        except (SmartThingsAuthError, SmartThingsApiError) as err:
            raise UpdateFailed(f"Error communicating with SmartThings: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating SmartThings data: {err}") from err
