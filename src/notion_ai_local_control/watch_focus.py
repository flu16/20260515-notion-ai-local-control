#!/usr/bin/env python3
"""
监听 macOS 应用中当前焦点元素的变化，并打印元素的所有属性。

用途：了解 Notion AI 窗口中各个 UI 元素的 AX 属性（角色、标题、描述、值、位置、大小、动作等），
      为后续自动化操作（设置输入、点击按钮）提供参考。

用法：
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus                    # 默认监听 "Notion"
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus "Google Chrome"    # 按应用名监听
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus com.apple.Safari   # 按 bundle ID 监听
"""

import sys
import time
from datetime import datetime

# PyObjC 的 ApplicationServices 框架 — 提供 macOS Accessibility (AX) API
from ApplicationServices import (
    AXUIElementCreateApplication,        # 通过 PID 创建应用的 AX 元素
    AXUIElementCopyAttributeValue,       # 读取 AX 元素的属性值
    AXUIElementCopyActionNames,          # 获取 AX 元素支持的操作列表
    AXUIElementSetAttributeValue,        # 设置 AX 元素的属性值（如 AXManualAccessibility）
    AXValueGetValue,                     # 解析 AXValue 类型的值（坐标、大小等）
    kAXErrorSuccess,                     # AX 操作成功的错误码
    kAXFocusedUIElementAttribute,        # 属性名：当前焦点元素
    kAXRoleAttribute,                    # 属性名：角色（Button/TextArea/StaticText...）
    kAXRoleDescriptionAttribute,         # 属性名：角色的人类可读描述
    kAXTitleAttribute,                   # 属性名：标题
    kAXDescriptionAttribute,             # 属性名：无障碍描述
    kAXValueAttribute,                   # 属性名：当前值
    kAXPositionAttribute,                # 属性名：在屏幕上的位置
    kAXSizeAttribute,                    # 属性名：大小
    kAXValueCGPointType,                 # CGPoint 类型的 AXValue 标识
    kAXValueCGSizeType,                  # CGSize 类型的 AXValue 标识
)
# Cocoa 框架 — 用于访问 NSWorkspace 获取运行中的应用列表
from Cocoa import NSWorkspace


# ---------------------------------------------------------------------------
# 辅助函数：从 AX 元素中安全地提取各种类型的属性值
# ---------------------------------------------------------------------------

def attr_str(element, attr: str) -> str:
    """
    读取 AX 元素的字符串属性。
    PyObjC 中 AXUIElementCopyAttributeValue 返回 (error_code, value) 元组。
    如果属性值是 AXUIElement，返回 '<AXUIElement>' 避免打印垃圾数据。
    过滤换行符和多余空格，使输出保持在一行内。
    """
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return ""
    raw = str(value)
    # AXUIElement 的字符串表示是一个内存地址，没有实际意义，统一标记
    if raw.startswith("<AXUIElement"):
        return "<AXUIElement>"
    # 将换行替换为空格，压缩多余空格，确保一行显示
    return raw.replace("\n", " ").replace("  ", " ")


def attr_point(element, attr: str) -> str:
    """
    读取 AX 元素的坐标属性（CGPoint 类型）。
    AXValueGetValue 将 AXValue 对象解析为 Python CGPoint 结构体。
    返回格式："x,y"，失败时返回空字符串。
    """
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return ""
    try:
        ok2, point = AXValueGetValue(value, kAXValueCGPointType, None)
        if ok2 and point is not None:
            return f"{int(point.x)},{int(point.y)}"
    except Exception:
        pass
    return ""


def attr_size(element, attr: str) -> str:
    """
    读取 AX 元素的尺寸属性（CGSize 类型）。
    返回格式："宽x高"，失败时返回空字符串。
    """
    ok, value = AXUIElementCopyAttributeValue(element, attr, None)
    if ok != kAXErrorSuccess or value is None:
        return ""
    try:
        ok2, size = AXValueGetValue(value, kAXValueCGSizeType, None)
        if ok2 and size is not None:
            return f"{int(size.width)}x{int(size.height)}"
    except Exception:
        pass
    return ""


def attr_actions(element) -> str:
    """
    获取 AX 元素支持的所有动作名称，用逗号拼接。
    例如 Button 通常支持 'AXPressAction'，TextArea 支持 'AXConfirmAction' 等。

    注意：AXUIElementCopyActionNames 返回 (error_code, tuple_of_names)，
    error_code 成功时为 0（kAXErrorSuccess），必须用 == 比较，不能 if not ok，
    因为 0 在 Python 中是 falsy！
    """
    ok, actions = AXUIElementCopyActionNames(element, None)
    if ok != kAXErrorSuccess or actions is None:
        return ""
    return ",".join(actions)


# ---------------------------------------------------------------------------
# 主循环：持续监控焦点变化
# ---------------------------------------------------------------------------

def main():
    # 第一个命令行参数作为目标应用名或 bundle ID，默认 Notion
    target = sys.argv[1] if len(sys.argv) > 1 else "Notion"

    # 遍历所有运行中的应用，按名称或 bundle ID 匹配
    app = None
    for running_app in NSWorkspace.sharedWorkspace().runningApplications():
        if running_app.localizedName() == target or running_app.bundleIdentifier() == target:
            app = running_app
            break

    if app is None:
        print(f"No running app found for '{target}'", file=sys.stderr)
        sys.exit(2)

    # 通过 PID 创建该应用的 AX 元素，作为访问整个应用 AX 树的入口
    app_element = AXUIElementCreateApplication(app.processIdentifier())

    # 开启 AXManualAccessibility — Electron 应用必须设此开关
    # 否则 AX API 返回 kAXErrorAPIDisabled (-25212)，永远读不到焦点
    AXUIElementSetAttributeValue(app_element, 'AXManualAccessibility', True)
    time.sleep(0.3)
    AXUIElementSetAttributeValue(app_element, 'AXManualAccessibility', True)

    name = app.localizedName() or target
    print(f"Watching focus for {name} pid={app.processIdentifier()}. Press Ctrl+C to stop.")
    sys.stdout.flush()

    last_line = ""  # 用于去重：只有变化时才打印
    while True:
        # 读取应用的当前焦点元素。这是整个监控的核心 API：
        # 无论用户在应用中点击了什么、Tab 到了哪里，这个属性都会反映当前焦点元素
        ok, focused = AXUIElementCopyAttributeValue(
            app_element, kAXFocusedUIElementAttribute, None
        )

        if ok == kAXErrorSuccess and focused is not None:
            # 成功获取到焦点元素 — 收集所有感兴趣的信息
            role = attr_str(focused, kAXRoleAttribute)
            role_desc = attr_str(focused, kAXRoleDescriptionAttribute)
            title = attr_str(focused, kAXTitleAttribute)
            desc = attr_str(focused, kAXDescriptionAttribute)
            value = attr_str(focused, kAXValueAttribute)
            pos = attr_point(focused, kAXPositionAttribute)
            size = attr_size(focused, kAXSizeAttribute)
            actions = attr_actions(focused)
            line = (
                f"role={role} roleDesc={role_desc} title={title} "
                f"desc={desc} value={value} pos={pos} size={size} actions={actions}"
            )
        else:
            # 焦点丢失或出错（比如窗口最小化、无焦点等）
            line = f"focusedErr={ok}"

        # 仅当信息相比上次有变化时才打印，避免刷屏
        if line != last_line:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # 精确到毫秒
            print(f"[{ts}] {line}")
            sys.stdout.flush()
            last_line = line

        # 每 200ms 检查一次，足够灵敏又不会太耗 CPU
        time.sleep(0.2)


if __name__ == "__main__":
    main()
