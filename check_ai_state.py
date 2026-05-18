#!/usr/bin/env python3
"""
判断 Notion AI 窗口当前所处的状态。

当前状态模型：
  - is_new_conversation: 当前对话框区域是否处在新对话状态。
  - is_attach_to_bottom: 当前对话框区域是否贴住底部。
  - conversation_state: 对话框状态。
  - input_state:        输入框状态。
  - model:              当前模型名。

核心区域划分：
  - 对话框区域：AXTextArea 上方的内容区，用来判断 new_conversation、回复内容、回复操作按钮。
  - 输入框区域：AXTextArea 及其下方工具栏，用来判断输入框和值、提交/停止按钮等。

对话框滚动/生成状态：
  - new_conversation:             对话框区域只有一句初始问候文本，没有完成态按钮。
  - generating:        输入框区域出现 "停止 AI 消息"，说明 AI 正在生成。
  - complete:          AI 回复已完成。

底部贴合状态：
  - is_attach_to_bottom=True:  回复完成后，未出现回到底部按钮，且完成态操作按钮可见。
  - is_attach_to_bottom=False: 新对话、生成中、脱离底部或未知状态。

输入框状态：
  - generating: 输入框区域出现 "停止 AI 消息"，说明问题已经提交，AI 正在生成。
  - typing:     未生成，且 AXTextArea.value 非空或输入框区域出现草稿文本。
  - empty:      未生成，且没有草稿/提交信号。

模型检测：
  - 当前模型由输入框区域里的模型选择 AXPopUpButton 暴露。
  - 该按钮的 AXDescription 通常就是模型名，例如 `Opus 4.7` / `GPT-5.5`。

用法：
    ./venv/bin/python check_ai_state.py          # 每 0.5 秒扫描一次，只输出变化
    ./venv/bin/python check_ai_state.py --once   # 单次人类可读输出
    ./venv/bin/python check_ai_state.py --json   # 单次 JSON 输出
"""

from datetime import datetime
import json
import sys
import time

from notion_ax import (
    ax_str,
    bounds_tuple,
    element_at_position,
    element_info,
    get_ai_window_context,
    kAXDescriptionAttribute,
    kAXTitleAttribute,
)


STOP_GENERATING_BUTTON_DESC = "停止 AI 消息"
SUBMIT_BUTTON_DESC = "提交 AI 消息"
INPUT_BUTTON_DESCRIPTIONS = {
    STOP_GENERATING_BUTTON_DESC,
    SUBMIT_BUTTON_DESC,
}

NEW_CONVERSATION_GREETINGS = {
    "在下乐意为你效劳。",
}

COMPLETED_SIGNAL_LABELS = {
    "拷贝回复",
    "保存到私人页面",
    "提供正面反馈",
    "提供负面反馈",
}

CONVERSATION_STATE_LABELS = {
    "new_conversation": "新对话",
    "generating": "正在生成",
    "complete": "完成",
    "unknown": "未知",
}

INPUT_STATE_LABELS = {
    "empty": "空输入",
    "typing": "正在输入",
    "generating": "已提交生成中",
    "unknown": "未知",
}

SCAN_Y_RANGE = (85, 98)
SCAN_X_RANGE = (70, 98)
SCAN_STEP = 2
FULL_SCAN_STEP = 1


def element_label(info: dict) -> str:
    """
    返回一个元素最适合用于识别的文字。

    目标搜索里已经确认 Notion 元素的文字可能来自：
    - AXDescription: 常见于按钮
    - AXTitle: 常见于菜单项
    - AXValue: 常见于正文、问候语、用户消息
    """
    return info.get("description") or info.get("title") or info.get("value") or ""


def scan_visible_elements(app_element, bounds: dict, step: int = FULL_SCAN_STEP) -> list[dict]:
    """
    扫描当前 AI 窗口可见元素，并按稳定属性去重。

    这是状态判断的基础数据来源。它比只扫右下角按钮更完整，
    能同时看见对话框区域和输入框区域中的元素。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    seen = set()
    elements = []

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
            elements.append(info)

    elements.sort(key=lambda e: (
        e["position"][1] if e.get("position") else 0,
        e["position"][0] if e.get("position") else 0,
        element_label(e),
    ))
    return elements


def find_input_text_area(elements: list[dict]) -> dict | None:
    """
    找当前窗口里的输入框。

    Notion AI 浮窗目前只观察到一个主要 AXTextArea。若未来出现多个，
    取 y 坐标最大的那个，通常就是底部输入框。
    """
    text_areas = [
        info for info in elements
        if info["role"] == "AXTextArea" and info.get("position")
    ]
    if not text_areas:
        return None
    text_areas.sort(key=lambda e: (e["position"][1], e["position"][0]))
    return text_areas[-1]


def split_elements_by_input_area(elements: list[dict], text_area: dict) -> tuple[list[dict], list[dict]]:
    """
    按输入框 y 坐标把窗口拆成两个逻辑区域。

    - 对话框区域：元素 position.y < AXTextArea.y
    - 输入框区域：元素 position.y >= AXTextArea.y

    这个划分不依赖窗口固定坐标，窗口移动后仍然有效。
    """
    text_area_y = text_area["position"][1]
    conversation_elements = []
    input_elements = []

    for info in elements:
        pos = info.get("position")
        if pos is not None and pos[1] < text_area_y:
            conversation_elements.append(info)
        else:
            input_elements.append(info)

    return conversation_elements, input_elements


def conversation_static_texts(conversation_elements: list[dict]) -> list[dict]:
    """
    返回对话框区域里的正文类文本元素。

    new_conversation 页面目前只有一个对话框文本：`在下乐意为你效劳。`。
    用户问题和 AI 回复也会以 AXStaticText / roleDesc=文本 暴露，
    因此一旦有真实对话，这里的数量和内容会明显变化。
    """
    return [
        info for info in conversation_elements
        if info["role"] == "AXStaticText" and info.get("role_description") == "文本"
    ]


def completed_signal_elements(elements: list[dict]) -> list[dict]:
    """
    查找已经完成回复的操作按钮信号。

    这些按钮出现时，页面不应再被判为 new_conversation。
    """
    return [
        info for info in elements
        if element_label(info) in COMPLETED_SIGNAL_LABELS
    ]


def is_stop_generating_button(info: dict) -> bool:
    """
    判断是否是生成中的停止按钮。

    该按钮通常在输入框区域右下角，AXDescription 为 `停止 AI 消息`。
    """
    return element_label(info) == STOP_GENERATING_BUTTON_DESC


def element_contains(container: dict, child: dict) -> bool:
    """
    判断 child 的左上角是否落在 container 的 bounds 内。

    用于识别模型选择按钮内部的静态文本，例如 `Opus 4.7` / `GPT-5.5`。
    这类文本不属于输入草稿。
    """
    c_pos = container.get("position")
    c_size = container.get("size")
    child_pos = child.get("position")
    if not c_pos or not c_size or not child_pos:
        return False

    cx, cy = c_pos
    cw, ch = c_size
    px, py = child_pos
    return cx <= px <= cx + cw and cy <= py <= cy + ch


def current_mode_pattern(input_elements: list[dict], text_area: dict | None) -> str:
    """
    检测当前 AI 交互模式。

    Notion AI 有三种模式，但 UI 上只有"询问模式"和"计划模式"会显示标签。
    "默认模式"不显示标签。因此：
      - 找到 "询问模式" → 返回 "ask"
      - 找到 "计划模式" → 返回 "plan"
      - 都没找到     → 返回 "default"

    模式标签是输入框正下方很近位置的 AXStaticText / roleDesc=文本。
    利用 text_area 底部 y 坐标做空间约束，避免远处文字误匹配。
    """
    if text_area is None:
        return "default"

    ta_pos = text_area.get("position")
    ta_size = text_area.get("size")
    if not ta_pos or not ta_size:
        return "default"

    ta_bottom = ta_pos[1] + ta_size[1]

    for info in input_elements:
        if info["role"] != "AXStaticText" or info.get("role_description") != "文本":
            continue
        pos = info.get("position")
        if not pos:
            continue

        # 只收输入框正下方 0~20px 范围内的元素
        dy = pos[1] - ta_bottom
        if not (0 <= dy <= 20):
            continue

        value = info.get("value", "")
        if value == "询问模式":
            return "ask"
        if value == "计划模式":
            return "plan"
    return "default"


MODE_PATTERN_LABELS = {
    "default": "默认模式",
    "ask": "询问模式",
    "plan": "计划模式",
}


def input_static_texts(input_elements: list[dict], text_area: dict | None) -> list[dict]:
    """
    返回实际输入框 bounds 内的静态文本。

    输入框里的草稿文本有时不会出现在 AXTextArea.value，
    而会暴露为 AXStaticText / roleDesc=文本。

    只统计落在 AXTextArea 自身矩形内的静态文本。底部工具栏、模型名、
    模式标签、回复正文等即使位于 AXTextArea.y 以下，也不属于草稿。
    """
    if text_area is None:
        return []

    texts = []
    for info in input_elements:
        if info["role"] != "AXStaticText" or info.get("role_description") != "文本":
            continue
        value = info.get("value", "")
        if not value:
            continue
        if not element_contains(text_area, info):
            continue
        texts.append(info)
    return texts


def input_state(input_elements: list[dict], text_area: dict | None) -> tuple[str, list[dict]]:
    """
    判断输入框状态。

    判断优先级：
      1. generating: 输入框区域出现 `停止 AI 消息`
      2. typing: 未生成，且 AXTextArea.value 非空，或输入框区域存在草稿 AXStaticText
      3. empty: 未生成，且没有上述输入信号

    注意：`提交 AI 消息` 在 empty 和 typing 状态都可能出现，
    因此只作为 input_button_desc 原始按钮文字返回，不参与 typing 判断。
    """
    stop_buttons = [
        info for info in input_elements
        if is_stop_generating_button(info)
    ]
    if stop_buttons:
        return "generating", stop_buttons

    if text_area is not None and text_area.get("value"):
        return "typing", [text_area]

    draft_texts = input_static_texts(input_elements, text_area)
    if draft_texts:
        return "typing", draft_texts

    return "empty", []


def is_back_to_bottom_button(info: dict) -> bool:
    """
    判断是否是“回到底部”按钮。

    已观察到的回到底部按钮特征：
      - role=AXButton
      - description/title/value 都为空
      - size 约为 32x32
      - actions 包含 AXPress

    这个按钮出现时，说明对话框当前脱离底部；必须保存并直接 press
    扫描得到的按钮对象，不能用中心点重新命中。
    """
    if info["role"] != "AXButton":
        return False
    if element_label(info):
        return False

    size = info.get("size")
    if not size:
        return False
    width, height = size
    if not (28 <= width <= 36 and 28 <= height <= 36):
        return False

    return "AXPress" in info.get("actions", [])


def is_new_conversation(conversation_elements: list[dict], completed_signals: list[dict]) -> bool:
    """
    判断对话框是否是 new_conversation。

    当前约定：
      1. 没有完成回复信号按钮。
      2. 对话框区域里 AXStaticText / roleDesc=文本 的数量为 1。
      3. 这个唯一文本是初始问候语。

    输入框里的草稿文字和模型名不计入，因为它们位于输入框区域。
    """
    if completed_signals:
        return False

    texts = conversation_static_texts(conversation_elements)
    if len(texts) != 1:
        return False

    return texts[0].get("value") in NEW_CONVERSATION_GREETINGS


def conversation_state(conversation_elements: list[dict], input_elements: list[dict]) -> tuple[str, list[dict]]:
    """
    判断对话框状态。

    判断优先级：
      - generating: 输入框区域出现 `停止 AI 消息`
      - new_conversation: 对话框区域只有初始问候文本，且没有完成态操作按钮
      - detach_to_bottom: 对话框区域出现“回到底部”按钮
      - attach_to_bottom: 出现完成态操作按钮，且没有“回到底部”按钮

    `attach_to_bottom` 必须有完成态操作按钮作为证据，例如：
    `拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`。
    否则 new_conversation 页面会因为没有“回到底部”按钮而被误判为 attach。

    返回 (状态, 命中状态的元素列表)。
    """
    stop_buttons = [
        info for info in input_elements
        if is_stop_generating_button(info)
    ]
    if stop_buttons:
        return "generating", stop_buttons

    completed_signals = completed_signal_elements(conversation_elements)
    if is_new_conversation(conversation_elements, completed_signals):
        return "new_conversation", conversation_static_texts(conversation_elements)

    back_to_bottom_buttons = [
        info for info in conversation_elements
        if is_back_to_bottom_button(info)
    ]
    if back_to_bottom_buttons:
        return "detach_to_bottom", back_to_bottom_buttons

    if completed_signals:
        return "attach_to_bottom", completed_signals

    return "unknown", []


def scan_for_input_button_desc(app_element, bounds: dict) -> str | None:
    """
    在窗口右下角区域扫描输入按钮文字。

    这个按钮目前只作为原始 UI 信息返回：
      - `提交 AI 消息`
      - `停止 AI 消息`

    不要从 `提交 AI 消息` 推断 input_state=typing，因为空输入时也可能显示它。
    """
    x0, y0, ww, wh = bounds_tuple(bounds)
    for yr in range(SCAN_Y_RANGE[0], SCAN_Y_RANGE[1], SCAN_STEP):
        for xr in range(SCAN_X_RANGE[0], SCAN_X_RANGE[1], SCAN_STEP):
            elem = element_at_position(
                app_element,
                float(x0 + ww * xr / 100.0),
                float(y0 + wh * yr / 100.0),
            )
            if elem is None:
                continue

            desc = ax_str(elem, kAXDescriptionAttribute)
            if desc in INPUT_BUTTON_DESCRIPTIONS:
                return desc
    return None


def is_new_conversation_state(conv_state: str) -> bool:
    """
    判断当前对话框区域是否是“新对话”状态。

    这里的“新对话”不是 macOS 层面的窗口对象是否刚创建，也不只看 AXTitle。
    已观察到 Notion AI 在完成回复后，窗口标题仍可能是 `Notion - 命令搜索`，
    因此 AXTitle 不能单独作为可靠依据。

    当前约定：
      - 只看窗口/对话框区域。
      - conversation_state == new_conversation 即为新对话。

    输入框区域是另一块独立区域，不参与这个判断。因为新对话里用户已经开始输入
    但还没提交时，input_state 会是 typing，此时对话框区域仍然是新对话。
    """
    return conv_state == "new_conversation"


def public_conversation_state(raw_conv_state: str) -> str:
    """
    把内部对话框状态转换成对外输出的 conversation_state。

    对外只暴露三个业务阶段：
      - new_conversation
      - generating
      - complete

    内部仍会区分 attach_to_bottom / detach_to_bottom，用来计算
    is_attach_to_bottom，以及在自动复制回复时决定是否需要先回到底部。
    """
    if raw_conv_state in ("attach_to_bottom", "detach_to_bottom"):
        return "complete"
    if raw_conv_state in ("new_conversation", "generating"):
        return raw_conv_state
    return "unknown"


def is_attach_to_bottom_state(raw_conv_state: str) -> bool:
    """
    判断当前对话框区域是否贴住底部。

    这个布尔字段是对外输出用的简化判断：
      - True:  内部状态 == attach_to_bottom
      - False: 其他状态，包括 new_conversation / generating / detach_to_bottom / unknown
    """
    return raw_conv_state == "attach_to_bottom"


def check_ai_state() -> dict:
    """
    检测 Notion AI 窗口的当前状态。
    """
    app_element, app, window, bounds, error = get_ai_window_context()
    if error:
        return {
            "success": False,
            "is_new_conversation": False,
            "is_attach_to_bottom": False,
            "window_title": None,
            "conversation_state": "unknown",
            "conversation_state_label": CONVERSATION_STATE_LABELS["unknown"],
            "input_state": "unknown",
            "input_state_label": INPUT_STATE_LABELS["unknown"],
            "model": None,
            "error": error,
        }

    elements = scan_visible_elements(app_element, bounds)
    text_area = find_input_text_area(elements)
    completed_signals = completed_signal_elements(elements)

    input_button_desc = scan_for_input_button_desc(app_element, bounds)
    if text_area is not None:
        conversation_elements, input_elements = split_elements_by_input_area(elements, text_area)
        conversation_texts = conversation_static_texts(conversation_elements)
    else:
        conversation_elements = []
        input_elements = elements
        conversation_texts = []

    raw_conv_state, conv_state_elements = conversation_state(conversation_elements, input_elements)
    conv_state = public_conversation_state(raw_conv_state)
    inp_state, inp_state_elements = input_state(input_elements, text_area)
    window_title = ax_str(window, kAXTitleAttribute)
    is_new_conversation = is_new_conversation_state(conv_state)
    is_attach_to_bottom = is_attach_to_bottom_state(raw_conv_state)
    from model_selector import current_model

    model_info = current_model(input_elements, text_area)
    mode_pat = current_mode_pattern(input_elements, text_area)

    return {
        "success": True,
        "is_new_conversation": is_new_conversation,
        "is_attach_to_bottom": is_attach_to_bottom,
        "window_title": window_title,
        "conversation_state": conv_state,
        "conversation_state_label": CONVERSATION_STATE_LABELS[conv_state],
        "input_state": inp_state,
        "input_state_label": INPUT_STATE_LABELS[inp_state],
        "mode_pattern": mode_pat,
        "mode_pattern_label": MODE_PATTERN_LABELS.get(mode_pat, mode_pat),
        "model": model_info["name"],
        "model_info": model_info,
        "input_button_desc": input_button_desc,
        "input_state_elements": [
            {
                "role": info["role"],
                "role_description": info.get("role_description"),
                "label": element_label(info),
                "value": info.get("value"),
                "position": info.get("position"),
                "size": info.get("size"),
                "actions": info.get("actions"),
            }
            for info in inp_state_elements
        ],
        "conversation_state_elements": [
            {
                "role": info["role"],
                "role_description": info.get("role_description"),
                "label": element_label(info),
                "position": info.get("position"),
                "size": info.get("size"),
                "actions": info.get("actions"),
            }
            for info in conv_state_elements
        ],
        "regions": {
            "has_text_area": text_area is not None,
            "text_area": {
                "position": text_area["position"],
                "size": text_area["size"],
                "value": text_area["value"],
            } if text_area is not None else None,
            "conversation_element_count": len(conversation_elements),
            "input_element_count": len(input_elements),
            "conversation_static_text_count": len(conversation_texts),
            "conversation_static_text_values": [
                info["value"] for info in conversation_texts
            ],
            "completed_signal_count": len(completed_signals),
            "completed_signal_labels": [
                element_label(info) for info in completed_signals
            ],
            "input_static_text_values": [
                info["value"] for info in input_static_texts(input_elements, text_area)
            ],
        },
    }


def state_key(result: dict) -> tuple:
    """
    生成状态变化检测 key。

    默认观察模式只在这个 key 变化时输出，避免每 0.5 秒刷屏。
    """
    return (
        result.get("success"),
        result.get("is_new_conversation"),
        result.get("is_attach_to_bottom"),
        result.get("conversation_state"),
        result.get("input_state"),
        result.get("mode_pattern"),
        result.get("model"),
        result.get("input_button_desc"),
        tuple(result.get("regions", {}).get("completed_signal_labels") or []),
        result.get("error"),
    )


def format_state_line(result: dict) -> str:
    """格式化一行状态输出。"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if not result.get("success"):
        return f"{ts} 等待/失败: {result.get('error', '未知错误')}"

    regions = result.get("regions", {})
    return (
        f"{ts} "
        f"新对话={'是' if result.get('is_new_conversation') else '否'} | "
        f"贴住底部={'是' if result.get('is_attach_to_bottom') else '否'} | "
        f"输入={result['input_state_label']}({result['input_state']}) | "
        f"模式={result.get('mode_pattern_label')}({result.get('mode_pattern')}) | "
        f"模型={result.get('model') or '无'} | "
        f"输入按钮={result.get('input_button_desc') or '无'} | "
        f"对话文本数={regions.get('conversation_static_text_count')} | "
        f"完成信号={regions.get('completed_signal_count')}"
    )


def print_once(result: dict):
    """打印单次人类可读状态。"""
    if result["success"]:
        print(f"新对话: {'是' if result.get('is_new_conversation') else '否'}")
        print(f"贴住底部: {'是' if result.get('is_attach_to_bottom') else '否'}")
        print(f"窗口标题: {result.get('window_title')}")
        print(f"输入框状态: {result['input_state_label']} ({result['input_state']})")
        print(f"当前模式: {result.get('mode_pattern_label')} ({result.get('mode_pattern')})")
        print(f"当前模型: {result.get('model')}")
        print(f"输入按钮: {result.get('input_button_desc')}")
        regions = result.get("regions", {})
        print(f"对话框文本数量: {regions.get('conversation_static_text_count')}")
        if regions.get("conversation_static_text_values"):
            print("对话框文本:")
            for value in regions["conversation_static_text_values"]:
                print(f"  - {value}")
        print(f"完成回复信号数量: {regions.get('completed_signal_count')}")
    else:
        print(f"检测失败: {result['error']}")


def public_json_result(result: dict) -> dict:
    """
    返回命令行 --json 使用的公开结构。

    JSON 保留 conversation_state / conversation_state_label，表示：
      - new_conversation
      - generating
      - complete

    同时额外提供 is_attach_to_bottom，表示完成态是否贴住底部。
    """
    return result


def main():
    use_json = "--json" in sys.argv
    use_once = "--once" in sys.argv

    if "-h" in sys.argv or "--help" in sys.argv:
        print("用法: ./venv/bin/python check_ai_state.py [选项]")
        print()
        print("默认: 每 0.5 秒扫描一次，只输出变化")
        print("  --once    单次人类可读输出")
        print("  --json    单次 JSON 输出")
        sys.exit(0)

    result = check_ai_state()

    if use_json:
        print(json.dumps(public_json_result(result), ensure_ascii=False, indent=2))
        sys.exit(0 if result["success"] else 1)

    if use_once:
        print("===== Notion AI 状态检测 =====\n")
        print_once(result)
        sys.exit(0 if result["success"] else 1)

    print("===== Notion AI 状态监听：每 0.5 秒扫描，只输出变化 =====")
    print("按 Ctrl+C 结束。\n")
    last_key = None
    try:
        while True:
            key = state_key(result)
            if key != last_key:
                print(format_state_line(result), flush=True)
                last_key = key

            time.sleep(0.5)
            result = check_ai_state()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
