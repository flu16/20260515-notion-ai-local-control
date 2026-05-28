#!/usr/bin/env python3
"""Unified command-line entrypoint for Notion AI Local Control."""

from __future__ import annotations

import sys
from collections.abc import Callable


COMMON_COMMANDS: dict[str, tuple[str, str, str]] = {
    "ask": (
        "notion_ai_local_control.ask_and_copy_reply",
        "main",
        "Ask Notion AI and copy the final reply.",
    ),
    "ask-cdp": (
        "notion_ai_local_control.ask_cdp",
        "main",
        "Beta: ask Notion AI through Electron CDP and copy the reply.",
    ),
    "state": (
        "notion_ai_local_control.check_ai_state",
        "main",
        "Inspect the current Notion AI state.",
    ),
    "open": (
        "notion_ai_local_control.open_ai_window",
        "main",
        "Open or check the Notion AI window.",
    ),
}

DEBUG_COMMANDS: dict[str, tuple[str, str, str]] = {
    "search": (
        "notion_ai_local_control.search_element",
        "main",
        "Search or list visible Accessibility elements.",
    ),
    "input": (
        "notion_ai_local_control.input_box",
        "main",
        "Read, write, clear, or attach files to the input box.",
    ),
    "model": (
        "notion_ai_local_control.model_selector",
        "main",
        "Read or switch the current Notion AI model.",
    ),
    "click": (
        "notion_ai_local_control.click_element",
        "main",
        "Click a labeled Accessibility element.",
    ),
    "focus": (
        "notion_ai_local_control.focus_element",
        "main",
        "Focus a labeled Accessibility element.",
    ),
    "watch-state": (
        "notion_ai_local_control.watch_state",
        "main",
        "Continuously watch Notion AI state.",
    ),
    "watch-focus": (
        "notion_ai_local_control.watch_focus",
        "main",
        "Continuously watch focused Accessibility elements.",
    ),
    "beta-cdp-input": (
        "notion_ai_local_control.beta_cdp_input",
        "main",
        "Beta: write to Notion AI via Electron CDP DOM events.",
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
    print('  notion-ai ask "1+1" --json')
    print('  notion-ai ask-cdp "1+1" --json')
    print("  notion-ai ask --from-stdin --json")
    print("  notion-ai state --json")
    print("  notion-ai open --check")
    print()
    print("调试示例:")
    print('  notion-ai search "拷贝回复"')
    print("  notion-ai input --read")
    print("  notion-ai model --current")
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
    if command == "ask":
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
