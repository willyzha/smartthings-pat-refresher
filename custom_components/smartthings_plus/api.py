"""SmartThings REST API client powered by the local PAT Rotator."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import aiohttp

from .const import (
    DEFAULT_TOKEN_REFRESH_LEEWAY,
    SMARTTHINGS_API_BASE,
)

_LOGGER = logging.getLogger(__name__)


class SmartThingsAuthError(Exception):
    """Authentication or token retrieval failure."""


class SmartThingsApiError(Exception):
    """SmartThings API request error."""


class SmartThingsApiClient:
    """Client for querying SmartThings REST API using auto-rotated PATs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rotator_url: str,
        access_token: str | None = None,
        expires_at: float = 0.0,
        on_token_refreshed: Callable[[str, float], Any] | None = None,
    ) -> None:
        """Initialize API client."""
        self._session = session
        self.rotator_url = rotator_url.rstrip("/")
        self.access_token = access_token
        self.expires_at = expires_at
        self.on_token_refreshed = on_token_refreshed

    async def async_fetch_token_from_rotator(self) -> dict[str, Any]:
        """Fetch the active Personal Access Token from the companion rotator service."""
        url = f"{self.rotator_url}/token"
        _LOGGER.debug("Fetching fresh SmartThings PAT from rotator at %s...", url)
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    raise SmartThingsAuthError(
                        "Rotator server has no active token. Run 'smartthings-pat-rotator setup'."
                    )
                if resp.status != 200:
                    err_text = await resp.text()
                    raise SmartThingsAuthError(
                        f"Failed to fetch token from rotator ({resp.status}): {err_text}"
                    )

                payload = await resp.json()
                token = payload.get("token")
                if not token:
                    raise SmartThingsAuthError("Rotator returned payload without a valid token.")

                self.access_token = token
                self.expires_at = payload.get("expires_at", time.time() + 86400)

                _LOGGER.info(
                    "Retrieved active SmartThings PAT. Valid for ~%.1f hours.",
                    (self.expires_at - time.time()) / 3600,
                )

                if self.on_token_refreshed:
                    cb_result = self.on_token_refreshed(self.access_token, self.expires_at)
                    if hasattr(cb_result, "__await__"):
                        asyncio.create_task(cb_result)

                return payload
        except aiohttp.ClientError as err:
            raise SmartThingsAuthError(f"Could not connect to PAT rotator at {url}: {err}") from err

    async def async_ensure_token_valid(self) -> None:
        """Verify token expiration and refresh from rotator ahead of time."""
        now = time.time()
        if not self.access_token or now + DEFAULT_TOKEN_REFRESH_LEEWAY >= self.expires_at:
            _LOGGER.info("Token missing or near expiration. Querying rotator for fresh token...")
            await self.async_fetch_token_from_rotator()

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Any = None,
        params: dict[str, Any] | None = None,
        retry_on_auth_err: bool = True,
    ) -> Any:
        """Make authenticated HTTP request to SmartThings API."""
        await self.async_ensure_token_valid()

        url = f"{SMARTTHINGS_API_BASE}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        async with self._session.request(
            method,
            url,
            headers=headers,
            json=data,
            params=params,
        ) as resp:
            if resp.status == 401 and retry_on_auth_err:
                _LOGGER.warning(
                    "Received 401 Unauthorized from SmartThings. Re-fetching token from rotator..."
                )
                await self.async_fetch_token_from_rotator()
                return await self._request(
                    method,
                    endpoint,
                    data=data,
                    params=params,
                    retry_on_auth_err=False,
                )

            if resp.status >= 400:
                body = await resp.text()
                raise SmartThingsApiError(f"SmartThings API request failed ({resp.status}): {body}")

            if resp.content_type == "application/json":
                return await resp.json()
            return await resp.text()

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Fetch list of all devices."""
        res = await self._request("GET", "/devices")
        if isinstance(res, dict) and "items" in res:
            return res["items"]
        return []

    async def async_get_device_status(self, device_id: str) -> dict[str, Any]:
        """Fetch current status for a specific device."""
        res = await self._request("GET", f"/devices/{device_id}/status")
        if isinstance(res, dict) and "components" in res:
            return res["components"]
        return {}

    async def async_execute_device_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        arguments: list[Any] | None = None,
        component: str = "main",
    ) -> Any:
        """Send capability command to a device."""
        payload = {
            "commands": [
                {
                    "component": component,
                    "capability": capability,
                    "command": command,
                    "arguments": arguments or [],
                }
            ]
        }
        return await self._request("POST", f"/devices/{device_id}/commands", data=payload)
