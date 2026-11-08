"""Lock platform for SmartThings Plus."""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.lock import LockEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:

    class LockEntity:  # type: ignore[no-redef]
        pass

    class HomeAssistant:  # type: ignore[no-redef]
        pass

    class ConfigEntry:  # type: ignore[no-redef]
        pass

    AddEntitiesCallback = Any  # type: ignore[misc,assignment]

from .const import DOMAIN
from .coordinator import SmartThingsDataUpdateCoordinator
from .entity import SmartThingsEntity

_LOGGER = logging.getLogger(__name__)

CAPABILITY_LOCK = "lock"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartThings Plus locks."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsLock] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            if CAPABILITY_LOCK in capabilities:
                entities.append(SmartThingsLock(coordinator, device_id, comp_id))

    async_add_entities(entities)


class SmartThingsLock(SmartThingsEntity, LockEntity):
    """Representation of a SmartThings lock."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str = "main",
    ) -> None:
        """Initialize lock."""
        super().__init__(coordinator, device_id, component_id)
        self._attr_unique_id = f"{device_id}_{component_id}_lock"
        dev_name = self.device_entry.get("label") or self.device_entry.get("name") or "Lock"
        if component_id == "main":
            self._attr_name = dev_name
        else:
            self._attr_name = f"{dev_name} {component_id.capitalize()}"

    @property
    def is_locked(self) -> bool | None:
        """Return true if lock is locked."""
        state = self.get_attribute_value(CAPABILITY_LOCK, "lock")
        if state is None:
            return None
        return state == "locked"

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        await self.async_execute_command(CAPABILITY_LOCK, "lock")

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        await self.async_execute_command(CAPABILITY_LOCK, "unlock")
