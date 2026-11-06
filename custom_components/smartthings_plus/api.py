"""SmartThings REST and OAuth2 API client."""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Callable
from urllib.parse import urlencode

import aiohttp

from .const import (
    DEFAULT_SCOPES,
    DEFAULT_TOKEN_REFRESH_LEEWAY,
    SMARTTHINGS_API_BASE,
    SMARTTHINGS_OAUTH_AUTHORIZE_URL,
    SMARTTHINGS_OAUTH_TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)


class SmartThingsAuthError(Exception):
    """Authentication or token refresh failure."""


class SmartThingsApiError(Exception):
    """SmartThings API request error."""


class SmartThingsApiClient:
    """Client for interacting with SmartThings OAuth2 and REST APIs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float = 0.0,
        on_token_refreshed: Callable[[str, str, float], Any] | None = None,
    ) -> None:
        """Initialize API client."""
        self._session = session
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.on_token_refreshed = on_token_refreshed

    @staticmethod
    def build_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str = "smartthings_plus",
        scopes: list[str] | None = None,
    ) -> str:
        """Construct OAuth authorization URL."""
        if scopes is None:
            scopes = DEFAULT_SCOPES
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"{SMARTTHINGS_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    def _basic_auth_header(self) -> str:
        """Construct Basic Auth header for token endpoint."""
        creds = f"{self.client_id}:{self.client_secret}".encode()
        return f"Basic {base64.b64encode(creds).decode()}"

    async def async_exchange_auth_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange authorization code for initial access and refresh tokens."""
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": self._basic_auth_header(),
            "Accept": "application/json",
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
        }

        async with self._session.post(
            SMARTTHINGS_OAUTH_TOKEN_URL,
            headers=headers,
            data=data,
        ) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                _LOGGER.error("Token exchange failed (%s): %s", resp.status, err_text)
                raise SmartThingsAuthError(
                    f"OAuth code exchange failed ({resp.status}): {err_text}"
                )

            payload = await resp.json()
            self._apply_token_response(payload)
            return payload

    async def async_refresh_token(self) -> dict[str, Any]:
        """Execute rolling token refresh using the single-use refresh token."""
        if not self.refresh_token:
            raise SmartThingsAuthError("No refresh token available to renew access.")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": self._basic_auth_header(),
            "Accept": "application/json",
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
        }

        _LOGGER.debug("Requesting rolling refresh token from SmartThings...")
        async with self._session.post(
            SMARTTHINGS_OAUTH_TOKEN_URL,
            headers=headers,
            data=data,
        ) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                _LOGGER.error("Token refresh failed (%s): %s", resp.status, err_text)
                raise SmartThingsAuthError(f"Token refresh failed ({resp.status}): {err_text}")

            payload = await resp.json()
            self._apply_token_response(payload)
            _LOGGER.info(
                "SmartThings OAuth token refreshed successfully. Next expiry in ~%.1f hours.",
                (self.expires_at - time.time()) / 3600,
            )
            return payload

    def _apply_token_response(self, payload: dict[str, Any]) -> None:
        """Store returned tokens and compute expiration."""
        self.access_token = payload.get("access_token")
        # SmartThings refresh tokens are single-use; a new one is returned each refresh
        new_refresh = payload.get("refresh_token")
        if new_refresh:
            self.refresh_token = new_refresh

        expires_in = int(payload.get("expires_in", 86400))
        self.expires_at = time.time() + expires_in

        if self.on_token_refreshed:
            cb_result = self.on_token_refreshed(
                self.access_token,
                self.refresh_token,
                self.expires_at,
            )
            if hasattr(cb_result, "__await__"):
                import asyncio
                asyncio.create_task(cb_result)

    async def async_ensure_token_valid(self) -> None:
        """Verify token expiration and refresh ahead of time."""
        now = time.time()
        # Refresh if token has expired or is expiring within leeway window (e.g. 2 hours)
        if now + DEFAULT_TOKEN_REFRESH_LEEWAY >= self.expires_at:
            _LOGGER.info(
                "Token close to expiration or expired (%.1fs remaining). Renewing...",
                self.expires_at - now,
            )
            await self.async_refresh_token()

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
                    "Received 401 Unauthorized from SmartThings. Forcing token refresh..."
                )
                await self.async_refresh_token()
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
