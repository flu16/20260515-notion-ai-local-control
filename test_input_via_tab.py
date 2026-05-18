#!/usr/bin/env python3
"""
测试从底部按钮通过 Shift+Tab 导航到输入框，然后粘贴文本。

思路：
  1. 先聚焦到底部工具栏的"提供背景信息"按钮
  2. 按 Shift+Tab 把焦点上移到输入框
  3. 粘贴文本

用法:
    ./venv/bin/python test_input_via_tab.py "hello world"
"""

import sys
import time

from notion_ax import (
    Quartz,
    get_ai_window_context,
    enable_manual_accessibility,
    element_at_position,
    ax_str,
    kAXRoleAttribute,
    kAXFocusedAttribute,
    AXUIElementSetAttributeValue,
    set_clipboard_text,
    get_clipboard_text,
    post_key,
    post_key_combo,
    KEY_V,
    KEY_TAB,
)


def find_element_by_desc(app_element, bounds: dict, desc: str) -> object:
    """在窗口内扫描指定 AXDescription 的元素。"""
    x0, y0 = bounds["x"], bounds["y"]
    w, h = bounds["width"], bounds["height"]

    # 先在底部区域高密度扫描
    for yr in range(82, 98, 1):
        for xr in range(0, 100, 1):
            elem = element_at_position(
                app_element,
                float(x0 + w * xr / 100.0),
                float(y0 + h * yr / 100.0),
            )
            if elem is None:
                continue
            if ax_str(elem, "AXDescription") == desc:
                return elem
    return None


def find_input_text_area(app_element, bounds: dict) -> object:
    """找 AXTextArea。"""
    x0, y0 = bounds["x"], bounds["y"]
    w, h = bounds["width"], bounds["height"]

    for yr in range(82, 98, 1):
        for xr in range(0, 100, 1):
            elem = element_at_position(
                app_element,
                float(x0 + w * xr / 100.0),
                float(y0 + h * yr / 100.0),
            )
            if elem is None:
                continue
            if ax_str(elem, kAXRoleAttribute) == "AXTextArea":
                return elem
    return None


def post_shift_tab():
    """发送 Shift+Tab。"""
    post_key(KEY_TAB, True, Quartz.kCGEventFlagMaskShift)
    time.sleep(0.05)
    post_key(KEY_TAB, False, Quartz.kCGEventFlagMaskShift)
    time.sleep(0.3)


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "hello"

    print("===== 测试: 从底部按钮 Shift+Tab 到输入框粘贴 =====\n")

    # 1. 获取窗口
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        print(f"错误: {error}")
        sys.exit(1)

    # 2. 找到"提供背景信息"按钮
    print("1) 搜索 '提供背景信息' 按钮...")
    btn = find_element_by_desc(app_element, bounds, "提供背景信息")
    if btn is None:
        print("   未找到按钮，尝试搜索输入框直接聚焦...")
        # fallback: 直接找输入框
        ta = find_input_text_area(app_element, bounds)
        if ta is None:
            print("   也找不到输入框")
            sys.exit(1)
    else:
        print("   找到按钮，设置 AXFocus...")
        AXUIElementSetAttributeValue(btn, kAXFocusedAttribute, True)
        time.sleep(0.3)

        # 3. 按 Shift+Tab
        print("2) 发送 Shift+Tab...")
        post_shift_tab()

    # 4. 找输入框验证焦点
    print("3) 搜索输入框...")
    ta = find_input_text_area(app_element, bounds)
    if ta is None:
        print("   未找到输入框")
        sys.exit(1)

    print(f"   找到输入框，当前 AXValue: {ax_str(ta, 'AXValue')!r}")

    # 5. 再次确认焦点在输入框
    AXUIElementSetAttributeValue(ta, kAXFocusedAttribute, True)
    time.sleep(0.2)

    # 6. 写入剪贴板并粘贴
    print(f"4) 写入剪贴板: {text!r}")
    set_clipboard_text(text)

    print("5) 发送 Cmd+V...")
    post_key_combo(KEY_V, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.5)

    # 7. 验证结果
    actual = ax_str(ta, "AXValue")
    print(f"\n===== 结果 =====")
    print(f"期望: {text!r}")
    print(f"实际: {actual!r}")

    if actual == text:
        print("\n✅ 成功！文本已写入输入框")
    else:
        print(f"\n❌ 失败。不匹配")


if __name__ == "__main__":
    main()
