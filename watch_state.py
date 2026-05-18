#!/usr/bin/env python3
"""
持续轮询 Notion AI 完整状态，每 0.5 秒扫描一次。

默认只在状态发生变化时输出。加上 --poll 则每 0.5 秒都输出。
如果 AI 窗口未打开，会持续等待，不会退出。

用法:
    ./venv/bin/python watch_state.py              # 默认：只在变化时输出
    ./venv/bin/python watch_state.py --poll        # 每 0.5 秒都输出
    ./venv/bin/python watch_state.py --json       # JSON 格式输出
    ./venv/bin/python watch_state.py --duration 60 # 只跑60秒
"""

import argparse
import json
import time
from datetime import datetime

from check_ai_state import check_ai_state


def format_state(result: dict) -> str:
    """只输出核心字段。"""
    if not result.get("success"):
        return "等待 AI 窗口..."

    return (
        f"新对话={'是' if result.get('is_new_conversation') else '否'} | "
        f"贴住底部={'是' if result.get('is_attach_to_bottom') else '否'} | "
        f"对话={result['conversation_state_label']}({result['conversation_state']}) | "
        f"输入={result['input_state_label']}({result['input_state']}) | "
        f"模式={result.get('mode_pattern_label') or '默认模式'}({result.get('mode_pattern') or 'default'}) | "
        f"模型={result.get('model') or '无'}"
    )


# 变化检测 key：只跟踪核心字段
def state_key(result: dict):
    return (
        result.get("success"),
        result.get("is_new_conversation"),
        result.get("is_attach_to_bottom"),
        result.get("conversation_state"),
        result.get("input_state"),
        result.get("mode_pattern"),
        result.get("model"),
    )


def main():
    parser = argparse.ArgumentParser(description="持续轮询 Notion AI 完整状态")
    parser.add_argument("--poll", action="store_true", help="每 0.5 秒都输出，即使状态没变")
    parser.add_argument("--duration", type=int, default=0, help="运行秒数，0 表示无限")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    print("开始轮询 Notion AI 状态 (每 0.5 秒)", flush=True)
    print("按 Ctrl+C 停止\n", flush=True)

    last_key = None
    start_time = time.time()
    count = 0
    waiting = False

    try:
        while True:
            if args.duration and (time.time() - start_time) >= args.duration:
                break

            count += 1
            result = check_ai_state()
            success = result.get("success", False)

            key = state_key(result)
            changed = (key != last_key)

            if success:
                if waiting:
                    waiting = False
                    if not args.json:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"{ts} AI 窗口已就绪", flush=True)

                if args.poll or changed:
                    if args.json:
                        data = {"timestamp": time.time(), "count": count}
                        data.update(result)
                        if changed:
                            data["changed"] = True
                        print(json.dumps(data, ensure_ascii=False), flush=True)
                    else:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        line = format_state(result)
                        print(f"{ts} {line}", flush=True)

                last_key = key
            else:
                if not waiting:
                    waiting = True
                    last_key = key
                    if not args.json:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        print(f"{ts} 等待 AI 窗口...", flush=True)
                elif args.poll and not args.json:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"{ts} 等待 AI 窗口...", flush=True)

            time.sleep(0.5)

    except KeyboardInterrupt:
        print(f"\n已停止。共检测 {count} 次。", flush=True)


if __name__ == "__main__":
    main()
