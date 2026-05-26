#!/usr/bin/env python3
"""Reply copy helpers for the Notion AI ask flow."""

from __future__ import annotations

import time

from .check_ai_state import (
    BOTTOM_COPY_Y_RANGE,
    COPY_REPLY_X_RANGE,
    scan_for_copy_reply_button,
)
from .conversation_actions import ensure_ai_window
from .notion_ax import get_clipboard_text, kAXErrorSuccess, press, set_clipboard_text


COPY_REPLY_LABEL = "拷贝回复"


def _print(message: str, quiet: bool = False):
    """按 quiet 参数控制普通日志输出。"""
    if not quiet:
        print(message, flush=True)


def wait_for_bottom_copy_button(timeout: float = 3.0) -> dict:
    """轻量确认：贴底后底部操作区会出现最新回复的拷贝按钮。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app_element, bounds, error = ensure_ai_window()
        if error:
            return {"success": False, "info": None, "error": error}

        target = scan_for_copy_reply_button(
            app_element,
            bounds,
            x_range=COPY_REPLY_X_RANGE,
            y_range=BOTTOM_COPY_Y_RANGE,
            step=1,
        )
        if target is not None:
            _, info = target
            return {"success": True, "info": info, "error": None}
        time.sleep(0.15)

    return {"success": False, "info": None, "error": f"等待底部 {COPY_REPLY_LABEL!r} 超时 ({timeout}s)"}
def copy_latest_visible_reply(timeout: float = 10.0, quiet: bool = False) -> dict:
    """
    复制当前底部可见的最新回复。

    调用前应已经确认：
      - conversation_state 不是 generating
      - conversation_state 是 complete
      - is_attach_to_bottom 是 True
    """
    set_clipboard_text("")
    deadline = time.time() + timeout
    pressed = None
    while time.time() < deadline:
        app_element, bounds, error = ensure_ai_window()
        if error:
            return {"success": False, "text": "", "error": error}

        target = scan_for_copy_reply_button(app_element, bounds)
        if target is not None:
            elem, info = target
            err = press(elem)
            if err != kAXErrorSuccess:
                return {
                    "success": False,
                    "text": "",
                    "error": f"AXPressAction 失败 (error_code={err})",
                }
            _print(f"  已按下: {COPY_REPLY_LABEL}", quiet)
            pressed = {"info": info}
            break
        time.sleep(0.2)

    if pressed is None:
        return {
            "success": False,
            "text": "",
            "error": f"等待 {timeout}s 后仍未找到可按的 {COPY_REPLY_LABEL!r}",
        }

    deadline = time.time() + 5.0
    text = ""
    while time.time() < deadline:
        text = get_clipboard_text()
        if text:
            break
        time.sleep(0.2)

    if not text:
        return {"success": False, "text": "", "error": "复制后剪贴板为空"}

    return {"success": True, "text": text, "copy_button_info": pressed["info"], "error": None}
