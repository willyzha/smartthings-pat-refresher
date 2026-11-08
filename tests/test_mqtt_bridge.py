"""Unit tests for SmartThings MQTT Discovery Bridge."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from rotator.dashboard import SmartThingsDashboardClient
from rotator.mqtt_bridge import SmartThingsMQTTBridge


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
    assert temp_conf["device_class"] == "temperature"
    assert temp_conf["state_topic"] == "smartthings/dev-washer/state"
    assert temp_conf["value_template"] == "{{ value_json.temperature }}"
    assert temp_conf["device"]["name"] == "Washer"

    # Sync lock
    published_messages.clear()
    lock_state = {"lock": "locked", "battery": 90}
    await bridge._sync_device("dev-lock", lock_state)

    lock_conf = next(c for c in published_messages if "homeassistant/lock" in c[0])[1]
    assert lock_conf["command_topic"] == "smartthings/dev-lock/lock/set"
    assert lock_conf["payload_lock"] == "LOCK"
    assert lock_conf["payload_unlock"] == "UNLOCK"
    assert lock_conf["state_locked"] == "locked"

    # Sync switch
    published_messages.clear()
    switch_state = {"switch": "off"}
    await bridge._sync_device("dev-switch", switch_state)

    switch_conf = next(c for c in published_messages if "homeassistant/switch" in c[0])[1]
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
