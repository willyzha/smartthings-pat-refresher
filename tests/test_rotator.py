"""Unit tests for SmartThings PAT Rotator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from rotator.browser import SmartThingsBrowserRotator
from rotator.server import RotatorServer
from rotator.storage import TokenStorage


def test_token_storage_lifecycle(tmp_path) -> None:
    """Test saving, retrieving, and expiration checks for PAT tokens."""
    token_file = tmp_path / "smartthings_pat.txt"
    metadata_file = tmp_path / "pat_metadata.json"

    storage = TokenStorage(token_file=token_file, metadata_file=metadata_file)

    assert storage.get_token() is None
    assert storage.is_expiring_soon() is True

    # Save fresh token
    test_token = "mock-pat-token-abcdef-123456"
    meta = storage.save_token(test_token, token_name="HA_AutoPAT_1", ttl_seconds=86400)

    assert storage.get_token() == test_token
    assert meta["token"] == test_token
    assert meta["expires_at"] > time.time() + 80000

    # With 2-hour leeway, an 86400s token is NOT expiring soon
    assert storage.is_expiring_soon(leeway_seconds=7200) is False

    # But with 86500s leeway, it IS expiring soon
    assert storage.is_expiring_soon(leeway_seconds=86500) is True


class TestRotatorServer(AioHTTPTestCase):
    """Integration test suite for the lightweight token server & proxy."""

    async def get_application(self) -> web.Application:
        """Create test application."""
        self.mock_storage = MagicMock(spec=TokenStorage)
        self.mock_storage.get_token.return_value = "pat-token-xyz-987"
        self.mock_storage.get_metadata.return_value = {
            "token": "pat-token-xyz-987",
            "token_name": "HA_AutoPAT_test",
            "created_at": time.time(),
            "expires_at": time.time() + 36000,
        }
        self.mock_storage.is_expiring_soon.return_value = False

        self.mock_rotator = MagicMock(spec=SmartThingsBrowserRotator)
        self.mock_rotator.async_rotate = AsyncMock(return_value="pat-token-newly-rotated-111")

        self.server = RotatorServer(
            storage=self.mock_storage,
            rotator=self.mock_rotator,
        )
        return self.server.app

    @pytest.mark.asyncio
    async def test_health_endpoint(self) -> None:
        """Test GET /health returns token status and validity."""
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "healthy"
        assert data["token_available"] is True
        assert data["hours_left"] > 0

    @pytest.mark.asyncio
    async def test_get_token_json_and_raw(self) -> None:
        """Test GET /token returns JSON and raw text."""
        # JSON format
        resp = await self.client.request("GET", "/token")
        assert resp.status == 200
        data = await resp.json()
        assert data["token"] == "pat-token-xyz-987"

        # Raw text format
        resp_raw = await self.client.request("GET", "/token?format=raw")
        assert resp_raw.status == 200
        text = await resp_raw.text()
        assert text == "pat-token-xyz-987"

    @pytest.mark.asyncio
    async def test_rotate_endpoint(self) -> None:
        """Test POST /rotate triggers browser rotator."""
        resp = await self.client.request("POST", "/rotate")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "success"
        assert data["token"] == "pat-token-newly-rotated-111"
        assert self.mock_rotator.async_rotate.called
