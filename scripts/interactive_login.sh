#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

# Clean any stale locks
rm -f data/session/Singleton*

echo "=========================================================="
echo "  SmartThings Interactive Session & Token Capturer"
echo "=========================================================="
echo "1. Opening Google Chrome on your display..."
echo "2. Sign in to your Samsung Account & complete 2FA."
echo "3. Once you reach the Personal Access Tokens dashboard,"
echo "   this script will automatically extract your cookies,"
echo "   mint a fresh 24h token, and close Chrome for you!"
echo "=========================================================="
echo ""

# Launch real Google Chrome on host display with CDP
export DISPLAY="${DISPLAY:-:0.0}"
/opt/google/chrome/chrome \
    --user-data-dir="$DIR/data/session" \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --no-first-run \
    --no-default-browser-check \
    "https://account.smartthings.com/tokens" &
CHROME_PID=$!

cleanup() {
    kill -TERM "$CHROME_PID" 2>/dev/null || true
    wait "$CHROME_PID" 2>/dev/null || true
    rm -f data/session/Singleton*
}
trap cleanup EXIT

echo "Chrome running with PID: $CHROME_PID. Waiting for DevTools port..."
sleep 3

# Run Playwright monitor inside Docker container
docker run --rm --network=host -v "$DIR:/app" -v "$DIR/data:/app/data" -w /app smartthings-pat-rotator python3 -c "
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright

STORAGE_STATE_FILE = Path('data/storage_state.json')
COOKIES_FILE = Path('data/cookies.txt')

async def monitor():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        except Exception as e:
            print('Could not connect to Chrome CDP:', e)
            sys.exit(1)
            
        context = browser.contexts[0]
        print('Connected to Chrome DevTools! Monitoring your login progress...')
        
        saved = False
        for i in range(600):
            for page in context.pages:
                url = page.url
                if 'account.smartthings.com/tokens' in url:
                    try:
                        content = await page.content()
                        if 'Generate new token' in content:
                            print('\n[SUCCESS] Detected Personal Access Tokens dashboard!')
                            await context.storage_state(path=str(STORAGE_STATE_FILE))
                            print(f'Saved portable session to: {STORAGE_STATE_FILE}')
                            
                            cookies = await context.cookies(['https://account.smartthings.com'])
                            if cookies:
                                cookie_header = '; '.join(f\"{c['name']}={c['value']}\" for c in cookies)
                                COOKIES_FILE.write_text(cookie_header + '\n', encoding='utf-8')
                                print(f'Extracted {len(cookies)} live cookies to: {COOKIES_FILE}')
                            
                            saved = True
                            break
                    except Exception:
                        pass
            if saved:
                break
            await asyncio.sleep(1)
            if i % 5 == 0:
                print('.', end='', flush=True)

        await browser.close()
        if not saved:
            sys.exit(1)

asyncio.run(monitor())
"

echo ""
echo "[SUCCESS] Session captured! Testing instant token rotation..."
curl -s -X POST http://localhost:8765/rotate
echo ""
echo "[DONE] Rotator is active and fully refreshed!"
