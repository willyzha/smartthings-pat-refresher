"""PAT Rotation engine with direct REST and Playwright browser automation fallback."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .const import (
    DEFAULT_COOKIES_FILE,
    DEFAULT_SESSION_DIR,
    DEFAULT_STORAGE_STATE_FILE,
    DEFAULT_TOKENS_URL,
    TOKEN_PREFIX,
)
from .rest import (
    RestAuthExpiredError,
    RestRotatorError,
    SmartThingsRestClient,
    extract_cookies_and_xsrf,
)
from .storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


class RotatorError(Exception):
    """Base error for PAT Rotator."""


class SessionExpiredError(RotatorError):
    """Samsung account session expired, re-authentication needed."""


class SmartThingsBrowserRotator:
    """Automates SmartThings PAT rotation via fast REST API with Playwright browser fallback."""

    def __init__(
        self,
        session_dir: Path | str = DEFAULT_SESSION_DIR,
        cookies_file: Path | str = DEFAULT_COOKIES_FILE,
        storage_state_file: Path | str = DEFAULT_STORAGE_STATE_FILE,
        storage: TokenStorage | None = None,
    ) -> None:
        """Initialize rotator."""
        self.session_dir = Path(session_dir)
        self.cookies_file = Path(cookies_file)
        self.storage_state_file = Path(storage_state_file)
        self.storage = storage or TokenStorage()
        self.rest_client = SmartThingsRestClient(
            storage=self.storage, cookies_file=self.cookies_file
        )

    async def async_interactive_setup(self) -> None:
        """Run headed browser for initial Samsung login and 2FA approval."""
        from playwright.async_api import async_playwright

        self.session_dir.mkdir(parents=True, exist_ok=True)
        print("\n=======================================================")
        print("  SmartThings PAT Rotator - Initial Setup")
        print("=======================================================")
        print("Opening Chromium browser...")
        print("1. Sign in to your Samsung Account.")
        print("2. Complete 2-Step Verification (SMS or prompt on Galaxy device).")
        print("3. Check 'Trust this browser' / 'Stay signed in' if prompted.")
        print("4. Once you see the 'Personal Access Tokens' page, close the browser.")
        print("=======================================================\n")

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.session_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(DEFAULT_TOKENS_URL)

            print("Waiting for authentication to complete...")
            try:
                await page.wait_for_url("**/tokens**", timeout=300000)  # 5 minutes
                await page.wait_for_load_state("networkidle", timeout=30000)
                print("\n[SUCCESS] Successfully authenticated with SmartThings!")

                # Extract full storage state and cookies
                try:
                    await context.storage_state(path=str(self.storage_state_file))
                    _LOGGER.info("Saved portable SSO storage state to %s", self.storage_state_file)
                except Exception as exc:
                    _LOGGER.debug("Could not export storage state: %s", exc)

                cookies = await context.cookies(["https://account.smartthings.com"])
                if cookies:
                    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    self.rest_client.save_cookies(cookie_header)
                    _LOGGER.info(
                        "Exported %d cookies from browser to %s",
                        len(cookies),
                        self.cookies_file,
                    )

            except Exception as err:
                print(f"\n[INFO] Window closed or timed out: {err}")
            finally:
                await context.close()

    async def async_import_cookies(self, cookie_data: str) -> None:
        """Import cookies from string or file, test via REST, and mint first PAT."""
        raw = cookie_data.strip()
        if len(raw) < 260 and Path(raw).is_file():
            raw = Path(raw).read_text(encoding="utf-8").strip()

        # Parse & validate format
        cookie_header, _ = extract_cookies_and_xsrf(raw)

        # Save to cookies file
        self.rest_client.save_cookies(cookie_header)
        _LOGGER.info("Saved cookies to %s", self.cookies_file)

        # Test immediately via REST API
        try:
            print("Verifying session with SmartThings API...")
            new_token = await self.rest_client.async_rotate()
            masked = f"{new_token[:8]}...{new_token[-4:]}"
            print(f"\n[SUCCESS] Session verified! Minted active PAT: {masked}")
        except RestAuthExpiredError as err:
            raise SessionExpiredError(
                "Provided cookies are invalid or expired on Samsung SmartThings."
            ) from err
        except RestRotatorError as err:
            raise RotatorError(f"SmartThings API error: {err}") from err

        # Also populate Playwright browser context if possible
        try:
            import json

            from playwright.async_api import async_playwright

            self.session_dir.mkdir(parents=True, exist_ok=True)
            cookies_to_add: list[dict[str, Any]] = []

            # Check if input is multi-domain JSON (Cookie-Editor or storage_state)
            if raw.startswith("[") or raw.startswith("{"):
                try:
                    parsed = json.loads(raw)
                    cookie_list = (
                        parsed
                        if isinstance(parsed, list)
                        else parsed.get("cookies", [parsed])
                    )
                    for c in cookie_list:
                        if isinstance(c, dict) and "name" in c and "value" in c:
                            entry = {
                                "name": str(c["name"]).strip(),
                                "value": str(c["value"]).strip(),
                                "domain": str(c.get("domain", "account.smartthings.com")).strip(),
                                "path": str(c.get("path", "/")).strip(),
                            }
                            if "expirationDate" in c:
                                entry["expires"] = int(c["expirationDate"])
                            elif "expires" in c:
                                entry["expires"] = int(c["expires"])
                            if "httpOnly" in c:
                                entry["httpOnly"] = bool(c["httpOnly"])
                            if "secure" in c:
                                entry["secure"] = bool(c["secure"])
                            if "sameSite" in c:
                                ss = str(c["sameSite"]).lower()
                                if ss in ("strict", "lax"):
                                    entry["sameSite"] = ss.capitalize()
                                elif ss in ("none", "no_restriction"):
                                    entry["sameSite"] = "None"
                            cookies_to_add.append(entry)
                except Exception as err:
                    _LOGGER.debug("JSON cookie parsing exception: %s", err)

            if not cookies_to_add:
                for item in cookie_header.split(";"):
                    if "=" in item:
                        k, v = item.strip().split("=", 1)
                        if k.strip():
                            cookies_to_add.append(
                                {
                                    "name": k.strip(),
                                    "value": v.strip(),
                                    "domain": "account.smartthings.com",
                                    "path": "/",
                                }
                            )

            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.session_dir),
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                await context.add_cookies(cookies_to_add)
                await context.storage_state(path=str(self.storage_state_file))
                await context.close()
                _LOGGER.info(
                    "Synced %d cookies into persistent session and %s",
                    len(cookies_to_add),
                    self.storage_state_file,
                )
        except Exception as err:
            _LOGGER.debug("Playwright cookie cache sync skipped: %s", err)

    async def async_rotate(
        self,
        headless: bool = True,
        token_name: str | None = None,
    ) -> str:
        """Rotate PAT. Uses fast REST API first, falling back to Playwright if needed."""
        name = token_name or f"{TOKEN_PREFIX}{int(time.time())}"

        # 1. Primary engine: Direct REST API (instantaneous, lightweight)
        if self.cookies_file.is_file():
            try:
                _LOGGER.info("Attempting REST API rotation...")
                return await self.rest_client.async_rotate(token_name=name)
            except RestAuthExpiredError as err:
                _LOGGER.warning("REST session cookies expired: %s. Falling back to browser...", err)
            except Exception as err:
                _LOGGER.warning("REST rotation error: %s. Falling back to browser...", err)

        # 2. Secondary engine: Headless browser automation via Playwright
        if not self.session_dir.exists():
            raise SessionExpiredError(
                "No session found. Please import cookies or run 'smartthings-pat-rotator setup'."
            )

        _LOGGER.info("Starting headless Playwright PAT rotation for '%s'...", name)
        return await self._async_playwright_rotate(headless=headless, token_name=name)

    async def _async_playwright_rotate(
        self,
        headless: bool = True,
        token_name: str | None = None,
    ) -> str:
        """Execute Playwright browser automation fallback."""
        from playwright.async_api import async_playwright

        name = token_name or f"{TOKEN_PREFIX}{int(time.time())}"

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.session_dir),
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )

            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(DEFAULT_TOKENS_URL, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=30000)

                if "signin" in page.url or "login" in page.url:
                    raise SessionExpiredError(
                        "Samsung login session expired. Please re-authenticate or import cookies."
                    )

                generate_btn = page.locator(
                    "button:has-text('Generate new token'), a:has-text('Generate new token')"
                ).first
                await generate_btn.wait_for(state="visible", timeout=15000)
                await generate_btn.click()

                token_input = page.locator(
                    "input[name='tokenName'], "
                    "input[placeholder*='Token Name'], "
                    "input[id*='tokenName']"
                ).first
                await token_input.wait_for(state="visible", timeout=10000)
                await token_input.fill(name)

                checkboxes = page.locator("input[type='checkbox']")
                count = await checkboxes.count()
                for i in range(count):
                    cb = checkboxes.nth(i)
                    if not await cb.is_checked():
                        await cb.check()

                submit_btn = page.locator(
                    "button[type='submit'], "
                    "button:has-text('Generate token'), "
                    "button:has-text('Save')"
                ).first
                await submit_btn.click()

                token_display = page.locator(
                    "input[readonly], code, pre, .token-value, input[value*='-']"
                ).first
                await token_display.wait_for(state="visible", timeout=15000)

                token_val = (
                    await token_display.input_value()
                    if await token_display.evaluate("el => el.tagName") == "INPUT"
                    else await token_display.inner_text()
                )

                token = token_val.strip()
                if not token or len(token) < 20:
                    raise RotatorError(f"Unexpected token value extracted: '{token}'")

                self.storage.save_token(token=token, token_name=name)

                # Export fresh cookies and full storage state if available
                try:
                    await context.storage_state(path=str(self.storage_state_file))
                except Exception as exc:
                    _LOGGER.debug("Could not export storage state: %s", exc)

                cookies = await context.cookies(["https://account.smartthings.com"])
                if cookies:
                    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    self.rest_client.save_cookies(cookie_header)

                return token

            finally:
                await context.close()


SmartThingsRotator = SmartThingsBrowserRotator
