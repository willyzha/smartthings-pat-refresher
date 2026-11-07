"""The SmartThings Plus integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:
    # Shim for standalone test environments
    class HomeAssistant:  # type: ignore[no-redef]
        data: dict = {}

        class config_entries:
            @staticmethod
            def async_update_entry(entry: Any, data: Any) -> None:
                pass

            @staticmethod
            async def async_forward_entry_setups(entry: Any, platforms: Any) -> None:
                pass

            @staticmethod
            async def async_unload_platforms(entry: Any, platforms: Any) -> bool:
                return True

    class ConfigEntry:  # type: ignore[no-redef]
        entry_id = "test_entry"
        data: dict = {}

    def async_get_clientsession(hass: Any) -> Any:
        return None

from .api import SmartThingsApiClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ROTATOR_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SmartThingsDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartThings Plus from a config entry."""
    session = async_get_clientsession(hass)
    rotator_url = entry.data[CONF_ROTATOR_URL]
    access_token = entry.data.get(CONF_ACCESS_TOKEN)

    # Callback triggered whenever a renewed PAT is retrieved
    async def async_on_token_refreshed(new_access_token: str, new_expires_at: float) -> None:
        _LOGGER.debug("Persisting newly rotated SmartThings PAT into Home Assistant config...")
        updated_data = {
            **entry.data,
            CONF_ACCESS_TOKEN: new_access_token,
        }
        hass.config_entries.async_update_entry(entry, data=updated_data)

    client = SmartThingsApiClient(
        session=session,
        rotator_url=rotator_url,
        access_token=access_token,
        on_token_refreshed=async_on_token_refreshed,
    )

    # Verify / retrieve token upon startup
    await client.async_ensure_token_valid()

    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = SmartThingsDataUpdateCoordinator(
        hass=hass,
        client=client,
        update_interval=timedelta(seconds=scan_interval),
    )

    if hasattr(coordinator, "async_config_entry_first_refresh"):
        await coordinator.async_config_entry_first_refresh()
    else:
        await coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
