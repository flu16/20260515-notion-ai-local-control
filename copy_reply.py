#!/usr/bin/env python3
"""
拷贝 Notion AI 当前可定位到的回复到剪贴板。

AI 完成输出后，消息下方会出现 "拷贝回复" 按钮。本脚本等待该按钮，
点击它，然后读取系统剪贴板中的回复文本。

注意：当前策略仍不保证命中最新回复，可能复制历史回复。以
PROJECT.md / HANDOFF.md 的能力边界说明为准。

用法：
    ./venv/bin/python copy_reply.py
    ./venv/bin/python copy_reply.py --timeout 60
"""

import sys
import time

from notion_ax import get_clipboard_text, kAXErrorSuccess, press
from search_element import search_element


def copy_ai_reply(wait_timeout: float = 30.0) -> dict:
    """
    等待 "拷贝回复" 按钮出现，然后拷贝其对应回复。

    当前搜索策略不能可靠证明该按钮属于最新回复。
    """
    print(f"等待 '拷贝回复' 按钮出现（最长 {wait_timeout}s）...")
    start_time = time.time()
    result = search_element("拷贝回复", wait_timeout=wait_timeout)

    if not result["success"]:
        elapsed = round(time.time() - start_time, 2)
        return {
            "success": False,
            "error": result["error"],
            "elapsed": elapsed,
            "tab_count": 0,
        }

    err = press(result["element"])
    elapsed = round(time.time() - start_time, 2)
    tab_count = result.get("info", {}).get("tab_count", 0)
    if err != kAXErrorSuccess:
        return {
            "success": False,
            "error": f"AXPressAction 失败 (error_code={err})",
            "elapsed": elapsed,
            "tab_count": tab_count,
        }

    time.sleep(0.2)
    text = get_clipboard_text()
    if text:
        preview = text[:100] + "..." if len(text) > 100 else text
        print(f"  已拷贝: {preview}")
    else:
        print("  (剪贴板为空)")

    return {
        "success": True,
        "text": text,
        "elapsed": elapsed,
        "tab_count": tab_count,
    }


def main():
    wait_timeout = 30.0

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--timeout", "-t") and i + 1 < len(args):
            wait_timeout = float(args[i + 1])
            i += 2
        elif args[i] in ("-h", "--help"):
            print("用法: ./venv/bin/python copy_reply.py [--timeout 秒数]")
            print("  --timeout / -t: 最大等待时间（秒），默认 30")
            sys.exit(0)
        else:
            i += 1

    print("===== 拷贝 Notion AI 回复 =====\n")
    result = copy_ai_reply(wait_timeout=wait_timeout)

    if result["success"]:
        print(f"\n拷贝成功! (耗时 {result['elapsed']}s, Tab {result['tab_count']} 次)")
        print(f"\n--- AI 回复 ---\n{result['text']}")
    else:
        print(f"\n拷贝失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
