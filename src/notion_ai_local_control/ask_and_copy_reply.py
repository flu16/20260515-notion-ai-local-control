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
    ./venv/bin/notion-ai ask "讲一个故事"
    ./venv/bin/notion-ai ask --from-stdin --json << 'NOTION_AI_AGENT_EOF'
    讲一个故事
    NOTION_AI_AGENT_EOF
    ./venv/bin/notion-ai ask --from-clipboard
    ./venv/bin/notion-ai ask --attach-file ./report.pdf "总结这个文件"
    ./venv/bin/notion-ai ask "讲一个故事" --new_conversation
    ./venv/bin/notion-ai ask "讲一个故事" --timeout 300
    ./venv/bin/notion-ai ask "讲一个故事" --json
    ./venv/bin/notion-ai ask "处理这个任务" --assign_task --json
"""

from __future__ import annotations

import argparse
import json
import sys

from .ask_flow import ask_and_copy_reply
from .notion_ax import get_clipboard_text


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
