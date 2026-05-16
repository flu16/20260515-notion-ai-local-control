#!/usr/bin/env python3
"""
打开 Notion AI 窗口（命令搜索）并检查窗口是否已打开。

Notion AI 浮动窗口通过 Cmd+Shift+J 打开，初始标题通常是
"命令搜索" 或 "Notion AI"。发送消息后标题会变成对话主题，因此
窗口识别还会用 AXTextArea 作为回退特征。

用法：
    ./venv/bin/python open_ai_window.py
    ./venv/bin/python open_ai_window.py --check
    ./venv/bin/python open_ai_window.py --open
"""

import sys
import time

from notion_ax import (
    ax_str,
    create_notion_app_element,
    enable_manual_accessibility,
    find_ai_window,
    get_bounds,
    kAXTitleAttribute,
    post_open_ai_shortcut,
)


def is_ai_window_open(app_element=None) -> dict:
    """
    检查 Notion AI 窗口是否已打开。
    """
    if app_element is None:
        app_element, app, error = create_notion_app_element()
        if error:
            return _closed(error)
        enable_manual_accessibility(app_element)

    window = find_ai_window(app_element)
    if window is None:
        return _closed(None)

    bounds = get_bounds(window)
    return {
        "open": True,
        "window_title": ax_str(window, kAXTitleAttribute),
        "window_position": (bounds["x"], bounds["y"]) if bounds else None,
        "window_size": (bounds["width"], bounds["height"]) if bounds else None,
        "error": None,
    }


def _closed(error: str | None) -> dict:
    return {
        "open": False,
        "window_title": None,
        "window_position": None,
        "window_size": None,
        "error": error,
    }


def open_ai_window() -> dict:
    """
    通过模拟 Cmd+Shift+J 打开 Notion AI 窗口。
    """
    app_element, app, error = create_notion_app_element()
    if error:
        return _closed(error)
    enable_manual_accessibility(app_element)

    post_open_ai_shortcut()
    print("已发送 Cmd+Shift+J，等待 AI 窗口出现...")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        time.sleep(0.3)
        status = is_ai_window_open(app_element)
        if status["open"]:
            print("  窗口已打开")
            return status

    print("  等待超时")
    return {
        **_closed("已发送 Cmd+Shift+J 但窗口未出现（超时 5 秒）"),
    }


def ensure_ai_window_open() -> dict:
    """
    确保 Notion AI 窗口已打开：先检查，未打开再发送快捷键。
    """
    status = is_ai_window_open()
    if status["open"]:
        print("AI 窗口已打开")
        return {**status, "already_open": True}

    print("AI 窗口未打开，正在发送 Cmd+Shift+J...")
    result = open_ai_window()
    return {**result, "already_open": False}


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python open_ai_window.py [选项]")
        print("  (无参数)          确保窗口打开（先检查，没开则发送 Cmd+Shift+J）")
        print("  --check            仅检查窗口是否已打开")
        print("  --open             直接发送 Cmd+Shift+J 打开")
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--check":
        print("===== 检查 AI 窗口状态 =====")
        status = is_ai_window_open()
        if status["open"]:
            pos = status["window_position"]
            siz = status["window_size"]
            pos_str = f"({int(pos[0])},{int(pos[1])})" if pos else "?"
            size_str = f"{int(siz[0])}x{int(siz[1])}" if siz else "?"
            print(f"  已打开: 位置={pos_str} 尺寸={size_str}")
        else:
            print(f"  未打开: {status.get('error') or '未找到 AI 窗口'}")
        sys.exit(0 if status["open"] else 1)

    if len(sys.argv) >= 2 and sys.argv[1] == "--open":
        print("===== 打开 AI 窗口 =====")
        result = open_ai_window()
        if result["open"]:
            print("  已打开")
        else:
            print(f"  失败: {result['error']}")
        sys.exit(0 if result["open"] else 1)

    print("===== 确保 AI 窗口打开 =====")
    result = ensure_ai_window_open()
    if result["open"]:
        print(f"  原本已打开: {result.get('already_open', False)}")
    else:
        print(f"  失败: {result.get('error', '未知')}")
    sys.exit(0 if result["open"] else 1)


if __name__ == "__main__":
    main()
