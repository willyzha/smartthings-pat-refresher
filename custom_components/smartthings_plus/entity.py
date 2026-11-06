"""Base entity class for SmartThings Plus."""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
except ImportError:
    # Standalone mock shim
    class CoordinatorEntity:  # type: ignore[no-redef]
        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

        @property
        def available(self) -> bool:
            return True

    class DeviceInfo:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

from .const import DOMAIN
from .coordinator import SmartThingsDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class SmartThingsEntity(CoordinatorEntity):
    """Base entity for SmartThings Plus."""

    _attr_unique_id: str | None = None
    _attr_name: str | None = None

    def __init__(
        self,
        coordinator: SmartThingsDataUpdateCoordinator,
        device_id: str,
        component_id: str = "main",
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device_id = device_id
        self.component_id = component_id

    @property
    def unique_id(self) -> str | None:
        """Return unique ID."""
        return self._attr_unique_id

    @property
    def name(self) -> str | None:
        """Return entity name."""
        return self._attr_name

    @property
    def device_entry(self) -> dict[str, Any]:
        """Return raw device metadata."""
        return self.coordinator.data.get(self.device_id, {}).get("device", {})

    @property
    def device_status(self) -> dict[str, Any]:
        """Return current status of all components for this device."""
        return self.coordinator.data.get(self.device_id, {}).get("status", {})

    @property
    def component_status(self) -> dict[str, Any]:
        """Return status for this specific component."""
        return self.device_status.get(self.component_id, {})

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device_id in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        device = self.device_entry
        name = device.get("label") or device.get("name") or "SmartThings Device"
        manufacturer = (
            device.get("manufacturerName")
            or device.get("deviceManufacturerCode")
            or "SmartThings"
        )
        model = (
            device.get("deviceModel")
            or device.get("deviceTypeName")
            or device.get("presentationId")
            or "SmartThings Plus Device"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=name,
            manufacturer=manufacturer,
            model=model,
        )

    def get_attribute_value(self, capability: str, attribute: str) -> Any:
        """Helper to get capability attribute value safely."""
        cap_data = self.component_status.get(capability, {})
        attr_data = cap_data.get(attribute, {})
        return attr_data.get("value")

    async def async_execute_command(
        self,
        capability: str,
        command: str,
        arguments: list[Any] | None = None,
    ) -> None:
        """Execute a command on the device and request coordinator refresh."""
        await self.coordinator.client.async_execute_device_command(
            device_id=self.device_id,
            capability=capability,
            command=command,
            arguments=arguments,
            component=self.component_id,
        )
        await self.coordinator.async_request_refresh()
