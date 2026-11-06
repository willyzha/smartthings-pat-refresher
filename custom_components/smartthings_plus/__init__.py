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
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
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

    client_id = entry.data[CONF_CLIENT_ID]
    client_secret = entry.data[CONF_CLIENT_SECRET]
    access_token = entry.data.get(CONF_ACCESS_TOKEN)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    expires_at = entry.data.get(CONF_EXPIRES_AT, 0.0)

    # Callback triggered whenever the rolling refresh token rotates
    async def async_on_token_refreshed(
        new_access_token: str,
        new_refresh_token: str,
        new_expires_at: float,
    ) -> None:
        _LOGGER.info("Updating Home Assistant config entry with newly refreshed OAuth token...")
        updated_data = {
            **entry.data,
            CONF_ACCESS_TOKEN: new_access_token,
            CONF_REFRESH_TOKEN: new_refresh_token,
            CONF_EXPIRES_AT: new_expires_at,
        }
        hass.config_entries.async_update_entry(entry, data=updated_data)

    client = SmartThingsApiClient(
        session=session,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        on_token_refreshed=async_on_token_refreshed,
    )

    # Ensure valid token upon startup
    await client.async_ensure_token_valid()

    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = SmartThingsDataUpdateCoordinator(
        hass=hass,
        client=client,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Initial data refresh
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
