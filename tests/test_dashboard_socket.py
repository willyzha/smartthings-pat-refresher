"""Unit tests for SmartThings Dashboard Socket.IO client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from rotator.dashboard import DashboardAuthError, SmartThingsDashboardClient


def test_extract_cookies_missing_file(tmp_path):
    missing_file = tmp_path / "does_not_exist.json"
    client = SmartThingsDashboardClient(storage_state_file=missing_file)
    with pytest.raises(DashboardAuthError):
        client._extract_cookies_and_expiry()


def test_extract_cookies_success(tmp_path):
    state_file = tmp_path / "storage_state.json"
    state_data = {
        "cookies": [
            {"name": "cake_session", "value": "secret_cake_val", "expires": 1800000000},
            {"name": "sa_did", "value": "device_id_val", "expires": 1900000000},
        ]
    }
    state_file.write_text(json.dumps(state_data), encoding="utf-8")

    client = SmartThingsDashboardClient(storage_state_file=state_file)
    cookie_str, cake_exp = client._extract_cookies_and_expiry()

    assert "cake_session=secret_cake_val" in cookie_str
    assert "sa_did=device_id_val" in cookie_str
    assert cake_exp == 1800000000
    assert client.get_health()["session_valid"] is True


def test_parse_devices_payload():
    client = SmartThingsDashboardClient()
    client.location_id = "loc-123"

    raw_devices = [
        {
            "deviceId": "dev-1",
            "name": "Front Door",
            "capabilities": ["lock", "battery"],
        },
        {
            "complexCloud": {
                "deviceId": "dev-2",
                "deviceName": "Washer",
                "capabilities": ["washerJobState", "washerMode"],
            }
        },
    ]

    client._parse_devices_payload(raw_devices)
    assert len(client.devices) == 2
    assert client.devices["dev-1"]["name"] == "Front Door"
    assert "lock" in client.devices["dev-1"]["capabilities"]
    assert client.devices["dev-2"]["name"] == "Washer"
    assert "washerJobState" in client.devices["dev-2"]["capabilities"]


def test_parse_status_and_flat_state():
    client = SmartThingsDashboardClient()

    raw_status = [
        {
            "deviceId": "dev-washer",
            "componentId": "main",
            "capabilityId": "washerJobState",
            "attributeName": "washerJobState",
            "value": "wash",
            "unit": None,
        },
        {
            "deviceId": "dev-washer",
            "componentId": "main",
            "capabilityId": "temperatureMeasurement",
            "attributeName": "temperature",
            "value": 72,
            "unit": "F",
        },
        {
            "deviceId": "dev-fridge",
            "componentId": "cooler",
            "capabilityId": "temperatureMeasurement",
            "attributeName": "temperature",
            "value": 37,
            "unit": "F",
        },
        {
            "deviceId": "dev-fridge",
            "componentId": "freezer",
            "capabilityId": "temperatureMeasurement",
            "attributeName": "temperature",
            "value": 0,
            "unit": "F",
        },
    ]

    client._parse_status_payload(raw_status)
    assert "dev-washer" in client.device_status
    assert client.device_status["dev-washer"]["washerJobState"]["value"] == "wash"

    flat_washer = client.get_device_flat_state("dev-washer")
    assert flat_washer["washerJobState"] == "wash"
    assert flat_washer["temperature"] == 72

    flat_fridge = client.get_device_flat_state("dev-fridge")
    assert flat_fridge["cooler_temperature"] == 37
    assert flat_fridge["freezer_temperature"] == 0


def test_handle_server_event_and_listeners():
    listener_calls = []

    def on_event(dev_id, state):
        listener_calls.append((dev_id, state))

    client = SmartThingsDashboardClient()
    client.add_listener(on_event)

    event_payload = {
        "data": {
            "deviceId": "dev-lock",
            "capability": "lock",
            "attribute": "lock",
            "value": "locked",
            "componentId": "main",
        }
    }

    client._handle_server_event("DEVICE_EVENT", event_payload)

    assert len(listener_calls) == 1
    assert listener_calls[0][0] == "dev-lock"
    assert listener_calls[0][1]["lock"] == "locked"
    assert client.get_device_flat_state("dev-lock")["lock"] == "locked"


@pytest.mark.asyncio
async def test_async_send_command():
    client = SmartThingsDashboardClient()
    client._call_service = AsyncMock(return_value={"status": "ACCEPTED"})

    res = await client.async_send_command(
        device_id="dev-switch",
        capability="switch",
        command="on",
    )

    assert res == {"status": "ACCEPTED"}
    client._call_service.assert_awaited_once_with(
        "create",
        "api/command",
        {
            "deviceId": "dev-switch",
            "componentId": "main",
            "capability": "switch",
            "command": "on",
            "arguments": [],
        },
        {},
    )
    # Check optimistic update
    assert client.device_status["dev-switch"]["switch"]["value"] == "on"
