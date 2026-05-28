#!/usr/bin/env python3
"""Generation and scroll-position wait helpers for the Notion AI ask flow."""

from __future__ import annotations

import time

from .check_ai_state import (
    check_ai_state,
    is_stop_generating_button_desc,
    scan_fast_completion_signals,
)
from .conversation_actions import ensure_ai_window, press_back_to_bottom
from .reply_copy import wait_for_bottom_copy_button


COPY_REPLY_LABEL = "拷贝回复"


def _print(message: str, quiet: bool = False):
    """按 quiet 参数控制普通日志输出。"""
    if not quiet:
        print(message, flush=True)


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
        if copy_reply is not None and not is_stop_generating_button_desc(signals.get("input_button_desc")):
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
