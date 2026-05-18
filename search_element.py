#!/usr/bin/env python3
"""
在 Notion AI 窗口中搜索和定位 UI 元素。

本脚本有两类入口：
  1. 指定目标搜索：传入一个文字，寻找 AXDescription、AXTitle 或 AXValue 等于该文字的元素。
  2. 列表扫描：使用 --list 列出当前窗口或指定区域内扫描到的唯一元素。

指定目标搜索的策略：
  1. 先做网格扫描：在窗口可见区域内按坐标命中测试，读取命中的 AX 元素。
  2. 同时匹配 AXDescription、AXTitle 和 AXValue；这能覆盖菜单项和正文文本。
  3. 全窗口搜索失败后，再用 Tab 导航轮动焦点，继续匹配 AXDescription / AXTitle / AXValue。
  4. 如果传入 --region，只在该局部区域内重复网格扫描，不回退到 Tab 导航。

列表扫描的策略：
  1. 默认只列出有 AXDescription 或 AXTitle 的元素。
  2. 加 --include-empty 后，也列出无 label 元素，显示为 <empty>。
  3. 加 --region 后，只扫描窗口百分比区域，适合找底部按钮或菜单附近元素。

用法：
    ./venv/bin/python search_element.py "提交 AI 消息"
    ./venv/bin/python search_element.py "添加图片、PDF 或 CSV"
    ./venv/bin/python search_element.py "拷贝回复" --region 0,55,60,90 --timeout 5
    ./venv/bin/python search_element.py "拷贝回复" --timeout 30
    ./venv/bin/python search_element.py --list
    ./venv/bin/python search_element.py --list --include-empty
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
    kAXValueAttribute,
    post_tab,
    raise_window,
)


def element_matches_label(element, target_label: str) -> tuple[bool, str | None]:
    """
    判断一个 AX 元素是否匹配指定文字。

    Notion/Electron 的不同控件暴露 label 的字段不一致：
    - 普通按钮通常在 AXDescription 中有文字，例如“拷贝回复”。
    - 菜单项可能只有 AXTitle，例如“添加图片、PDF 或 CSV”。
    - 正文或问候语常常没有 label，但会暴露在 AXValue，例如“在下乐意为你效劳。”。

    返回：
      (是否匹配, 命中的属性名)

    命中的属性名会打印到命令行，方便确认该控件主要依赖哪个 AX 字段。
    """
    if ax_str(element, kAXDescriptionAttribute) == target_label:
        return True, "AXDescription"
    if ax_str(element, kAXTitleAttribute) == target_label:
        return True, "AXTitle"
    if ax_str(element, kAXValueAttribute) == target_label:
        return True, "AXValue"
    return False, None


def grid_scan_element(app_element, bounds: dict, target_description: str,
                      step: int = 1, x_range=(0, 100), y_range=(0, 100)):
    """
    在窗口百分比区域内网格扫描目标元素。

    参数说明：
      bounds: AI 窗口的屏幕坐标和尺寸。
      target_description: 要匹配的文字，会同时匹配 AXDescription / AXTitle / AXValue。
      step: 百分比步长；step=1 最密，较稳但稍慢。
      x_range/y_range: 窗口百分比区域，例如 x=(0, 60), y=(55, 90)。

    重要细节：
      返回的是扫描时命中的 AX 元素对象本身。对于无 label 的图标按钮，
      后续如果要点击，应保存并直接 press 这个对象，避免重新按中心点命中到正文。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    for yr in range(y_range[0], y_range[1] + 1, step):
        for xr in range(x_range[0], x_range[1] + 1, step):
            elem = element_at_position(
                app_element,
                float(x0 + ww * xr / 100.0),
                float(y0 + wh * yr / 100.0),
            )
            if elem is None:
                continue
            matched, matched_attribute = element_matches_label(elem, target_description)
            if matched:
                info = element_info(elem)
                info["method"] = "grid_scan"
                info["matched_attribute"] = matched_attribute
                info["scan_region"] = (x_range[0], y_range[0], x_range[1], y_range[1])
                return elem, info
    return None, None


def tab_navigate_to_element(app_element, target_description: str,
                            wait_timeout: float = 0.0, max_rounds: int = 30):
    """
    用 Tab 轮动焦点，直到当前焦点元素的 AXDescription、AXTitle 或 AXValue 匹配目标。

    这个方法只用于全窗口目标搜索的回退路径。局部搜索不会使用它，
    因为 Tab 焦点链无法限制在某个 --region 内。
    """
    start_time = time.time()
    tab_count = 0

    while True:
        post_tab()
        tab_count += 1

        focused = focused_element(app_element)
        if focused is not None:
            matched, matched_attribute = element_matches_label(focused, target_description)
            if matched:
                info = element_info(focused)
                info.update({
                    "method": "tab_navigate",
                    "matched_attribute": matched_attribute,
                    "tab_count": tab_count,
                    "elapsed": round(time.time() - start_time, 2),
                })
                return focused, info

        if wait_timeout <= 0 and tab_count >= max_rounds:
            return None, None
        if wait_timeout > 0 and (time.time() - start_time) >= wait_timeout:
            return None, None


def search_element(target_description: str, wait_timeout: float = 0.0,
                   step: int = 1, x_range=(0, 100), y_range=(0, 100)) -> dict:
    """
    在 Notion AI 窗口中搜索指定文字对应的元素。

    匹配字段：
      - AXDescription
      - AXTitle
      - AXValue

    全窗口搜索：
      先网格扫描；如果找不到，再通过 Tab 导航查找焦点元素。

    局部搜索：
      如果传入 x_range/y_range，只在该区域内做网格扫描；不会回退到 Tab 导航。
      如果同时传入 wait_timeout，会在超时时间内重复扫描该局部区域。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {"success": False, "description": target_description, "error": error}

    raise_window(window)

    x0, y0, ww, wh = bounds_tuple(bounds)
    print(f"AI 窗口: ({int(x0)},{int(y0)}) {int(ww)}x{int(wh)}")

    has_region = x_range != (0, 100) or y_range != (0, 100)
    if has_region:
        print(
            f"局部网格扫描寻找 {target_description!r}: "
            f"x={x_range[0]}%-{x_range[1]}%, y={y_range[0]}%-{y_range[1]}%, step={step}%"
        )
    else:
        print(f"网格扫描寻找 {target_description!r}...")

    deadline = time.time() + wait_timeout if wait_timeout > 0 else None
    while True:
        element, info = grid_scan_element(
            app_element,
            bounds,
            target_description,
            step=step,
            x_range=x_range,
            y_range=y_range,
        )
        if element is not None:
            print(f"  网格命中! role={info['role']}")
            return {
                "success": True,
                "element": element,
                "description": target_description,
                "method": "region_grid_scan" if has_region else "grid_scan",
                "info": info,
            }

        if not has_region or deadline is None or time.time() >= deadline:
            break
        time.sleep(0.2)

    if has_region:
        if wait_timeout > 0:
            msg = f"局部区域等待 {wait_timeout}s 后仍未找到"
        else:
            msg = "局部区域未找到"
        return {"success": False, "description": target_description, "error": msg}

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
    在窗口百分比区域内扫描可见 AX 元素，并按位置去重。

    这是 --list 的底层扫描函数。它不负责过滤空 label；
    是否显示无 label 元素由 list_all_elements(..., include_empty=...) 决定。
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
    列出 AI 窗口中扫描到的唯一可见元素。

    默认行为：
      只列出有 AXDescription 或 AXTitle 的元素。

    include_empty=True：
      同时列出没有 AXDescription / AXTitle 的元素，并显示为 <empty>。
      这对寻找“回到底部”这类无 label 图标按钮很有用。
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
    """
    解析 --region 参数。

    输入格式是窗口百分比坐标：X1,Y1,X2,Y2。
    例如 0,55,60,90 表示：
      x 从窗口左侧 0% 到 60%
      y 从窗口顶部 55% 到 90%
    """
    parts = value.split(",")
    if len(parts) != 4:
        raise ValueError("region 必须是 x1,y1,x2,y2")
    x1, y1, x2, y2 = [int(part.strip()) for part in parts]
    if not (0 <= x1 <= x2 <= 100 and 0 <= y1 <= y2 <= 100):
        raise ValueError("region 百分比必须满足 0 <= x1 <= x2 <= 100, 0 <= y1 <= y2 <= 100")
    return (x1, x2), (y1, y2)


def print_elements(result: dict):
    """
    打印 --list 的扫描结果。

    每个元素会显示：
      - label：AXDescription 或 AXTitle；无 label 时显示 <empty>
      - role：AXButton / AXMenuItem / AXTextArea 等
      - roleDesc：AXRoleDescription，例如“HTML 内容”
      - pos/size：屏幕坐标和尺寸
      - actions：AXPress / AXShowMenu 等可执行动作
    """
    if not result["success"]:
        print(f"错误: {result['error']}")
        sys.exit(1)

    print(f"找到 {len(result['elements'])} 个唯一元素:\n")
    for i, el in enumerate(result["elements"], 1):
        pos_str = f"({int(el['position'][0])},{int(el['position'][1])})" if el["position"] else "?"
        size_str = f"{int(el['size'][0])}x{int(el['size'][1])}" if el["size"] else "?"
        print(f"  {i}. {el['label']}")
        print(f"     role={el['role']}  roleDesc={el['role_description']}  pos={pos_str}  size={size_str}  "
              f"actions={el['actions']}")
        if el["description"] and el["description"] != el["label"]:
            print(f"     description={el['description']}")
        if el["title"] and el["title"] != el["label"]:
            print(f"     title={el['title']}")
        if el["value"]:
            print(f"     value={el['value']}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: ./venv/bin/python search_element.py <目标文字> [选项]")
        print("      ./venv/bin/python search_element.py --list [选项]")
        print()
        print("目标搜索示例（同时匹配 AXDescription、AXTitle 和 AXValue）:")
        print('  ./venv/bin/python search_element.py "提交 AI 消息"')
        print('  ./venv/bin/python search_element.py "添加图片、PDF 或 CSV"')
        print('  ./venv/bin/python search_element.py "在下乐意为你效劳。"')
        print('  ./venv/bin/python search_element.py "拷贝回复" --region 0,55,60,90 --timeout 5')
        print('  ./venv/bin/python search_element.py "拷贝回复" --timeout 30')
        print()
        print("列表扫描示例:")
        print('  ./venv/bin/python search_element.py --list')
        print('  ./venv/bin/python search_element.py --list --include-empty')
        print('  ./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty')
        print()
        print("选项:")
        print("  --timeout / -t SEC    等待超时（秒）。全局搜索用于 Tab 回退；局部搜索用于重复扫描该区域")
        print("  --step N              网格扫描步长百分比。数字越小越密，越慢也越稳")
        print("  --list                列出窗口内可见元素，而不是搜索单个目标")
        print("  --region X1,Y1,X2,Y2  只扫描窗口百分比区域，例如 0,55,60,90")
        print("  --include-empty       仅配合 --list 使用：列出没有 AXDescription/AXTitle 的元素")
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
    x_range = (0, 100)
    y_range = (0, 100)

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] in ("--timeout", "-t") and i + 1 < len(args):
            wait_timeout = float(args[i + 1])
            i += 2
        elif args[i] == "--step" and i + 1 < len(args):
            step = int(args[i + 1])
            i += 2
        elif args[i] == "--region" and i + 1 < len(args):
            try:
                x_range, y_range = parse_region(args[i + 1])
            except ValueError as exc:
                print(f"错误: {exc}")
                sys.exit(1)
            i += 2
        else:
            i += 1

    print(f"===== 搜索元素: {target!r} =====\n")
    result = search_element(
        target,
        wait_timeout=wait_timeout,
        step=step,
        x_range=x_range,
        y_range=y_range,
    )

    if not result["success"]:
        print(f"\n搜索失败: {result['error']}")
        sys.exit(1)

    info = result["info"]
    print("\n搜索成功!")
    print(f"  方式: {result['method']}")
    if info.get("scan_region"):
        x1, y1, x2, y2 = info["scan_region"]
        print(f"  扫描区域: x={x1}%-{x2}%, y={y1}%-{y2}%")
    if info.get("matched_attribute"):
        print(f"  匹配属性: {info['matched_attribute']}")
    print(f"  角色: {info.get('role', '?')}")
    if info.get("role_description"):
        print(f"  角色描述: {info['role_description']}")
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
