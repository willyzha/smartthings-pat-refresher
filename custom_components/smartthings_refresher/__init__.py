"""SmartThings Refresher: Non-vendored wrapper around core SmartThings with PAT Rotator."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from aiohttp import ClientSession, ClientTimeout
from pysmartthings import (
    Category,
    DeviceEvent,
    SmartThings,
    SmartThingsAuthenticationFailedError,
    SmartThingsConnectionError,
)
from pysmartthings.models import HealthStatus

try:
    from homeassistant.components.smartthings import (
        MAIN,
        PLATFORMS,
        FullDevice,
        SmartThingsData,
        process_status,
    )
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.event import async_track_time_interval
except ImportError:
    # Standalone mock types for unit testing
    class FullDevice:  # type: ignore[no-redef]
        def __init__(self, device: Any, status: dict[str, Any], online: bool) -> None:
            self.device = device
            self.status = status
            self.online = online

    class SmartThingsData:  # type: ignore[no-redef]
        def __init__(
            self,
            devices: dict[str, Any],
            scenes: dict[str, Any],
            rooms: dict[str, str],
            client: Any,
        ) -> None:
            self.devices = devices
            self.scenes = scenes
            self.rooms = rooms
            self.client = client

    MAIN = "main"
    PLATFORMS = []  # type: ignore[assignment]

    def process_status(status: Any) -> Any:
        return status

    class ConfigEntry:  # type: ignore[no-redef]
        runtime_data: Any = None
        data: dict[str, Any] = {}
        options: dict[str, Any] = {}

    class HomeAssistant:  # type: ignore[no-redef]
        pass

    class ConfigEntryAuthFailed(Exception):  # type: ignore[no-redef]
        pass

    class ConfigEntryNotReady(Exception):  # type: ignore[no-redef]
        pass

    def async_get_clientsession(hass: Any) -> ClientSession:
        return ClientSession()

    def async_track_time_interval(hass: Any, cb: Any, interval: Any) -> Any:
        return lambda: None

from .const import (
    CONF_REFRESH_INTERVAL,
    CONF_ROTATOR_URL,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_ROTATOR_URL,
)

_LOGGER = logging.getLogger(__name__)

type SmartThingsRefresherConfigEntry = ConfigEntry[SmartThingsData] if TYPE_CHECKING else Any


async def async_setup_entry(
    hass: HomeAssistant, entry: SmartThingsRefresherConfigEntry
) -> bool:
    """Initialize SmartThings Refresher config entry with token rotator hook."""
    rotator_url = entry.data.get(CONF_ROTATOR_URL, DEFAULT_ROTATOR_URL).rstrip("/")
    session = async_get_clientsession(hass)

    async def _fetch_rotator_token() -> str:
        """Fetch fresh Personal Access Token from rotator container."""
        timeout = ClientTimeout(total=10)
        try:
            async with session.get(
                f"{rotator_url}/token?format=raw", timeout=timeout
            ) as resp:
                if resp.status == 200:
                    token = (await resp.text()).strip()
                    if token and len(token) > 20:
                        return token
                raise ConfigEntryAuthFailed(
                    f"Rotator at {rotator_url} returned HTTP {resp.status}"
                )
        except Exception as err:
            raise ConfigEntryAuthFailed(
                f"Cannot retrieve token from PAT rotator at {rotator_url}: {err}"
            ) from err

    client = SmartThings(session=session)
    client.refresh_token_function = _fetch_rotator_token

    # Authenticate initial token
    initial_token = await _fetch_rotator_token()
    client.authenticate(initial_token)

    # Initial device, room, scene, and status discovery
    try:
        locations = await client.get_locations()
        if not locations:
            raise ConfigEntryNotReady("No locations found in SmartThings account.")
        location_id = locations[0].location_id

        rooms = {
            room.room_id: room.name
            for room in await client.get_rooms(location_id=location_id)
        }
        devices = await client.get_devices()

        device_status: dict[str, FullDevice] = {}
        for dev in devices:
            main_comp = dev.components.get(MAIN)
            if (
                main_comp is not None
                and main_comp.manufacturer_category is Category.BLUETOOTH_TRACKER
            ):
                device_status[dev.device_id] = FullDevice(
                    device=dev,
                    status={},
                    online=True,
                )
                continue

            raw_status = await client.get_device_status(dev.device_id)
            health = await client.get_device_health(dev.device_id)
            device_status[dev.device_id] = FullDevice(
                device=dev,
                status=process_status(raw_status),
                online=health.state == HealthStatus.ONLINE,
            )

        scenes = {
            scene.scene_id: scene
            for scene in await client.get_scenes(location_id=location_id)
        }

    except SmartThingsAuthenticationFailedError as err:
        raise ConfigEntryAuthFailed(f"SmartThings authentication error: {err}") from err
    except SmartThingsConnectionError as err:
        raise ConfigEntryNotReady(f"Failed to connect to SmartThings API: {err}") from err

    entry.runtime_data = SmartThingsData(
        devices=device_status,
        scenes=scenes,
        rooms=rooms,
        client=client,
    )

    # Periodic polling loop to synchronize status without requiring paid OAuth SmartApp
    async def _async_poll_device_statuses(_: datetime | None = None) -> None:
        """Poll device statuses and trigger entity updates."""
        for dev_id, full_dev in list(device_status.items()):
            try:
                raw = await client.get_device_status(dev_id)
                new_status = process_status(raw)
                old_status = full_dev.status
                full_dev.status = new_status

                # Dispatch any updated attributes to listeners
                for comp_id, caps in new_status.items():
                    old_caps = old_status.get(comp_id, {})
                    for cap_id, attrs in caps.items():
                        old_attrs = old_caps.get(cap_id, {})
                        for attr_id, attr_val in attrs.items():
                            old_val = old_attrs.get(attr_id)
                            if old_val is None or old_val.value != attr_val.value:
                                key = (dev_id, comp_id, cap_id)
                                listeners = getattr(
                                    client,
                                    "_SmartThings__capability_event_listeners",
                                    {},
                                ).get(key, [])
                                if listeners:
                                    event = DeviceEvent(
                                        device_id=dev_id,
                                        component_id=comp_id,
                                        capability=cap_id,
                                        attribute=attr_id,
                                        value=attr_val.value,
                                        data=attr_val.data,
                                    )
                                    for cb in list(listeners):
                                        try:
                                            cb(event)
                                        except Exception as exc:
                                            _LOGGER.debug("Listener callback error: %s", exc)
            except Exception as err:
                _LOGGER.debug("Status polling failed for device %s: %s", dev_id, err)

    interval_sec = entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    if hasattr(entry, "async_on_unload"):
        entry.async_on_unload(
            async_track_time_interval(
                hass, _async_poll_device_statuses, timedelta(seconds=interval_sec)
            )
        )

    # Forward entry setups to platforms
    if hasattr(hass, "config_entries") and PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SmartThingsRefresherConfigEntry
) -> bool:
    """Unload a config entry."""
    if hasattr(hass, "config_entries") and PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True
