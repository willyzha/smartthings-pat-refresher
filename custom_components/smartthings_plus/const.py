"""Constants for the SmartThings Plus integration."""

DOMAIN = "smartthings_plus"

PLATFORMS = [
    "switch",
    "light",
    "sensor",
    "binary_sensor",
    "climate",
    "lock",
]

# SmartThings Endpoints
SMARTTHINGS_API_BASE = "https://api.smartthings.com/v1"

# Configuration Keys
CONF_ROTATOR_URL = "rotator_url"
CONF_ACCESS_TOKEN = "access_token"
CONF_SCAN_INTERVAL = "scan_interval"

# Timing and Connection Defaults
DEFAULT_ROTATOR_URL = "http://smartthings-pat-rotator:8765"
DEFAULT_SCAN_INTERVAL = 30  # seconds between device status polls
DEFAULT_TOKEN_REFRESH_LEEWAY = 7200  # renew 2 hours before 24h expiration
