"""Binary sensor platform for SmartThings Plus."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

try:
    from homeassistant.components.binary_sensor import (
        BinarySensorDeviceClass,
        BinarySensorEntity,
    )
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:

    class BinarySensorEntity:  # type: ignore[no-redef]
        pass

    class BinarySensorDeviceClass:  # type: ignore[no-redef]
        MOTION = "motion"
        DOOR = "door"
        MOISTURE = "moisture"
        PRESENCE = "presence"
        SMOKE = "smoke"

    class HomeAssistant:  # type: ignore[no-redef]
        pass

    class ConfigEntry:  # type: ignore[no-redef]
        pass

    AddEntitiesCallback = Any  # type: ignore[misc,assignment]

from .const import DOMAIN
from .coordinator import SmartThingsDataUpdateCoordinator
from .entity import SmartThingsEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinarySensorTypeConfig:
    """Binary sensor definition."""

    capability: str
    attribute: str
    on_value: str
    name_suffix: str
    device_class: str | None


BINARY_SENSOR_TYPES: list[BinarySensorTypeConfig] = [
    BinarySensorTypeConfig(
        capability="motionSensor",
        attribute="motion",
        on_value="active",
        name_suffix="Motion",
        device_class=getattr(BinarySensorDeviceClass, "MOTION", "motion"),
    ),
    BinarySensorTypeConfig(
        capability="contactSensor",
        attribute="contact",
        on_value="open",
        name_suffix="Contact",
        device_class=getattr(BinarySensorDeviceClass, "DOOR", "door"),
    ),
    BinarySensorTypeConfig(
        capability="waterSensor",
        attribute="water",
        on_value="wet",
        name_suffix="Moisture",
        device_class=getattr(BinarySensorDeviceClass, "MOISTURE", "moisture"),
    ),
    BinarySensorTypeConfig(
        capability="presenceSensor",
        attribute="presence",
        on_value="present",
        name_suffix="Presence",
        device_class=getattr(BinarySensorDeviceClass, "PRESENCE", "presence"),
    ),
    BinarySensorTypeConfig(
        capability="smokeDetector",
        attribute="smoke",
        on_value="detected",
        name_suffix="Smoke",
        device_class=getattr(BinarySensorDeviceClass, "SMOKE", "smoke"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartThings Plus binary sensors."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsBinarySensor] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            for cfg in BINARY_SENSOR_TYPES:
                if cfg.capability in capabilities:
                    entities.append(
                        SmartThingsBinarySensor(
                            coordinator=coordinator,
                            device_id=device_id,
                            component_id=comp_id,
                            config=cfg,
                        )
                    )

    async_add_entities(entities)


class SmartThingsBinarySensor(SmartThingsEntity, BinarySensorEntity):
    """Representation of a SmartThings binary sensor."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str,
        config: BinarySensorTypeConfig,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator, device_id, component_id)
        self.config = config
        self._attr_unique_id = f"{device_id}_{component_id}_{config.attribute}"

        dev_entry = self.device_entry
        dev_name = dev_entry.get("label") or dev_entry.get("name") or "Binary Sensor"
        prefix = f"{dev_name} {component_id.capitalize()}" if component_id != "main" else dev_name
        self._attr_name = f"{prefix} {config.name_suffix}"

        self._attr_device_class = config.device_class

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on/active."""
        val = self.get_attribute_value(self.config.capability, self.config.attribute)
        if val is None:
            return None
        return str(val).lower() == self.config.on_value.lower()
