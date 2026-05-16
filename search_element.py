#!/usr/bin/env python3
"""
在 Notion AI 窗口中搜索和定位 UI 元素。

组合策略：
  1. 网格扫描：在当前窗口可见区域内按坐标命中测试，速度快。
  2. Tab 导航：网格找不到时轮动焦点，可覆盖滚动后才出现的元素。

用法：
    ./venv/bin/python search_element.py "提交 AI 消息"
    ./venv/bin/python search_element.py "拷贝回复" --timeout 30
    ./venv/bin/python search_element.py --list
    ./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty
"""

import sys
import time

from notion_ax import (
    ax_str,
    bounds_tuple,
    element_at_position,
    element_info,
    focused_element,
    get_ai_window_context,
    kAXDescriptionAttribute,
    kAXTitleAttribute,
    post_tab,
    raise_window,
)


def grid_scan_element(app_element, bounds: dict, target_description: str, step: int = 1):
    """
    在窗口区域内网格扫描 AXDescription。

    step 是百分比步长；step=1 约 10,000 次命中测试，较稳但稍慢。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    for yr in range(0, 101, step):
        for xr in range(0, 101, step):
            elem = element_at_position(
                app_element,
                float(x0 + ww * xr / 100.0),
                float(y0 + wh * yr / 100.0),
            )
            if elem is None:
                continue
            if ax_str(elem, kAXDescriptionAttribute) == target_description:
                info = element_info(elem, description=target_description)
                info["method"] = "grid_scan"
                return elem, info
    return None, None


def tab_navigate_to_element(app_element, target_description: str,
                            wait_timeout: float = 0.0, max_rounds: int = 30):
    """
    用 Tab 轮动焦点，直到当前焦点元素的 AXDescription 匹配目标。
    """
    start_time = time.time()
    tab_count = 0

    while True:
        post_tab()
        tab_count += 1

        focused = focused_element(app_element)
        if focused is not None:
            desc = ax_str(focused, kAXDescriptionAttribute)
            if desc == target_description:
                info = element_info(focused, description=desc)
                info.update({
                    "method": "tab_navigate",
                    "tab_count": tab_count,
                    "elapsed": round(time.time() - start_time, 2),
                })
                return focused, info

        if wait_timeout <= 0 and tab_count >= max_rounds:
            return None, None
        if wait_timeout > 0 and (time.time() - start_time) >= wait_timeout:
            return None, None


def search_element(target_description: str, wait_timeout: float = 0.0,
                   step: int = 1) -> dict:
    """
    在 Notion AI 窗口中搜索指定 AXDescription 的元素。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "description": target_description, "error": error}

    raise_window(window)

    x0, y0, ww, wh = bounds_tuple(bounds)
    print(f"AI 窗口: ({int(x0)},{int(y0)}) {int(ww)}x{int(wh)}")

    print(f"网格扫描寻找 {target_description!r}...")
    element, info = grid_scan_element(app_element, bounds, target_description, step=step)
    if element is not None:
        print(f"  网格命中! role={info['role']}")
        return {
            "success": True,
            "element": element,
            "description": target_description,
            "method": "grid_scan",
            "info": info,
        }

    if wait_timeout > 0:
        print(f"  网格未找到，Tab 导航等待 {wait_timeout}s...")
    else:
        print("  网格未找到，Tab 导航...")

    element, info = tab_navigate_to_element(
        app_element, target_description, wait_timeout=wait_timeout
    )
    if element is None:
        msg = f"等待 {wait_timeout}s 后仍未找到" if wait_timeout > 0 else "两种方式均未找到"
        return {"success": False, "description": target_description, "error": msg}

    print(f"  Tab 命中! (第 {info['tab_count']} 次, 耗时 {info['elapsed']}s)")
    return {
        "success": True,
        "element": element,
        "description": target_description,
        "method": "tab_navigate",
        "info": info,
    }


def scan_region(bounds: dict, x_range=(0, 100), y_range=(0, 100), step: int = 2):
    """
    在窗口百分比区域内扫描可见 AX 元素。
    """
    app_element, app, window, current_bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "elements": [], "error": error}

    x0, y0, ww, wh = bounds_tuple(bounds or current_bounds)
    seen = set()
    elements = []

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
                info["description"],
                info["title"],
                info["position"],
                info["size"],
            )
            if key in seen:
                continue
            seen.add(key)

            info["value"] = info["value"][:80]
            info["label"] = info["description"] or info["title"]
            elements.append(info)

    elements.sort(key=lambda e: (
        e["position"][1] if e.get("position") else 0,
        e["position"][0] if e.get("position") else 0,
        e["label"] or "",
    ))
    return {"success": True, "elements": elements}


def list_all_elements(x_range=(0, 100), y_range=(0, 100), step: int = 2,
                      include_empty: bool = False) -> dict:
    """
    用网格扫描列出 AI 窗口中所有唯一 AXDescription/AXTitle 的可见元素。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "elements": [], "error": error}

    result = scan_region(bounds, x_range=x_range, y_range=y_range, step=step)
    if not result["success"]:
        return result

    seen_labels = set()
    elements = []
    for info in result["elements"]:
        label = info["label"]
        if not label and not include_empty:
            continue
        if label:
            key = ("label", label)
        else:
            key = ("empty", info["role"], info["position"], info["size"])
            info["label"] = "<empty>"
        if key in seen_labels:
            continue
        seen_labels.add(key)
        elements.append(info)

    elements.sort(key=lambda e: e["label"])
    return {"success": True, "elements": elements}


def parse_region(value: str):
    parts = value.split(",")
    if len(parts) != 4:
        raise ValueError("region 必须是 x1,y1,x2,y2")
    x1, y1, x2, y2 = [int(part.strip()) for part in parts]
    if not (0 <= x1 <= x2 <= 100 and 0 <= y1 <= y2 <= 100):
        raise ValueError("region 百分比必须满足 0 <= x1 <= x2 <= 100, 0 <= y1 <= y2 <= 100")
    return (x1, x2), (y1, y2)


def print_elements(result: dict):
    if not result["success"]:
        print(f"错误: {result['error']}")
        sys.exit(1)

    print(f"找到 {len(result['elements'])} 个唯一元素:\n")
    for i, el in enumerate(result["elements"], 1):
        pos_str = f"({int(el['position'][0])},{int(el['position'][1])})" if el["position"] else "?"
        size_str = f"{int(el['size'][0])}x{int(el['size'][1])}" if el["size"] else "?"
        print(f"  {i}. {el['label']}")
        print(f"     role={el['role']}  pos={pos_str}  size={size_str}  "
              f"actions={el['actions']}")
        if el["description"] and el["description"] != el["label"]:
            print(f"     description={el['description']}")
        if el["title"] and el["title"] != el["label"]:
            print(f"     title={el['title']}")
        if el["value"]:
            print(f"     value={el['value']}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python search_element.py <description> [选项]")
        print('  ./venv/bin/python search_element.py "提交 AI 消息"')
        print('  ./venv/bin/python search_element.py "拷贝回复" --timeout 30')
        print('  ./venv/bin/python search_element.py --list')
        print('  ./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty')
        print()
        print("选项:")
        print("  --timeout / -t SEC  等待超时（秒），默认 0（即刻返回）")
        print("  --step N            网格扫描步长百分比（默认 1）")
        print("  --list              列出窗口内所有可见元素（调试用）")
        print("  --region X1,Y1,X2,Y2  只扫描窗口百分比区域，配合 --list 使用")
        print("  --include-empty     列出没有 AXDescription/AXTitle 的元素")
        sys.exit(0)

    if sys.argv[1] == "--list":
        print("===== 列出 AI 窗口所有元素 =====\n")
        x_range = (0, 100)
        y_range = (0, 100)
        step = 2
        include_empty = False
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--region" and i + 1 < len(args):
                try:
                    x_range, y_range = parse_region(args[i + 1])
                except ValueError as exc:
                    print(f"错误: {exc}")
                    sys.exit(1)
                i += 2
            elif args[i] == "--step" and i + 1 < len(args):
                step = int(args[i + 1])
                i += 2
            elif args[i] == "--include-empty":
                include_empty = True
                i += 1
            else:
                i += 1

        print(f"扫描区域: x={x_range[0]}%-{x_range[1]}%, y={y_range[0]}%-{y_range[1]}%, step={step}%")
        result = list_all_elements(
            x_range=x_range,
            y_range=y_range,
            step=step,
            include_empty=include_empty,
        )
        print_elements(result)
        sys.exit(0)

    target = sys.argv[1]
    wait_timeout = 0.0
    step = 1

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] in ("--timeout", "-t") and i + 1 < len(args):
            wait_timeout = float(args[i + 1])
            i += 2
        elif args[i] == "--step" and i + 1 < len(args):
            step = int(args[i + 1])
            i += 2
        else:
            i += 1

    print(f"===== 搜索元素: {target!r} =====\n")
    result = search_element(target, wait_timeout=wait_timeout, step=step)

    if not result["success"]:
        print(f"\n搜索失败: {result['error']}")
        sys.exit(1)

    info = result["info"]
    print("\n搜索成功!")
    print(f"  方式: {result['method']}")
    print(f"  角色: {info.get('role', '?')}")
    if info.get("position"):
        print(f"  位置: ({int(info['position'][0])}, {int(info['position'][1])})")
    if info.get("size"):
        print(f"  尺寸: {int(info['size'][0])}x{int(info['size'][1])}")
    if "actions" in info:
        print(f"  动作: {info['actions']}")
    if "tab_count" in info:
        print(f"  Tab 次数: {info['tab_count']}")
        print(f"  耗时: {info['elapsed']}s")


if __name__ == "__main__":
    main()
