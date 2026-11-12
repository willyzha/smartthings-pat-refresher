"""Unit tests for SmartThings MQTT Discovery Bridge."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from rotator.dashboard import SmartThingsDashboardClient
from rotator.mqtt_bridge import SmartThingsMQTTBridge, _clean_entity_name, _normalize_unit


@pytest.mark.asyncio
async def test_mqtt_discovery_payloads():
    dashboard = SmartThingsDashboardClient()
    dashboard.devices["dev-washer"] = {
        "deviceId": "dev-washer",
        "name": "Washer",
        "capabilities": ["washerJobState", "temperatureMeasurement"],
    }
    dashboard.devices["dev-lock"] = {
        "deviceId": "dev-lock",
        "name": "Front Door",
        "capabilities": ["lock", "battery"],
    }
    dashboard.devices["dev-switch"] = {
        "deviceId": "dev-switch",
        "name": "Living Room Plug",
        "capabilities": ["switch"],
    }

    bridge = SmartThingsMQTTBridge(
        dashboard_client=dashboard,
        mqtt_host="127.0.0.1",
        topic_prefix="smartthings",
        discovery_prefix="homeassistant",
    )

    published_messages = []

    async def mock_publish(topic, payload, retain=False, qos=0):
        published_messages.append(
            (topic, json.loads(payload) if payload.startswith("{") else payload)
        )

    bridge._safe_publish = mock_publish
    bridge._connected = True
    bridge._client = MagicMock()

    # Sync washer
    washer_state = {
        "washerJobState": "wash",
        "temperature": 105,
    }
    await bridge._sync_device("dev-washer", washer_state)

    # Check that HA discovery configs were published
    washer_configs = [p for p in published_messages if "homeassistant/sensor" in p[0]]
    assert len(washer_configs) >= 2

    # Check temperature sensor config
    temp_conf = next(c for c in washer_configs if "temperature" in c[0])[1]
    assert temp_conf["has_entity_name"] is True
    assert temp_conf["name"] == "Temperature"
    assert temp_conf["device_class"] == "temperature"
    assert temp_conf["state_topic"] == "smartthings/dev-washer/state"
    assert temp_conf["value_template"] == "{{ value_json.temperature }}"
    assert temp_conf["device"]["name"] == "Washer"

    # Check washer job state sensor config (cleaned suffix without device name)
    job_conf = next(c for c in washer_configs if "washerJobState" in c[0])[1]
    assert job_conf["has_entity_name"] is True
    assert job_conf["name"] == "Job State"

    # Sync lock
    published_messages.clear()
    lock_state = {"lock": "locked", "battery": 90}
    await bridge._sync_device("dev-lock", lock_state)

    lock_conf = next(c for c in published_messages if "homeassistant/lock" in c[0])[1]
    assert lock_conf["has_entity_name"] is True
    assert lock_conf["name"] == "Lock"
    assert lock_conf["command_topic"] == "smartthings/dev-lock/lock/set"
    assert lock_conf["payload_lock"] == "LOCK"
    assert lock_conf["payload_unlock"] == "UNLOCK"
    assert lock_conf["state_locked"] == "locked"

    # Sync switch
    published_messages.clear()
    switch_state = {"switch": "off"}
    await bridge._sync_device("dev-switch", switch_state)

    switch_conf = next(c for c in published_messages if "homeassistant/switch" in c[0])[1]
    assert switch_conf["has_entity_name"] is True
    assert switch_conf["name"] == "Switch"
    assert switch_conf["command_topic"] == "smartthings/dev-switch/switch/set"
    assert switch_conf["payload_on"] == "on"
    assert switch_conf["payload_off"] == "off"


@pytest.mark.asyncio
async def test_handle_mqtt_command_switch():
    dashboard = SmartThingsDashboardClient()
    dashboard.async_send_command = AsyncMock()
    bridge = SmartThingsMQTTBridge(
        dashboard_client=dashboard,
        mqtt_host="127.0.0.1",
    )
    bridge._safe_publish = AsyncMock()

    # Simulate incoming message: smartthings/dev-plug/switch/set -> ON
    msg = MagicMock()
    msg.topic = "smartthings/dev-plug/switch/set"
    msg.payload = b"ON"

    await bridge._handle_mqtt_message(msg)

    dashboard.async_send_command.assert_awaited_once_with("dev-plug", "switch", "on")
    bridge._safe_publish.assert_awaited()


@pytest.mark.asyncio
async def test_handle_mqtt_command_lock():
    dashboard = SmartThingsDashboardClient()
    dashboard.async_send_command = AsyncMock()
    bridge = SmartThingsMQTTBridge(
        dashboard_client=dashboard,
        mqtt_host="127.0.0.1",
    )
    bridge._safe_publish = AsyncMock()

    # Simulate incoming message: smartthings/dev-lock/lock/set -> UNLOCK
    msg = MagicMock()
    msg.topic = "smartthings/dev-lock/lock/set"
    msg.payload = b"UNLOCK"

    await bridge._handle_mqtt_message(msg)

    dashboard.async_send_command.assert_awaited_once_with("dev-lock", "lock", "unlock")
    bridge._safe_publish.assert_awaited()


def test_clean_entity_name():
    assert _clean_entity_name("Black", "Auto Reconnection") == "Auto Reconnection"
    assert (
        _clean_entity_name(
            "Alpstuga Air Quality Monitor",
            "Alpstuga Air Quality Monitor Available Version",
        )
        == "Available Version"
    )
    assert _clean_entity_name("Washer", "Washer Job State") == "Job State"
    assert _clean_entity_name("Washer", "Temperature") == "Temperature"
    assert _clean_entity_name("Switch", "Switch") == "Switch"


def test_normalize_unit():
    assert _normalize_unit("C") == "°C"
    assert _normalize_unit("c") == "°C"
    assert _normalize_unit("F") == "°F"
    assert _normalize_unit("f") == "°F"
    assert _normalize_unit("ppm") == "ppm"
    assert _normalize_unit("%") == "%"
    assert _normalize_unit("μg/m^3") == "µg/m³"
    assert _normalize_unit(None) is None


@pytest.mark.asyncio
async def test_mqtt_discovery_air_quality_dynamic_units():
    dashboard = SmartThingsDashboardClient()
    dashboard.devices["dev-air"] = {
        "deviceId": "dev-air",
        "name": "ALPSTUGA air quality monitor",
        "capabilities": ["temperatureMeasurement", "carbonDioxideMeasurement"],
    }
    dashboard.device_status["dev-air"] = {
        "temperature": {"value": 21.2, "unit": "C"},
        "carbonDioxide": {"value": 950, "unit": "ppm"},
    }

    bridge = SmartThingsMQTTBridge(
        dashboard_client=dashboard,
        mqtt_host="127.0.0.1",
    )

    published = []

    async def mock_publish(topic, payload, retain=False, qos=0):
        published.append((topic, json.loads(payload) if payload.startswith("{") else payload))

    bridge._safe_publish = mock_publish
    bridge._connected = True
    bridge._client = MagicMock()

    flat_state = {"temperature": 21.2, "carbonDioxide": 950}
    await bridge._sync_device("dev-air", flat_state)

    # Verify temperature uses dynamic °C
    temp_conf = next(c for c in published if "temperature" in c[0])[1]
    assert temp_conf["unit_of_measurement"] == "°C"
    assert temp_conf["device_class"] == "temperature"
    assert temp_conf["state_class"] == "measurement"
    assert temp_conf["has_entity_name"] is True
    assert temp_conf["name"] == "Temperature"

    # Verify carbon dioxide uses ppm and carbon_dioxide device class
    co2_conf = next(c for c in published if "carbonDioxide" in c[0])[1]
    assert co2_conf["unit_of_measurement"] == "ppm"
    assert co2_conf["device_class"] == "carbon_dioxide"
    assert co2_conf["state_class"] == "measurement"
    assert co2_conf["has_entity_name"] is True
    assert co2_conf["name"] == "Carbon Dioxide"
