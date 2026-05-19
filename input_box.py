#!/usr/bin/env python3
"""
在 Notion AI 窗口中操作文本输入区（AXTextArea）。

当前稳定能力：
  - 读取输入框 AXValue。
  - 不使用鼠标、不使用 Shift+Tab，向输入框输入文本。
  - 不使用鼠标、不使用 Shift+Tab，清空输入框。

核心发现：
  AXFocusedUIElement 是 AXTextArea 不等于真实可输入。
  真正关键的是输入框是否有有效插入点。

假焦点状态：
  - AXFocusedUIElement = AXTextArea / 文本输入区
  - AXInsertionPointLineNumber = 9223372036854775807
  - AXSelectedText 读取失败
  - Cmd+V 不能进入真实输入框

真输入状态：
  - AXInsertionPointLineNumber = 0
  - AXSelectedText = ""
  - Cmd+V 可以进入真实输入框

稳定输入路径：
  1. 找到输入框 AXTextArea。
  2. 设置 AXFocusedAttribute=True。
  3. 设置 AXSelectedTextRange=(0,0)，创建真实插入点。
  4. 确认 AXInsertionPointLineNumber 有效。
  5. 写剪贴板并发送 Cmd+V。
  6. 读取 AXValue 验证。

用法：
    ./venv/bin/python input_box.py "你好，Notion AI"
    ./venv/bin/python input_box.py --clear
    ./venv/bin/python input_box.py --read
    ./venv/bin/python input_box.py --focus-state
"""

import difflib
import sys
import time

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementSetAttributeValue,
    AXValueCreate,
    kAXErrorSuccess,
    kAXValueCFRangeType,
)
from Foundation import NSRange

from notion_ax import (
    Quartz,
    ax_str,
    element_at_position,
    element_info,
    focused_element,
    get_ai_window_context,
    kAXFocusedAttribute,
    kAXRoleAttribute,
    kAXValueAttribute,
    KEY_A,
    KEY_DELETE,
    KEY_V,
    post_key,
    post_key_combo,
    set_clipboard_text,
)


# 输入框扫描范围。Notion AI 输入框稳定出现在浮窗底部区域。
TEXT_AREA_SCAN_Y_RANGE = range(82, 99, 1)
TEXT_AREA_SCAN_X_RANGE = range(0, 100, 1)

# 未激活真实插入点时，Notion/Electron 暴露的特殊行号。
INVALID_INSERTION_LINE_NUMBER = 9223372036854775807

# Rich text editors can normalize pasted content in their AXValue. Exact
# equality is still preferred; long prompts additionally allow a length-based
# match as long as no old input residue is detected.
LONG_TEXT_SOFT_MATCH_MIN_LENGTH = 1000
LONG_TEXT_MAX_LENGTH_RATIO = 0.02


def _init_environment():
    """
    返回 (app_element, bounds, pid, error)。

    如果 AI 窗口未打开，会发送 Cmd+Shift+J 并等待窗口出现。
    """
    from notion_ax import post_open_ai_shortcut, raise_window

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
    在窗口底部区域扫描查找输入框 AXTextArea。

    注意：这里找到的是 AX 输入框元素，不代表它已经有真实插入点。
    是否真实可输入，要继续看 AXInsertionPointLineNumber / AXSelectedText。
    """
    x0, y0 = bounds["x"], bounds["y"]
    w, h = bounds["width"], bounds["height"]

    for yr in TEXT_AREA_SCAN_Y_RANGE:
        for xr in TEXT_AREA_SCAN_X_RANGE:
            elem = element_at_position(
                app_element,
                float(x0 + w * xr / 100.0),
                float(y0 + h * yr / 100.0),
            )
            if elem is None:
                continue
            if ax_str(elem, kAXRoleAttribute) == "AXTextArea":
                info = element_info(elem)
                info["role"] = "AXTextArea"
                return elem, info
    return None, None


def read_text_activation_info(text_area) -> dict:
    """
    读取输入框真实编辑激活状态相关属性。

    这些属性比 AXFocusedUIElement 更能说明 Electron 编辑器是否真正可输入。
    """
    line_ok, line_number = AXUIElementCopyAttributeValue(
        text_area, "AXInsertionPointLineNumber", None
    )
    selected_ok, selected_text = AXUIElementCopyAttributeValue(
        text_area, "AXSelectedText", None
    )
    range_ok, selected_range = AXUIElementCopyAttributeValue(
        text_area, "AXSelectedTextRange", None
    )

    line_valid = (
        line_ok == kAXErrorSuccess
        and line_number is not None
        and int(line_number) != INVALID_INSERTION_LINE_NUMBER
    )

    return {
        "insertion_line_error": line_ok,
        "insertion_line_number": int(line_number) if line_ok == kAXErrorSuccess else None,
        "insertion_line_valid": line_valid,
        "selected_text_error": selected_ok,
        "selected_text": str(selected_text) if selected_ok == kAXErrorSuccess else None,
        "selected_range_error": range_ok,
        "selected_range": str(selected_range) if range_ok == kAXErrorSuccess else None,
    }


def activate_text_area_insertion_point(text_area) -> dict:
    """
    激活输入框的真实插入点。

    只设置 AXFocusedAttribute=True 不够；Electron 可能只进入 AX 假焦点状态。
    设置 AXSelectedTextRange=(0,0) 会创建真实插入点，使 Cmd+V 能进入输入框。
    """
    focus_err = AXUIElementSetAttributeValue(text_area, kAXFocusedAttribute, True)
    time.sleep(0.12)

    range_value = AXValueCreate(kAXValueCFRangeType, NSRange(0, 0))
    range_err = AXUIElementSetAttributeValue(
        text_area, "AXSelectedTextRange", range_value
    )
    time.sleep(0.18)

    activation = read_text_activation_info(text_area)
    activation.update({
        "focus_error": focus_err,
        "set_selected_range_error": range_err,
        "activated": (
            focus_err == kAXErrorSuccess
            and range_err == kAXErrorSuccess
            and activation["insertion_line_valid"]
            and activation["selected_text_error"] == kAXErrorSuccess
        ),
    })
    return activation


def read_number_of_characters(text_area) -> int:
    """
    读取输入框当前字符数。

    用于替换已有文本：不要用 Cmd+A，因为它可能破坏刚激活的真实插入点。
    正确做法是设置 AXSelectedTextRange=(0, 字符数)，再粘贴替换选区。
    """
    ok, value = AXUIElementCopyAttributeValue(text_area, "AXNumberOfCharacters", None)
    if ok == kAXErrorSuccess and value is not None:
        return int(value)
    return len(ax_str(text_area, kAXValueAttribute))


def set_selected_text_range(text_area, location: int, length: int) -> int:
    """设置输入框选区范围。"""
    range_value = AXValueCreate(kAXValueCFRangeType, NSRange(location, length))
    return AXUIElementSetAttributeValue(text_area, "AXSelectedTextRange", range_value)


def validate_pasted_text(expected: str, actual: str, replace_existing: bool = True,
                         before_text: str = "") -> dict:
    """验证粘贴结果，重点防止替换时把输入框旧文本一起发出去。"""
    exact = actual == expected if replace_existing else expected in actual
    ratio = difflib.SequenceMatcher(None, expected, actual).ratio() if expected or actual else 1.0
    length_delta = abs(len(actual) - len(expected))
    length_ratio = length_delta / max(len(expected), 1)
    has_residue = (
        replace_existing
        and bool(before_text)
        and before_text not in expected
        and before_text in actual
    )
    length_match = (
        replace_existing
        and len(expected) >= LONG_TEXT_SOFT_MATCH_MIN_LENGTH
        and length_ratio <= LONG_TEXT_MAX_LENGTH_RATIO
        and not has_residue
    )
    soft_match = (
        replace_existing
        and len(expected) >= LONG_TEXT_SOFT_MATCH_MIN_LENGTH
        and ratio >= 0.90
        and length_ratio <= LONG_TEXT_MAX_LENGTH_RATIO
        and not has_residue
    )
    return {
        "success": exact or length_match,
        "exact_match": exact,
        "soft_match": soft_match,
        "length_match": length_match,
        "has_residue": has_residue,
        "similarity": ratio,
        "expected_len": len(expected),
        "actual_len": len(actual),
        "before_len": len(before_text),
        "length_delta": len(actual) - len(expected),
    }


def read_input_text(app_element=None, bounds=None) -> dict:
    """读取 AI 输入框当前文字。"""
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
        "activation_info": read_text_activation_info(text_area),
    }


def is_focused_input_text_area(app_element=None, bounds=None) -> dict:
    """
    判断当前 AX 焦点是否在 Notion AI 输入文本框上。

    注意：focused=True 只代表 AX 焦点，不代表真实可输入。
    返回中的 activation_info 才能说明真实插入点是否有效。
    """
    if app_element is None or bounds is None:
        app_element, bounds, pid, error = _init_environment()
        if error:
            return {"success": False, "focused": False, "error": error}

    focused = focused_element(app_element)
    if focused is None:
        return {
            "success": True,
            "focused": False,
            "focused_info": None,
            "activation_info": None,
            "error": None,
        }

    info = element_info(focused)
    focused_is_text_area = (
        info["role"] == "AXTextArea"
        and info.get("role_description") == "文本输入区"
    )

    return {
        "success": True,
        "focused": focused_is_text_area,
        "focused_info": info,
        "activation_info": read_text_activation_info(focused) if focused_is_text_area else None,
        "error": None,
    }


def input_text(text: str, replace_existing: bool = True,
               app_element=None, bounds=None, quiet: bool = False) -> dict:
    """
    向 Notion AI 输入文本。

    默认替换输入框已有内容。实现不使用鼠标，不使用 Shift+Tab。
    """
    if app_element is None or bounds is None:
        app_element, bounds, pid, error = _init_environment()
        if error:
            return {
                "success": False,
                "text": "",
                "expected_text": text,
                "method": "selected_range_paste",
                "error": error,
            }

    text_area, info = find_text_area(app_element, bounds)
    if text_area is None:
        return {
            "success": False,
            "text": "",
            "expected_text": text,
            "method": "selected_range_paste",
            "error": "未找到 AXTextArea（输入框）",
        }

    activation = activate_text_area_insertion_point(text_area)
    if not activation["activated"]:
        return {
            "success": False,
            "text": ax_str(text_area, kAXValueAttribute),
            "expected_text": text,
            "method": "selected_range_paste",
            "replace_existing": replace_existing,
            "text_area_info": info,
            "activation_info": activation,
            "error": "未能激活输入框真实插入点",
        }

    before_text = ax_str(text_area, kAXValueAttribute)

    set_clipboard_text(text)
    post_key_combo(KEY_V, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.35)
    primed_text = ax_str(text_area, kAXValueAttribute)

    replace_strategy = {
        "before_len": len(before_text),
        "primed_len": len(primed_text),
        "double_paste": False,
        "always_double_paste": replace_existing,
    }
    if replace_existing:
        post_key_combo(KEY_A, Quartz.kCGEventFlagMaskCommand)
        time.sleep(0.12)
        post_key_combo(KEY_V, Quartz.kCGEventFlagMaskCommand)
        time.sleep(0.35)
        replace_strategy["double_paste"] = True

    validation = validate_pasted_text(
        text,
        ax_str(text_area, kAXValueAttribute),
        replace_existing,
        before_text,
    )
    actual = ax_str(text_area, kAXValueAttribute)
    deadline = time.time() + 5.0
    while not validation["success"] and time.time() < deadline:
        time.sleep(0.2)
        actual = ax_str(text_area, kAXValueAttribute)
        validation = validate_pasted_text(text, actual, replace_existing, before_text)

    success = validation["success"]
    if success and not quiet:
        print(f"  输入成功: {actual!r}")
    elif not quiet:
        print(f"  输入不匹配: 期望包含/等于 {text!r}, 实际 {actual!r}")

    return {
        "success": success,
        "text": actual,
        "expected_text": text,
        "method": "selected_range_paste",
        "replace_existing": replace_existing,
        "replace_strategy": replace_strategy,
        "validation": validation,
        "text_area_info": info,
        "activation_info": activation,
        "error": None if success else "粘贴验证不匹配",
    }


def set_input_text(text: str, app_element=None, bounds=None) -> dict:
    """
    设置 AI 输入框文字。

    兼容旧调用名；真实实现见 input_text(...)。
    """
    return input_text(text, replace_existing=True, app_element=app_element, bounds=bounds)


def clear_input_text(app_element=None, bounds=None) -> dict:
    """
    清空 AI 输入框。

    清空也先激活真实插入点，然后 Cmd+A -> Delete。
    不使用 Shift+Tab，避免触发 Notion AI 模式切换。
    """
    if app_element is None or bounds is None:
        app_element, bounds, pid, error = _init_environment()
        if error:
            return {"success": False, "error": error}

    text_area, info = find_text_area(app_element, bounds)
    if text_area is None:
        return {"success": False, "error": "未找到 AXTextArea（输入框）"}

    activation = activate_text_area_insertion_point(text_area)
    if not activation["activated"]:
        return {
            "success": False,
            "text": ax_str(text_area, kAXValueAttribute),
            "text_area_info": info,
            "activation_info": activation,
            "error": "未能激活输入框真实插入点",
        }

    post_key_combo(KEY_A, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.12)
    post_key(KEY_DELETE, True)
    time.sleep(0.05)
    post_key(KEY_DELETE, False)
    time.sleep(0.25)

    actual = ax_str(text_area, kAXValueAttribute)
    success = actual == ""
    if success:
        print("  已清空")
    else:
        print(f"  清空后仍有内容: {actual!r}")

    return {
        "success": success,
        "text": actual,
        "method": "selected_range_delete",
        "text_area_info": info,
        "activation_info": activation,
        "error": None if success else "清空后输入框仍有内容",
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python input_box.py [选项或文字]")
        print()
        print("  设置文字:")
        print('    ./venv/bin/python input_box.py "你的问题"')
        print()
        print("  操作选项:")
        print("    --read              读取输入框当前内容")
        print("    --focus-state       判断 AX 焦点和真实插入点状态")
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
            activation = result.get("activation_info", {})
            print(f"插入点行号: {activation.get('insertion_line_number')}")
            print(f"插入点有效: {activation.get('insertion_line_valid')}")
        else:
            print(f"失败: {result['error']}")
        sys.exit(0 if result["success"] else 1)

    if "--focus-state" in sys.argv:
        result = is_focused_input_text_area()
        if result["success"]:
            print(f"AX 焦点在输入文本框上: {result['focused']}")
            info = result.get("focused_info")
            if info:
                print(f"当前焦点 role: {info.get('role')}")
                print(f"当前焦点 roleDesc: {info.get('role_description')}")
                print(f"当前焦点 value: {info.get('value')!r}")
                if info.get("position"):
                    print(f"位置: ({int(info['position'][0])}, {int(info['position'][1])})")
                if info.get("size"):
                    print(f"尺寸: {int(info['size'][0])}x{int(info['size'][1])}")
            activation = result.get("activation_info")
            if activation:
                print(f"插入点行号: {activation.get('insertion_line_number')}")
                print(f"插入点有效: {activation.get('insertion_line_valid')}")
                print(f"AXSelectedText 读取错误码: {activation.get('selected_text_error')}")
                print(f"AXSelectedText: {activation.get('selected_text')!r}")
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
