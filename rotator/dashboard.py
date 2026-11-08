"""SmartThings Consumer Dashboard Socket.IO Client.

Connects to wss://my.smartthings.com/socket.io/ using the 30-day persistent cake_session cookie.
Receives real-time push events, fetches device states, and sends control commands.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp

from .const import DEFAULT_STORAGE_STATE_FILE

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL = "https://my.smartthings.com/location"
WS_BASE_URL = "wss://my.smartthings.com/socket.io/"


class DashboardError(Exception):
    """Base error for dashboard client."""


class DashboardAuthError(DashboardError):
    """Authentication failed or session expired."""


class SmartThingsDashboardClient:
    """Maintains a persistent FeathersJS Socket.IO connection to my.smartthings.com."""

    def __init__(
        self,
        storage_state_file: Path | str = DEFAULT_STORAGE_STATE_FILE,
        on_event: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.storage_state_file = Path(storage_state_file)
        self.on_event = on_event
        self._listeners: list[Callable[[str, dict[str, Any]], Any]] = []
        if on_event:
            self._listeners.append(on_event)
        self._running = False
        self._connected = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._msg_id = 0

        # Cached data
        self.location_id: str | None = None
        self.devices: dict[str, dict[str, Any]] = {}
        self.device_status: dict[str, dict[str, Any]] = {}
        self.device_health: dict[str, str] = {}
        self._pending_responses: dict[int, asyncio.Future[Any]] = {}
        self._cake_expires: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None and not self._ws.closed

    def get_health(self) -> dict[str, Any]:
        """Return status metrics for the dashboard connection."""
        now = time.time()
        days_left = max(0.0, (self._cake_expires - now) / 86400) if self._cake_expires else 0.0
        return {
            "connected": self.is_connected,
            "devices_count": len(self.devices),
            "location_id": self.location_id,
            "session_valid": days_left > 0 or self._connected,
            "cake_session_expires": self._cake_expires,
            "days_left": round(days_left, 1),
        }

    def add_listener(self, listener: Callable[[str, dict[str, Any]], Any]) -> None:
        """Register a callback for device state changes."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, dict[str, Any]], Any]) -> None:
        """Unregister a callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self, dev_id: str, state: dict[str, Any]) -> None:
        """Notify all registered listeners of a state change."""
        for cb in list(self._listeners):
            try:
                res = cb(dev_id, state)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                _LOGGER.debug("Error in state change listener: %s", e)

    def get_device_flat_state(self, device_id: str) -> dict[str, Any]:
        """Return a flat dictionary of attribute values for a device."""
        st = self.device_status.get(device_id, {})
        flat: dict[str, Any] = {}
        for key, data in st.items():
            if isinstance(data, dict) and "value" in data:
                flat[key] = data["value"]
            else:
                flat[key] = data
        return flat

    def _extract_cookies_and_expiry(self) -> tuple[str, float]:
        """Extract cookie header string and expiration timestamp from storage_state.json."""
        if not self.storage_state_file.is_file():
            raise DashboardAuthError(f"Session file not found: {self.storage_state_file}")

        try:
            state = json.loads(self.storage_state_file.read_text(encoding="utf-8"))
            cookies = state.get("cookies", [])
            cake_exp = 0.0
            cookie_parts = []
            for c in cookies:
                cookie_parts.append(f"{c['name']}={c['value']}")
                if c.get("name") == "cake_session":
                    exp = c.get("expires", 0)
                    if exp > 0:
                        cake_exp = float(exp)

            self._cake_expires = cake_exp
            return "; ".join(cookie_parts), cake_exp
        except Exception as err:
            raise DashboardAuthError(f"Failed to read storage state: {err}") from err

    async def _fetch_csrf_token(self, cookie_str: str) -> str:
        """Fetch csrfToken from my.smartthings.com HTML."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
            "Cookie": cookie_str,
            "Origin": "https://my.smartthings.com",
        }
        assert self._session is not None
        async with self._session.get(DASHBOARD_URL, headers=headers, allow_redirects=False) as resp:
            if resp.status in (301, 302, 307):
                loc = resp.headers.get("Location", "")
                if "login" in loc or "signin" in loc:
                    raise DashboardAuthError(
                        "my.smartthings.com session expired (redirected to login). "
                        "Run './scripts/interactive_login.sh' to re-authenticate."
                    )
            if resp.status != 200:
                raise DashboardError(f"HTTP error fetching dashboard HTML: {resp.status}")

            text = await resp.text()
            # Extract csrfToken
            match = re.search(r'csrfToken:\s*["\']([^"\']+)["\']', text)
            if not match:
                idx = text.find('csrfToken: "')
                if idx != -1:
                    end = text.find('"', idx + 12)
                    return text[idx + 12 : end]
                raise DashboardError("csrfToken not found in my.smartthings.com HTML.")
            return match.group(1)

    async def _send_frame(self, frame: str) -> None:
        """Send raw frame over active WebSocket."""
        if self._ws and not self._ws.closed:
            await self._ws.send_str(frame)

    async def _call_service(
        self, method: str, service: str, *args: Any, timeout: float = 15.0
    ) -> Any:
        """Send a FeathersJS service request frame and await response."""
        self._msg_id += 1
        msg_id = self._msg_id
        payload = [method, service] + list(args)
        frame = f"42{msg_id}{json.dumps(payload, separators=(',', ':'))}"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending_responses[msg_id] = fut

        await self._send_frame(frame)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_responses.pop(msg_id, None)

    async def async_send_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        arguments: list[Any] | None = None,
        component_id: str = "main",
    ) -> Any:
        """Send device control command over Socket.IO."""
        cmd_payload = {
            "deviceId": device_id,
            "componentId": component_id,
            "capability": capability,
            "command": command,
            "arguments": arguments or [],
        }
        _LOGGER.info(
            "Sending SmartThings command to %s: %s.%s(%s)",
            device_id,
            capability,
            command,
            arguments,
        )
        res = await self._call_service("create", "api/command", cmd_payload, {})
        # Optimistically update cached attribute
        if capability == "switch":
            self.device_status.setdefault(device_id, {})["switch"] = {"value": command}
        elif capability == "lock":
            self.device_status.setdefault(device_id, {})["lock"] = {
                "value": "locked" if command == "lock" else "unlocked"
            }
        return res

    async def async_extend_session(self) -> Any:
        """Extend 30-day session by calling api/auth.create({ extend: True })."""
        _LOGGER.info("Calling api/auth.create to extend 30-day dashboard session...")
        try:
            res = await self._call_service(
                "create",
                "api/auth",
                {"extend": True, "stayLoggedIn": True, "sessionLength": 2592000},
                {},
            )
            _LOGGER.info("Extended session result: %s", res)
            return res
        except Exception as err:
            _LOGGER.warning("Could not extend session: %s", err)
            return None

    def _parse_incoming_frame(self, payload: str) -> None:
        """Parse Socket.IO / Engine.IO frame from server."""
        if not payload:
            return

        # 1. Engine.IO ping -> reply pong 3
        if payload == "2":
            asyncio.create_task(self._send_frame("3"))
            return

        # 2. Socket.IO ACK response: 43<id>[null, <result>]
        if payload.startswith("43"):
            idx = payload.find("[")
            if idx != -1:
                try:
                    msg_id = int(payload[2:idx])
                    data = json.loads(payload[idx:])
                    # data format: [err, result]
                    err, result = data[0], data[1] if len(data) > 1 else None
                    if msg_id in self._pending_responses:
                        fut = self._pending_responses[msg_id]
                        if not fut.done():
                            if err:
                                fut.set_exception(DashboardError(str(err)))
                            else:
                                fut.set_result(result)
                except Exception as exc:
                    _LOGGER.debug("Error parsing ACK frame: %s", exc)
            return

        # 3. Server event push: 42[event_name, data]
        if payload.startswith("42"):
            idx = payload.find("[")
            if idx != -1:
                try:
                    data = json.loads(payload[idx:])
                    event_name = data[0] if len(data) > 0 else ""
                    event_data = data[1] if len(data) > 1 else {}
                    self._handle_server_event(event_name, event_data)
                except Exception as exc:
                    _LOGGER.debug("Error parsing event frame: %s", exc)

    def _handle_server_event(self, event_name: str, event_data: Any) -> None:
        """Handle real-time push events from SmartThings server."""
        if "DEVICE_EVENT" in event_name or "SPIGOT_EVENT" in event_name:
            # Extract device updates
            update_data = event_data.get("data") if isinstance(event_data, dict) else event_data
            if isinstance(update_data, dict):
                dev_id = update_data.get("deviceId")
                cap = update_data.get("capability")
                attr = update_data.get("attribute")
                val = update_data.get("value")
                unit = update_data.get("unit")
                comp = update_data.get("componentId", "main")
                if dev_id and attr:
                    key = attr if comp in ("main", None, "") else f"{comp}_{attr}"
                    st = self.device_status.setdefault(dev_id, {})
                    st[key] = {
                        "value": val,
                        "unit": unit,
                        "capability": cap,
                        "componentId": comp,
                        "timestamp": time.time(),
                    }
                    _LOGGER.debug("Live state update: %s -> %s = %s", dev_id, key, val)
                    self._notify_listeners(dev_id, self.get_device_flat_state(dev_id))

    def _parse_devices_payload(self, raw_data: list[dict[str, Any]]) -> None:
        """Normalize raw device objects from 435 api/device query."""
        for item in raw_data:
            dev_id = item.get("deviceId")
            name = item.get("label") or item.get("name") or item.get("deviceName")

            # Handle complexCloud / cloud / basic nested wrappers
            for wrapper_key in ("complexCloud", "cloud", "basic"):
                if not dev_id and wrapper_key in item and isinstance(item[wrapper_key], dict):
                    wrapper = item[wrapper_key]
                    dev_id = wrapper.get("deviceId")
                    name = (
                        wrapper.get("deviceName")
                        or wrapper.get("name")
                        or wrapper.get("label")
                        or name
                    )
                    caps = wrapper.get("capabilities", [])
                    break
            else:
                caps = item.get("capabilities", [])

            if dev_id and name:
                self.devices[dev_id] = {
                    "deviceId": dev_id,
                    "name": name,
                    "label": item.get("label", name),
                    "locationId": item.get("locationId", self.location_id),
                    "roomId": item.get("roomId"),
                    "capabilities": caps,
                }
        _LOGGER.info("Parsed %d SmartThings devices from dashboard.", len(self.devices))

    def _parse_status_payload(self, raw_status: list[dict[str, Any]]) -> None:
        """Normalize raw attribute list from 433 api/device/status query."""
        for item in raw_status:
            dev_id = item.get("deviceId")
            attr = item.get("attributeName")
            val = item.get("value")
            unit = item.get("unit")
            cap = item.get("capabilityId")
            comp = item.get("componentId", "main")
            if dev_id and attr:
                key = attr if comp in ("main", None, "") else f"{comp}_{attr}"
                st = self.device_status.setdefault(dev_id, {})
                st[key] = {
                    "value": val,
                    "unit": unit,
                    "capability": cap,
                    "componentId": comp,
                    "timestamp": item.get("timestamp"),
                }

    async def _reader_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Continuously read and process frames from WebSocket."""
        extend_counter = 0
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._parse_incoming_frame(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

            extend_counter += 1
            if extend_counter >= 860:
                extend_counter = 0
                asyncio.create_task(self.async_extend_session())

    async def _run_loop(self) -> None:
        """Main loop managing connection, sync, and event listening."""
        while self._running:
            try:
                cookie_str, _ = self._extract_cookies_and_expiry()
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()

                _LOGGER.info("Connecting to my.smartthings.com dashboard...")
                csrf_token = await self._fetch_csrf_token(cookie_str)
                ws_url = (
                    f"{WS_BASE_URL}?csrfToken={csrf_token}"
                    "&x-st-client-os=unknown&x-st-client-appversion=unknown"
                    "&x-st-client-devicemodel=unknown&lang=en-US&EIO=4&transport=websocket"
                )
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    ),
                    "Cookie": cookie_str,
                    "Origin": "https://my.smartthings.com",
                }

                async with self._session.ws_connect(ws_url, headers=headers) as ws:
                    self._ws = ws
                    self._connected = True
                    _LOGGER.info("Connected to SmartThings Socket.IO WebSocket!")

                    # Start reader task to process frames concurrently while initializing
                    reader_task = asyncio.create_task(self._reader_loop(ws))

                    try:
                        # 1. Handshake: Send 40
                        await self._send_frame("40")
                        await asyncio.sleep(0.2)

                        # 2. Authenticate
                        auth_res = await self._call_service("authenticate", {})
                        _LOGGER.info(
                            "Authenticated dashboard session for: %s",
                            auth_res.get("user", {}).get("userName", "User"),
                        )

                        # 3. Find locations
                        locations = await self._call_service("find", "api/location", {})
                        if locations and isinstance(locations, list) and len(locations) > 0:
                            self.location_id = locations[0].get("locationId")
                            _LOGGER.info(
                                "Active Location: %s (%s)",
                                locations[0].get("name"),
                                self.location_id,
                            )

                        if self.location_id:
                            # 4. Fetch Devices
                            dev_res = await self._call_service(
                                "find",
                                "api/device",
                                {"locationId": self.location_id, "locale": {"language": "en"}},
                            )
                            raw_devs = (
                                dev_res.get("data", []) if isinstance(dev_res, dict) else dev_res
                            )
                            if isinstance(raw_devs, list):
                                self._parse_devices_payload(raw_devs)

                            # 5. Fetch Full Status Dump
                            status_res = await self._call_service(
                                "find",
                                "api/device/status",
                                {"locationId": self.location_id, "deviceIds": None},
                            )
                            if isinstance(status_res, list):
                                self._parse_status_payload(status_res)
                                _LOGGER.info(
                                    "Loaded full status for %d devices.", len(self.device_status)
                                )

                            # 6. Fetch Health
                            health_res = await self._call_service(
                                "find", "api/device/health", {"locationId": self.location_id}
                            )
                            if isinstance(health_res, list):
                                for h in health_res:
                                    if "deviceId" in h:
                                        self.device_health[h["deviceId"]] = h.get("state", "ONLINE")

                            # 7. Subscribe to Live Push Events
                            await self._call_service(
                                "create",
                                "api/subscription",
                                {"locationId": self.location_id, "filters": []},
                                {},
                            )
                            _LOGGER.info("Subscribed to live device events successfully!")

                            # 8. Notify initial state
                            for dev_id in self.device_status:
                                self._notify_listeners(dev_id, self.get_device_flat_state(dev_id))

                        # Await reader task until disconnect
                        await reader_task
                    finally:
                        if not reader_task.done():
                            reader_task.cancel()
                            try:
                                await reader_task
                            except asyncio.CancelledError:
                                pass

            except DashboardAuthError as err:
                _LOGGER.error("Dashboard auth failed: %s", err)
                self._connected = False
                await asyncio.sleep(60)  # Wait 1 minute before retrying
            except Exception as err:
                _LOGGER.warning("Dashboard connection dropped (%s). Reconnecting in 10s...", err)
                self._connected = False
                await asyncio.sleep(10)
            finally:
                self._connected = False

    def start(self) -> None:
        """Start the background dashboard client task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop client and disconnect."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        self._connected = False
