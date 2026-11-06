"""Pytest fixtures and test doubles for SmartThings Plus."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

MOCK_CLIENT_ID = "mock-client-id-123"
MOCK_CLIENT_SECRET = "mock-client-secret-456"
MOCK_ACCESS_TOKEN = "st-access-token-initial"
MOCK_REFRESH_TOKEN = "st-refresh-token-initial"
MOCK_NEW_ACCESS_TOKEN = "st-access-token-refreshed"
MOCK_NEW_REFRESH_TOKEN = "st-refresh-token-new-rolling"

MOCK_DEVICE_ID_SWITCH = "dev-switch-001"
MOCK_DEVICE_ID_LIGHT = "dev-light-002"
MOCK_DEVICE_ID_SENSOR = "dev-sensor-003"
MOCK_DEVICE_ID_BINARY = "dev-binary-004"
MOCK_DEVICE_ID_CLIMATE = "dev-climate-005"
MOCK_DEVICE_ID_LOCK = "dev-lock-006"

MOCK_DEVICES_LIST = [
    {
        "deviceId": MOCK_DEVICE_ID_SWITCH,
        "name": "Outlet 1",
        "label": "Living Room Lamp",
        "components": [
            {
                "id": "main",
                "capabilities": [{"id": "switch"}],
            }
        ],
    },
    {
        "deviceId": MOCK_DEVICE_ID_LIGHT,
        "name": "Dimmer 1",
        "label": "Ceiling Light",
        "components": [
            {
                "id": "main",
                "capabilities": [{"id": "switch"}, {"id": "switchLevel"}],
            }
        ],
    },
    {
        "deviceId": MOCK_DEVICE_ID_SENSOR,
        "name": "Multi Sensor",
        "label": "Office Climate Sensor",
        "components": [
            {
                "id": "main",
                "capabilities": [
                    {"id": "temperatureMeasurement"},
                    {"id": "relativeHumidityMeasurement"},
                    {"id": "battery"},
                    {"id": "powerMeter"},
                    {"id": "energyMeter"},
                    {"id": "illuminanceMeasurement"},
                ],
            }
        ],
    },
    {
        "deviceId": MOCK_DEVICE_ID_BINARY,
        "name": "Door Sensor",
        "label": "Front Door",
        "components": [
            {
                "id": "main",
                "capabilities": [
                    {"id": "motionSensor"},
                    {"id": "contactSensor"},
                    {"id": "waterSensor"},
                    {"id": "presenceSensor"},
                    {"id": "smokeDetector"},
                ],
            }
        ],
    },
    {
        "deviceId": MOCK_DEVICE_ID_CLIMATE,
        "name": "Thermostat 1",
        "label": "Main Thermostat",
        "components": [
            {
                "id": "main",
                "capabilities": [
                    {"id": "thermostatMode"},
                    {"id": "thermostatCoolingSetpoint"},
                    {"id": "thermostatHeatingSetpoint"},
                    {"id": "temperatureMeasurement"},
                ],
            }
        ],
    },
    {
        "deviceId": MOCK_DEVICE_ID_LOCK,
        "name": "Smart Lock",
        "label": "Front Door Lock",
        "components": [
            {
                "id": "main",
                "capabilities": [{"id": "lock"}],
            }
        ],
    },
]

MOCK_DEVICE_STATUSES = {
    MOCK_DEVICE_ID_SWITCH: {
        "main": {
            "switch": {"switch": {"value": "on"}},
        }
    },
    MOCK_DEVICE_ID_LIGHT: {
        "main": {
            "switch": {"switch": {"value": "on"}},
            "switchLevel": {"level": {"value": 80}},
        }
    },
    MOCK_DEVICE_ID_SENSOR: {
        "main": {
            "temperatureMeasurement": {"temperature": {"value": 22.5, "unit": "C"}},
            "relativeHumidityMeasurement": {"humidity": {"value": 45}},
            "battery": {"battery": {"value": 90}},
            "powerMeter": {"power": {"value": 150}},
            "energyMeter": {"energy": {"value": 12.4}},
            "illuminanceMeasurement": {"illuminance": {"value": 350}},
        }
    },
    MOCK_DEVICE_ID_BINARY: {
        "main": {
            "motionSensor": {"motion": {"value": "active"}},
            "contactSensor": {"contact": {"value": "open"}},
            "waterSensor": {"water": {"value": "dry"}},
            "presenceSensor": {"presence": {"value": "present"}},
            "smokeDetector": {"smoke": {"value": "clear"}},
        }
    },
    MOCK_DEVICE_ID_CLIMATE: {
        "main": {
            "thermostatMode": {"thermostatMode": {"value": "cool"}},
            "thermostatCoolingSetpoint": {"coolingSetpoint": {"value": 23.0}},
            "thermostatHeatingSetpoint": {"heatingSetpoint": {"value": 19.5}},
            "temperatureMeasurement": {"temperature": {"value": 24.0, "unit": "C"}},
        }
    },
    MOCK_DEVICE_ID_LOCK: {
        "main": {
            "lock": {"lock": {"value": "locked"}},
        }
    },
}


class MockAiohttpResponse:
    """Mock aiohttp response object with async context manager support."""

    def __init__(
        self,
        status: int = 200,
        json_data: Any = None,
        text_data: str = "",
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self.content_type = content_type

    async def json(self) -> Any:
        return self._json_data

    async def text(self) -> str:
        return self._text_data

    async def __aenter__(self) -> MockAiohttpResponse:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        pass


@pytest.fixture
def mock_session() -> MagicMock:
    """Fixture for mocked aiohttp ClientSession."""
    session = MagicMock()
    return session
