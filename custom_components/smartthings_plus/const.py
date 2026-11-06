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
SMARTTHINGS_OAUTH_TOKEN_URL = "https://api.smartthings.com/oauth/token"
SMARTTHINGS_OAUTH_AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"

# Configuration Keys
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_REDIRECT_URI = "redirect_uri"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AUTH_CODE = "auth_code"

# Timing defaults
DEFAULT_SCAN_INTERVAL = 30  # seconds between device status polls
DEFAULT_TOKEN_REFRESH_LEEWAY = 7200  # refresh 2 hours before 24h expiration
DEFAULT_REDIRECT_URI = "https://localhost"

# SmartThings OAuth Scopes
DEFAULT_SCOPES = [
    "r:devices:*",
    "w:devices:*",
    "x:devices:*",
    "r:locations:*",
    "r:scenes:*",
]
