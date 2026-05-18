#!/usr/bin/env python3
"""
读取和切换 Notion AI 当前使用的模型。

模型按钮识别规则集中在本文件的 current_model(...)：
  - role=AXPopUpButton
  - roleDesc=弹出式按钮
  - 位于输入框 AXTextArea 下方
  - 内部包含同名 AXStaticText

模型菜单打开后，候选项暴露为：
  - role=AXMenuItem
  - roleDesc=菜单项
  - label 为模型名
  - actions 包含 AXPress

用法：
    ./venv/bin/python model_selector.py --current
    ./venv/bin/python model_selector.py --list
    ./venv/bin/python model_selector.py "GPT-5.4"
    ./venv/bin/python model_selector.py "自动"
"""

import sys
import time

from check_ai_state import (
    element_contains,
    element_label,
    find_input_text_area,
    scan_visible_elements,
    split_elements_by_input_area,
)
from notion_ax import (
    bounds_tuple,
    element_at_position,
    element_info,
    get_ai_window_context,
    kAXErrorSuccess,
    press,
    raise_window,
)


FULL_SCAN_STEP = 1
MENU_SCAN_STEP = 1
MODEL_MENU_TIMEOUT = 3.0


def is_below_text_area(info: dict, text_area: dict | None) -> bool:
    """
    判断元素是否位于输入框下方。

    模型选择器虽然属于输入区，但它不在 AXTextArea 内部，而是在输入框
    下方工具栏里。用这个空间条件可以排除页面上方或菜单中的其它
    AXPopUpButton。
    """
    if text_area is None:
        return True

    elem_pos = info.get("position")
    ta_pos = text_area.get("position")
    ta_size = text_area.get("size")
    if not elem_pos or not ta_pos or not ta_size:
        return False

    text_area_bottom = ta_pos[1] + ta_size[1]
    return elem_pos[1] >= text_area_bottom


def current_model(input_elements: list[dict], text_area: dict | None = None) -> dict:
    """
    检测当前使用的模型。

    模型选择器目前暴露为输入框区域中的 AXPopUpButton：
      - role=AXPopUpButton
      - roleDesc=弹出式按钮
      - description=<模型名>
      - position.y 在 AXTextArea 下方

    同一区域还有其它 AXPopUpButton，例如 `提供背景信息`、`设置`。
    模型按钮的稳定特征是：
      1. 位于输入框下方。
      2. 内部包含一个同名 AXStaticText。
    """
    popup_buttons = [
        info for info in input_elements
        if (
            info["role"] == "AXPopUpButton"
            and element_label(info)
            and is_below_text_area(info, text_area)
        )
    ]
    static_texts = [
        info for info in input_elements
        if info["role"] == "AXStaticText" and info.get("role_description") == "文本"
    ]

    for button in popup_buttons:
        label = element_label(button)
        for text in static_texts:
            if text.get("value") == label and element_contains(button, text):
                return {
                    "name": label,
                    "element": {
                        "role": button["role"],
                        "role_description": button.get("role_description"),
                        "label": label,
                        "position": button.get("position"),
                        "size": button.get("size"),
                        "actions": button.get("actions"),
                    },
                    "text_element": {
                        "role": text["role"],
                        "role_description": text.get("role_description"),
                        "value": text.get("value"),
                        "position": text.get("position"),
                        "size": text.get("size"),
                    },
                }

    return {
        "name": None,
        "element": None,
        "text_element": None,
    }


def scan_visible_element_refs(app_element, bounds: dict, step: int = FULL_SCAN_STEP) -> list[tuple[object, dict]]:
    """
    扫描窗口可见元素，并保留 AX 元素对象引用。

    check_ai_state.scan_visible_elements(...) 只返回 dict；这里需要保留
    element 对象，后续才能对模型按钮或菜单项执行 AXPress。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    seen = set()
    results = []

    for yr in range(0, 101, step):
        for xr in range(0, 101, step):
            elem = element_at_position(
                app_element,
                float(x0 + ww * xr / 100.0),
                float(y0 + wh * yr / 100.0),
            )
            if elem is None:
                continue

            info = element_info(elem)
            key = (
                info["role"],
                info.get("role_description"),
                info["description"],
                info["title"],
                info["value"],
                info["position"],
                info["size"],
            )
            if key in seen:
                continue
            seen.add(key)
            results.append((elem, info))

    results.sort(key=lambda item: (
        item[1]["position"][1] if item[1].get("position") else 0,
        item[1]["position"][0] if item[1].get("position") else 0,
        element_label(item[1]),
    ))
    return results


def model_info_from_elements(elements: list[dict]) -> tuple[dict, dict | None, list[dict]]:
    """
    从扫描结果里读取当前模型。

    返回：
      (model_info, text_area, input_elements)
    """
    text_area = find_input_text_area(elements)
    if text_area is None:
        return {
            "name": None,
            "element": None,
            "text_element": None,
        }, None, elements

    _, input_elements = split_elements_by_input_area(elements, text_area)
    return current_model(input_elements, text_area), text_area, input_elements


def get_current_model() -> dict:
    """读取当前模型。"""
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "model": None, "error": error}

    raise_window(window)
    elements = scan_visible_elements(app_element, bounds)
    model_info, text_area, input_elements = model_info_from_elements(elements)
    if not model_info["name"]:
        return {
            "success": False,
            "model": None,
            "model_info": model_info,
            "error": "未找到模型选择按钮",
        }

    return {
        "success": True,
        "model": model_info["name"],
        "model_info": model_info,
        "error": None,
    }


def same_lightweight_info(left: dict, right: dict) -> bool:
    """判断两个扫描 info 是否指向同一个轻量 AX 元素。"""
    right_label = right.get("label") or element_label(right)
    return (
        left.get("role") == right.get("role")
        and left.get("role_description") == right.get("role_description")
        and element_label(left) == right_label
        and left.get("position") == right.get("position")
        and left.get("size") == right.get("size")
    )


def find_model_button_ref(app_element, bounds: dict) -> tuple[object, dict, dict] | tuple[None, None, dict]:
    """
    找当前模型按钮，并返回可 press 的 AX 元素对象。
    """
    refs = scan_visible_element_refs(app_element, bounds)
    elements = [info for _, info in refs]
    model_info, text_area, input_elements = model_info_from_elements(elements)
    button_info = model_info.get("element")
    if not button_info:
        return None, None, model_info

    for elem, info in refs:
        if same_lightweight_info(info, button_info):
            return elem, info, model_info

    return None, None, model_info


def is_model_menu_item(info: dict, target_model: str | None = None) -> bool:
    """
    判断是否是模型菜单项。

    模型菜单里的候选项是 AXMenuItem，并且支持 AXPress。传入 target_model
    时，只匹配指定模型名。
    """
    if info["role"] != "AXMenuItem":
        return False
    if "AXPress" not in info.get("actions", []):
        return False
    label = element_label(info)
    if not label:
        return False
    if target_model is not None and label != target_model:
        return False
    return True


def scan_model_menu_items(app_element, bounds: dict) -> list[tuple[object, dict]]:
    """
    扫描当前打开的模型菜单项。

    菜单打开时，候选模型以 AXMenuItem 暴露。
    """
    refs = scan_visible_element_refs(app_element, bounds, step=MENU_SCAN_STEP)
    return [
        (elem, info)
        for elem, info in refs
        if is_model_menu_item(info)
    ]


def wait_for_model_menu_item(app_element, bounds: dict, target_model: str,
                             timeout: float = MODEL_MENU_TIMEOUT) -> tuple[object, dict] | tuple[None, None]:
    """等待目标模型菜单项出现。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for elem, info in scan_model_menu_items(app_element, bounds):
            if is_model_menu_item(info, target_model):
                return elem, info
        time.sleep(0.15)
    return None, None


def list_models() -> dict:
    """
    打开模型菜单并列出当前可见模型选项。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "models": [], "error": error}

    raise_window(window)
    button, button_info, model_info = find_model_button_ref(app_element, bounds)
    if button is None:
        return {
            "success": False,
            "models": [],
            "current_model": model_info.get("name"),
            "error": "未找到模型选择按钮",
        }

    err = press(button)
    if err != kAXErrorSuccess:
        return {
            "success": False,
            "models": [],
            "current_model": model_info.get("name"),
            "action_error": err,
            "error": f"打开模型菜单失败 (error_code={err})",
        }

    time.sleep(0.25)
    items = scan_model_menu_items(app_element, bounds)
    models = []
    seen = set()
    for elem, info in items:
        label = element_label(info)
        if label not in seen:
            seen.add(label)
            models.append(label)

    return {
        "success": True,
        "current_model": model_info.get("name"),
        "models": models,
        "error": None,
    }


def select_model(target_model: str) -> dict:
    """
    选择指定模型。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "target_model": target_model, "error": error}

    raise_window(window)
    button, button_info, model_info = find_model_button_ref(app_element, bounds)
    current = model_info.get("name")
    if button is None:
        # 可能菜单已经打开：此时主界面的 AXPopUpButton 会暂时消失，
        # 但模型候选项 AXMenuItem 已经可见，可以直接选择。
        menu_item, menu_info = wait_for_model_menu_item(app_element, bounds, target_model, timeout=0.8)
        if menu_item is None:
            return {
                "success": False,
                "target_model": target_model,
                "current_model": current,
                "error": "未找到模型选择按钮，也未找到已打开菜单中的目标模型",
            }

        select_err = press(menu_item)
        if select_err != kAXErrorSuccess:
            return {
                "success": False,
                "target_model": target_model,
                "current_model": current,
                "menu_item_info": menu_info,
                "action_error": select_err,
                "error": f"选择模型失败 (error_code={select_err})",
            }

        return wait_until_current_model(app_element, bounds, target_model, previous_model=current)

    if current == target_model:
        return {
            "success": True,
            "target_model": target_model,
            "current_model": current,
            "changed": False,
            "error": None,
        }

    open_err = press(button)
    if open_err != kAXErrorSuccess:
        return {
            "success": False,
            "target_model": target_model,
            "current_model": current,
            "action_error": open_err,
            "error": f"打开模型菜单失败 (error_code={open_err})",
        }

    menu_item, menu_info = wait_for_model_menu_item(app_element, bounds, target_model)
    if menu_item is None:
        visible_models = [element_label(info) for _, info in scan_model_menu_items(app_element, bounds)]
        return {
            "success": False,
            "target_model": target_model,
            "current_model": current,
            "visible_models": visible_models,
            "error": "未找到目标模型菜单项",
        }

    select_err = press(menu_item)
    if select_err != kAXErrorSuccess:
        return {
            "success": False,
            "target_model": target_model,
            "current_model": current,
            "menu_item_info": menu_info,
            "action_error": select_err,
            "error": f"选择模型失败 (error_code={select_err})",
        }

    return wait_until_current_model(app_element, bounds, target_model, previous_model=current)


def wait_until_current_model(app_element, bounds: dict, target_model: str,
                             previous_model: str | None = None) -> dict:
    """
    等待模型按钮恢复，并验证当前模型。
    """
    deadline = time.time() + 3.0
    final_model = None
    final_info = None
    while time.time() < deadline:
        time.sleep(0.2)
        elements = scan_visible_elements(app_element, bounds)
        final_info, _, _ = model_info_from_elements(elements)
        final_model = final_info.get("name")
        if final_model == target_model:
            break

    return {
        "success": final_model == target_model,
        "target_model": target_model,
        "previous_model": previous_model,
        "current_model": final_model,
        "changed": final_model == target_model and previous_model != target_model,
        "model_info": final_info,
        "error": None if final_model == target_model else "选择后验证模型失败",
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python model_selector.py [选项或模型名]")
        print()
        print("选项:")
        print("  --current       读取当前模型")
        print("  --list          打开模型菜单并列出可见模型")
        print()
        print("示例:")
        print('  ./venv/bin/python model_selector.py --current')
        print('  ./venv/bin/python model_selector.py --list')
        print('  ./venv/bin/python model_selector.py "GPT-5.4"')
        print('  ./venv/bin/python model_selector.py "自动"')
        sys.exit(0)

    if sys.argv[1] == "--current":
        result = get_current_model()
        if result["success"]:
            print(f"当前模型: {result['model']}")
        else:
            print(f"失败: {result['error']}")
            sys.exit(1)
        return

    if sys.argv[1] == "--list":
        result = list_models()
        if result["success"]:
            print(f"当前模型: {result.get('current_model')}")
            print("可见模型:")
            for model in result["models"]:
                print(f"  - {model}")
        else:
            print(f"失败: {result['error']}")
            sys.exit(1)
        return

    target_model = sys.argv[1]
    print(f"===== 选择模型: {target_model!r} =====")
    result = select_model(target_model)
    if result["success"]:
        if result.get("changed"):
            print(f"已切换: {result.get('previous_model')} -> {result['current_model']}")
        else:
            print(f"当前已是目标模型: {result['current_model']}")
    else:
        print(f"失败: {result['error']}")
        if result.get("visible_models"):
            print("当前可见模型:")
            for model in result["visible_models"]:
                print(f"  - {model}")
        sys.exit(1)


if __name__ == "__main__":
    main()
