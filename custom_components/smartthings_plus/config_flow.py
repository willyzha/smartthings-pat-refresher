"""Config flow for SmartThings Plus integration."""

from __future__ import annotations

import logging
from typing import Any

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

from .api import SmartThingsApiClient, SmartThingsApiError, SmartThingsAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ROTATOR_URL,
    DEFAULT_ROTATOR_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SmartThingsPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartThings Plus."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Configure integration using the SmartThings PAT Rotator URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            rotator_url = user_input[CONF_ROTATOR_URL].strip().rstrip("/")
            session = async_get_clientsession(self.hass)
            client = SmartThingsApiClient(session=session, rotator_url=rotator_url)

            try:
                # 1. Verify rotator endpoint & fetch active PAT
                await client.async_fetch_token_from_rotator()

                # 2. Verify connection to SmartThings REST API
                await client.async_get_devices()

                return self.async_create_entry(
                    title="SmartThings Plus",
                    data={
                        CONF_ROTATOR_URL: rotator_url,
                        CONF_ACCESS_TOKEN: client.access_token,
                    },
                )
            except SmartThingsAuthError as err:
                _LOGGER.warning("Authentication error with rotator: %s", err)
                if "no active token" in str(err).lower():
                    errors["base"] = "no_token"
                else:
                    errors["base"] = "cannot_connect"
            except SmartThingsApiError as err:
                _LOGGER.warning("SmartThings API error: %s", err)
                errors["base"] = "api_error"
            except Exception as err:
                _LOGGER.exception("Unexpected error connecting to rotator: %s", err)
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_ROTATOR_URL, default=DEFAULT_ROTATOR_URL): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
