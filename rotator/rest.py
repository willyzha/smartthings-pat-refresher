"""Direct REST API client for account.smartthings.com token management."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from .const import (
    DEFAULT_COOKIES_FILE,
    SMARTTHINGS_ACCOUNT_API,
    TOKEN_PREFIX,
)
from .storage import TokenStorage

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCOPES: list[str] = [
    "r:locations:*",
    "w:locations:*",
    "x:locations:*",
    "r:devices:*",
    "w:devices:*",
    "x:devices:*",
    "r:scenes:*",
    "x:scenes:*",
    "r:rules:*",
    "r:apps:*",
    "w:apps:*",
    "r:installedapps:*",
    "w:installedapps:*",
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class RestRotatorError(Exception):
    """Base exception for REST API rotator operations."""


class RestAuthExpiredError(RestRotatorError):
    """Cookies or session expired on account.smartthings.com."""


def extract_cookies_and_xsrf(cookie_data: str) -> tuple[str, str]:
    """Parse raw cookie data (header format or JSON) and extract cookie string and XSRF token."""
    raw = cookie_data.strip()
    if len(raw) < 260 and Path(raw).is_file():
        raw = Path(raw).read_text(encoding="utf-8").strip()

    cookie_dict: dict[str, str] = {}

    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            cookie_list = parsed if isinstance(parsed, list) else [parsed]
            for c in cookie_list:
                name = c.get("name")
                val = c.get("value")
                if name and val is not None:
                    cookie_dict[name.strip()] = str(val).strip()
        except Exception as err:
            raise RestRotatorError(f"Could not parse cookie JSON: {err}") from err
    else:
        for item in raw.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                k_clean = k.strip()
                if k_clean:
                    cookie_dict[k_clean] = v.strip()

    if not cookie_dict:
        raise RestRotatorError("No valid cookies found in input.")

    cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
    xsrf_token = cookie_dict.get("XSRF-TOKEN") or cookie_dict.get("xsrf-token") or ""

    return cookie_header, xsrf_token


class SmartThingsRestClient:
    """Manages Personal Access Tokens directly via account.smartthings.com internal endpoints."""

    def __init__(
        self,
        storage: TokenStorage | None = None,
        cookies_file: Path | str = DEFAULT_COOKIES_FILE,
    ) -> None:
        """Initialize client."""
        self.storage = storage or TokenStorage()
        self.cookies_file = Path(cookies_file)

    def get_stored_cookies(self) -> str | None:
        """Read saved cookie string from cookies file."""
        if self.cookies_file.is_file():
            content = self.cookies_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        return None

    def save_cookies(self, cookie_data: str) -> None:
        """Persist cookies securely to disk."""
        self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
        raw = cookie_data.strip()
        self.cookies_file.write_text(raw + "\n", encoding="utf-8")
        self.cookies_file.chmod(0o600)

    async def async_list_tokens(self, cookie_data: str | None = None) -> list[dict[str, Any]]:
        """List all PATs on account.smartthings.com."""
        raw_cookies = cookie_data or self.get_stored_cookies()
        if not raw_cookies:
            raise RestRotatorError("No cookies available to list tokens.")

        cookie_header, xsrf_token = extract_cookies_and_xsrf(raw_cookies)
        headers = {
            "Cookie": cookie_header,
            "X-XSRF-TOKEN": xsrf_token,
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        timeout = ClientTimeout(total=15)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(SMARTTHINGS_ACCOUNT_API, headers=headers) as resp:
                if resp.status in (401, 403):
                    raise RestAuthExpiredError(
                        f"Authentication expired (HTTP {resp.status}). Fresh cookies required."
                    )
                if resp.status != 200:
                    text = await resp.text()
                    raise RestRotatorError(f"Failed to list tokens (HTTP {resp.status}): {text}")
                return await resp.json()

    async def async_create_token(
        self,
        cookie_data: str | None = None,
        token_name: str | None = None,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a fresh PAT on account.smartthings.com and return response dict."""
        raw_cookies = cookie_data or self.get_stored_cookies()
        if not raw_cookies:
            raise RestRotatorError("No cookies available to create token.")

        cookie_header, xsrf_token = extract_cookies_and_xsrf(raw_cookies)
        name = token_name or f"{TOKEN_PREFIX}{int(time.time())}"
        token_scopes = scopes or DEFAULT_SCOPES

        payload = {
            "deviceId": str(uuid.uuid4()),
            "deviceName": name,
            "scope": token_scopes,
        }

        headers = {
            "Cookie": cookie_header,
            "X-XSRF-TOKEN": xsrf_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        timeout = ClientTimeout(total=20)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                SMARTTHINGS_ACCOUNT_API, json=payload, headers=headers
            ) as resp:
                if resp.status in (401, 403):
                    raise RestAuthExpiredError(
                        f"Authentication expired (HTTP {resp.status}). Fresh cookies required."
                    )
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise RestRotatorError(f"Failed to create token (HTTP {resp.status}): {text}")

                data = await resp.json()
                if not data.get("accessToken"):
                    raise RestRotatorError(f"No accessToken in response: {data}")
                return data

    async def async_delete_token(
        self,
        auth_key: str,
        cookie_data: str | None = None,
    ) -> bool:
        """Delete a token by authKey."""
        raw_cookies = cookie_data or self.get_stored_cookies()
        if not raw_cookies:
            raise RestRotatorError("No cookies available to delete token.")

        cookie_header, xsrf_token = extract_cookies_and_xsrf(raw_cookies)
        url = f"{SMARTTHINGS_ACCOUNT_API}/{auth_key}"
        headers = {
            "Cookie": cookie_header,
            "X-XSRF-TOKEN": xsrf_token,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
        }

        timeout = ClientTimeout(total=15)
        async with ClientSession(timeout=timeout) as session:
            async with session.delete(url, headers=headers) as resp:
                return resp.status in (200, 204)

    async def async_cleanup_old_tokens(
        self,
        cookie_data: str | None = None,
        current_auth_key: str | None = None,
        prefix: str = TOKEN_PREFIX,
    ) -> int:
        """Best-effort cleanup of previously rotated tokens matching prefix."""
        try:
            tokens = await self.async_list_tokens(cookie_data=cookie_data)
            deleted = 0
            for item in tokens:
                dev_name = item.get("deviceName", "")
                auth_key = item.get("authKey", "")
                if (
                    auth_key
                    and dev_name.startswith(prefix)
                    and auth_key != current_auth_key
                ):
                    _LOGGER.info(
                        "Cleaning up old rotated PAT '%s' (authKey: %s...)",
                        dev_name,
                        auth_key[:8],
                    )
                    if await self.async_delete_token(auth_key=auth_key, cookie_data=cookie_data):
                        deleted += 1
            return deleted
        except Exception as err:
            _LOGGER.debug("Non-critical cleanup error: %s", err)
            return 0

    async def async_rotate(
        self,
        cookie_data: str | None = None,
        token_name: str | None = None,
    ) -> str:
        """Execute instantaneous REST rotation and save new token to storage."""
        name = token_name or f"{TOKEN_PREFIX}{int(time.time())}"
        _LOGGER.info("Executing REST PAT rotation for '%s'...", name)

        result = await self.async_create_token(cookie_data=cookie_data, token_name=name)
        access_token: str = result["accessToken"]
        auth_key: str = result.get("sanitizedToken", {}).get("authKey", "")

        # Save to disk
        self.storage.save_token(token=access_token, token_name=name)

        # Cleanup older tokens matching TOKEN_PREFIX
        await self.async_cleanup_old_tokens(
            cookie_data=cookie_data,
            current_auth_key=auth_key,
        )

        return access_token
