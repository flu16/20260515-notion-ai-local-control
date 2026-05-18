#!/usr/bin/env python3
"""
持续轮询 Notion AI 完整状态，每秒检测一次。

包含：对话框状态、输入框状态、当前模型、完成态信号、右下角按钮等。
只打印状态发生变化时的结果，减少噪音。

用法:
    ./venv/bin/python watch_state.py
    ./venv/bin/python watch_state.py --verbose       # 每秒都打印
    ./venv/bin/python watch_state.py --duration 60   # 只跑60秒
"""

import argparse
import json
import time

from check_ai_state import check_ai_state


def format_state(result: dict) -> str:
    """只输出三个核心字段：对话框状态、输入框状态、模型。"""
    if not result.get("success"):
        return f"错误: {result.get('error', '未知')}"

    return (
        f"对话={result['conversation_state_label']}({result['conversation_state']}) | "
        f"输入={result['input_state_label']}({result['input_state']}) | "
        f"模型={result.get('model') or '无'}"
    )


# 变化检测 key：只跟踪三个核心字段
def state_key(result: dict):
    return (
        result.get("success"),
        result.get("conversation_state"),
        result.get("input_state"),
        result.get("model"),
    )


def main():
    parser = argparse.ArgumentParser(description="持续轮询 Notion AI 完整状态")
    parser.add_argument("--verbose", action="store_true", help="每秒都打印，即使状态没变")
    parser.add_argument("--duration", type=int, default=0, help="运行秒数，0 表示无限")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    print("开始轮询 Notion AI 状态 (每 0.5 秒)", flush=True)
    print("按 Ctrl+C 停止\n", flush=True)

    last_key = None
    start_time = time.time()
    count = 0

    try:
        while True:
            if args.duration and (time.time() - start_time) >= args.duration:
                break

            count += 1
            result = check_ai_state()

            key = state_key(result)

            changed = (key != last_key)

            if args.verbose or changed:
                if args.json:
                    data = {"timestamp": time.time(), "count": count}
                    data.update(result)
                    if changed:
                        data["changed"] = True
                    print(json.dumps(data, ensure_ascii=False), flush=True)
                else:
                    prefix = "[变化]" if changed else "[保持]"
                    line = format_state(result)
                    print(f"{prefix} [{count}] {line}", flush=True)

                last_key = key

            time.sleep(0.5)

    except KeyboardInterrupt:
        print(f"\n已停止。共检测 {count} 次。", flush=True)


if __name__ == "__main__":
    main()
