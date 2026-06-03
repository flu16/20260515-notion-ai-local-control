#!/usr/bin/env python3
"""Start Notion desktop with Electron CDP enabled."""

from __future__ import annotations

import argparse
import json
import urllib.request

from .beta_cdp_input import (
    CdpError,
    DEFAULT_PORT,
    cdp_is_running,
    restart_notion_with_cdp,
    wait_for_cdp_server,
)


def _json_url(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def start_cdp(port: int = DEFAULT_PORT, restart: bool = False,
              timeout: float = 15.0) -> dict:
    launch_info = None
    already_running = cdp_is_running(port)

    if restart or not already_running:
        launch_info = restart_notion_with_cdp(port)
        wait_for_cdp_server(port=port, timeout=timeout)

    version = _json_url(f"http://127.0.0.1:{port}/json/version")
    return {
        "success": True,
        "port": port,
        "alreadyRunning": already_running and not restart,
        "launchInfo": launch_info,
        "version": version,
        "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start Notion desktop with --remote-debugging-port enabled.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--restart", action="store_true", help="Restart Notion even if CDP is already reachable")
    parser.add_argument("--timeout", type=float, default=15.0, help="Seconds to wait for CDP to become reachable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = start_cdp(port=args.port, restart=args.restart, timeout=args.timeout)
    except (CdpError, OSError) as exc:
        result = {
            "success": False,
            "port": args.port,
            "error": str(exc),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("success"):
        state = "already running" if result.get("alreadyRunning") else "started"
        print(f"Notion CDP {state} on 127.0.0.1:{result['port']}")
        version = result.get("version") or {}
        browser = version.get("Browser")
        if browser:
            print(browser)
    else:
        print(f"Failed to start Notion CDP: {result.get('error')}")
        return 1
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
