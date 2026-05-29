#!/usr/bin/env python3
"""CDP-backed Notion AI ask flow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .beta_cdp_input import (
    CdpError,
    DEFAULT_PORT,
    DEFAULT_WAIT_TEXTBOX_INTERVAL,
    DEFAULT_WAIT_TEXTBOX_TIMEOUT,
    QUICK_SEARCH_URL,
    cdp_is_running,
    copy_reply,
    dom_status,
    restart_notion_with_cdp,
    set_file_input_files,
    set_text_and_submit,
    start_new_conversation_cdp,
    wait_for_attachments_ready_cdp,
    wait_for_cdp_server,
    wait_for_cdp_ready,
    wait_for_generation_finished_cdp as wait_for_generation_finished_observer,
    wait_for_generation_started_cdp as wait_for_generation_started_observer,
)
from .notion_ax import get_clipboard_text, set_clipboard_text


def _print(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, flush=True)


def _question_marker(question: str) -> str:
    marker = " ".join(question.strip().split())
    return marker[:120]


def _body_contains_question(status: dict, question: str) -> bool:
    marker = _question_marker(question)
    if not marker:
        return False
    body = status.get("bodyTextTail") or ""
    compact_body = " ".join(body.split())
    if marker in compact_body:
        return True

    dense_marker = "".join(marker.split())
    dense_body = "".join(body.split())
    return bool(dense_marker and dense_marker in dense_body)


def _visible_textbox_text(status: dict) -> str:
    for textbox in status.get("textboxes", []):
        if textbox.get("visible"):
            return textbox.get("text") or ""
    return ""


def _file_seen_in_text(file_path: str, text: str) -> bool:
    path = Path(file_path)
    filename = path.name
    compact_text = " ".join(text.split())
    if filename in text or filename in compact_text:
        return True
    return path.stem in text and path.suffix in text


def wait_for_attachments_in_context_cdp(file_paths: list[str],
                                        timeout: float = 120.0,
                                        quiet: bool = False,
                                        port: int = DEFAULT_PORT) -> dict:
    deadline = time.time() + timeout
    last_key = None
    last_status = None

    while time.time() < deadline:
        status = dom_status(port, QUICK_SEARCH_URL, body_limit=30000)
        last_status = status
        body = status.get("bodyTextTail") or ""
        button_labels = "\n".join(
            button.get("label") or ""
            for button in status.get("buttons", [])
        )
        visible_text = body + "\n" + button_labels
        seen = [
            str(Path(path).name)
            for path in file_paths
            if _file_seen_in_text(path, visible_text)
        ]
        complete = (
            len(seen) == len(file_paths)
            and not status.get("hasStop")
            and not status.get("hasGeneratingText")
        )
        key = (
            tuple(sorted(seen)),
            status.get("hasStop"),
            status.get("hasGeneratingText"),
            status.get("copyReplyCount"),
        )
        if key != last_key:
            _print(
                "  CDP 附件上下文: "
                f"seen={', '.join(seen) if seen else '无'} | "
                f"generating={'是' if status.get('hasStop') or status.get('hasGeneratingText') else '否'}",
                quiet,
            )
            last_key = key

        if complete:
            return {
                "success": True,
                "files": file_paths,
                "seen": seen,
                "state": status,
                "error": None,
            }
        time.sleep(0.35)

    return {
        "success": False,
        "files": file_paths,
        "state": last_status,
        "error": f"等待 CDP 附件进入对话上下文超时 ({timeout}s)",
    }


def ensure_cdp_ai_ready(port: int, auto_restart: bool, restart: bool,
                        timeout: float, interval: float) -> dict:
    launch_info = None
    if restart or (auto_restart and not cdp_is_running(port)):
        launch_info = restart_notion_with_cdp(port)
        wait_for_cdp_server(port)

    status = wait_for_cdp_ready(port, QUICK_SEARCH_URL, timeout, interval)
    return {"launch_info": launch_info, "status": status}


def wait_until_generation_started_cdp(question: str, timeout: float,
                                      quiet: bool = False,
                                      port: int = DEFAULT_PORT) -> dict:
    _print("  CDP 状态: 等待生成开始（页面内 MutationObserver）", quiet)
    try:
        return wait_for_generation_started_observer(
            question,
            port=port,
            timeout=timeout,
        )
    except CdpError as exc:
        _print(f"  MutationObserver 等待失败，回退轮询: {exc}", quiet)
        return wait_until_generation_started_polling_cdp(
            question,
            timeout=timeout,
            quiet=quiet,
            port=port,
        )


def wait_until_generation_started_polling_cdp(question: str, timeout: float,
                                              quiet: bool = False,
                                              port: int = DEFAULT_PORT) -> dict:
    deadline = time.time() + timeout
    last_key = None
    saw_question = False
    last_status = None

    while time.time() < deadline:
        status = dom_status(port, QUICK_SEARCH_URL, body_limit=20000)
        last_status = status
        saw_question = saw_question or _body_contains_question(status, question)
        textbox_text = _visible_textbox_text(status)
        key = (
            status.get("hasStop"),
            status.get("hasGeneratingText"),
            bool(status.get("enabledSubmit")),
            status.get("copyReplyCount"),
            bool(textbox_text),
            saw_question,
        )
        if key != last_key:
            _print(
                "  CDP 状态: "
                f"stop={'是' if status.get('hasStop') else '否'} | "
                f"generating={'是' if status.get('hasGeneratingText') else '否'} | "
                f"submit={'可用' if status.get('enabledSubmit') else '不可用'} | "
                f"copy={status.get('copyReplyCount')} | "
                f"question={'已出现' if saw_question else '未出现'}",
                quiet,
            )
            last_key = key

        if status.get("hasStop") or (saw_question and not textbox_text):
            return {"success": True, "state": status, "error": None}
        time.sleep(0.25)

    return {
        "success": False,
        "state": last_status,
        "error": f"等待 CDP 生成开始超时 ({timeout}s)",
    }


def wait_until_generation_finished_cdp(question: str, timeout: float,
                                       quiet: bool = False,
                                       port: int = DEFAULT_PORT) -> dict:
    _print("  CDP 状态: 等待生成完成（页面内 MutationObserver）", quiet)
    try:
        return wait_for_generation_finished_observer(
            question,
            port=port,
            timeout=timeout,
        )
    except CdpError as exc:
        _print(f"  MutationObserver 等待失败，回退轮询: {exc}", quiet)
        return wait_until_generation_finished_polling_cdp(
            question,
            timeout=timeout,
            quiet=quiet,
            port=port,
        )


def wait_until_generation_finished_polling_cdp(question: str, timeout: float,
                                               quiet: bool = False,
                                               port: int = DEFAULT_PORT) -> dict:
    deadline = time.time() + timeout
    last_key = None
    saw_question = False
    saw_stop = False
    last_status = None

    while time.time() < deadline:
        status = dom_status(port, QUICK_SEARCH_URL, body_limit=30000)
        last_status = status
        saw_question = saw_question or _body_contains_question(status, question)
        saw_stop = saw_stop or bool(status.get("hasStop"))
        key = (
            status.get("hasStop"),
            status.get("hasGeneratingText"),
            status.get("copyReplyCount"),
            bool(status.get("enabledSubmit")),
            saw_question,
            saw_stop,
        )
        if key != last_key:
            _print(
                "  CDP 状态: "
                f"stop={'是' if status.get('hasStop') else '否'} | "
                f"generating={'是' if status.get('hasGeneratingText') else '否'} | "
                f"copy={status.get('copyReplyCount')} | "
                f"question={'已出现' if saw_question else '未出现'}",
                quiet,
            )
            last_key = key

        if (
            saw_question
            and not status.get("hasStop")
            and not status.get("hasGeneratingText")
            and status.get("copyReplyCount", 0) > 0
            and (saw_stop or not status.get("enabledSubmit"))
        ):
            return {"success": True, "state": status, "error": None}
        time.sleep(0.35)

    return {
        "success": False,
        "state": last_status,
        "error": f"等待 CDP 生成完成超时 ({timeout}s)",
    }


def copy_latest_reply_cdp(timeout: float = 10.0,
                          quiet: bool = False,
                          port: int = DEFAULT_PORT) -> dict:
    set_clipboard_text("")
    deadline = time.time() + timeout
    clicked = None

    while time.time() < deadline:
        clicked = copy_reply(port, QUICK_SEARCH_URL)
        if clicked.get("ok"):
            _print("  已点击 CDP 拷贝回复", quiet)
            break
        time.sleep(0.25)

    if not clicked or not clicked.get("ok"):
        return {"success": False, "text": "", "error": "等待 CDP 拷贝回复按钮超时"}

    deadline = time.time() + 5.0
    text = ""
    while time.time() < deadline:
        text = get_clipboard_text()
        if text:
            break
        time.sleep(0.2)

    if not text:
        return {"success": False, "text": "", "error": "CDP 点击拷贝回复后剪贴板为空"}

    return {
        "success": True,
        "text": text,
        "copy_button_info": clicked,
        "error": None,
    }


def ask_and_copy_reply_cdp(question: str,
                           timeout: float = 300.0,
                           new_conversation: bool = False,
                           assign_task: bool = False,
                           attach_files: list[str] | None = None,
                           quiet: bool = False,
                           port: int = DEFAULT_PORT,
                           auto_restart: bool = True,
                           restart_with_cdp: bool = False) -> dict:
    started_at = time.time()

    try:
        _print("===== CDP 后台提问 =====", quiet)
        ready = ensure_cdp_ai_ready(
            port,
            auto_restart=auto_restart,
            restart=restart_with_cdp,
            timeout=DEFAULT_WAIT_TEXTBOX_TIMEOUT,
            interval=DEFAULT_WAIT_TEXTBOX_INTERVAL,
        )
        launch_info = ready.get("launch_info") if isinstance(ready, dict) else None

        if new_conversation:
            _print("1. CDP 开始新对话", quiet)
            clicked = start_new_conversation_cdp(port, QUICK_SEARCH_URL)
            if not clicked.get("ok"):
                return {
                    "success": False,
                    "text": "",
                    "step": "new_conversation",
                    "error": clicked.get("error"),
                    "details": clicked,
                }
            wait_for_cdp_ready(port, QUICK_SEARCH_URL)

        if attach_files:
            _print("2. CDP 上传附件到上下文", quiet)
            attached = set_file_input_files(attach_files, port, QUICK_SEARCH_URL)
            if not attached.get("ok"):
                return {
                    "success": False,
                    "text": "",
                    "step": "attach_files",
                    "error": attached.get("error"),
                    "details": attached,
                }
            context_ready = wait_for_attachments_ready_cdp(
                attached["files"],
                port=port,
                timeout=120.0,
            )
            if not context_ready["success"]:
                return {
                    "success": False,
                    "text": "",
                    "step": "wait_attachments",
                    "error": context_ready["error"],
                    "files": context_ready.get("files", []),
                    "final_state": context_ready.get("state") or context_ready.get("status"),
                }

        _print("3. CDP 写入并提交问题", quiet)
        wait_for_cdp_ready(port, QUICK_SEARCH_URL)
        submitted = set_text_and_submit(question, port, QUICK_SEARCH_URL)
        if not submitted.get("ok"):
            return {
                "success": False,
                "text": "",
                "step": "input_submit",
                "error": submitted.get("error"),
                "details": submitted,
            }

        if assign_task:
            _print("4. 等待 CDP 生成开始", quiet)
            started = wait_until_generation_started_cdp(
                question,
                timeout=timeout,
                quiet=quiet,
                port=port,
            )
            if not started["success"]:
                return {
                    "success": False,
                    "text": "",
                    "mode": "assign_task",
                    "step": "wait_generating",
                    "error": started["error"],
                    "final_state": started.get("state"),
                }
            return {
                "success": True,
                "text": "",
                "mode": "assign_task",
                "elapsed": round(time.time() - started_at, 2),
                "final_state": started["state"],
                "launch_info": launch_info,
                "error": None,
            }

        _print("4. 等待 CDP 生成完成", quiet)
        finished = wait_until_generation_finished_cdp(
            question,
            timeout=timeout,
            quiet=quiet,
            port=port,
        )
        if not finished["success"]:
            return {
                "success": False,
                "text": "",
                "step": "wait_finished",
                "error": finished["error"],
                "final_state": finished.get("state"),
            }

        _print("5. CDP 拷贝最新回复", quiet)
        copied = copy_latest_reply_cdp(timeout=10.0, quiet=quiet, port=port)
        if not copied["success"]:
            return {
                "success": False,
                "text": "",
                "step": "copy",
                "error": copied["error"],
            }

        return {
            "success": True,
            "text": copied["text"],
            "elapsed": round(time.time() - started_at, 2),
            "final_state": finished["state"],
            "copy_button_info": copied.get("copy_button_info"),
            "launch_info": launch_info,
            "error": None,
        }
    except (CdpError, subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
        return {"success": False, "text": "", "step": "cdp", "error": str(exc)}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用 Electron CDP 后台向 Notion AI 提问")
    parser.add_argument("question", nargs="?", help="要提交给 Notion AI 的问题")
    parser.add_argument("--from-stdin", action="store_true", help="从 stdin 读取问题文本")
    parser.add_argument("--from-clipboard", action="store_true", help="从系统剪贴板读取问题文本")
    parser.add_argument("--timeout", "-t", type=float, default=300.0)
    parser.add_argument("--new_conversation", action="store_true", help="先开始新对话")
    parser.add_argument("--assign_task", action="store_true", help="提交后只等待进入生成中")
    parser.add_argument(
        "--attach-file",
        action="append",
        default=[],
        dest="attach_files",
        help="通过 CDP file input 上传附件，可重复传入多个文件",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-auto-restart", action="store_true",
                        help="CDP 端口不可用时不自动重启 Notion")
    parser.add_argument("--no-auto-open", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--restart-with-cdp", action="store_true",
                        help="需要时重启 Notion 并带 CDP 端口启动")
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
    result = ask_and_copy_reply_cdp(
        args.question,
        timeout=args.timeout,
        new_conversation=args.new_conversation,
        assign_task=args.assign_task,
        attach_files=args.attach_files,
        quiet=args.quiet or args.json,
        port=args.port,
        auto_restart=not (args.no_auto_restart or args.no_auto_open),
        restart_with_cdp=args.restart_with_cdp,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["success"] else 1

    if result["success"]:
        if result.get("mode") == "assign_task":
            print(f"\n任务已通过 CDP 发布，AI 已进入生成中。耗时 {result['elapsed']}s。")
            return 0
        print(f"\nCDP 完成，耗时 {result['elapsed']}s。")
        print("\n--- AI 回复 ---")
        print(result["text"])
        return 0

    print(f"\n失败: {result.get('error')}")
    if result.get("step"):
        print(f"失败步骤: {result['step']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
