"""Config flow for SmartThings Refresher integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientSession, ClientTimeout

try:
    import voluptuous as vol
    from homeassistant import config_entries
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:
    # Shim for standalone test environment
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

from .const import CONF_ROTATOR_URL, DEFAULT_ROTATOR_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SMARTTHINGS_LOCATIONS_API = "https://api.smartthings.com/v1/locations"


class SmartThingsRefresherConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartThings Refresher."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Configure integration using the SmartThings PAT Rotator URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            rotator_url = user_input[CONF_ROTATOR_URL].rstrip("/")

            session = (
                async_get_clientsession(self.hass)
                if hasattr(self, "hass") and self.hass
                else None
            )

            close_session = False
            if session is None:
                session = ClientSession()
                close_session = True

            try:
                # 1. Verify connection to the PAT rotator server
                timeout = ClientTimeout(total=10)
                async with session.get(
                    f"{rotator_url}/token?format=raw", timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        errors["base"] = "cannot_connect"
                        return self._show_user_form(user_input, errors)
                    token = (await resp.text()).strip()

                if not token or len(token) < 20:
                    errors["base"] = "invalid_token"
                    return self._show_user_form(user_input, errors)

                # 2. Verify token against SmartThings API
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                }
                async with session.get(
                    SMARTTHINGS_LOCATIONS_API,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status in (401, 403):
                        errors["base"] = "invalid_token"
                        return self._show_user_form(user_input, errors)
                    if resp.status != 200:
                        errors["base"] = "cannot_connect"
                        return self._show_user_form(user_input, errors)

                    locations_data = await resp.json()
                    items = locations_data.get("items", [])
                    loc_name = items[0].get("name", "Home") if items else "Home"

                return self.async_create_entry(
                    title=f"SmartThings ({loc_name})",
                    data={
                        CONF_ROTATOR_URL: rotator_url,
                    },
                )

            except Exception as err:
                _LOGGER.error("Failed to connect to SmartThings or Rotator: %s", err)
                errors["base"] = "cannot_connect"
            finally:
                if close_session:
                    await session.close()

        return self._show_user_form(user_input, errors)

    def _show_user_form(
        self, user_input: dict[str, Any] | None, errors: dict[str, str]
    ) -> dict[str, Any]:
        """Show the configuration form."""
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ROTATOR_URL,
                    default=(
                        user_input.get(CONF_ROTATOR_URL, DEFAULT_ROTATOR_URL)
                        if user_input
                        else DEFAULT_ROTATOR_URL
                    ),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
