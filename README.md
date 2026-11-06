# SmartThings PAT Refresher & Rotator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

Keep using Samsung SmartThings with **Home Assistant** (and custom scripts) **for free**, even after Samsung limited Personal Access Tokens (PATs) to 24 hours and introduced a $4.99/month developer fee.

This repository provides two flexible solutions:
1. 🔄 **SmartThings PAT Auto-Rotator (`smartthings-pat-rotator`)**: A lightweight automation tool that logs into the free portal ([account.smartthings.com/tokens](https://account.smartthings.com/tokens)) once every 20 hours to auto-generate a fresh, free 24-hour PAT. **Zero resident memory between runs** and no monthly fees.
2. 🏠 **SmartThings Plus (`smartthings_plus`)**: A native Home Assistant HACS custom integration with automatic rolling OAuth2 token renewal and local polling.

---

## Solution 1: Free 24h PAT Auto-Rotator (CLI & Daemon)

The easiest way to keep using SmartThings for **$0/free** without paying Samsung's $4.99/mo fee.

### Features
- ⚡ **Zero Resident RAM**: Runs on-demand for ~15 seconds once every 20 hours to mint a new token, then completely terminates (or runs as a tiny <15MB background daemon).
- 🔐 **Persistent 2FA Session**: You log in and approve 2FA once during setup. Subsequent rotations are 100% headless and unattended.
- 🧹 **Automatic Cleanup**: Deletes expired auto-generated tokens to keep your Samsung account clean.
- 🌐 **Built-in Token Server & Transparent Reverse Proxy**:
  - `GET http://localhost:8765/token`: Returns the active valid token.
  - `GET http://localhost:8765/health`: Health status and remaining validity hours.
  - Transparent proxy at `http://localhost:8765/v1/...`: Injects the active token into requests to `https://api.smartthings.com/v1/...` so integrations never see an expired token.
  - File sink: Atomically writes the plaintext token to `data/smartthings_pat.txt` (chmod `0600`).

### Quickstart

```bash
# 1. Install dependencies & Playwright Chromium
pip install -e ".[rotator]"
playwright install chromium

# 2. One-time interactive setup (opens browser to sign in and approve 2FA once)
smartthings-pat-rotator setup

# 3. Test a one-shot rotation immediately
smartthings-pat-rotator rotate

# 4. Check current token status
smartthings-pat-rotator status
```

### Running as a Background Service

To run the background scheduler (rotates every 20 hours) and lightweight HTTP server:
```bash
smartthings-pat-rotator serve --port 8765
```

### Connecting to Home Assistant

- **Option A (File Mount)**: Mount `data/smartthings_pat.txt` into your Home Assistant directory (e.g. `/config/smartthings_pat.txt`).
- **Option B (HTTP Endpoint)**: Query `http://<host>:8765/token?format=raw` in your Home Assistant REST sensor or automation.
- **Option C (Transparent Proxy)**: Point any custom script or integration base URL to `http://<host>:8765/v1` instead of `https://api.smartthings.com/v1`.

---

## Solution 2: SmartThings Plus HACS Custom Integration

If you have a SmartThings Developer App or OAuth client credentials, `smartthings_plus` runs 100% natively inside Home Assistant with zero external servers.

### Key Features
- 🔄 **Continuous Rolling Token Renewal**: Proactively exchanges rolling refresh tokens directly inside HA.
- ⚡ **Local Polling via DataUpdateCoordinator**: Polls device status every 30s with no port forwarding or Nabu Casa needed.
- 📱 **Platforms**: Switches, lights (with 0-255 brightness scaling), sensors, binary sensors, thermostats (climate), and locks.
- 💻 **Flexible Config Flow**: UI setup supporting both redirect URLs and manual code paste.

---

## Development & Testing

```bash
# Run tests
pytest -v

# Run linter
ruff check .
```

---

## License

This project is licensed under the [MIT License](LICENSE).
