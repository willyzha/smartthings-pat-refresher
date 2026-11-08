"""Tests for RotatorServer SmartThings Dashboard endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from rotator.dashboard import SmartThingsDashboardClient
from rotator.server import RotatorServer
from rotator.storage import TokenStorage


@pytest.fixture
async def dashboard_client_and_app(tmp_path):
    token_file = tmp_path / "pat.txt"
    storage = TokenStorage(token_file=token_file)

    dashboard = SmartThingsDashboardClient(storage_state_file=tmp_path / "session.json")
    dashboard.devices = {
        "dev-1": {
            "deviceId": "dev-1",
            "name": "Washer",
            "capabilities": ["washerJobState"],
        }
    }
    dashboard.device_status = {
        "dev-1": {"washerJobState": {"value": "wash", "componentId": "main"}}
    }

    server = RotatorServer(
        storage=storage,
        dashboard_client=dashboard,
    )
    return server, dashboard


@pytest.mark.asyncio
async def test_dashboard_endpoints(dashboard_client_and_app):
    server, dashboard = dashboard_client_and_app
    app = server.app

    async with TestClient(TestServer(app)) as client:
        # GET /dashboard/health
        resp = await client.get("/dashboard/health")
        assert resp.status == 200
        health = await resp.json()
        assert "connected" in health
        assert "devices_count" in health
        assert health["devices_count"] == 1

        # GET /dashboard/devices
        resp = await client.get("/dashboard/devices")
        assert resp.status == 200
        data = await resp.json()
        assert data["count"] == 1
        assert data["devices"][0]["name"] == "Washer"

        # GET /dashboard/devices/{device_id}/status
        resp = await client.get("/dashboard/devices/dev-1/status")
        assert resp.status == 200
        st = await resp.json()
        assert st["deviceId"] == "dev-1"
        assert st["state"]["washerJobState"] == "wash"

        # GET /dashboard/devices/unknown/status -> 404
        resp = await client.get("/dashboard/devices/unknown/status")
        assert resp.status == 404

        # POST /dashboard/devices/{device_id}/command
        dashboard.async_send_command = AsyncMock(return_value={"status": "OK"})
        resp = await client.post(
            "/dashboard/devices/dev-1/command",
            json={"capability": "switch", "command": "on"},
        )
        assert resp.status == 200
        res = await resp.json()
        assert res["status"] == "success"
        dashboard.async_send_command.assert_awaited_once_with(
            device_id="dev-1",
            capability="switch",
            command="on",
            arguments=[],
            component_id="main",
        )
