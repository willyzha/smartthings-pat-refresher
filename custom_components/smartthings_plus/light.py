"""Light platform for SmartThings Plus."""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.light import (
        ATTR_BRIGHTNESS,
        ColorMode,
        LightEntity,
    )
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:

    class LightEntity:  # type: ignore[no-redef]
        pass

    class ColorMode:  # type: ignore[no-redef]
        ONOFF = "on_off"
        BRIGHTNESS = "brightness"

    ATTR_BRIGHTNESS = "brightness"

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
    """Set up SmartThings Plus lights."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsLight] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            if CAPABILITY_SWITCH_LEVEL in capabilities:
                entities.append(SmartThingsLight(coordinator, device_id, comp_id))

    async_add_entities(entities)


class SmartThingsLight(SmartThingsEntity, LightEntity):
    """Representation of a SmartThings light/dimmer."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str = "main",
    ) -> None:
        """Initialize light."""
        super().__init__(coordinator, device_id, component_id)
        self._attr_unique_id = f"{device_id}_{component_id}_light"
        dev_name = self.device_entry.get("label") or self.device_entry.get("name") or "Light"
        if component_id != "main":
            self._attr_name = f"{dev_name} {component_id.capitalize()}"
        else:
            self._attr_name = dev_name

        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_color_mode = ColorMode.BRIGHTNESS

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        state = self.get_attribute_value(CAPABILITY_SWITCH, "switch")
        if state is None:
            return None
        return state == "on"

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        level = self.get_attribute_value(CAPABILITY_SWITCH_LEVEL, "level")
        if level is None:
            return None
        return max(0, min(255, round(int(level) * 255 / 100)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn light on and optionally adjust brightness."""
        if ATTR_BRIGHTNESS in kwargs:
            ha_brightness = kwargs[ATTR_BRIGHTNESS]
            st_level = max(1, min(100, round(ha_brightness * 100 / 255)))
            await self.async_execute_command(
                CAPABILITY_SWITCH_LEVEL,
                "setLevel",
                [st_level],
            )
        else:
            await self.async_execute_command(CAPABILITY_SWITCH, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn light off."""
        await self.async_execute_command(CAPABILITY_SWITCH, "off")
