"""Interactive helper to capture and save Playwright storage_state.json for headless deployments."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_LOGGER = logging.getLogger("save_storage_state")

DATA_DIR = Path("data")
SESSION_DIR = DATA_DIR / "session"
STORAGE_STATE_FILE = DATA_DIR / "storage_state.json"
COOKIES_FILE = DATA_DIR / "cookies.txt"


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  SmartThings Playwright Session Capturer")
    print("=" * 60)
    print("Opening Chromium on your desktop display...")
    print("1. Sign in to your Samsung Account.")
    print("2. Complete 2-Step Verification on your phone.")
    print("3. Once the 'Personal Access Tokens' page loads, close the browser.")
    print("=" * 60 + "\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print("Navigating to https://account.smartthings.com/tokens...")
        await page.goto("https://account.smartthings.com/tokens")

        # Monitor page until tokens page is reached or browser window is closed
        print("Waiting for you to sign in...")
        saved = False

        for _ in range(600):  # Wait up to 10 minutes
            if page.is_closed() or not context.pages:
                break

            try:
                if "account.smartthings.com/tokens" in page.url:
                    content = await page.content()
                    if "Generate new token" in content and not saved:
                        print("\n[SUCCESS] Detected Personal Access Tokens dashboard!")
                        await context.storage_state(path=str(STORAGE_STATE_FILE))
                        print(f"Saved full session state to: {STORAGE_STATE_FILE}")

                        # Also export cookies.txt
                        cookies = await context.cookies(["https://account.smartthings.com"])
                        if cookies:
                            cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                            COOKIES_FILE.write_text(cookie_header + "\n", encoding="utf-8")
                            print(f"Saved fresh cookies to: {COOKIES_FILE}")

                        saved = True
                        print("\nYou can now close the browser window.")
            except Exception:
                pass

            await asyncio.sleep(1)

        # Final save upon window close
        try:
            await context.storage_state(path=str(STORAGE_STATE_FILE))
            print(f"\nFinal session saved to {STORAGE_STATE_FILE} successfully!")
        except Exception:
            pass

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
