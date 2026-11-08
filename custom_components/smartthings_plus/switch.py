"""Switch platform for SmartThings Plus."""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.switch import SwitchEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:

    class SwitchEntity:  # type: ignore[no-redef]
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

CAPABILITY_SWITCH = "switch"
CAPABILITY_SWITCH_LEVEL = "switchLevel"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartThings Plus switches."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsSwitch] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            # If it has switchLevel, let light.py handle it so we have brightness
            if CAPABILITY_SWITCH in capabilities and CAPABILITY_SWITCH_LEVEL not in capabilities:
                entities.append(SmartThingsSwitch(coordinator, device_id, comp_id))

    async_add_entities(entities)


class SmartThingsSwitch(SmartThingsEntity, SwitchEntity):
    """Representation of a SmartThings switch."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str = "main",
    ) -> None:
        """Initialize switch."""
        super().__init__(coordinator, device_id, component_id)
        self._attr_unique_id = f"{device_id}_{component_id}_switch"
        dev_name = self.device_entry.get("label") or self.device_entry.get("name") or "Switch"
        if component_id != "main":
            self._attr_name = f"{dev_name} {component_id.capitalize()}"
        else:
            self._attr_name = dev_name

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        state = self.get_attribute_value(CAPABILITY_SWITCH, "switch")
        if state is None:
            return None
        return state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn switch on."""
        await self.async_execute_command(CAPABILITY_SWITCH, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn switch off."""
        await self.async_execute_command(CAPABILITY_SWITCH, "off")
