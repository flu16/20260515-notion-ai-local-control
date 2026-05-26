#!/usr/bin/env python3
"""Attachment upload helpers for the Notion AI ask flow."""

from __future__ import annotations

import time
from pathlib import Path

from .check_ai_state import element_label
from .input_box import find_text_area
from .notion_ax import element_at_position, element_info, kAXErrorSuccess, press

from .conversation_actions import ensure_ai_window, scan_visible_element_objects


ATTACHMENT_REMOVE_PREFIX = "从上下文中移除"
ALLOW_UPLOAD_LABEL = "允许上传"


def _print(message: str, quiet: bool = False):
    """按 quiet 参数控制普通日志输出。"""
    if not quiet:
        print(message, flush=True)


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
