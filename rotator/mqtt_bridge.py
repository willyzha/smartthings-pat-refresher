"""Home Assistant MQTT Discovery Bridge for SmartThings Dashboard Client.

Publishes Home Assistant MQTT Discovery configurations for SmartThings devices
(Washer, Dryer, Refrigerator, Range, Lock, Air Quality, Plugs, Switches)
and maintains bidirectional state synchronization without any custom Python in HA.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

import aiomqtt

if TYPE_CHECKING:
    from .dashboard import SmartThingsDashboardClient

_LOGGER = logging.getLogger(__name__)

# Standard capability / attribute mappings to Home Assistant entities
ENTITY_MAPPINGS: dict[str, dict[str, Any]] = {
    # Temperature
    "temperature": {
        "component": "sensor",
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": "°F",
        "icon": "mdi:thermometer",
    },
    "coolingSetpoint": {
        "component": "sensor",
        "device_class": "temperature",
        "unit_of_measurement": "°F",
        "icon": "mdi:thermometer-chevron-up",
    },
    "heatingSetpoint": {
        "component": "sensor",
        "device_class": "temperature",
        "unit_of_measurement": "°F",
        "icon": "mdi:thermometer-chevron-down",
    },
    "refrigerationSetpoint": {
        "component": "sensor",
        "device_class": "temperature",
        "unit_of_measurement": "°F",
        "icon": "mdi:thermometer",
    },
    # Humidity
    "humidity": {
        "component": "sensor",
        "device_class": "humidity",
        "state_class": "measurement",
        "unit_of_measurement": "%",
        "icon": "mdi:water-percent",
    },
    # Battery
    "battery": {
        "component": "sensor",
        "device_class": "battery",
        "state_class": "measurement",
        "unit_of_measurement": "%",
    },
    # Air Quality & Dust
    "fineDustLevel": {
        "component": "sensor",
        "name_suffix": "PM2.5",
        "device_class": "pm25",
        "state_class": "measurement",
        "unit_of_measurement": "µg/m³",
        "icon": "mdi:blur",
    },
    "dustLevel": {
        "component": "sensor",
        "name_suffix": "PM10",
        "device_class": "pm10",
        "state_class": "measurement",
        "unit_of_measurement": "µg/m³",
        "icon": "mdi:blur",
    },
    "veryFineDustLevel": {
        "component": "sensor",
        "name_suffix": "PM1.0",
        "device_class": "pm1",
        "state_class": "measurement",
        "unit_of_measurement": "µg/m³",
        "icon": "mdi:blur",
    },
    "airQualityHealthConcern": {
        "component": "sensor",
        "name_suffix": "Air Quality Health Concern",
        "icon": "mdi:shield-alert-outline",
    },
    "airQuality": {
        "component": "sensor",
        "name_suffix": "Air Quality",
        "icon": "mdi:air-filter",
    },
    "carbonDioxide": {
        "component": "sensor",
        "name_suffix": "Carbon Dioxide",
        "device_class": "carbon_dioxide",
        "state_class": "measurement",
        "unit_of_measurement": "ppm",
        "icon": "mdi:molecule-co2",
    },
    "carbonDioxideHealthConcern": {
        "component": "sensor",
        "name_suffix": "CO2 Health Concern",
        "icon": "mdi:shield-alert-outline",
    },
    "fineDustHealthConcern": {
        "component": "sensor",
        "name_suffix": "Dust Health Concern",
        "icon": "mdi:shield-alert-outline",
    },
    # Appliances: Washer & Dryer
    "washerJobState": {
        "component": "sensor",
        "name_suffix": "Job State",
        "icon": "mdi:washing-machine",
    },
    "washerMode": {
        "component": "sensor",
        "name_suffix": "Mode",
        "icon": "mdi:washing-machine",
    },
    "dryerJobState": {
        "component": "sensor",
        "name_suffix": "Job State",
        "icon": "mdi:tumble-dryer",
    },
    "dryerMode": {
        "component": "sensor",
        "name_suffix": "Mode",
        "icon": "mdi:tumble-dryer",
    },
    "machineState": {
        "component": "sensor",
        "name_suffix": "Machine State",
        "icon": "mdi:power-cycle",
    },
    "completionTime": {
        "component": "sensor",
        "name_suffix": "Completion Time",
        "device_class": "timestamp",
        "icon": "mdi:clock-end",
    },
    # Range / Oven / Cooktop
    "ovenOperatingState": {
        "component": "sensor",
        "name_suffix": "Oven Operating State",
        "icon": "mdi:stove",
    },
    "cooktopOperatingState": {
        "component": "sensor",
        "name_suffix": "Cooktop Operating State",
        "icon": "mdi:stove",
    },
    # Energy & Power
    "power": {
        "component": "sensor",
        "device_class": "power",
        "state_class": "measurement",
        "unit_of_measurement": "W",
    },
    "energy": {
        "component": "sensor",
        "device_class": "energy",
        "state_class": "total_increasing",
        "unit_of_measurement": "kWh",
    },
    # Binary sensors
    "contact": {
        "component": "binary_sensor",
        "device_class": "door",
        "payload_on": "open",
        "payload_off": "closed",
    },
    "door": {
        "component": "binary_sensor",
        "device_class": "door",
        "payload_on": "open",
        "payload_off": "closed",
    },
    "doorState": {
        "component": "binary_sensor",
        "device_class": "door",
        "payload_on": "open",
        "payload_off": "closed",
    },
    "motion": {
        "component": "binary_sensor",
        "device_class": "motion",
        "payload_on": "active",
        "payload_off": "inactive",
    },
    "presence": {
        "component": "binary_sensor",
        "device_class": "presence",
        "payload_on": "present",
        "payload_off": "not present",
    },
    "water": {
        "component": "binary_sensor",
        "device_class": "moisture",
        "payload_on": "wet",
        "payload_off": "dry",
    },
    "smoke": {
        "component": "binary_sensor",
        "device_class": "smoke",
        "payload_on": "detected",
        "payload_off": "clear",
    },
    "carbonMonoxide": {
        "component": "binary_sensor",
        "device_class": "gas",
        "payload_on": "detected",
        "payload_off": "clear",
    },
    # Controls
    "switch": {
        "component": "switch",
        "command_topic_suffix": "switch/set",
        "payload_on": "on",
        "payload_off": "off",
        "state_on": "on",
        "state_off": "off",
    },
    "lock": {
        "component": "lock",
        "command_topic_suffix": "lock/set",
        "payload_lock": "LOCK",
        "payload_unlock": "UNLOCK",
        "state_locked": "locked",
        "state_unlocked": "unlocked",
    },
}

IGNORED_ATTRIBUTES = {
    "supportedModes",
    "supportedCourses",
    "supportedCycles",
    "supportedAcModes",
    "supportedFanModes",
    "supportedThermostatFanModes",
    "supportedPrograms",
    "supportedSteps",
    "optionalCourseData",
    "data",
    "apiVersion",
    "ocf",
}


def _split_camel_case(s: str) -> str:
    """Convert camelCase string to Title Case string."""
    # e.g. washerJobState -> Washer Job State
    subbed = re.sub(r"([A-Z])", r" \1", s)
    return subbed.replace("_", " ").title().strip()


def _clean_entity_name(device_name: str, suffix: str) -> str:
    """Clean entity name suffix by removing redundant device name prefix if present."""
    if not device_name or not suffix:
        return suffix

    # Direct case-insensitive prefix match
    if suffix.lower().startswith(device_name.lower()):
        remainder = suffix[len(device_name) :].strip(" -_:")
        if remainder:
            return remainder

    # Word-based prefix match (e.g. normalized whitespace/punctuation)
    d_words = device_name.lower().split()
    s_words = suffix.split()
    idx = 0
    while idx < len(d_words) and idx < len(s_words) and d_words[idx] == s_words[idx].lower():
        idx += 1
    if idx > 0 and idx == len(d_words):
        remainder = " ".join(s_words[idx:]).strip(" -_:")
        if remainder:
            return remainder

    return suffix


def _normalize_unit(unit: str | None) -> str | None:
    """Normalize unit string to Home Assistant standard unit."""
    if not unit or not isinstance(unit, str):
        return None
    u = unit.strip()
    if u in ("C", "c", "°C", "degC", "degreesC"):
        return "°C"
    if u in ("F", "f", "°F", "degF", "degreesF"):
        return "°F"
    if u in ("μg/m^3", "ug/m3", "µg/m3", "μg/m³"):
        return "µg/m³"
    if u in ("ppm", "PPM"):
        return "ppm"
    if u in ("%", "percent"):
        return "%"
    return u


class SmartThingsMQTTBridge:
    """Home Assistant MQTT Discovery Bridge for SmartThings."""

    def __init__(
        self,
        dashboard_client: SmartThingsDashboardClient,
        mqtt_host: str,
        mqtt_port: int = 1883,
        mqtt_username: str | None = None,
        mqtt_password: str | None = None,
        topic_prefix: str = "smartthings",
        discovery_prefix: str = "homeassistant",
    ) -> None:
        self.dashboard_client = dashboard_client
        self.host = mqtt_host
        self.port = mqtt_port
        self.username = mqtt_username
        self.password = mqtt_password
        self.topic_prefix = topic_prefix.rstrip("/")
        self.discovery_prefix = discovery_prefix.rstrip("/")

        self._running = False
        self._connected = False
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._discovered_entities: set[str] = set()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def start(self) -> None:
        """Start background MQTT bridge loop."""
        if not self._running:
            self._running = True
            # Register listener on dashboard client
            self.dashboard_client.add_listener(self._on_dashboard_event)
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop MQTT bridge."""
        self._running = False
        self.dashboard_client.remove_listener(self._on_dashboard_event)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False
        self._client = None

    def _on_dashboard_event(self, device_id: str, flat_state: dict[str, Any]) -> None:
        """Callback from SmartThingsDashboardClient when device state updates."""
        if self.is_connected:
            asyncio.create_task(self._sync_device(device_id, flat_state))

    async def _safe_publish(
        self, topic: str, payload: str, retain: bool = False, qos: int = 0
    ) -> None:
        """Publish an MQTT message safely."""
        if not self.is_connected or not self._client:
            return
        try:
            await self._client.publish(topic, payload, retain=retain, qos=qos)
        except Exception as err:
            _LOGGER.debug("MQTT publish failed (%s): %s", topic, err)

    async def _sync_device(self, device_id: str, flat_state: dict[str, Any]) -> None:
        """Ensure device discovery configs are published, then publish state."""
        dev_info = self.dashboard_client.devices.get(device_id, {})
        dev_name = dev_info.get("name") or dev_info.get("label") or f"SmartThings {device_id[:8]}"

        # 1. Discover any newly seen attributes or capabilities
        await self._discover_device_entities(device_id, dev_name, dev_info, flat_state)

        # 2. Publish state payload
        state_topic = f"{self.topic_prefix}/{device_id}/state"
        payload = json.dumps(flat_state)
        await self._safe_publish(state_topic, payload, retain=True)

    async def _discover_device_entities(
        self,
        device_id: str,
        device_name: str,
        device_info: dict[str, Any],
        flat_state: dict[str, Any],
    ) -> None:
        """Generate and publish Home Assistant MQTT discovery configs."""
        sw_ver = (
            flat_state.get("version")
            or flat_state.get("currentVersion")
            or flat_state.get("versionNumber")
        )
        device_dict: dict[str, Any] = {
            "identifiers": [f"smartthings_{device_id}"],
            "name": device_name,
            "manufacturer": "Samsung SmartThings",
            "model": "SmartThings Device",
        }
        if sw_ver and isinstance(sw_ver, (str, int)):
            device_dict["sw_version"] = str(sw_ver)

        # Check capabilities (e.g. switch, lock)
        caps = [
            c if isinstance(c, str) else c.get("id", "")
            for c in device_info.get("capabilities", [])
        ]
        if "switch" in caps and "switch" not in flat_state:
            flat_state = dict(flat_state)
            flat_state.setdefault("switch", "off")
        if "lock" in caps and "lock" not in flat_state:
            flat_state = dict(flat_state)
            flat_state.setdefault("lock", "unlocked")

        for key, val in flat_state.items():
            if key in IGNORED_ATTRIBUTES or isinstance(val, (dict, list)):
                continue

            entity_id = f"{device_id}_{key}"
            if entity_id in self._discovered_entities:
                continue

            # Determine base attribute name if prefixed by component
            base_attr = key.split("_", 1)[-1] if "_" in key else key
            mapping = ENTITY_MAPPINGS.get(base_attr, {})

            component = mapping.get("component")
            if not component:
                # Infer type
                if isinstance(val, bool):
                    component = "binary_sensor"
                else:
                    component = "sensor"

            # Build config payload
            raw_suffix = mapping.get("name_suffix") or _split_camel_case(key)
            name = _clean_entity_name(device_name, raw_suffix)
            unique_id = f"smartthings_{device_id}_{key}"

            config: dict[str, Any] = {
                "name": name,
                "has_entity_name": True,
                "unique_id": unique_id,
                "state_topic": f"{self.topic_prefix}/{device_id}/state",
                "availability_topic": f"{self.topic_prefix}/status",
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_dict,
            }

            # Check if SmartThings provided a unit in device_status
            raw_unit = None
            st_device = getattr(self.dashboard_client, "device_status", {}).get(device_id, {})
            if isinstance(st_device, dict):
                attr_entry = st_device.get(key)
                if isinstance(attr_entry, dict):
                    raw_unit = attr_entry.get("unit")
                if not raw_unit and "_" in key:
                    base_k = key.split("_", 1)[-1]
                    attr_entry_base = st_device.get(base_k)
                    if isinstance(attr_entry_base, dict):
                        raw_unit = attr_entry_base.get("unit")

            normalized_unit = _normalize_unit(raw_unit)

            if component == "sensor":
                config["value_template"] = f"{{{{ value_json.{key} }}}}"
                if "device_class" in mapping:
                    config["device_class"] = mapping["device_class"]
                if "state_class" in mapping:
                    config["state_class"] = mapping["state_class"]
                elif normalized_unit and isinstance(val, (int, float)):
                    config["state_class"] = "measurement"

                unit = normalized_unit or mapping.get("unit_of_measurement")
                if unit:
                    config["unit_of_measurement"] = unit

                if "icon" in mapping:
                    config["icon"] = mapping["icon"]

            elif component == "binary_sensor":
                config["value_template"] = f"{{{{ value_json.{key} }}}}"
                if "device_class" in mapping:
                    config["device_class"] = mapping["device_class"]
                config["payload_on"] = mapping.get("payload_on", True)
                config["payload_off"] = mapping.get("payload_off", False)

            elif component == "switch":
                config["value_template"] = f"{{{{ value_json.{key} }}}}"
                config["command_topic"] = f"{self.topic_prefix}/{device_id}/switch/set"
                config["payload_on"] = "on"
                config["payload_off"] = "off"
                config["state_on"] = "on"
                config["state_off"] = "off"
                config["icon"] = "mdi:power"

            elif component == "lock":
                config["value_template"] = f"{{{{ value_json.{key} }}}}"
                config["command_topic"] = f"{self.topic_prefix}/{device_id}/lock/set"
                config["payload_lock"] = "LOCK"
                config["payload_unlock"] = "UNLOCK"
                config["state_locked"] = "locked"
                config["state_unlocked"] = "unlocked"

            disc_topic = f"{self.discovery_prefix}/{component}/smartthings_{unique_id}/config"
            _LOGGER.info("Publishing Home Assistant MQTT discovery for %s (%s)", name, disc_topic)
            await self._safe_publish(disc_topic, json.dumps(config), retain=True)
            self._discovered_entities.add(entity_id)

    async def _publish_all_discoveries_and_states(self) -> None:
        """Publish discovery and state for all currently known devices."""
        for dev_id in list(self.dashboard_client.devices.keys()):
            flat_state = self.dashboard_client.get_device_flat_state(dev_id)
            await self._sync_device(dev_id, flat_state)

    async def _handle_mqtt_message(self, message: aiomqtt.Message) -> None:
        """Handle incoming command messages from Home Assistant on smartthings/+/+/set."""
        try:
            topic_str = str(message.topic)
            parts = topic_str.split("/")
            # Expected format: <topic_prefix>/<device_id>/<capability>/set
            if len(parts) < 4 or parts[-1] != "set":
                return

            device_id = parts[1]
            capability = parts[2]
            payload_str = message.payload.decode("utf-8").strip() if message.payload else ""

            _LOGGER.info(
                "Received MQTT command for %s.%s: '%s'", device_id, capability, payload_str
            )

            if capability == "switch":
                cmd = "on" if payload_str.lower() in ("on", "1", "true") else "off"
                await self.dashboard_client.async_send_command(device_id, "switch", cmd)
                # Optimistically update and publish state
                state = self.dashboard_client.get_device_flat_state(device_id)
                state["switch"] = cmd
                await self._safe_publish(
                    f"{self.topic_prefix}/{device_id}/state", json.dumps(state), retain=True
                )

            elif capability == "lock":
                cmd = (
                    "lock"
                    if "lock" in payload_str.lower() and "un" not in payload_str.lower()
                    else "unlock"
                )
                await self.dashboard_client.async_send_command(device_id, "lock", cmd)
                # Optimistically update and publish state
                state = self.dashboard_client.get_device_flat_state(device_id)
                state["lock"] = "locked" if cmd == "lock" else "unlocked"
                await self._safe_publish(
                    f"{self.topic_prefix}/{device_id}/state", json.dumps(state), retain=True
                )

            else:
                await self.dashboard_client.async_send_command(device_id, capability, payload_str)

        except Exception as err:
            _LOGGER.error("Failed to handle MQTT message: %s", err)

    async def _run_loop(self) -> None:
        """Main connection and message processing loop."""
        while self._running:
            try:
                will = aiomqtt.Will(
                    topic=f"{self.topic_prefix}/status",
                    payload="offline",
                    retain=True,
                )
                _LOGGER.info("Connecting to MQTT broker at %s:%s...", self.host, self.port)
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    will=will,
                ) as client:
                    self._client = client
                    self._connected = True
                    _LOGGER.info("Connected to MQTT broker successfully!")

                    # Publish online status
                    await client.publish(f"{self.topic_prefix}/status", "online", retain=True)

                    # Subscribe to command topics
                    cmd_topic = f"{self.topic_prefix}/+/+/set"
                    await client.subscribe(cmd_topic)
                    _LOGGER.info("Subscribed to MQTT command topic: %s", cmd_topic)

                    # Publish discovery and initial states
                    await self._publish_all_discoveries_and_states()

                    # Message loop
                    async for message in client.messages:
                        await self._handle_mqtt_message(message)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.warning("MQTT bridge connection dropped (%s). Retrying in 10s...", err)
                self._connected = False
                self._client = None
                await asyncio.sleep(10)
            finally:
                self._connected = False
                self._client = None
