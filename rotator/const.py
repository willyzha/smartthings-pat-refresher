"""Constants for SmartThings PAT Rotator."""

from pathlib import Path

DEFAULT_TOKENS_URL = "https://account.smartthings.com/tokens"
DEFAULT_ROTATION_INTERVAL_HOURS = 20
DEFAULT_DATA_DIR = Path("data")
DEFAULT_SESSION_DIR = DEFAULT_DATA_DIR / "session"
DEFAULT_TOKEN_FILE = DEFAULT_DATA_DIR / "smartthings_pat.txt"
DEFAULT_METADATA_FILE = DEFAULT_DATA_DIR / "pat_metadata.json"
DEFAULT_SERVER_PORT = 8765
DEFAULT_SERVER_HOST = "0.0.0.0"
TOKEN_PREFIX = "HA_AutoPAT_"
SMARTTHINGS_API_BASE = "https://api.smartthings.com/v1"
