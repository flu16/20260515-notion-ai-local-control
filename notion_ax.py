#!/usr/bin/env python3
"""
Shared macOS Accessibility helpers for driving the Notion AI window.

This module deliberately stays low-level: it knows how to find Notion,
recognize the AI window, read AX attributes, post keyboard events,
and use the system clipboard. Higher-level scripts decide what to do with
those primitives.
"""

import time

import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString
from ApplicationServices import (
    AXUIElementCopyActionNames,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyElementAtPosition,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
    kAXDescriptionAttribute,
    kAXErrorSuccess,
    kAXFocusedAttribute,
    kAXFocusedUIElementAttribute,
    kAXMinimizedAttribute,
    kAXPositionAttribute,
    kAXPressAction,
    kAXRaiseAction,
    kAXRoleDescriptionAttribute,
    kAXRoleAttribute,
    kAXSizeAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXWindowsAttribute,
)
from Cocoa import NSWorkspace


NOTION_APP_NAME = "Notion"
NOTION_BUNDLE_ID = "notion.id"
AI_WINDOW_TITLE_MARKERS = ("命令搜索",)
MAIN_WINDOW_MIN_WIDTH = 700
MAIN_WINDOW_MIN_HEIGHT = 450
FLOATING_AI_MIN_Y = 80
FLOATING_AI_MAX_HEIGHT = 760

KEY_A = 0
KEY_V = 9
KEY_J = 38
KEY_TAB = 48
KEY_DELETE = 51


def ax_str(element, attr: str) -> str:
    """Read an AX string-like attribute. Return an empty string on failure."""
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    return str(value) if ok == kAXErrorSuccess and value is not None else ""


def ax_point(element, attr: str):
    """Read an AX CGPoint attribute as (x, y). Return None on failure."""
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return None
    try:
        ok2, point = AXValueGetValue(value, kAXValueCGPointType, None)
        if ok2 and point is not None:
            return (point.x, point.y)
    except Exception:
        pass
    return None


def ax_size(element, attr: str):
    """Read an AX CGSize attribute as (width, height). Return None on failure."""
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return None
    try:
        ok2, size = AXValueGetValue(value, kAXValueCGSizeType, None)
        if ok2 and size is not None:
            return (size.width, size.height)
    except Exception:
        pass
    return None


def ax_actions(element) -> list[str]:
    """Read supported AX action names."""
    ok, actions = AXUIElementCopyActionNames(element, None)
    if ok != kAXErrorSuccess or actions is None:
        return []
    return list(actions)


def ax_bool(element, attr: str) -> bool | None:
    """Read an AX boolean attribute. Return None on failure."""
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return None
    return bool(value)


def element_info(element, description: str | None = None) -> dict:
    """Collect the small, stable AX fields useful for debugging."""
    return {
        "role": ax_str(element, kAXRoleAttribute),
        "role_description": ax_str(element, kAXRoleDescriptionAttribute),
        "description": description if description is not None else ax_str(element, kAXDescriptionAttribute),
        "title": ax_str(element, kAXTitleAttribute),
        "value": ax_str(element, kAXValueAttribute),
        "position": ax_point(element, kAXPositionAttribute),
        "size": ax_size(element, kAXSizeAttribute),
        "actions": ax_actions(element),
    }


def find_notion_app():
    """Return the running Notion app, or None if Notion is not running."""
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.localizedName() == NOTION_APP_NAME or app.bundleIdentifier() == NOTION_BUNDLE_ID:
            return app
    return None


def create_notion_app_element():
    """Return (app_element, app, error)."""
    app = find_notion_app()
    if app is None:
        return None, None, "Notion 未运行"
    return AXUIElementCreateApplication(app.processIdentifier()), app, None


def enable_manual_accessibility(app_element, settle: float = 0.3):
    """
    Enable AXManualAccessibility for Electron.

    Setting it twice is intentionally kept from the proven scripts: the first
    write initializes Electron's AX bridge, the second confirms it is active.
    """
    AXUIElementSetAttributeValue(app_element, "AXManualAccessibility", True)
    time.sleep(settle)
    AXUIElementSetAttributeValue(app_element, "AXManualAccessibility", True)


def app_windows(app_element):
    ok, windows = AXUIElementCopyAttributeValue(app_element, kAXWindowsAttribute, None)
    if ok != kAXErrorSuccess or windows is None:
        return []
    return list(windows)


def is_ai_window_title(title: str) -> bool:
    return any(marker in title for marker in AI_WINDOW_TITLE_MARKERS)


def is_minimized(window) -> bool:
    return ax_bool(window, kAXMinimizedAttribute) is True


def is_floating_ai_shaped_window(window) -> bool:
    """Return True for the centered command-window shape, not the main workspace."""
    bounds = get_bounds(window)
    if not bounds or is_minimized(window):
        return False
    return (
        bounds["y"] >= FLOATING_AI_MIN_Y
        and bounds["height"] <= FLOATING_AI_MAX_HEIGHT
        and bounds["width"] >= MAIN_WINDOW_MIN_WIDTH
    )


def is_ai_window(app_element, window) -> bool:
    title = ax_str(window, kAXTitleAttribute)
    return is_ai_window_title(title) or is_floating_ai_shaped_window(window)


def is_likely_notion_main_window(app_element, window) -> bool:
    """
    Return True for Notion's regular workspace window, not the AI command window.

    The AI command window starts with a "命令搜索" title. After the title changes
    to a conversation topic, use the floating-window shape as a fallback. Do not
    rely on internal AI button labels because the main Notion workspace can
    expose the same labels.
    """
    title = ax_str(window, kAXTitleAttribute)
    if is_ai_window(app_element, window):
        return False

    bounds = get_bounds(window)
    if not bounds:
        return False

    return (
        bounds["width"] >= MAIN_WINDOW_MIN_WIDTH
        and bounds["height"] >= MAIN_WINDOW_MIN_HEIGHT
    )


def find_notion_main_windows(app_element) -> list:
    """Return Notion workspace windows that are not AI command windows."""
    return [window for window in app_windows(app_element) if is_likely_notion_main_window(app_element, window)]


def minimize_window(window, settle: float = 0.2):
    result = AXUIElementSetAttributeValue(window, kAXMinimizedAttribute, True)
    time.sleep(settle)
    return result


def minimize_notion_main_windows(app_element) -> int:
    """Minimize regular Notion windows so Cmd+Shift+J can open the AI window."""
    minimized = 0
    for window in find_notion_main_windows(app_element):
        if minimize_window(window) == kAXErrorSuccess:
            minimized += 1
    return minimized


def find_ai_window(app_element):
    """
    Find the Notion AI floating window.

    The title starts as "命令搜索", then changes to the chat topic after a message
    is sent. The fallback checks the floating-window geometry; internal labels
    are not enough because the main Notion workspace can expose the same AI
    controls.
    """
    windows = app_windows(app_element)

    for window in windows:
        if is_ai_window(app_element, window):
            return window
    return None


def get_bounds(element):
    """Return AX element bounds as a dict, or None."""
    pos = ax_point(element, kAXPositionAttribute)
    size = ax_size(element, kAXSizeAttribute)
    if pos is None or size is None:
        return None
    return {"x": pos[0], "y": pos[1], "width": size[0], "height": size[1]}


def get_ai_window_context():
    """Return (app_element, app, window, bounds, error) for the current AI window."""
    app_element, app, error = create_notion_app_element()
    if error:
        return None, None, None, None, error

    enable_manual_accessibility(app_element)
    window = find_ai_window(app_element)
    if window is None:
        return app_element, app, None, None, "未找到 AI 窗口，请按 Cmd+Shift+J 打开"

    bounds = get_bounds(window)
    if bounds is None:
        return app_element, app, window, None, "无法获取窗口坐标"

    return app_element, app, window, bounds, None


def post_key(keycode: int, keydown: bool, modifiers: int = 0):
    event = Quartz.CGEventCreateKeyboardEvent(None, keycode, keydown)
    if modifiers:
        Quartz.CGEventSetFlags(event, modifiers)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def post_key_combo(keycode: int, modifiers: int = 0, pause: float = 0.05):
    post_key(keycode, True, modifiers)
    time.sleep(pause)
    post_key(keycode, False, modifiers)
    time.sleep(pause)


def post_tab():
    post_key(KEY_TAB, True)
    time.sleep(0.05)
    post_key(KEY_TAB, False)
    time.sleep(0.15)


def post_open_ai_shortcut():
    post_key_combo(KEY_J, Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift)


def raise_window(window, settle: float = 0.3):
    AXUIElementPerformAction(window, kAXRaiseAction)
    time.sleep(settle)


def set_focused(element, focused: bool = True):
    return AXUIElementSetAttributeValue(element, kAXFocusedAttribute, focused)


def press(element):
    return AXUIElementPerformAction(element, kAXPressAction)


def focused_element(app_element):
    ok, element = AXUIElementCopyAttributeValue(app_element, kAXFocusedUIElementAttribute, None)
    if ok != kAXErrorSuccess or element is None:
        return None
    return element


def element_at_position(app_element, x: float, y: float):
    ok, element = AXUIElementCopyElementAtPosition(app_element, x, y, None)
    if ok != kAXErrorSuccess or element is None:
        return None
    return element


def set_clipboard_text(text: str):
    pb = NSPasteboard.generalPasteboard()
    pb.declareTypes_owner_([NSPasteboardTypeString], None)
    pb.setString_forType_(text, NSPasteboardTypeString)


def get_clipboard_text() -> str:
    text = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
    return text or ""


def bounds_tuple(bounds: dict):
    return bounds["x"], bounds["y"], bounds["width"], bounds["height"]


__all__ = [
    "KEY_A",
    "KEY_DELETE",
    "KEY_J",
    "KEY_TAB",
    "KEY_V",
    "Quartz",
    "ax_actions",
    "ax_bool",
    "ax_point",
    "ax_size",
    "ax_str",
    "bounds_tuple",
    "create_notion_app_element",
    "element_at_position",
    "element_info",
    "enable_manual_accessibility",
    "find_ai_window",
    "find_notion_app",
    "find_notion_main_windows",
    "focused_element",
    "get_ai_window_context",
    "get_bounds",
    "get_clipboard_text",
    "is_ai_window",
    "is_ai_window_title",
    "is_floating_ai_shaped_window",
    "is_likely_notion_main_window",
    "is_minimized",
    "kAXDescriptionAttribute",
    "kAXErrorSuccess",
    "kAXFocusedAttribute",
    "kAXMinimizedAttribute",
    "kAXPositionAttribute",
    "kAXRoleDescriptionAttribute",
    "kAXRoleAttribute",
    "kAXSizeAttribute",
    "kAXTitleAttribute",
    "kAXValueAttribute",
    "minimize_notion_main_windows",
    "minimize_window",
    "post_key",
    "post_key_combo",
    "post_open_ai_shortcut",
    "post_tab",
    "press",
    "raise_window",
    "set_clipboard_text",
    "set_focused",
]
