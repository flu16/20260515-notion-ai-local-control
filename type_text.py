#!/usr/bin/env python3
"""
在 Notion AI 窗口中操作文本输入区（AXTextArea）。

当前已知能力以 PROJECT.md / HANDOFF.md 为准：
读取输入框 AXValue 可用；无鼠标的文本写入仍不稳定或失败。
本脚本保留剪贴板 + Cmd+V 路径用于继续实验，并用 AXValue 做结果验证。

用法：
    ./venv/bin/python type_text.py "你好，Notion AI"
    ./venv/bin/python type_text.py --clear
    ./venv/bin/python type_text.py --read
"""

import sys
import time

from notion_ax import (
    Quartz,
    ax_str,
    element_at_position,
    element_info,
    get_ai_window_context,
    kAXRoleAttribute,
    kAXValueAttribute,
    KEY_V,
    post_key_combo,
    post_open_ai_shortcut,
    raise_window,
    set_clipboard_text,
    set_focused,
)


TEXT_AREA_Y_RATIOS = (0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94)
TEXT_AREA_X_RATIOS = (0.18, 0.25, 0.32, 0.39, 0.46, 0.53, 0.60, 0.67, 0.74, 0.81, 0.88)


def _init_environment():
    """
    Return (app_element, bounds, pid, error).

    If the AI window is not open yet, send Cmd+Shift+J and wait briefly.
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error and "未找到 AI 窗口" not in error:
        return None, None, 0, error

    if window is None:
        post_open_ai_shortcut()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            time.sleep(0.3)
            app_element, app, window, bounds, error = get_ai_window_context()
            if window is not None:
                print("  AI 窗口已打开")
                break
        if window is None:
            return None, None, 0, "未找到 AI 窗口，请按 Cmd+Shift+J 打开"

    raise_window(window)
    return app_element, bounds, app.processIdentifier(), None


def find_text_area(app_element, bounds: dict):
    """
    在窗口底部区域扫描查找 AXTextArea。
    """
    x0, y0 = bounds["x"], bounds["y"]
    w, h = bounds["width"], bounds["height"]

    for y_ratio in TEXT_AREA_Y_RATIOS:
        for x_ratio in TEXT_AREA_X_RATIOS:
            elem = element_at_position(
                app_element,
                float(x0 + w * x_ratio),
                float(y0 + h * y_ratio),
            )
            if elem is None:
                continue
            if ax_str(elem, kAXRoleAttribute) == "AXTextArea":
                info = element_info(elem)
                info["role"] = "AXTextArea"
                return elem, info
    return None, None


def focus_text_area(text_area, info: dict):
    """
    让 Electron 文本框进入可输入状态。

    不使用鼠标事件。这里只设置 AX 焦点，后续由快捷键粘贴。
    """
    set_focused(text_area, True)
    time.sleep(0.2)


def read_input_text(app_element=None, bounds=None) -> dict:
    """
    读取 AI 输入框当前文字。
    """
    if app_element is None or bounds is None:
        app_element, bounds, pid, error = _init_environment()
        if error:
            return {"success": False, "text": "", "error": error}

    text_area, info = find_text_area(app_element, bounds)
    if text_area is None:
        return {"success": False, "text": "", "error": "未找到 AXTextArea（输入框）"}

    return {
        "success": True,
        "text": ax_str(text_area, kAXValueAttribute),
        "text_area_info": info,
    }


def set_input_text(text: str, app_element=None, bounds=None) -> dict:
    """
    尝试通过剪贴板粘贴方式设置 AI 输入框文字。

    该路径在当前 Notion/Electron 环境下尚未稳定打通；返回 success
    只表示粘贴后 AXValue 与期望文本一致。
    """
    if app_element is None or bounds is None:
        app_element, bounds, pid, error = _init_environment()
        if error:
            return {"success": False, "text": text, "method": "paste", "error": error}

    text_area, info = find_text_area(app_element, bounds)
    if text_area is None:
        return {
            "success": False,
            "text": text,
            "method": "paste",
            "error": "未找到 AXTextArea（输入框）",
        }

    set_clipboard_text(text)
    focus_text_area(text_area, info)
    post_key_combo(KEY_V, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.2)

    actual = ax_str(text_area, kAXValueAttribute)
    success = actual == text
    if success:
        print(f"  输入成功: {text!r}")
    else:
        print(f"  输入不匹配: 期望 {text!r}, 实际 {actual!r}")

    return {
        "success": success,
        "text": actual,
        "method": "paste",
        "error": None if success else "粘贴验证不匹配",
    }


def clear_input_text(app_element=None, bounds=None) -> dict:
    """清空 AI 输入框。"""
    return set_input_text("", app_element=app_element, bounds=bounds)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python type_text.py [选项或文字]")
        print()
        print("  设置文字:")
        print('    ./venv/bin/python type_text.py "你的问题"')
        print()
        print("  操作选项:")
        print("    --read              读取输入框当前内容")
        print("    --clear             清空输入框")
        sys.exit(0)

    if "--read" in sys.argv:
        result = read_input_text()
        if result["success"]:
            print(f"输入框内容: {result['text']!r}")
            info = result.get("text_area_info", {})
            if info.get("position"):
                print(f"位置: ({int(info['position'][0])}, {int(info['position'][1])})")
            if info.get("size"):
                print(f"尺寸: {int(info['size'][0])}x{int(info['size'][1])}")
        else:
            print(f"失败: {result['error']}")
        sys.exit(0 if result["success"] else 1)

    if "--clear" in sys.argv:
        print("===== 清空 AI 输入框 =====")
        result = clear_input_text()
        if result["success"]:
            print("已清空")
        else:
            print(f"失败: {result['error']}")
        sys.exit(0 if result["success"] else 1)

    text = sys.argv[1]
    print(f"===== 设置输入框文字: {text!r} =====")
    result = set_input_text(text)
    if result["success"]:
        print(f"\n设置成功: {result['text']!r}")
    else:
        print(f"\n失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
