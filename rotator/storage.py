"""Storage management for SmartThings PAT."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .const import DEFAULT_METADATA_FILE, DEFAULT_TOKEN_FILE

_LOGGER = logging.getLogger(__name__)


class TokenStorage:
    """Handles thread-safe and permission-safe persistence of PATs."""

    def __init__(
        self,
        token_file: Path | str = DEFAULT_TOKEN_FILE,
        metadata_file: Path | str = DEFAULT_METADATA_FILE,
    ) -> None:
        """Initialize storage with file paths."""
        self.token_file = Path(token_file)
        self.metadata_file = Path(metadata_file)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create parent directories if they don't exist."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

    def save_token(
        self,
        token: str,
        token_name: str,
        ttl_seconds: int = 86400,
    ) -> dict[str, Any]:
        """Save new token and metadata with secure permissions."""
        self._ensure_dirs()
        now = time.time()
        metadata = {
            "token": token,
            "token_name": token_name,
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "ttl_seconds": ttl_seconds,
        }

        # Write plaintext token file (e.g. for Home Assistant volume mount)
        self.token_file.write_text(token.strip() + "\n", encoding="utf-8")
        self.token_file.chmod(0o600)

        # Write metadata JSON
        self.metadata_file.write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        self.metadata_file.chmod(0o600)

        _LOGGER.info(
            "Saved new PAT '%s'. Valid until %s (%.1f hours)",
            token_name,
            time.ctime(metadata["expires_at"]),
            ttl_seconds / 3600,
        )
        return metadata

    def get_token(self) -> str | None:
        """Return the current active token string, if any."""
        if self.token_file.is_file():
            content = self.token_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        return None

    def get_metadata(self) -> dict[str, Any] | None:
        """Return metadata dictionary for current token."""
        if self.metadata_file.is_file():
            try:
                return json.loads(self.metadata_file.read_text(encoding="utf-8"))
            except Exception as err:
                _LOGGER.warning("Could not read PAT metadata: %s", err)
        return None

    def is_expiring_soon(self, leeway_seconds: int = 7200) -> bool:
        """Return True if token is missing, expired, or expiring within leeway."""
        meta = self.get_metadata()
        if not meta or "expires_at" not in meta:
            return True
        return time.time() + leeway_seconds >= meta["expires_at"]
