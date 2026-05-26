#!/usr/bin/env python3
"""
通过 macOS Accessibility API 点击 Notion AI 窗口中的按钮。

================================================================
本文件只负责"点击"，搜索定位由 search_element.py 提供。
================================================================

核心发现（经过多轮实验验证）：

1. Notion 是 Electron 应用，对 macOS 无障碍 API 的支持不完整。
   AXUIElementPerformAction(kAXPressAction) 必须在 AXManualAccessibility 开启后才生效，
   否则返回 success 但实际不会触发任何效果。

2. AXManualAccessibility 由 search_element.py 在初始化时自动设置，
   本文件不需要重复设置。

================================================================
用法：
================================================================

    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提供背景信息"
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提交 AI 消息"
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "拷贝回复" --timeout 30
"""

import sys

# 搜索功能统一由 search_element 模块提供
from .notion_ax import kAXErrorSuccess, press
from .search_element import search_element


# ---------------------------------------------------------------------------
# 主点击函数
# ---------------------------------------------------------------------------

def click_button(target_description: str, wait_timeout: float = 0.0) -> dict:
    """
    点击 Notion AI 窗口中的指定按钮。

    参数：
      target_description: 按钮的 AXDescription，如 "提交 AI 消息"
      wait_timeout: 等待超时（秒）。
        0（默认）：不等待，找不到立即返回失败
        >0：在超时时间内持续轮动等待目标出现，
            适用于 "拷贝回复" 这类在 AI 输出完成后才出现的按钮。

    返回：
      {
        "success": True/False,
        "description": 目标描述文字,
        "method": "grid_scan" | "tab_navigate"（使用的搜索方式）,
        "element_info": { ... 搜索到的元素属性 ... },
        "error": "..." (仅失败时)
      }
    """
    # --- 1. 用 search_element 模块定位目标元素 ---
    result = search_element(target_description, wait_timeout=wait_timeout)

    if not result["success"]:
        return {
            "success": False,
            "description": target_description,
            "error": result.get("error", "搜索失败"),
        }

    element = result["element"]
    element_info = result.get("info", {})

    # --- 2. 执行 AXPressAction 点击 ---
    err = press(element)
    success = err == kAXErrorSuccess
    print(f"  AXPressAction error_code={err} {'成功' if success else '失败'}")

    return {
        "success": success,
        "description": target_description,
        "method": result.get("method", "unknown"),
        "element_info": element_info,
        "action_error": err,
    }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element <description> [--timeout 秒数]")
        print('示例: PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提供背景信息"')
        print('      PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "拷贝回复" --timeout 30')
        print('      PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提交 AI 消息"')
        print()
        print("  --timeout / -t: 等待超时（秒），适用于 AI 输出完成后才出现的按钮")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    target = sys.argv[1]
    wait_timeout = 0.0

    # 解析可选参数 --timeout / -t
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] in ("--timeout", "-t") and i + 1 < len(args):
            wait_timeout = float(args[i + 1])
            i += 2
        else:
            i += 1

    print(f"===== 点击按钮: {target!r} =====\n")
    result = click_button(target, wait_timeout=wait_timeout)

    if result["success"]:
        print(f"\n点击成功! ({result['description']}) via {result['method']}")
    else:
        print(f"\n点击失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
