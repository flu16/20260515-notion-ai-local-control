#!/usr/bin/env python3
"""Main orchestration flow for asking Notion AI and copying the reply."""

from __future__ import annotations

import time

from .attachment_flow import wait_for_attachments_ready
from .conversation_actions import ensure_ai_window, press_labeled_button, start_new_conversation
from .generation_wait import wait_until_attached, wait_until_generation_finished, wait_until_generation_started
from .input_box import input_text, paste_files_at_current_insertion_point
from .reply_copy import copy_latest_visible_reply


SUBMIT_LABELS = ("提交 AI 消息", "Submit AI message")


def _print(message: str, quiet: bool = False):
    """按 quiet 参数控制普通日志输出。"""
    if not quiet:
        print(message, flush=True)


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
        SUBMIT_LABELS,
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
