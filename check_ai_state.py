#!/usr/bin/env python3
"""
判断 Notion AI 窗口当前所处的状态。

三种互斥状态：
  - idle:       输入框为空，按钮为 "输入一条消息"
  - ready:      已输入内容，按钮为 "提交 AI 消息"
  - generating: AI 正在生成，按钮为 "停止 AI 消息"

用法：
    ./venv/bin/python check_ai_state.py
    ./venv/bin/python check_ai_state.py --json
"""

import json
import sys

from notion_ax import (
    ax_str,
    bounds_tuple,
    element_at_position,
    get_ai_window_context,
    kAXDescriptionAttribute,
)


STATE_BUTTONS = {
    "idle": "输入一条消息",
    "ready": "提交 AI 消息",
    "generating": "停止 AI 消息",
}

STATE_LABELS = {
    "idle": "等待输入",
    "ready": "等待提交",
    "generating": "正在生成",
    "unknown": "未知",
}

SCAN_Y_RANGE = (85, 98)
SCAN_X_RANGE = (70, 98)
SCAN_STEP = 2


def scan_for_state_button(app_element, bounds: dict):
    """
    在窗口右下角区域扫描状态按钮。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    for yr in range(SCAN_Y_RANGE[0], SCAN_Y_RANGE[1], SCAN_STEP):
        for xr in range(SCAN_X_RANGE[0], SCAN_X_RANGE[1], SCAN_STEP):
            elem = element_at_position(
                app_element,
                float(x0 + ww * xr / 100.0),
                float(y0 + wh * yr / 100.0),
            )
            if elem is None:
                continue

            desc = ax_str(elem, kAXDescriptionAttribute)
            for state_key, button_desc in STATE_BUTTONS.items():
                if desc == button_desc:
                    return state_key, desc
    return None, None


def check_ai_state() -> dict:
    """
    检测 Notion AI 窗口的当前状态。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {
            "success": False,
            "state": "unknown",
            "state_label": STATE_LABELS["unknown"],
            "error": error,
        }

    state_key, button_desc = scan_for_state_button(app_element, bounds)
    if state_key is None:
        state_key = "unknown"

    return {
        "success": True,
        "state": state_key,
        "state_label": STATE_LABELS[state_key],
        "button_desc": button_desc,
    }


def main():
    use_json = "--json" in sys.argv

    if not use_json:
        print("===== Notion AI 状态检测 =====\n")

    result = check_ai_state()

    if use_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["success"]:
            print(f"当前状态: {result['state_label']}")
            print(f"匹配按钮: {result['button_desc']}")
        else:
            print(f"检测失败: {result['error']}")

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
