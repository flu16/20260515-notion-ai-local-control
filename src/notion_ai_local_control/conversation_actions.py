#!/usr/bin/env python3
"""Window, scanning, and button actions for Notion AI conversations."""

from __future__ import annotations

import time

from .check_ai_state import (
    element_label,
    scan_for_back_to_bottom_button,
)
from .notion_ax import (
    bounds_tuple,
    element_at_position,
    element_info,
    get_ai_window_context,
    kAXErrorSuccess,
    minimize_notion_main_windows,
    post_open_ai_shortcut,
    press,
    raise_window,
)


NEW_CONVERSATION_LABEL = "开始新对话"


def _print(message: str, quiet: bool = False):
    """按 quiet 参数控制普通日志输出。"""
    if not quiet:
        print(message, flush=True)


def ensure_ai_window(timeout: float = 5.0) -> tuple[object | None, dict | None, str | None]:
    """
    确保 Notion AI 窗口存在，并返回 (app_element, bounds, error)。

    如果窗口没有打开，会发送 Cmd+Shift+J。若窗口本来已经打开，不会重复打开，
    避免把用户已经打开的窗口关掉或切换掉。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if window is not None and bounds is not None:
        raise_window(window)
        return app_element, bounds, None

    if error and "未找到 AI 窗口" not in error:
        return None, None, error

    minimize_notion_main_windows(app_element)
    post_open_ai_shortcut()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.25)
        app_element, app, window, bounds, error = get_ai_window_context()
        if window is not None and bounds is not None:
            raise_window(window)
            return app_element, bounds, None

    return None, None, "未找到 AI 窗口"


def scan_visible_element_objects(step: int = 1, x_range=(0, 100),
                                 y_range=(0, 100)) -> list[tuple[object, dict]]:
    """
    扫描当前 AI 窗口可见元素，返回可直接 AXPress 的元素对象和轻量信息。

    check_ai_state.py 只返回 dict 信息；而这里需要真正按按钮，所以重新扫描并保留
    AX 元素对象本身。
    """
    app_element, bounds, error = ensure_ai_window()
    if error:
        return []

    x0, y0, ww, wh = bounds_tuple(bounds)
    seen = set()
    elements: list[tuple[object, dict]] = []

    for yr in range(y_range[0], y_range[1] + 1, step):
        for xr in range(x_range[0], x_range[1] + 1, step):
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
                info.get("description"),
                info.get("title"),
                info.get("value"),
                info.get("position"),
                info.get("size"),
            )
            if key in seen:
                continue
            seen.add(key)
            elements.append((elem, info))

    elements.sort(key=lambda item: (
        item[1]["position"][1] if item[1].get("position") else 0,
        item[1]["position"][0] if item[1].get("position") else 0,
        element_label(item[1]),
    ))
    return elements


def bottom_most(elements: list[tuple[object, dict]]) -> tuple[object, dict] | None:
    """返回 y 坐标最靠下的元素。"""
    if not elements:
        return None
    return max(
        elements,
        key=lambda item: (
            item[1]["position"][1] if item[1].get("position") else -1,
            item[1]["position"][0] if item[1].get("position") else -1,
        ),
    )


def label_options(label: str | tuple[str, ...] | list[str] | set[str]) -> set[str]:
    """把单个 label 或多个候选 label 统一成集合。"""
    if isinstance(label, str):
        return {label}
    return set(label)


def find_labeled_button(label: str | tuple[str, ...] | list[str] | set[str],
                        x_range=(0, 100), y_range=(0, 100),
                        step: int = 1) -> tuple[object, dict] | None:
    """在指定可见区域内查找最靠下的可按 label 按钮。"""
    labels = label_options(label)
    matches = [
        (elem, info)
        for elem, info in scan_visible_element_objects(
            step=step,
            x_range=x_range,
            y_range=y_range,
        )
        if element_label(info) in labels and "AXPress" in info.get("actions", [])
    ]
    return bottom_most(matches)


def press_labeled_button(label: str | tuple[str, ...] | list[str] | set[str],
                         timeout: float = 5.0,
                         x_range=(0, 100), y_range=(0, 100),
                         step: int = 1, quiet: bool = False) -> dict:
    """
    等待并按下指定 label 的按钮。

    用全窗口可见元素扫描，不使用 Tab，避免焦点链跑到别的位置。
    """
    deadline = time.time() + timeout
    last_count = 0
    labels = label_options(label)
    label_text = " / ".join(sorted(labels))
    while time.time() < deadline:
        target = find_labeled_button(label, x_range=x_range, y_range=y_range, step=step)
        last_count = 1 if target is not None else 0
        if target is not None:
            elem, info = target
            err = press(elem)
            if err == kAXErrorSuccess:
                _print(f"  已按下: {element_label(info) or label_text}", quiet)
                return {"success": True, "info": info, "error": None}
            return {
                "success": False,
                "info": info,
                "error": f"AXPressAction 失败 (error_code={err})",
            }
        time.sleep(0.2)

    return {
        "success": False,
        "info": None,
        "error": f"等待 {timeout}s 后仍未找到可按的 {label_text!r}，最后匹配数={last_count}",
    }


def wait_for_new_conversation_light(timeout: float = 4.0,
                                    app_element=None,
                                    bounds=None,
                                    quiet: bool = False) -> dict:
    """
    轻量等待新对话就绪。

    不跑完整状态机；只确认对话区域出现 Notion AI face 图像，并返回当前窗口 context。
    输入框草稿不会被“开始新对话”清空，后续 input_text 的双粘贴会覆盖它。
    """
    deadline = time.time() + timeout
    last_key = None
    last_result = None

    while time.time() < deadline:
        if app_element is None or bounds is None:
            app_element, bounds, error = ensure_ai_window(timeout=1.0)
            if error:
                last_result = {"success": False, "error": error}
                time.sleep(0.15)
                continue

        has_notion_ai_face = False
        for _, info in scan_visible_element_objects(
            step=2,
            x_range=(0, 18),
            y_range=(45, 82),
        ):
            if (
                info.get("role") == "AXImage"
                and element_label(info) == "Notion AI face"
            ):
                has_notion_ai_face = True
                break

        key = (has_notion_ai_face,)
        if key != last_key:
            _print(
                "  新对话轻量信号: "
                f"Notion AI face={'是' if has_notion_ai_face else '否'}",
                quiet,
            )
            last_key = key

        if has_notion_ai_face:
            return {
                "success": True,
                "state": {
                    "conversation_state": "new_conversation",
                },
                "app_element": app_element,
                "bounds": bounds,
                "error": None,
            }

        last_result = {
            "success": False,
            "has_notion_ai_face": has_notion_ai_face,
        }
        time.sleep(0.15)

    return {
        "success": False,
        "state": last_result,
        "app_element": None,
        "bounds": None,
        "error": f"等待新对话轻量信号超时 ({timeout}s)",
    }
def press_back_to_bottom(timeout: float = 5.0, quiet: bool = False) -> dict:
    """
    按下对话框里的无 label 32x32 回到底部按钮。

    这个按钮没有文字，必须保存扫描到的 AX 元素对象后直接 press。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        app_element, bounds, error = ensure_ai_window()
        if error:
            return {"success": False, "info": None, "error": error}

        target = scan_for_back_to_bottom_button(app_element, bounds)
        if target is None:
            target = scan_for_back_to_bottom_button(
                app_element,
                bounds,
                x_range=(0, 100),
                y_range=(0, 100),
            )
        if target is not None:
            elem, info = target
            err = press(elem)
            if err == kAXErrorSuccess:
                _print("  已按下回到底部按钮", quiet)
                return {"success": True, "info": info, "error": None}
            return {
                "success": False,
                "info": info,
                "error": f"AXPressAction 失败 (error_code={err})",
            }
        time.sleep(0.2)

    return {"success": False, "info": None, "error": f"等待 {timeout}s 后仍未找到回到底部按钮"}
def start_new_conversation(timeout: float = 10.0, quiet: bool = False,
                           app_element=None, bounds=None) -> dict:
    """
    按下 `开始新对话`，并等待窗口回到新对话状态。

    这个步骤只在用户显式传入 --new_conversation 时执行。默认流程不会自动开新对话，
    以免打断用户当前正在看的上下文。
    输入框可能保留旧内容；后续 input_text 会在写入前清空并验证无残留。
    """
    pressed = press_labeled_button(
        NEW_CONVERSATION_LABEL,
        timeout=5.0,
        x_range=(75, 100),
        y_range=(0, 20),
        quiet=quiet,
    )
    if not pressed["success"]:
        return {
            "success": False,
            "state": None,
            "error": pressed["error"],
        }

    if app_element is None or bounds is None:
        app_element, bounds, error = ensure_ai_window(timeout=1.0)
        if error:
            return {
                "success": False,
                "state": None,
                "app_element": None,
                "bounds": None,
                "error": error,
            }
    return wait_for_new_conversation_light(
        timeout=min(timeout, 4.0),
        app_element=app_element,
        bounds=bounds,
        quiet=quiet,
    )
