"""Lightweight HTTP token server and transparent reverse proxy for SmartThings PAT."""

from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import ClientSession, web

from .browser import SmartThingsBrowserRotator
from .const import (
    DEFAULT_ROTATION_INTERVAL_HOURS,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    SMARTTHINGS_API_BASE,
)
from .storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


class RotatorServer:
    """Lightweight token server & transparent reverse proxy (< 15MB RAM)."""

    def __init__(
        self,
        storage: TokenStorage | None = None,
        rotator: SmartThingsBrowserRotator | None = None,
        host: str = DEFAULT_SERVER_HOST,
        port: int = DEFAULT_SERVER_PORT,
        rotation_interval_hours: int = DEFAULT_ROTATION_INTERVAL_HOURS,
    ) -> None:
        """Initialize server."""
        self.storage = storage or TokenStorage()
        self.rotator = rotator or SmartThingsBrowserRotator(storage=self.storage)
        self.host = host
        self.port = port
        self.rotation_interval_hours = rotation_interval_hours
        self.app = web.Application()
        self._session: ClientSession | None = None
        self._background_task: asyncio.Task | None = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register routes."""
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/token", self.handle_get_token)
        self.app.router.add_post("/rotate", self.handle_post_rotate)

        # Transparent reverse proxy to SmartThings API
        self.app.router.add_route("*", "/v1/{path:.*}", self.handle_proxy)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health and token validity status."""
        meta = self.storage.get_metadata() or {}
        now = time.time()
        expires_at = meta.get("expires_at", 0)
        hours_left = max(0.0, (expires_at - now) / 3600)
        return web.json_response(
            {
                "status": "healthy",
                "token_available": self.storage.get_token() is not None,
                "created_at": meta.get("created_at"),
                "expires_at": expires_at,
                "hours_left": round(hours_left, 2),
                "expiring_soon": self.storage.is_expiring_soon(
                    leeway_seconds=(24 - self.rotation_interval_hours) * 3600
                ),
            }
        )

    async def handle_get_token(self, request: web.Request) -> web.Response:
        """Retrieve the current active Personal Access Token."""
        token = self.storage.get_token()
        if not token:
            return web.json_response(
                {"error": "No token available. Run rotation or setup first."},
                status=404,
            )

        if request.query.get("format") == "raw":
            return web.Response(text=token, content_type="text/plain")

        meta = self.storage.get_metadata() or {}
        return web.json_response(
            {
                "token": token,
                "created_at": meta.get("created_at"),
                "expires_at": meta.get("expires_at"),
            }
        )

    async def handle_post_rotate(self, request: web.Request) -> web.Response:
        """Trigger an immediate headless token rotation."""
        try:
            new_token = await self.rotator.async_rotate()
            return web.json_response(
                {
                    "status": "success",
                    "token": new_token,
                    "message": "Rotated successfully.",
                }
            )
        except Exception as err:
            _LOGGER.exception("Rotation failed: %s", err)
            return web.json_response({"error": str(err)}, status=500)

    async def handle_proxy(self, request: web.Request) -> web.StreamResponse:
        """Transparent reverse proxy to https://api.smartthings.com/v1/{path}."""
        token = self.storage.get_token()
        if not token:
            return web.Response(text="Proxy error: No active SmartThings PAT", status=503)

        path = request.match_info.get("path", "")
        target_url = f"{SMARTTHINGS_API_BASE}/{path}"

        headers = dict(request.headers)
        # Inject fresh Bearer token
        headers["Authorization"] = f"Bearer {token}"
        headers.pop("Host", None)

        body = await request.read()

        if self._session is None:
            self._session = ClientSession()

        try:
            async with self._session.request(
                request.method,
                target_url,
                headers=headers,
                params=request.query,
                data=body if body else None,
            ) as resp:
                resp_headers = dict(resp.headers)
                # Remove hop-by-hop headers
                for h in ("Transfer-Encoding", "Content-Encoding", "Connection"):
                    resp_headers.pop(h, None)

                content = await resp.read()
                return web.Response(
                    body=content,
                    status=resp.status,
                    headers=resp_headers,
                )
        except Exception as err:
            _LOGGER.error("Proxy forwarding error: %s", err)
            return web.Response(text=f"Proxy forwarding error: {err}", status=502)

    async def _rotation_loop(self) -> None:
        """Periodic background task that checks and rotates tokens ahead of expiration."""
        _LOGGER.info(
            "Background PAT rotation worker started (target interval: every %dh).",
            self.rotation_interval_hours,
        )
        while True:
            try:
                # Rotate if token has fewer than (24 - rotation_interval_hours) hours remaining
                leeway = (24 - self.rotation_interval_hours) * 3600
                if self.storage.is_expiring_soon(leeway_seconds=leeway):
                    _LOGGER.info("Token due for rotation. Launching headless browser...")
                    await self.rotator.async_rotate()
            except Exception as err:
                _LOGGER.error("Background rotation worker encountered error: %s", err)

            # Check every 10 minutes
            await asyncio.sleep(600)

    async def start(self) -> None:
        """Start HTTP server and background rotation task."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        _LOGGER.info("SmartThings PAT Rotator server running at http://%s:%s", self.host, self.port)

        self._background_task = asyncio.create_task(self._rotation_loop())
        try:
            await asyncio.Event().wait()
        finally:
            if self._background_task:
                self._background_task.cancel()
            if self._session:
                await self._session.close()
            await runner.cleanup()
