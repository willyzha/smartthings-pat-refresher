"""CLI interface for SmartThings PAT Rotator."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from .browser import SmartThingsBrowserRotator
from .const import (
    DEFAULT_COOKIES_FILE,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_STORAGE_STATE_FILE,
)
from .server import RotatorServer
from .storage import TokenStorage


def setup_logging(verbose: bool = False) -> None:
    """Configure stdout logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_setup(args: argparse.Namespace) -> None:
    """Run interactive 1-time browser setup."""
    rotator = SmartThingsBrowserRotator(
        session_dir=args.session_dir,
        cookies_file=args.cookies_file,
        storage_state_file=args.storage_state,
    )
    asyncio.run(rotator.async_interactive_setup())


def cmd_import_cookies(args: argparse.Namespace) -> None:
    """Import session cookies from your regular browser."""
    cookie_input = args.cookies
    if not cookie_input:
        if args.file:
            from pathlib import Path

            cookie_input = Path(args.file).read_text(encoding="utf-8")
        else:
            print("Paste your cookies (JSON or header string) and press Enter followed by Ctrl+D:")
            cookie_input = sys.stdin.read()

    rotator = SmartThingsBrowserRotator(
        session_dir=args.session_dir,
        cookies_file=args.cookies_file,
        storage_state_file=args.storage_state,
    )
    try:
        asyncio.run(rotator.async_import_cookies(cookie_input))
    except Exception as err:
        print(f"\n[ERROR] Cookie import failed: {err}", file=sys.stderr)
        sys.exit(1)


def cmd_rotate(args: argparse.Namespace) -> None:
    """Execute a single one-shot headless rotation."""
    storage = TokenStorage(token_file=args.token_file)
    rotator = SmartThingsBrowserRotator(
        session_dir=args.session_dir,
        cookies_file=args.cookies_file,
        storage_state_file=args.storage_state,
        storage=storage,
    )
    try:
        token = asyncio.run(rotator.async_rotate(headless=not args.headed))
        print(f"\nSuccessfully rotated PAT: {token}")
    except Exception as err:
        print(f"\n[ERROR] Rotation failed: {err}", file=sys.stderr)
        sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start token server, transparent proxy, and background rotation loop."""
    storage = TokenStorage(token_file=args.token_file)
    rotator = SmartThingsBrowserRotator(
        session_dir=args.session_dir,
        cookies_file=args.cookies_file,
        storage_state_file=args.storage_state,
        storage=storage,
    )
    server = RotatorServer(
        storage=storage,
        rotator=rotator,
        host=args.host,
        port=args.port,
        rotation_interval_hours=args.interval,
    )
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nServer stopped.")


def cmd_status(args: argparse.Namespace) -> None:
    """Display current token status and time remaining."""
    storage = TokenStorage(token_file=args.token_file)
    meta = storage.get_metadata()
    if not meta or not storage.get_token():
        print("No active PAT found. Run 'smartthings-pat-rotator setup' first.")
        sys.exit(1)

    token = meta["token"]
    masked = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
    expires_at = meta.get("expires_at", 0)
    now = time.time()
    hours_left = max(0.0, (expires_at - now) / 3600)

    print("\nSmartThings PAT Status:")
    print(f"  Token:        {masked}")
    print(f"  Token Name:   {meta.get('token_name', 'N/A')}")
    print(f"  Created:      {time.ctime(meta.get('created_at', 0))}")
    print(f"  Expires:      {time.ctime(expires_at)}")
    print(f"  Time Left:    {hours_left:.1f} hours")
    if hours_left <= 0:
        print("  Status:       EXPIRED")
    elif hours_left < 4:
        print("  Status:       WARNING (Expiring soon)")
    else:
        print("  Status:       VALID")
    print()


def cmd_get_token(args: argparse.Namespace) -> None:
    """Print the raw unmasked token string for scripts or piping."""
    storage = TokenStorage(token_file=args.token_file)
    token = storage.get_token()
    if not token:
        sys.exit(1)
    print(token)


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="smartthings-pat-rotator",
        description="Lightweight 24-hour SmartThings Personal Access Token (PAT) Auto-Rotator",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug logging"
    )
    parser.add_argument(
        "--session-dir",
        default="data/session",
        help="Path to browser session directory (default: data/session)",
    )
    parser.add_argument(
        "--cookies-file",
        default=str(DEFAULT_COOKIES_FILE),
        help=f"Path to cookies file (default: {DEFAULT_COOKIES_FILE})",
    )
    parser.add_argument(
        "--storage-state",
        default=str(DEFAULT_STORAGE_STATE_FILE),
        help=f"Path to Playwright storage_state.json (default: {DEFAULT_STORAGE_STATE_FILE})",
    )
    parser.add_argument(
        "--token-file",
        default="data/smartthings_pat.txt",
        help="Path to output token file (default: data/smartthings_pat.txt)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    p_setup = subparsers.add_parser("setup", help="1-time interactive login to approve 2FA")
    p_setup.set_defaults(func=cmd_setup)

    # import-cookies
    p_import = subparsers.add_parser(
        "import-cookies", help="Import session cookies from regular browser"
    )
    p_import.add_argument("--file", help="Path to cookie JSON file")
    p_import.add_argument("cookies", nargs="?", help="Cookie string or JSON")
    p_import.set_defaults(func=cmd_import_cookies)

    # rotate
    p_rotate = subparsers.add_parser("rotate", help="One-shot headless token rotation")
    p_rotate.add_argument("--headed", action="store_true", help="Run browser with visible UI")
    p_rotate.set_defaults(func=cmd_rotate)

    # serve
    p_serve = subparsers.add_parser("serve", help="Run background daemon & HTTP proxy")
    p_serve.add_argument(
        "--host", default=DEFAULT_SERVER_HOST, help=f"Host (default: {DEFAULT_SERVER_HOST})"
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVER_PORT,
        help=f"Port (default: {DEFAULT_SERVER_PORT})",
    )
    p_serve.add_argument(
        "--interval",
        type=int,
        default=20,
        help="Rotation interval hours (default: 20)",
    )
    p_serve.set_defaults(func=cmd_serve)

    # status
    p_status = subparsers.add_parser("status", help="Check current token validity")
    p_status.set_defaults(func=cmd_status)

    # get-token
    p_get = subparsers.add_parser("get-token", help="Print raw token string to stdout")
    p_get.set_defaults(func=cmd_get_token)

    args = parser.parse_args()
    setup_logging(args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
