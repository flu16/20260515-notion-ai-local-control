#!/usr/bin/env python3
"""
向 Notion AI 提问，等待回复完成，然后复制最新回复。

当前流程：
  1. 用 input_box.py 中已经验证稳定的方法写入问题。
  2. 按输入区里的 `提交 AI 消息` 按钮提交。
  3. 等待状态先进入 generating，再等待它退出 generating。
  4. 如果 conversation_state=complete 但 is_attach_to_bottom=False，
     先按无 label 的 32x32 回到底部按钮。
  5. 等到 is_attach_to_bottom=True 后，只按当前底部可见的 `拷贝回复`。
  6. 读取系统剪贴板，作为最终回复文本。

重要原则：
  - 生成中即使短暂出现 `拷贝回复`，也不能复制。
  - 必须等 check_ai_state 确认非 generating 后，再判断 attach/detach。
  - 复制按钮选最靠下的可见按钮，尽量对应最新回复。

用法：
    ./venv/bin/python ask_and_copy_reply.py "讲一个故事"
    ./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
    讲一个故事
    NOTION_AI_AGENT_EOF
    ./venv/bin/python ask_and_copy_reply.py --from-clipboard
    ./venv/bin/python ask_and_copy_reply.py --attach-file ./report.pdf "总结这个文件"
    ./venv/bin/python ask_and_copy_reply.py "讲一个故事" --new_conversation
    ./venv/bin/python ask_and_copy_reply.py "讲一个故事" --timeout 300
    ./venv/bin/python ask_and_copy_reply.py "讲一个故事" --json
    ./venv/bin/python ask_and_copy_reply.py "处理这个任务" --assign_task --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from check_ai_state import (
    BOTTOM_COPY_Y_RANGE,
    COPY_REPLY_X_RANGE,
    STOP_GENERATING_BUTTON_DESC,
    check_ai_state,
    element_label,
    scan_fast_completion_signals,
    scan_for_back_to_bottom_button,
    scan_for_copy_reply_button,
)
from input_box import find_text_area, input_text, paste_files_at_current_insertion_point
from notion_ax import (
    bounds_tuple,
    element_at_position,
    element_info,
    get_ai_window_context,
    get_clipboard_text,
    kAXErrorSuccess,
    minimize_notion_main_windows,
    post_open_ai_shortcut,
    press,
    raise_window,
    set_clipboard_text,
)


SUBMIT_LABEL = "提交 AI 消息"
NEW_CONVERSATION_LABEL = "开始新对话"
COPY_REPLY_LABEL = "拷贝回复"
COPY_SUCCESS_TOAST = "回复已拷贝到剪贴板"
ATTACHMENT_REMOVE_PREFIX = "从上下文中移除"
ALLOW_UPLOAD_LABEL = "允许上传"


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


def find_labeled_button(label: str, x_range=(0, 100), y_range=(0, 100),
                        step: int = 1) -> tuple[object, dict] | None:
    """在指定可见区域内查找最靠下的可按 label 按钮。"""
    matches = [
        (elem, info)
        for elem, info in scan_visible_element_objects(
            step=step,
            x_range=x_range,
            y_range=y_range,
        )
        if element_label(info) == label and "AXPress" in info.get("actions", [])
    ]
    return bottom_most(matches)


def press_labeled_button(label: str, timeout: float = 5.0,
                         x_range=(0, 100), y_range=(0, 100),
                         step: int = 1, quiet: bool = False) -> dict:
    """
    等待并按下指定 label 的按钮。

    用全窗口可见元素扫描，不使用 Tab，避免焦点链跑到别的位置。
    """
    deadline = time.time() + timeout
    last_count = 0
    while time.time() < deadline:
        target = find_labeled_button(label, x_range=x_range, y_range=y_range, step=step)
        last_count = 1 if target is not None else 0
        if target is not None:
            elem, info = target
            err = press(elem)
            if err == kAXErrorSuccess:
                _print(f"  已按下: {label}", quiet)
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
        "error": f"等待 {timeout}s 后仍未找到可按的 {label!r}，最后匹配数={last_count}",
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


def find_attachment_remove_buttons(file_paths: list[str]) -> list[tuple[object, dict]]:
    """
    查找附件卡片上的“从上下文中移除...”按钮。

    Notion 会把文件名文本拆成多段，但移除按钮 description 会包含完整文件名，
    是确认附件已经进入上下文的稳定信号。
    """
    app_element, bounds, error = ensure_ai_window()
    if error:
        return []

    targets = {
        Path(path).name: Path(path)
        for path in file_paths
    }
    filenames = set(targets)
    matches = []
    anchors = []

    # Fast coarse pass: locate filename text. Notion splits "foo.txt" into
    # "foo" and ".txt"; the stem is the most useful anchor for the card.
    for elem, info in scan_visible_element_objects(step=2, x_range=(0, 100), y_range=(45, 100)):
        label = element_label(info)
        if (
            info.get("role") == "AXButton"
            and label.startswith(ATTACHMENT_REMOVE_PREFIX)
            and "AXPress" in info.get("actions", [])
            and any(filename in label for filename in filenames)
        ):
            matches.append((elem, info))
            continue

        if info.get("role") != "AXStaticText":
            continue
        position = info.get("position")
        if not label or not position:
            continue
        for filename, file_path in targets.items():
            if label in {filename, file_path.stem}:
                anchors.append((filename, position))

    if matches:
        return matches

    seen = set()
    for filename, (anchor_x, anchor_y) in anchors:
        # The remove button sits at the attachment card's top-right. In observed
        # layouts it is roughly 145-170px right and 18-22px above the stem text.
        for y in range(int(anchor_y) - 28, int(anchor_y) + 6):
            for x in range(int(anchor_x) + 110, int(anchor_x) + 240):
                elem = element_at_position(app_element, float(x), float(y))
                if elem is None:
                    continue
                info = element_info(elem)
                key = (
                    info.get("role"),
                    info.get("description"),
                    info.get("title"),
                    info.get("value"),
                    info.get("position"),
                    info.get("size"),
                )
                if key in seen:
                    continue
                seen.add(key)

                label = element_label(info)
                if (
                    info.get("role") == "AXButton"
                    and label.startswith(ATTACHMENT_REMOVE_PREFIX)
                    and "AXPress" in info.get("actions", [])
                    and filename in label
                ):
                    matches.append((elem, info))
                    break
            if matches and filename in element_label(matches[-1][1]):
                break
    return matches


def find_attachment_upload_spinners() -> list[dict]:
    """
    查找附件卡片上传中的转圈状态。

    上传中 spinner 在 AX 中通常是输入框上方的无 label AXGroup，roleDesc=状态，
    尺寸约 18-40px。它只能说明“仍在上传中”，不是成功信号。
    """
    app_element, bounds, error = ensure_ai_window()
    if error:
        return []

    text_area, text_area_info = find_text_area(app_element, bounds)
    text_area_y = (
        text_area_info.get("position", (None, None))[1]
        if text_area_info
        else None
    )

    spinners = []
    for _, info in scan_visible_element_objects(step=2, x_range=(0, 100), y_range=(55, 98)):
        position = info.get("position")
        size = info.get("size") or (0, 0)
        if (
            info.get("role") == "AXGroup"
            and info.get("role_description") == "状态"
            and not element_label(info)
            and position
            and (text_area_y is None or position[1] < text_area_y)
            and 18 <= size[0] <= 40
            and 18 <= size[1] <= 40
        ):
            spinners.append(info)
    return spinners


def wait_for_attachments_uploaded(file_paths: list[str], timeout: float = 15.0,
                                  quiet: bool = False) -> dict:
    """等待所有目标文件出现附件移除按钮。"""
    filenames = {Path(path).name for path in file_paths}
    deadline = time.time() + timeout
    last_seen = set()
    last_infos = []

    while time.time() < deadline:
        buttons = find_attachment_remove_buttons(file_paths)
        seen = set()
        infos = []
        for _, info in buttons:
            label = element_label(info)
            infos.append(info)
            for filename in filenames:
                if filename in label:
                    seen.add(filename)

        if seen != last_seen:
            _print(
                "  附件上传信号: "
                + (", ".join(sorted(seen)) if seen else "未发现"),
                quiet,
            )
            last_seen = seen
            last_infos = infos

        if filenames.issubset(seen):
            return {
                "success": True,
                "files": sorted(seen),
                "attachment_buttons": infos,
                "error": None,
            }

        time.sleep(0.3)

    return {
        "success": False,
        "files": sorted(last_seen),
        "attachment_buttons": last_infos,
        "error": "等待附件进入上下文超时",
    }


def press_allow_upload_once(quiet: bool = False) -> dict:
    """
    单次扫描并按下“允许上传”按钮。

    不做超时等待；用于附件等待循环中避免没有弹窗时白等。
    """
    saw_trust_prompt = False
    for elem, info in scan_visible_element_objects(step=2, x_range=(0, 100), y_range=(35, 90)):
        label = element_label(info)
        saw_trust_prompt = saw_trust_prompt or label == "你是否信任这些文件？"
        if label == ALLOW_UPLOAD_LABEL and "AXPress" in info.get("actions", []):
            err = press(elem)
            if err == kAXErrorSuccess:
                _print(f"  已按下: {ALLOW_UPLOAD_LABEL}", quiet)
                time.sleep(0.2)
                return {
                    "success": True,
                    "pressed": True,
                    "saw_trust_prompt": saw_trust_prompt,
                    "info": info,
                    "error": None,
                }
            return {
                "success": False,
                "pressed": False,
                "saw_trust_prompt": saw_trust_prompt,
                "info": info,
                "error": f"AXPressAction 失败 (error_code={err})",
            }

    return {
        "success": True,
        "pressed": False,
        "saw_trust_prompt": saw_trust_prompt,
        "info": None,
        "error": None,
    }


def wait_for_attachments_ready(file_paths: list[str], timeout: float = 120.0,
                               quiet: bool = False,
                               missing_spinner_grace: float = 5.0) -> dict:
    """
    等待附件可提交。

    快路径：一旦出现“从上下文中移除{文件名}”按钮就立即返回。
    如果看到上传 spinner，说明仍在上传，继续等待。
    如果 spinner 消失但成功按钮还没出现，给一个短暂宽限期，之后判定上传失败。
    如果期间出现“不受信任文件”确认，按“允许上传”后继续等附件信号。
    """
    filenames = {Path(path).name for path in file_paths}
    deadline = time.time() + timeout
    last_seen = set()
    last_spinner_count = None
    saw_spinner = False
    spinner_missing_since = None
    pressed_allow_upload = False

    while time.time() < deadline:
        buttons = find_attachment_remove_buttons(file_paths)
        seen = set()
        infos = []
        for _, info in buttons:
            label = element_label(info)
            infos.append(info)
            for filename in filenames:
                if filename in label:
                    seen.add(filename)

        if seen != last_seen:
            _print(
                "  附件上传信号: "
                + (", ".join(sorted(seen)) if seen else "未发现"),
                quiet,
            )
            last_seen = seen

        if filenames.issubset(seen):
            return {
                "success": True,
                "files": sorted(seen),
                "attachment_buttons": infos,
                "pressed_allow_upload": pressed_allow_upload,
                "error": None,
            }

        spinners = find_attachment_upload_spinners()
        spinner_count = len(spinners)
        if spinner_count != last_spinner_count:
            _print(
                "  附件上传中状态: "
                + (f"{spinner_count} 个 spinner" if spinner_count else "未发现"),
                quiet,
            )
            last_spinner_count = spinner_count

        if spinner_count:
            saw_spinner = True
            spinner_missing_since = None

        allowed = press_allow_upload_once(quiet=quiet)
        if not allowed["success"]:
            return {
                "success": False,
                "files": sorted(last_seen),
                "attachment_buttons": infos,
                "pressed_allow_upload": pressed_allow_upload,
                "error": allowed["error"],
            }
        pressed_allow_upload = pressed_allow_upload or allowed["pressed"]

        if not spinner_count:
            if saw_spinner:
                if spinner_missing_since is None:
                    spinner_missing_since = time.time()
                elif time.time() - spinner_missing_since >= missing_spinner_grace:
                    return {
                        "success": False,
                        "files": sorted(last_seen),
                        "attachment_buttons": infos,
                        "pressed_allow_upload": pressed_allow_upload,
                        "error": "附件上传状态已消失，但未出现进入上下文的成功按钮",
                    }
            elif time.time() + missing_spinner_grace < deadline:
                # 小文件可能一闪而过，因此没有看到 spinner 时仍给成功按钮一些出现时间。
                pass

        time.sleep(0.15)

    return {
        "success": False,
        "files": sorted(last_seen),
        "attachment_buttons": [],
        "pressed_allow_upload": pressed_allow_upload,
        "error": "等待附件进入上下文超时",
    }


def allow_untrusted_upload_if_present(timeout: float = 2.0,
                                      quiet: bool = False) -> dict:
    """
    如果 Notion 弹出“你是否信任这些文件？”确认框，按下“允许上传”。

    没有弹窗时返回 skipped=True，不视为失败。
    """
    deadline = time.time() + timeout
    saw_trust_prompt = False

    while time.time() < deadline:
        elements = scan_visible_element_objects(step=1, x_range=(0, 100), y_range=(0, 100))
        saw_trust_prompt = saw_trust_prompt or any(
            element_label(info) == "你是否信任这些文件？"
            for _, info in elements
        )

        for elem, info in elements:
            if element_label(info) == ALLOW_UPLOAD_LABEL and "AXPress" in info.get("actions", []):
                err = press(elem)
                if err == kAXErrorSuccess:
                    _print(f"  已按下: {ALLOW_UPLOAD_LABEL}", quiet)
                    time.sleep(0.5)
                    return {
                        "success": True,
                        "pressed": True,
                        "skipped": False,
                        "info": info,
                        "error": None,
                    }
                return {
                    "success": False,
                    "pressed": False,
                    "skipped": False,
                    "info": info,
                    "error": f"AXPressAction 失败 (error_code={err})",
                }

        time.sleep(0.2)

    if saw_trust_prompt:
        return {
            "success": False,
            "pressed": False,
            "skipped": False,
            "info": None,
            "error": f"看到信任文件提示，但未找到可按的 {ALLOW_UPLOAD_LABEL!r}",
        }

    return {
        "success": True,
        "pressed": False,
        "skipped": True,
        "info": None,
        "error": None,
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


def detached_complete_state(back_button_info: dict) -> dict:
    """用回到底部按钮证据构造轻量完成态，避免长回复完整 AX 扫描。"""
    return {
        "success": True,
        "is_new_conversation": False,
        "is_attach_to_bottom": False,
        "window_title": None,
        "conversation_state": "complete",
        "conversation_state_label": "完成",
        "input_state": "empty",
        "input_state_label": "空输入",
        "model": None,
        "input_button_desc": None,
        "input_state_elements": [],
        "conversation_state_elements": [back_button_info],
        "regions": {
            "completed_signal_count": 0,
            "completed_signal_labels": [],
        },
    }


def attached_state_from_copy_button(state: dict, copy_button_info: dict) -> dict:
    """用局部底部按钮证据构造一个轻量贴底状态，避免完整 AX 扫描。"""
    attached = dict(state)
    attached["conversation_state"] = "complete"
    attached["conversation_state_label"] = "完成"
    attached["is_attach_to_bottom"] = True
    attached["conversation_state_elements"] = [copy_button_info]
    regions = dict(attached.get("regions") or {})
    regions["completed_signal_count"] = max(1, regions.get("completed_signal_count", 0))
    regions["completed_signal_labels"] = [COPY_REPLY_LABEL]
    attached["regions"] = regions
    return attached


def attached_complete_state(copy_button_info: dict) -> dict:
    """用 `拷贝回复` 按钮证据构造轻量完成且贴底状态。"""
    return {
        "success": True,
        "is_new_conversation": False,
        "is_attach_to_bottom": True,
        "window_title": None,
        "conversation_state": "complete",
        "conversation_state_label": "完成",
        "input_state": "empty",
        "input_state_label": "空输入",
        "model": None,
        "input_button_desc": None,
        "input_state_elements": [],
        "conversation_state_elements": [copy_button_info],
        "regions": {
            "completed_signal_count": 1,
            "completed_signal_labels": [COPY_REPLY_LABEL],
        },
    }


def wait_for_detached_completion(timeout: float, quiet: bool = False) -> dict:
    """
    等待生成结束。

    长回复常见完成态是出现回到底部按钮；短回复常见完成态是直接贴底并出现
    `拷贝回复`。两条路径必须一起观察，不能只等回到底部按钮。
    """
    deadline = time.time() + timeout
    last_result = None
    last_state_key = None
    last_signal_key = None
    next_full_check_at = time.time() + 1.0

    while time.time() < deadline:
        app_element, bounds, error = ensure_ai_window()
        if error:
            return {"success": False, "state": last_result, "error": error}

        signals = scan_fast_completion_signals(app_element, bounds)
        signal_key = (
            signals.get("input_button_desc"),
            signals.get("has_back_to_bottom"),
            signals.get("has_copy_reply"),
        )
        if signal_key != last_signal_key:
            _print(
                "  快速信号: "
                f"输入按钮={signals.get('input_button_desc') or '无'} | "
                f"回到底部={'是' if signals.get('has_back_to_bottom') else '否'} | "
                f"拷贝回复={'是' if signals.get('has_copy_reply') else '否'}",
                quiet,
            )
            last_signal_key = signal_key

        back_to_bottom = signals.get("back_to_bottom_button")
        if back_to_bottom is not None:
            _, info = back_to_bottom
            _print("  快速检测到完成态：出现回到底部按钮", quiet)
            return {"success": True, "state": detached_complete_state(info), "error": None}

        copy_reply = signals.get("copy_reply_button")
        if copy_reply is not None and signals.get("input_button_desc") != STOP_GENERATING_BUTTON_DESC:
            _, info = copy_reply
            _print("  快速检测到完成态：出现拷贝回复按钮", quiet)
            return {"success": True, "state": attached_complete_state(info), "error": None}

        now = time.time()
        if now < next_full_check_at:
            time.sleep(0.2)
            continue
        next_full_check_at = now + 2.0

        result = check_ai_state()
        last_result = result
        key = (
            result.get("success"),
            result.get("conversation_state"),
            result.get("input_state"),
            result.get("input_button_desc"),
            result.get("error"),
        )
        if key != last_state_key:
            if result.get("success"):
                _print(
                    "  状态: "
                    f"对话={result.get('conversation_state')} | "
                    f"输入={result.get('input_state')} | "
                    f"按钮={result.get('input_button_desc') or '无'}",
                    quiet,
                )
            else:
                _print(f"  状态检测失败: {result.get('error')}", quiet)
            last_state_key = key

        if (
            result.get("success")
            and result.get("conversation_state") == "complete"
            and result.get("input_state") != "generating"
        ):
            return {"success": True, "state": result, "error": None}

        time.sleep(0.2)

    return {
        "success": False,
        "state": last_result,
        "error": f"等待生成完成并进入稳定对话框状态超时 ({timeout}s)",
    }


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


def wait_for_state(predicate, timeout: float, interval: float = 0.5,
                   quiet: bool = False, label: str = "状态") -> dict:
    """反复调用 check_ai_state，直到 predicate(result) 为真。"""
    deadline = time.time() + timeout
    last_result = None
    last_key = None

    while time.time() < deadline:
        result = check_ai_state()
        last_result = result
        key = (
            result.get("success"),
            result.get("conversation_state"),
            result.get("input_state"),
            result.get("input_button_desc"),
            result.get("error"),
        )
        if key != last_key:
            if result.get("success"):
                _print(
                    "  状态: "
                    f"对话={result.get('conversation_state')} | "
                    f"输入={result.get('input_state')} | "
                    f"按钮={result.get('input_button_desc') or '无'}",
                    quiet,
                )
            else:
                _print(f"  状态检测失败: {result.get('error')}", quiet)
            last_key = key

        if predicate(result):
            return {"success": True, "state": result, "error": None}
        time.sleep(interval)

    return {
        "success": False,
        "state": last_result,
        "error": f"等待 {label} 超时 ({timeout}s)",
    }


def wait_until_generation_finished(timeout: float, quiet: bool = False) -> dict:
    """
    等待回复生成完成。

    先尽量确认进入过 generating，再等待退出 generating。这样可以避免提交后还没来得及
    切换按钮时，被误认为已经完成。
    """
    saw_generating_or_complete = wait_for_state(
        lambda r: (
            r.get("success")
            and (
                r.get("conversation_state") == "generating"
                or (
                    r.get("conversation_state") == "complete"
                    and r.get("input_state") != "generating"
                )
            )
        ),
        timeout=min(10.0, timeout),
        interval=0.35,
        quiet=quiet,
        label="进入 generating 或快速完成",
    )
    if saw_generating_or_complete["success"]:
        state = saw_generating_or_complete.get("state") or {}
        if (
            state.get("conversation_state") == "complete"
            and state.get("input_state") != "generating"
        ):
            _print("  已快速完成，未等待 generating 窗口耗尽", quiet)
            return saw_generating_or_complete
    else:
        _print("  未观察到 generating，继续等待非生成完成态", quiet)

    return wait_for_detached_completion(timeout=timeout, quiet=quiet)


def wait_until_generation_started(timeout: float, quiet: bool = False) -> dict:
    """
    等待回复进入 generating。

    用于 --assign_task 发布任务模式：只要 Notion AI 开始生成，就代表任务已经交给
    远端 AI，不再等待完整回复。
    """
    return wait_for_state(
        lambda r: (
            r.get("success")
            and r.get("conversation_state") == "generating"
        ),
        timeout=timeout,
        interval=0.35,
        quiet=quiet,
        label="进入 generating",
    )


def wait_until_attached(timeout: float, quiet: bool = False,
                        initial_state: dict | None = None) -> dict:
    """
    等待对话框贴住底部。

    若当前 complete 但没有贴住底部，就按回到底部按钮；然后等待贴住底部。
    """
    deadline = time.time() + timeout
    last_state = None

    while time.time() < deadline:
        if initial_state is not None:
            result = initial_state
            initial_state = None
        else:
            result = check_ai_state()
        if not result.get("success"):
            last_state = result
            time.sleep(0.3)
            continue

        last_state = result
        if (
            result.get("conversation_state") == "complete"
            and result.get("is_attach_to_bottom")
        ):
            return {"success": True, "state": result, "error": None}

        if (
            result.get("conversation_state") == "complete"
            and not result.get("is_attach_to_bottom")
        ):
            pressed = press_back_to_bottom(timeout=2.0, quiet=quiet)
            if not pressed["success"]:
                return {"success": False, "state": result, "error": pressed["error"]}
            quick_attached = wait_for_bottom_copy_button(timeout=3.0)
            if quick_attached["success"]:
                return {
                    "success": True,
                    "state": attached_state_from_copy_button(result, quick_attached["info"]),
                    "error": None,
                }
            time.sleep(0.3)
            continue

        time.sleep(0.3)

    return {
        "success": False,
        "state": last_state,
        "error": f"等待 is_attach_to_bottom=True 超时 ({timeout}s)",
    }


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


def ask_and_copy_reply(question: str, timeout: float = 300.0,
                       new_conversation: bool = False,
                       assign_task: bool = False,
                       attach_files: list[str] | None = None,
                       quiet: bool = False) -> dict:
    """
    执行提问流程。

    默认完整执行：输入问题、提交、等待完成、贴底、复制回复。
    assign_task=True 时只等待 AI 进入 generating，然后立即返回。
    """
    started_at = time.time()
    title = "===== 发布任务 =====" if assign_task else "===== 提问并复制回复 ====="
    _print(title, quiet)

    app_element, bounds, error = ensure_ai_window()
    if error:
        return {"success": False, "text": "", "error": error}

    step_number = 1
    if new_conversation:
        _print(f"{step_number}. 开始新对话", quiet)
        started = start_new_conversation(
            timeout=10.0,
            quiet=quiet,
            app_element=app_element,
            bounds=bounds,
        )
        if not started["success"]:
            return {
                "success": False,
                "text": "",
                "step": "new_conversation",
                "error": started["error"],
            }
        app_element = started.get("app_element") or app_element
        bounds = started.get("bounds") or bounds
        step_number += 1

    _print(f"{step_number}. 写入问题", quiet)
    typed = input_text(
        question,
        replace_existing=True,
        app_element=app_element,
        bounds=bounds,
        quiet=quiet,
    )
    if not typed["success"]:
        return {
            "success": False,
            "text": "",
            "step": "input",
            "error": typed["error"],
        }
    step_number += 1

    if attach_files:
        time.sleep(0.2)
        _print(f"{step_number}. 粘贴文件", quiet)
        pasted = paste_files_at_current_insertion_point(
            attach_files,
            quiet=quiet,
        )
        if not pasted["success"]:
            return {
                "success": False,
                "text": "",
                "step": "attach_files",
                "error": pasted["error"],
                "files": pasted.get("files", []),
            }

        uploaded = wait_for_attachments_ready(
            pasted["files"],
            timeout=120.0,
            quiet=quiet,
        )
        if not uploaded["success"]:
            return {
                "success": False,
                "text": "",
                "step": "wait_attachments",
                "error": uploaded["error"],
                "files": uploaded.get("files", []),
            }
        step_number += 1

    _print(f"{step_number}. 提交问题", quiet)
    submitted = press_labeled_button(
        SUBMIT_LABEL,
        timeout=5.0,
        x_range=(70, 100),
        y_range=(82, 100),
        quiet=quiet,
    )
    if not submitted["success"]:
        return {"success": False, "text": "", "step": "submit", "error": submitted["error"]}
    step_number += 1

    if assign_task:
        _print(f"{step_number}. 等待 AI 开始生成", quiet)
        started = wait_until_generation_started(timeout=timeout, quiet=quiet)
        if not started["success"]:
            return {
                "success": False,
                "text": "",
                "mode": "assign_task",
                "step": "wait_generating",
                "error": started["error"],
            }

        elapsed = round(time.time() - started_at, 2)
        return {
            "success": True,
            "text": "",
            "mode": "assign_task",
            "elapsed": elapsed,
            "final_state": started["state"],
            "error": None,
        }

    _print(f"{step_number}. 等待生成完成", quiet)
    finished = wait_until_generation_finished(timeout=timeout, quiet=quiet)
    if not finished["success"]:
        return {"success": False, "text": "", "step": "wait_finished", "error": finished["error"]}
    step_number += 1

    _print(f"{step_number}. 确保贴住底部", quiet)
    attached = wait_until_attached(
        timeout=30.0,
        quiet=quiet,
        initial_state=finished.get("state"),
    )
    if not attached["success"]:
        return {"success": False, "text": "", "step": "attach", "error": attached["error"]}
    step_number += 1

    _print(f"{step_number}. 复制最新回复", quiet)
    copied = copy_latest_visible_reply(timeout=10.0, quiet=quiet)
    if not copied["success"]:
        return {"success": False, "text": "", "step": "copy", "error": copied["error"]}

    elapsed = round(time.time() - started_at, 2)
    return {
        "success": True,
        "text": copied["text"],
        "elapsed": elapsed,
        "final_state": attached["state"],
        "copy_button_info": copied.get("copy_button_info"),
        "error": None,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="向 Notion AI 提问并复制最终回复")
    parser.add_argument(
        "question",
        nargs="?",
        help="要提交给 Notion AI 的问题；AI/自动化调用方建议统一用 --from-stdin",
    )
    parser.add_argument(
        "--from-stdin",
        action="store_true",
        help="从 stdin 读取问题文本；AI/自动化调用方推荐配合 heredoc 使用",
    )
    parser.add_argument(
        "--from-clipboard",
        action="store_true",
        help="从系统剪贴板读取问题文本；保留给人工调试和旧自动化兼容",
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=float,
        default=300.0,
        help="等待生成完成的最长秒数；--assign_task 下为等待进入生成中的最长秒数",
    )
    parser.add_argument(
        "--new_conversation",
        action="store_true",
        help="打开窗口后先按 `开始新对话`，确认进入新对话空输入状态后再提问",
    )
    parser.add_argument(
        "--assign_task",
        action="store_true",
        help="发布任务模式：提交后只等待 AI 进入生成中，不等待完成也不复制回复",
    )
    parser.add_argument(
        "--attach-file",
        action="append",
        default=[],
        dest="attach_files",
        help="写入问题后把本地文件粘贴到 Notion AI 输入框，可重复传入多个文件",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--quiet", action="store_true", help="减少过程日志")
    args = parser.parse_args(argv)

    source_count = sum([
        bool(args.from_stdin),
        bool(args.from_clipboard),
        args.question is not None,
    ])
    if source_count > 1:
        parser.error("--from-stdin、--from-clipboard 和 question 只能使用一种")

    if args.from_stdin:
        args.question = sys.stdin.read()
        if not args.question:
            parser.error("--from-stdin 已设置，但 stdin 里没有文本")
    elif args.from_clipboard:
        args.question = get_clipboard_text()
        if not args.question:
            parser.error("--from-clipboard 已设置，但系统剪贴板里没有文本")
    elif args.question is None:
        parser.error("必须提供 question，或使用 --from-stdin / --from-clipboard 读取问题")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result = ask_and_copy_reply(
        args.question,
        timeout=args.timeout,
        new_conversation=args.new_conversation,
        assign_task=args.assign_task,
        attach_files=args.attach_files,
        quiet=args.quiet or args.json,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["success"] else 1

    if result["success"]:
        if result.get("mode") == "assign_task":
            print(f"\n任务已发布，AI 已进入生成中。耗时 {result['elapsed']}s。")
            return 0
        print(f"\n完成，耗时 {result['elapsed']}s。")
        print("\n--- AI 回复 ---")
        print(result["text"])
        return 0

    print(f"\n失败: {result.get('error')}")
    if result.get("step"):
        print(f"失败步骤: {result['step']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
