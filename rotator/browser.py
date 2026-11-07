"""Playwright browser automation for SmartThings Personal Access Tokens."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .const import DEFAULT_SESSION_DIR, DEFAULT_TOKENS_URL, TOKEN_PREFIX
from .storage import TokenStorage

_LOGGER = logging.getLogger(__name__)


class RotatorError(Exception):
    """Base error for PAT Rotator."""


class SessionExpiredError(RotatorError):
    """Samsung account session expired, re-authentication needed."""


class SmartThingsBrowserRotator:
    """Automates token creation on account.smartthings.com/tokens via Playwright."""

    def __init__(
        self,
        session_dir: Path | str = DEFAULT_SESSION_DIR,
        storage: TokenStorage | None = None,
    ) -> None:
        """Initialize browser rotator."""
        self.session_dir = Path(session_dir)
        self.storage = storage or TokenStorage()

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

            # Wait for user to complete login and navigate to tokens page
            print("Waiting for authentication to complete...")
            try:
                # Wait until URL is account.smartthings.com/tokens and page has loaded
                await page.wait_for_url("**/tokens**", timeout=300000)  # 5 minutes
                await page.wait_for_load_state("networkidle", timeout=30000)
                print("\n[SUCCESS] Successfully authenticated with SmartThings!")
            except Exception as err:
                print(f"\n[INFO] Window closed or timed out: {err}")
            finally:
                await context.close()

    async def async_import_cookies(self, cookie_data: str) -> None:
        """Import cookies from JSON or header string and verify session."""
        import json
        from playwright.async_api import async_playwright

        self.session_dir.mkdir(parents=True, exist_ok=True)
        raw = cookie_data.strip()

        # Check if cookie_data is a file path
        if Path(raw).is_file():
            raw = Path(raw).read_text(encoding="utf-8").strip()

        cookies_to_add: list[dict[str, Any]] = []

        # Try parsing JSON format (e.g. Cookie-Editor export)
        if raw.startswith("[") or raw.startswith("{"):
            try:
                parsed = json.loads(raw)
                cookie_list = parsed if isinstance(parsed, list) else [parsed]
                for c in cookie_list:
                    cookie_entry = {
                        "name": c["name"],
                        "value": str(c["value"]),
                        "domain": c.get("domain", ".smartthings.com"),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        cookie_entry["secure"] = bool(c["secure"])
                    if "httpOnly" in c:
                        cookie_entry["httpOnly"] = bool(c["httpOnly"])
                    if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
                        cookie_entry["sameSite"] = c["sameSite"]
                    cookies_to_add.append(cookie_entry)
            except Exception as err:
                raise RotatorError(f"Could not parse cookie JSON: {err}") from err
        else:
            # Parse Cookie header string: "key1=val1; key2=val2"
            for item in raw.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    if k.strip():
                        cookies_to_add.append(
                            {
                                "name": k.strip(),
                                "value": v.strip(),
                                "domain": ".smartthings.com",
                                "path": "/",
                            }
                        )

        if not cookies_to_add:
            raise RotatorError("No valid cookies found in input.")

        _LOGGER.info("Importing %d cookies into session profile...", len(cookies_to_add))

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.session_dir),
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                await context.add_cookies(cookies_to_add)
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(DEFAULT_TOKENS_URL, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)

                if "signin" in page.url or "login" in page.url:
                    raise SessionExpiredError(
                        "Cookies imported, but Samsung redirected to login page. "
                        "Make sure you copied all cookies while logged into account.smartthings.com/tokens."
                    )

                print("\n[SUCCESS] Cookies successfully imported and session verified on SmartThings!")
            finally:
                await context.close()

    async def async_rotate(
        self,
        headless: bool = True,
        token_name: str | None = None,
    ) -> str:
        """Execute headless rotation using saved persistent session."""
        from playwright.async_api import async_playwright

        if not self.session_dir.exists():
            raise SessionExpiredError(
                "No session found. Please run 'smartthings-pat-rotator setup' first to log in."
            )

        name = token_name or f"{TOKEN_PREFIX}{int(time.time())}"
        _LOGGER.info("Starting headless PAT rotation for '%s'...", name)

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

                # Check if redirected to login / SSO
                if "signin" in page.url or "login" in page.url:
                    raise SessionExpiredError(
                        "Samsung login session expired. Please run 'smartthings-pat-rotator setup'."
                    )

                # Click "Generate new token" button
                generate_btn = page.locator(
                    "button:has-text('Generate new token'), a:has-text('Generate new token')"
                ).first
                await generate_btn.wait_for(state="visible", timeout=15000)
                await generate_btn.click()

                # Fill Token Name input
                token_input = page.locator(
                    "input[name='tokenName'], "
                    "input[placeholder*='Token Name'], "
                    "input[id*='tokenName']"
                ).first
                await token_input.wait_for(state="visible", timeout=10000)
                await token_input.fill(name)

                # Select all scopes (e.g. click "Authorized Scopes" checkboxes)
                checkboxes = page.locator("input[type='checkbox']")
                count = await checkboxes.count()
                for i in range(count):
                    cb = checkboxes.nth(i)
                    if not await cb.is_checked():
                        await cb.check()

                # Submit creation form
                submit_btn = page.locator(
                    "button[type='submit'], "
                    "button:has-text('Generate token'), "
                    "button:has-text('Save')"
                ).first
                await submit_btn.click()

                # Wait for token output display
                # SmartThings typically displays the token in an input with a copy button
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

                # Save new token
                self.storage.save_token(token=token, token_name=name)

                # Best effort: clean up older automated tokens
                await self._cleanup_old_tokens(page)

                return token

            finally:
                await context.close()

    async def _cleanup_old_tokens(self, page: Any) -> None:
        """Best effort removal of previously expired auto-generated tokens."""
        try:
            # Look for tokens matching TOKEN_PREFIX
            del_buttons = page.locator(
                f"tr:has-text('{TOKEN_PREFIX}') button:has-text('Delete')"
            )
            count = await del_buttons.count()
            # Leave the latest one, delete older ones
            for i in range(max(0, count - 1)):
                btn = del_buttons.nth(i)
                if await btn.is_visible():
                    await btn.click()
                    # Confirm if dialog appears
                    confirm_btn = page.locator(
                        "button:has-text('Confirm'), button:has-text('OK')"
                    ).first
                    if await confirm_btn.is_visible():
                        await confirm_btn.click()
        except Exception as err:
            _LOGGER.debug("Non-critical cleanup warning: %s", err)
