"""Tests for SmartThings Plus entity platforms."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.smartthings_plus.binary_sensor import (
    BINARY_SENSOR_TYPES,
    SmartThingsBinarySensor,
)
from custom_components.smartthings_plus.climate import (
    HVACMode,
    SmartThingsClimate,
)
from custom_components.smartthings_plus.coordinator import SmartThingsDataUpdateCoordinator
from custom_components.smartthings_plus.light import SmartThingsLight
from custom_components.smartthings_plus.lock import SmartThingsLock
from custom_components.smartthings_plus.sensor import (
    SENSOR_TYPES,
    SmartThingsSensor,
)
from custom_components.smartthings_plus.switch import SmartThingsSwitch
from tests.conftest import (
    MOCK_DEVICE_ID_BINARY,
    MOCK_DEVICE_ID_CLIMATE,
    MOCK_DEVICE_ID_LIGHT,
    MOCK_DEVICE_ID_LOCK,
    MOCK_DEVICE_ID_SENSOR,
    MOCK_DEVICE_ID_SWITCH,
    MOCK_DEVICE_STATUSES,
    MOCK_DEVICES_LIST,
)


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Fixture creating a populated coordinator mock."""
    coord = MagicMock(spec=SmartThingsDataUpdateCoordinator)
    coord.data = {
        d["deviceId"]: {
            "device": d,
            "status": MOCK_DEVICE_STATUSES.get(d["deviceId"], {}),
        }
        for d in MOCK_DEVICES_LIST
    }
    coord.client = MagicMock()
    coord.client.async_execute_device_command = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_switch_entity(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsSwitch turn on, turn off, and is_on state."""
    switch = SmartThingsSwitch(mock_coordinator, MOCK_DEVICE_ID_SWITCH)
    assert switch.is_on is True
    assert switch.unique_id == f"{MOCK_DEVICE_ID_SWITCH}_main_switch"

    await switch.async_turn_off()
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_SWITCH,
        capability="switch",
        command="off",
        arguments=None,
        component="main",
    )

    await switch.async_turn_on()
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_SWITCH,
        capability="switch",
        command="on",
        arguments=None,
        component="main",
    )


@pytest.mark.asyncio
async def test_light_entity(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsLight turn on with brightness scale conversion."""
    light = SmartThingsLight(mock_coordinator, MOCK_DEVICE_ID_LIGHT)
    assert light.is_on is True
    # In mock, level is 80 out of 100 -> round(80 * 255 / 100) = 204
    assert light.brightness == 204

    # Test setting brightness via HA 0-255 scale
    await light.async_turn_on(brightness=128)
    # round(128 * 100 / 255) = 50
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_LIGHT,
        capability="switchLevel",
        command="setLevel",
        arguments=[50],
        component="main",
    )


@pytest.mark.asyncio
async def test_sensor_entities(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsSensor native value and unit parsing."""
    sensors = {
        cfg.capability: SmartThingsSensor(
            mock_coordinator, MOCK_DEVICE_ID_SENSOR, "main", cfg
        )
        for cfg in SENSOR_TYPES
    }

    temp_sensor = sensors["temperatureMeasurement"]
    assert temp_sensor.native_value == 22.5
    assert temp_sensor.native_unit_of_measurement == "°C"

    humidity_sensor = sensors["relativeHumidityMeasurement"]
    assert humidity_sensor.native_value == 45
    assert humidity_sensor.native_unit_of_measurement == "%"

    battery_sensor = sensors["battery"]
    assert battery_sensor.native_value == 90

    power_sensor = sensors["powerMeter"]
    assert power_sensor.native_value == 150
    assert power_sensor.native_unit_of_measurement == "W"


@pytest.mark.asyncio
async def test_binary_sensor_entities(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsBinarySensor state mapping."""
    bin_sensors = {
        cfg.capability: SmartThingsBinarySensor(
            mock_coordinator, MOCK_DEVICE_ID_BINARY, "main", cfg
        )
        for cfg in BINARY_SENSOR_TYPES
    }

    # In mock, motion is "active" -> is_on should be True
    assert bin_sensors["motionSensor"].is_on is True
    # In mock, contact is "open" -> is_on should be True
    assert bin_sensors["contactSensor"].is_on is True
    # In mock, water is "dry" -> is_on should be False (on_value is "wet")
    assert bin_sensors["waterSensor"].is_on is False
    # In mock, presence is "present" -> is_on should be True
    assert bin_sensors["presenceSensor"].is_on is True
    # In mock, smoke is "clear" -> is_on should be False (on_value is "detected")
    assert bin_sensors["smokeDetector"].is_on is False


@pytest.mark.asyncio
async def test_climate_entity(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsClimate HVAC mode and temperature adjustments."""
    climate = SmartThingsClimate(mock_coordinator, MOCK_DEVICE_ID_CLIMATE)
    assert climate.hvac_mode == HVACMode.COOL
    assert climate.current_temperature == 24.0
    assert climate.target_temperature == 23.0

    await climate.async_set_hvac_mode(HVACMode.HEAT)
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_CLIMATE,
        capability="thermostatMode",
        command="setThermostatMode",
        arguments=["heat"],
        component="main",
    )

    await climate.async_set_temperature(temperature=21.5)
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_CLIMATE,
        capability="thermostatCoolingSetpoint",
        command="setCoolingSetpoint",
        arguments=[21.5],
        component="main",
    )


@pytest.mark.asyncio
async def test_lock_entity(mock_coordinator: MagicMock) -> None:
    """Test SmartThingsLock state and lock/unlock commands."""
    lock = SmartThingsLock(mock_coordinator, MOCK_DEVICE_ID_LOCK)
    assert lock.is_locked is True

    await lock.async_unlock()
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_LOCK,
        capability="lock",
        command="unlock",
        arguments=None,
        component="main",
    )

    await lock.async_lock()
    mock_coordinator.client.async_execute_device_command.assert_called_with(
        device_id=MOCK_DEVICE_ID_LOCK,
        capability="lock",
        command="lock",
        arguments=None,
        component="main",
    )
