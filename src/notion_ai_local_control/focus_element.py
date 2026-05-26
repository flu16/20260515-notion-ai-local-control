#!/usr/bin/env python3
"""
聚焦到 Notion AI 窗口中的指定元素。

用法:
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.focus_element "提供背景信息"
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.focus_element "设置"
    PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.focus_element "提交 AI 消息"
"""

import sys

from .notion_ax import set_focused
from .search_element import search_element


def focus_element(target_description: str) -> dict:
    result = search_element(target_description)
    if not result["success"]:
        return {
            "success": False,
            "description": target_description,
            "error": result.get("error", "搜索失败"),
        }

    element = result["element"]
    err = set_focused(element, True)
    success = err == 0  # kAXErrorSuccess == 0

    return {
        "success": success,
        "description": target_description,
        "method": result.get("method", "unknown"),
        "element_info": result.get("info", {}),
        "focus_error": err,
    }


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.focus_element <description>")
        print('示例: PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.focus_element "提供背景信息"')
        sys.exit(0)

    target = sys.argv[1]
    print(f"===== 聚焦元素: {target!r} =====\n")
    result = focus_element(target)

    if result["success"]:
        print(f"聚焦成功: {result['description']} via {result['method']}")
        info = result.get("element_info", {})
        if info.get("position"):
            print(f"  位置: {info['position']}")
        if info.get("role"):
            print(f"  角色: {info['role']}")
    else:
        print(f"聚焦失败: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
