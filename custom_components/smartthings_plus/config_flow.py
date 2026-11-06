"""Config flow for SmartThings Plus integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:
    # Shim for standalone environment
    class vol:  # type: ignore[no-redef]
        @staticmethod
        def Schema(schema_dict: Any) -> Any:
            return schema_dict

        @staticmethod
        def Required(key: str, default: Any = None) -> str:
            return key

        @staticmethod
        def Optional(key: str, default: Any = None) -> str:
            return key

    class config_entries:  # type: ignore[no-redef]
        class ConfigFlow:
            def __init_subclass__(cls, domain: str = "") -> None:
                cls.DOMAIN = domain

            def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
                return {"type": "form", **kwargs}

            def async_create_entry(self, **kwargs: Any) -> dict[str, Any]:
                return {"type": "create_entry", **kwargs}

    def async_get_clientsession(hass: Any) -> Any:
        return None

from .api import SmartThingsApiClient, SmartThingsAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_CODE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPIRES_AT,
    CONF_REDIRECT_URI,
    CONF_REFRESH_TOKEN,
    DEFAULT_REDIRECT_URI,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SmartThingsPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartThings Plus."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._redirect_uri: str = DEFAULT_REDIRECT_URI
        self._auth_url: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Step 1: Collect OAuth Client ID and Secret."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID].strip()
            self._client_secret = user_input[CONF_CLIENT_SECRET].strip()
            self._redirect_uri = user_input.get(CONF_REDIRECT_URI, DEFAULT_REDIRECT_URI).strip()

            self._auth_url = SmartThingsApiClient.build_authorization_url(
                client_id=self._client_id,
                redirect_uri=self._redirect_uri,
            )
            return await self.async_step_auth_code()

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
                vol.Optional(CONF_REDIRECT_URI, default=DEFAULT_REDIRECT_URI): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_auth_code(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Step 2: User approves OAuth in browser and submits the code or redirect URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw_code = user_input[CONF_AUTH_CODE].strip()
            code = self._extract_code(raw_code)

            try:
                session = async_get_clientsession(self.hass)
                client = SmartThingsApiClient(
                    session=session,
                    client_id=self._client_id,  # type: ignore[arg-type]
                    client_secret=self._client_secret,  # type: ignore[arg-type]
                )
                tokens = await client.async_exchange_auth_code(code, self._redirect_uri)

                # Verify connection by listing devices
                await client.async_get_devices()

                return self.async_create_entry(
                    title="SmartThings Plus",
                    data={
                        CONF_CLIENT_ID: self._client_id,
                        CONF_CLIENT_SECRET: self._client_secret,
                        CONF_REDIRECT_URI: self._redirect_uri,
                        CONF_ACCESS_TOKEN: tokens["access_token"],
                        CONF_REFRESH_TOKEN: tokens["refresh_token"],
                        CONF_EXPIRES_AT: client.expires_at,
                    },
                )
            except SmartThingsAuthError:
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error during SmartThings token exchange: %s", err)
                errors["base"] = "cannot_connect"

        schema = vol.Schema({vol.Required(CONF_AUTH_CODE): str})

        return self.async_show_form(
            step_id="auth_code",
            data_schema=schema,
            errors=errors,
            description_placeholders={"auth_url": self._auth_url},
        )

    @staticmethod
    def _extract_code(raw_input: str) -> str:
        """Extract authorization code whether user pasted full URL or just the code."""
        if "?" in raw_input or "code=" in raw_input:
            parsed = urlparse(raw_input)
            params = parse_qs(parsed.query)
            if "code" in params and params["code"]:
                return params["code"][0]
        return raw_input
