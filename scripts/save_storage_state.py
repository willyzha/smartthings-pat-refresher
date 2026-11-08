"""Interactive helper to capture and save Playwright storage_state.json for headless deployments.

Launches official Google Chrome on the desktop display without automation flags (avoiding Akamai bot
detection), connects via Chrome DevTools Protocol (CDP), and extracts in-memory session cookies the
instant authentication completes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_LOGGER = logging.getLogger("save_storage_state")

DATA_DIR = Path("data")
SESSION_DIR = DATA_DIR / "session"
STORAGE_STATE_FILE = DATA_DIR / "storage_state.json"
COOKIES_FILE = DATA_DIR / "cookies.txt"


def find_chrome_binary() -> str:
    """Find installed Google Chrome binary."""
    candidates = [
        "/opt/google/chrome/chrome",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    raise FileNotFoundError("Google Chrome or Chromium binary not found on system.")


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    chrome_bin = find_chrome_binary()
    print("\n" + "=" * 65)
    print("  SmartThings Session Capturer (Official Chrome + CDP)")
    print("=" * 65)
    print("Using Chrome:", chrome_bin)
    print("Opening Google Chrome on your display...")
    print("1. Sign in to your Samsung Account.")
    print("2. Complete 2-Step Verification on your phone.")
    print("3. As soon as the 'Personal Access Tokens' page loads,")
    print("   this script will automatically extract the session and close Chrome!")
    print("=" * 65 + "\n")

    # Launch official Chrome with remote debugging on port 9222
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0.0")
    proc = subprocess.Popen([
        chrome_bin,
        f"--user-data-dir={SESSION_DIR.resolve()}",
        "--remote-debugging-port=9222",
        "--remote-debugging-address=0.0.0.0",
        "--no-first-run",
        "--no-default-browser-check",
        "https://account.smartthings.com/tokens",
    ], env=env)

    # Wait for Chrome DevTools port to open
    await asyncio.sleep(2.5)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
            context = browser.contexts[0]

            print("Waiting for you to sign in and reach the tokens dashboard...")
            saved = False

            for _ in range(600):  # Wait up to 10 minutes
                if proc.poll() is not None:
                    print("\n[INFO] Chrome was closed.")
                    break

                for page in context.pages:
                    url = page.url
                    if "account.smartthings.com/tokens" in url:
                        try:
                            content = await page.content()
                            if "Generate new token" in content:
                                print("\n[SUCCESS] Detected Personal Access Tokens dashboard!")

                                # 1. Extract and save storage state (cookies + localStorage)
                                await context.storage_state(path=str(STORAGE_STATE_FILE))
                                print(f"Saved portable session state to: {STORAGE_STATE_FILE}")

                                # 2. Extract in-memory SmartThings cookies
                                cookies = await context.cookies(["https://account.smartthings.com"])
                                if cookies:
                                    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                                    COOKIES_FILE.write_text(cookie_header + "\n", encoding="utf-8")
                                    print(f"Extracted {len(cookies)} live cookies to: {COOKIES_FILE}")

                                saved = True
                                break
                        except Exception:
                            pass

                if saved:
                    break
                await asyncio.sleep(1)

            if saved:
                print("\n[SUCCESS] All credentials captured successfully! Closing browser...")
            else:
                print("\n[WARNING] Sign-in was not completed before window closed.")

            await browser.close()
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
