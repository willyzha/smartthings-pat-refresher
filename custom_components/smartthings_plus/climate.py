"""Climate platform for SmartThings Plus."""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.climate import (
        ClimateEntity,
        ClimateEntityFeature,
        HVACMode,
    )
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class ClimateEntity:  # type: ignore[no-redef]
        pass
    class ClimateEntityFeature:  # type: ignore[no-redef]
        TARGET_TEMPERATURE = 1
        TARGET_TEMPERATURE_RANGE = 2
    class HVACMode:  # type: ignore[no-redef]
        OFF = "off"
        HEAT = "heat"
        COOL = "cool"
        AUTO = "auto"
    class UnitOfTemperature:  # type: ignore[no-redef]
        CELSIUS = "°C"
        FAHRENHEIT = "°F"
    ATTR_TEMPERATURE = "temperature"
    class HomeAssistant:  # type: ignore[no-redef]
        pass
    class ConfigEntry:  # type: ignore[no-redef]
        pass
    AddEntitiesCallback = Any  # type: ignore[misc,assignment]

from .const import DOMAIN
from .coordinator import SmartThingsDataUpdateCoordinator
from .entity import SmartThingsEntity

_LOGGER = logging.getLogger(__name__)

CAPABILITY_THERMOSTAT_MODE = "thermostatMode"
CAPABILITY_COOLING_SETPOINT = "thermostatCoolingSetpoint"
CAPABILITY_HEATING_SETPOINT = "thermostatHeatingSetpoint"
CAPABILITY_TEMPERATURE = "temperatureMeasurement"

ST_TO_HA_HVAC = {
    "off": HVACMode.OFF,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "auto": HVACMode.AUTO,
}
HA_TO_ST_HVAC = {v: k for k, v in ST_TO_HA_HVAC.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartThings Plus climate entities."""
    coordinator: SmartThingsDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SmartThingsClimate] = []

    for device_id, data in coordinator.data.items():
        device = data.get("device", {})
        components = device.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "main")
            capabilities = [c.get("id") for c in comp.get("capabilities", [])]

            if (
                CAPABILITY_THERMOSTAT_MODE in capabilities
                or CAPABILITY_COOLING_SETPOINT in capabilities
                or CAPABILITY_HEATING_SETPOINT in capabilities
            ):
                entities.append(SmartThingsClimate(coordinator, device_id, comp_id))

    async_add_entities(entities)


class SmartThingsClimate(SmartThingsEntity, ClimateEntity):
    """Representation of a SmartThings thermostat."""

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str = "main",
    ) -> None:
        """Initialize climate entity."""
        super().__init__(coordinator, device_id, component_id)
        self._attr_unique_id = f"{device_id}_{component_id}_climate"
        dev_name = self.device_entry.get("label") or self.device_entry.get("name") or "Thermostat"
        if component_id == "main":
            self._attr_name = dev_name
        else:
            self._attr_name = f"{dev_name} {component_id.capitalize()}"

        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        )

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        temp_cap = self.component_status.get(CAPABILITY_TEMPERATURE, {})
        unit = temp_cap.get("temperature", {}).get("unit", "C")
        return "°F" if unit.upper() == "F" else "°C"

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        val = self.get_attribute_value(CAPABILITY_TEMPERATURE, "temperature")
        return float(val) if val is not None else None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature based on current mode."""
        mode = self.hvac_mode
        if mode == HVACMode.HEAT:
            val = self.get_attribute_value(CAPABILITY_HEATING_SETPOINT, "heatingSetpoint")
        else:
            val = self.get_attribute_value(CAPABILITY_COOLING_SETPOINT, "coolingSetpoint")
        return float(val) if val is not None else None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the highbound target temperature."""
        val = self.get_attribute_value(CAPABILITY_COOLING_SETPOINT, "coolingSetpoint")
        return float(val) if val is not None else None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lowbound target temperature."""
        val = self.get_attribute_value(CAPABILITY_HEATING_SETPOINT, "heatingSetpoint")
        return float(val) if val is not None else None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        mode = self.get_attribute_value(CAPABILITY_THERMOSTAT_MODE, "thermostatMode")
        return ST_TO_HA_HVAC.get(str(mode).lower(), HVACMode.OFF)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        st_mode = HA_TO_ST_HVAC.get(hvac_mode)
        if st_mode:
            await self.async_execute_command(
                CAPABILITY_THERMOSTAT_MODE,
                "setThermostatMode",
                [st_mode],
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            target = kwargs[ATTR_TEMPERATURE]
            if self.hvac_mode == HVACMode.HEAT:
                await self.async_execute_command(
                    CAPABILITY_HEATING_SETPOINT,
                    "setHeatingSetpoint",
                    [target],
                )
            else:
                await self.async_execute_command(
                    CAPABILITY_COOLING_SETPOINT,
                    "setCoolingSetpoint",
                    [target],
                )
        if "target_temp_low" in kwargs:
            await self.async_execute_command(
                CAPABILITY_HEATING_SETPOINT,
                "setHeatingSetpoint",
                [kwargs["target_temp_low"]],
            )
        if "target_temp_high" in kwargs:
            await self.async_execute_command(
                CAPABILITY_COOLING_SETPOINT,
                "setCoolingSetpoint",
                [kwargs["target_temp_high"]],
            )
