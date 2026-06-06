#!/usr/bin/env python3
"""Unified command-line entrypoint for Notion AI Local Control."""

from __future__ import annotations

import sys
from collections.abc import Callable


COMMON_COMMANDS: dict[str, tuple[str, str, str]] = {
    "start": (
        "notion_ai_local_control.start_cdp",
        "main",
        "Start Notion desktop with Electron CDP enabled.",
    ),
    "ask-and-reply": (
        "notion_ai_local_control.ask_cdp",
        "main",
        "Ask Notion AI through Electron CDP and copy the final reply.",
    ),
    "app": (
        "notion_ai_local_control.tab_bar_cdp",
        "main",
        "Control Notion desktop main-app tabs through Electron CDP.",
    ),
}

DEBUG_COMMANDS: dict[str, tuple[str, str, str]] = {
    "cdp-debug": (
        "notion_ai_local_control.beta_cdp_input",
        "main",
        "Debug: read/write the Notion AI quick-search textbox through CDP.",
    ),
}

COMMANDS: dict[str, tuple[str, str, str]] = {
    **COMMON_COMMANDS,
    **DEBUG_COMMANDS,
}


def print_help() -> None:
    print("用法: notion-ai <command> [args...]")
    print()
    print("常用示例:")
    print("  notion-ai start --json")
    print('  notion-ai ask-and-reply "1+1" --json')
    print("  notion-ai ask-and-reply --from-stdin --json")
    print('  notion-ai app ask "请只回复：OK" --json')
    print()
    print("调试示例:")
    print("  notion-ai cdp-debug --status")
    print()
    print("常用 command:")
    width = max(len(name) for name in COMMANDS)
    for name, (_, _, description) in COMMON_COMMANDS.items():
        print(f"  {name.ljust(width)}  {description}")
    print()
    print("调试 command:")
    for name, (_, _, description) in DEBUG_COMMANDS.items():
        print(f"  {name.ljust(width)}  {description}")
    print()
    print("查看子命令帮助:")
    print("  notion-ai <command> --help")
    print()
    print("未安装时可用:")
    print("  PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli <command> [args...]")


def _load_callable(module_name: str, attr_name: str) -> Callable:
    module = __import__(module_name, fromlist=[attr_name])
    return getattr(module, attr_name)


def _run_argv_main(command: str, argv: list[str]) -> int:
    module_name, attr_name, _ = COMMANDS[command]
    target = _load_callable(module_name, attr_name)

    old_argv = sys.argv[:]
    sys.argv = [f"notion-ai {command}", *argv]
    if command in {"ask-and-reply", "start"}:
        try:
            result = target(argv)
            return int(result or 0)
        finally:
            sys.argv = old_argv

    try:
        result = target()
        return int(result or 0)
    finally:
        sys.argv = old_argv


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print_help()
        return 0

    command = args[0]
    if command not in COMMANDS:
        print(f"未知 command: {command}", file=sys.stderr)
        print("使用 `notion-ai --help` 查看可用命令。", file=sys.stderr)
        return 2

    return _run_argv_main(command, args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
