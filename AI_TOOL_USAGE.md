# AI Tool Usage Guide

这份文件给其他 AI/编码代理使用，例如 OpenClaude、Claude Code、Codex 或类似工具。

本项目的目标不是让 AI 直接操作 Notion UI 的细节，而是提供一个稳定命令行入口，
让 AI 可以向 Notion AI 提问，并拿到最终回复文本。

## 最重要的工具

首选工具是：

```bash
./venv/bin/python ask_and_copy_reply.py "你的问题"
```

它会完成完整流程：

1. 确保 Notion AI 窗口打开。
2. 把问题写入 Notion AI 输入框。
3. 点击 `提交 AI 消息`。
4. 等待 AI 生成完成。
5. 如果长回复导致页面脱离底部，自动点击回到底部按钮。
6. 点击最新回复底部的 `拷贝回复`。
7. 等待剪贴板从旧内容变成新回复。
8. 把回复文本输出到命令行。

## 推荐调用方式

### 新开一个对话再提问

如果你希望问题不受当前 Notion AI 对话上下文影响，使用：

```bash
./venv/bin/python ask_and_copy_reply.py "请总结一下什么是 MCP" --new_conversation --timeout 180
```

`--new_conversation` 会先点击 `开始新对话`，确认对话框回到新对话状态后再输入问题。

这是最推荐的默认方式。

### 沿用当前对话继续提问

如果你明确想接着当前 Notion AI 上下文继续问，使用：

```bash
./venv/bin/python ask_and_copy_reply.py "继续上一段，给我三个例子" --timeout 180
```

不要加 `--new_conversation`。

### 获取 JSON 结果

如果你是 AI 代理，推荐使用 JSON，便于判断成功或失败：

```bash
./venv/bin/python ask_and_copy_reply.py "请只回答：OK" --new_conversation --timeout 120 --json
```

成功时的典型结构：

```json
{
  "success": true,
  "text": "OK",
  "elapsed": 18.4,
  "final_state": {
    "success": true,
    "is_new_conversation": false,
    "is_attach_to_bottom": true,
    "conversation_state": "complete",
    "input_state": "empty",
    "model": "Opus 4.7"
  },
  "error": null
}
```

失败时的典型结构：

```json
{
  "success": false,
  "text": "",
  "step": "wait_finished",
  "error": "等待生成完成并进入稳定对话框状态 超时 (120.0s)"
}
```

AI 调用方应该只把 `success=true` 时的 `text` 当作 Notion AI 回复。

## 参数说明

### `question`

必填。要提交给 Notion AI 的问题。

示例：

```bash
./venv/bin/python ask_and_copy_reply.py "用中文解释一下 Accessibility API"
```

### `--new_conversation`

可选。先开始新对话，再提交问题。

推荐在独立任务中默认使用它，避免受到旧上下文影响。

适合：

- 单次问答
- 让 Notion AI 处理一段独立输入
- 需要可复现结果

不适合：

- 明确要延续当前对话
- 要让 Notion AI 继续上一轮回答

### `--timeout`

可选。等待生成完成的最长秒数，默认 `120`。

建议：

- 短问题：`60` 到 `120`
- 长故事、长总结、复杂分析：`180` 到 `300`

示例：

```bash
./venv/bin/python ask_and_copy_reply.py "请写一篇 1500 字故事" --new_conversation --timeout 300
```

### `--json`

可选。输出结构化 JSON。

AI/自动化脚本优先使用这个参数。

### `--quiet`

可选。减少过程日志。

如果已经使用 `--json`，脚本会自动安静运行，只输出 JSON。

## 状态模型

`check_ai_state.py` 和 `ask_and_copy_reply.py` 使用同一套状态模型。

### 对话框状态

`conversation_state` 只表示阶段：

```text
new_conversation
generating
complete
unknown
```

含义：

- `new_conversation`：对话框区域仍是新对话，通常只有初始问候语
- `generating`：AI 正在生成
- `complete`：AI 回复已完成
- `unknown`：没有命中稳定规则，通常是短暂过渡或异常状态

### 贴底状态

是否贴住底部由单独字段表示：

```json
"is_attach_to_bottom": true
```

含义：

- `true`：完成态已贴住底部，可以看到最新回复操作区
- `false`：新对话、生成中、脱离底部或未知状态

长回复完成时经常会先出现：

```json
{
  "conversation_state": "complete",
  "is_attach_to_bottom": false
}
```

这不是失败。`ask_and_copy_reply.py` 会自动点击回到底部按钮，然后再复制回复。

### 新对话状态

是否新对话由：

```json
"is_new_conversation": true
```

表示。

这个判断只看对话框区域，不看输入框区域。也就是说，如果用户已经在新对话输入框里打字但还没提交，
它仍然可能是新对话。

## 辅助工具

### 检查当前状态

```bash
./venv/bin/python check_ai_state.py --json
```

用于调试当前 Notion AI 状态。

典型输出：

```json
{
  "success": true,
  "is_new_conversation": false,
  "is_attach_to_bottom": true,
  "conversation_state": "complete",
  "input_state": "empty",
  "model": "Opus 4.7"
}
```

### 持续监听状态

```bash
./venv/bin/python watch_state.py
```

会每 0.5 秒扫描一次，只在状态变化时输出。

### 打开 Notion AI 窗口

通常不需要手动调用，因为 `ask_and_copy_reply.py` 会自己确保窗口打开。

调试时可以用：

```bash
./venv/bin/python open_ai_window.py --open
```

这个命令是幂等的：如果窗口已经打开，不会再次发送快捷键。

## AI 调用方的建议逻辑

如果你是另一个 AI/自动化代理，请按下面逻辑调用：

```text
1. 优先使用 ask_and_copy_reply.py。
2. 独立问题默认加 --new_conversation。
3. 长任务把 --timeout 提高到 180 或 300。
4. 自动化场景使用 --json。
5. 只在 success=true 时读取 text。
6. 如果 success=false，读取 step 和 error 判断失败点。
7. 不要直接用鼠标点击 Notion UI。
8. 不要直接改 AXValue 试图输入文本。
9. 不要用 Shift+Tab 来找复制按钮。
```

推荐伪代码：

```python
import json
import subprocess

cmd = [
    "./venv/bin/python",
    "ask_and_copy_reply.py",
    "请解释一下 MCP，并给一个例子",
    "--new_conversation",
    "--timeout",
    "180",
    "--json",
]

completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
result = json.loads(completed.stdout)

if result["success"]:
    answer = result["text"]
else:
    raise RuntimeError(f"{result.get('step')}: {result.get('error')}")
```

## 不推荐直接使用的底层脚本

下面这些脚本主要用于调试或开发，不建议普通 AI 调用方直接依赖：

- `search_element.py`
- `click_element.py`
- `focus_element.py`
- `watch_focus.py`
- `input_box.py`

原因：

- 它们是底层能力，不保证完整流程。
- 直接组合它们容易绕过已经验证过的等待、贴底、剪贴板变化判断。
- 目前稳定闭环已经在 `ask_and_copy_reply.py` 中实现。

## 常见失败和处理

### Notion AI 窗口未打开

`ask_and_copy_reply.py` 通常会自动打开窗口。

如果仍失败，可以先运行：

```bash
./venv/bin/python open_ai_window.py --open
```

再重试。

### 生成超时

提高 `--timeout`：

```bash
./venv/bin/python ask_and_copy_reply.py "请写一个长故事" --new_conversation --timeout 300 --json
```

### 复制后剪贴板没有变化

脚本会返回失败，不会把旧剪贴板误当成回复。

这通常说明：

- `拷贝回复` 没有真正触发
- Notion UI 短暂异常
- 回复操作区没有稳定出现

可以重试一次，或先用：

```bash
./venv/bin/python check_ai_state.py --json
```

查看是否已经：

```json
{
  "conversation_state": "complete",
  "is_attach_to_bottom": true
}
```

## 当前边界

- 这个工具依赖 macOS Accessibility 权限。
- 这个工具依赖 Notion 桌面端当前 UI 结构。
- Notion UI 改版后，按钮 label 或 AX 结构可能需要重新验证。
- 这个工具目前不是 MCP server；它是一个稳定 CLI 工具。
- 未来如果 CLI 接口稳定，可以再包装成 MCP。
