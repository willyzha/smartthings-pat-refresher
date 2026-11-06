"""Sensor platform for SmartThings Plus."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

try:
    from homeassistant.components.sensor import (
        SensorDeviceClass,
        SensorEntity,
        SensorStateClass,
    )
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import (
        PERCENTAGE,
        UnitOfEnergy,
        UnitOfPower,
        UnitOfTemperature,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class SensorEntity:  # type: ignore[no-redef]
        pass
    class SensorDeviceClass:  # type: ignore[no-redef]
        TEMPERATURE = "temperature"
        HUMIDITY = "humidity"
        BATTERY = "battery"
        POWER = "power"
        ENERGY = "energy"
        ILLUMINANCE = "illuminance"
    class SensorStateClass:  # type: ignore[no-redef]
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"
    PERCENTAGE = "%"
    class UnitOfTemperature:  # type: ignore[no-redef]
        CELSIUS = "°C"
        FAHRENHEIT = "°F"
    class UnitOfPower:  # type: ignore[no-redef]
        WATT = "W"
    class UnitOfEnergy:  # type: ignore[no-redef]
        KILO_WATT_HOUR = "kWh"
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
class SensorTypeConfig:
    """Sensor definition config."""

    capability: str
    attribute: str
    name_suffix: str
    device_class: str | None
    state_class: str | None
    native_unit: str | None


SENSOR_TYPES: list[SensorTypeConfig] = [
    SensorTypeConfig(
        capability="temperatureMeasurement",
        attribute="temperature",
        name_suffix="Temperature",
        device_class=getattr(SensorDeviceClass, "TEMPERATURE", "temperature"),
        state_class=getattr(SensorStateClass, "MEASUREMENT", "measurement"),
        native_unit=getattr(UnitOfTemperature, "CELSIUS", "°C"),
    ),
    SensorTypeConfig(
        capability="relativeHumidityMeasurement",
        attribute="humidity",
        name_suffix="Humidity",
        device_class=getattr(SensorDeviceClass, "HUMIDITY", "humidity"),
        state_class=getattr(SensorStateClass, "MEASUREMENT", "measurement"),
        native_unit=PERCENTAGE,
    ),
    SensorTypeConfig(
        capability="battery",
        attribute="battery",
        name_suffix="Battery",
        device_class=getattr(SensorDeviceClass, "BATTERY", "battery"),
        state_class=getattr(SensorStateClass, "MEASUREMENT", "measurement"),
        native_unit=PERCENTAGE,
    ),
    SensorTypeConfig(
        capability="powerMeter",
        attribute="power",
        name_suffix="Power",
        device_class=getattr(SensorDeviceClass, "POWER", "power"),
        state_class=getattr(SensorStateClass, "MEASUREMENT", "measurement"),
        native_unit=getattr(UnitOfPower, "WATT", "W"),
    ),
    SensorTypeConfig(
        capability="energyMeter",
        attribute="energy",
        name_suffix="Energy",
        device_class=getattr(SensorDeviceClass, "ENERGY", "energy"),
        state_class=getattr(SensorStateClass, "TOTAL_INCREASING", "total_increasing"),
        native_unit=getattr(UnitOfEnergy, "KILO_WATT_HOUR", "kWh"),
    ),
    SensorTypeConfig(
        capability="illuminanceMeasurement",
        attribute="illuminance",
        name_suffix="Illuminance",
        device_class=getattr(SensorDeviceClass, "ILLUMINANCE", "illuminance"),
        state_class=getattr(SensorStateClass, "MEASUREMENT", "measurement"),
        native_unit="lx",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartThings Plus sensors."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsSensor] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            for cfg in SENSOR_TYPES:
                if cfg.capability in capabilities:
                    entities.append(
                        SmartThingsSensor(
                            coordinator=coordinator,
                            device_id=device_id,
                            component_id=comp_id,
                            config=cfg,
                        )
                    )

    async_add_entities(entities)


class SmartThingsSensor(SmartThingsEntity, SensorEntity):
    """Representation of a SmartThings sensor."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str,
        config: SensorTypeConfig,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator, device_id, component_id)
        self.config = config
        self._attr_unique_id = f"{device_id}_{component_id}_{config.attribute}"

        dev_name = self.device_entry.get("label") or self.device_entry.get("name") or "Sensor"
        prefix = f"{dev_name} {component_id.capitalize()}" if component_id != "main" else dev_name
        self._attr_name = f"{prefix} {config.name_suffix}"

        self._attr_device_class = config.device_class
        self._attr_state_class = config.state_class
        self._attr_native_unit_of_measurement = config.native_unit

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self.get_attribute_value(self.config.capability, self.config.attribute)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit of measurement, honoring SmartThings reported unit if present."""
        cap_data = self.component_status.get(self.config.capability, {})
        attr_data = cap_data.get(self.config.attribute, {})
        st_unit = attr_data.get("unit")
        if st_unit:
            # SmartThings units C/F conversion to HA
            if st_unit.upper() == "C":
                return "°C"
            if st_unit.upper() == "F":
                return "°F"
            return st_unit
        return self._attr_native_unit_of_measurement
