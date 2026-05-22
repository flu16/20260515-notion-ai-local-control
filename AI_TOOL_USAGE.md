# AI Tool Usage Guide

这份文件给其他 AI/编码代理使用，例如 OpenClaude、Claude Code、Codex 或类似工具。

本项目的目标不是让 AI 直接操作 Notion UI 的细节，而是提供一个稳定命令行入口，
让 AI 可以向 Notion AI 提问，并拿到最终回复文本。

## 最重要的工具

首选工具是：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[任意长代码 / 任意长提示词 / 短问题]
NOTION_AI_AGENT_EOF
```

这是给 AI/自动化代理调用 Notion AI 的主入口。除非是在调试底层 UI 能力，否则不要绕过它去直接点击
Notion UI、手动找输入框、手动点复制按钮或组合多个底层脚本。

AI 调用方无论问题简单还是复杂，都统一使用 `--from-stdin` 加单引号 heredoc。
这能避免 shell 引号、换行、代码块、路径空格和 `$()` 等内容被命令行提前解析。
注意：`--from-stdin` 只是问题来源；脚本内部仍会把问题写入系统剪贴板，再用已经验证稳定的 Cmd+V 流程粘贴到 Notion AI 输入框。
直接把问题作为命令行参数只适合人工临时调试；`--from-clipboard` 保留给人工调试和旧自动化兼容。

它会完成完整流程：

1. 确保 Notion AI 窗口打开。
2. 把问题写入 Notion AI 输入框，并用双粘贴覆盖策略替换残留内容。
3. 点击 `提交 AI 消息`。
4. 等待 AI 生成完成。
5. 如果长回复导致页面脱离底部，自动点击回到底部按钮。
6. 点击最新回复底部的 `拷贝回复`。
7. 清空剪贴板后等待复制结果写入，并读取当前剪贴板内容作为回复。
8. 把回复文本输出到命令行。

如果只是把一个长任务发布给 Notion AI，不需要本地代理等待最终回复，使用
`--assign_task`：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
[任意长任务]
NOTION_AI_AGENT_EOF
```

这个模式在提交后只等到 `conversation_state=generating`，确认 AI 已经开始生成就返回；
不会等待完成、不会回到底部，也不会复制回复。

## 对话上下文策略

调用方必须先判断这次问题和当前 Notion AI 对话是不是同一个系列。

### 同一系列问题：沿用当前对话

如果这次问题是在继续、追问、改写、扩展或引用上一轮 Notion AI 的回复，默认不要开新对话。

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[连续追问]
NOTION_AI_AGENT_EOF
```

不要加 `--new_conversation`。这样 Notion AI 会保留当前对话上下文，适合连续相关的问题。

### 独立问题：才新开对话

只有当问题应该不受当前 Notion AI 对话上下文影响时，才显式使用 `--new_conversation`：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --new_conversation --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[独立问题]
NOTION_AI_AGENT_EOF
```

`--new_conversation` 会先点击 `开始新对话`，确认对话框回到新对话状态后再输入问题。

不要因为“每次工具调用都想干净”而机械地加 `--new_conversation`。连续相关的多轮问答需要沿用当前对话。

## 推荐调用方式

### 延续当前对话继续提问

如果问题与当前 Notion AI 对话是同一个任务、同一个主题或同一轮分析，使用：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[连续追问]
NOTION_AI_AGENT_EOF
```

不要加 `--new_conversation`。

### 新开一个对话再提问

如果你希望问题不受当前 Notion AI 对话上下文影响，使用：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --new_conversation --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[独立问题]
NOTION_AI_AGENT_EOF
```

`--new_conversation` 会先点击 `开始新对话`，确认对话框回到新对话状态后再输入问题。

### 获取 JSON 结果

如果你是 AI 代理，推荐使用 JSON，便于判断成功或失败：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[任意长代码 / 任意长提示词 / 短问题]
NOTION_AI_AGENT_EOF
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

发布任务模式成功时的典型结构：

```json
{
  "success": true,
  "text": "",
  "mode": "assign_task",
  "elapsed": 2.1,
  "final_state": {
    "success": true,
    "conversation_state": "generating",
    "input_state": "generating"
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
  "error": "等待生成完成并进入稳定对话框状态 超时 (300.0s)"
}
```

AI 调用方应该只把 `success=true` 时的 `text` 当作 Notion AI 回复。

### 默认使用 heredoc/stdin 传入

AI 调用方无论问题简单还是复杂，都不要把问题拼进 shell 命令字符串。
统一使用 `--from-stdin` 加单引号 heredoc：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[任意长代码 / 任意长提示词 / 短问题]
NOTION_AI_AGENT_EOF
```

`--from-stdin` 会从标准输入读取问题文本；写入 Notion AI 输入框时，脚本内部仍会把这段文本写入系统剪贴板，再走稳定的 Cmd+V 粘贴流程。
单引号 heredoc 会让 shell 按字面量传输内容，绕开引号、换行、`$(...)` 和路径空格的解析问题。

如果这段问题是独立任务，再额外加 `--new_conversation`；如果是连续追问，不要加。

### 输入框残留会自动覆盖

调用方不需要先手动清空 Notion AI 输入框。`ask_and_copy_reply.py` 写入问题时会默认执行双粘贴覆盖：

```text
1. 激活输入框真实插入点。
2. 先 Cmd+V 粘贴一次问题文本，唤醒 Notion/Electron 富文本编辑器的真实键盘接管。
3. Cmd+A 全选当前输入框内容。
4. 再 Cmd+V 粘贴同一个问题文本，覆盖旧残留和第一次临时粘贴内容。
```

这个策略用于处理输入框里已经残留长文本、链接 token、文件名 token 或 Markdown-like 内容的情况。
不要在外层脚本里额外组合 `input_box.py --clear`、鼠标点击或手写快捷键清空；直接调用
`ask_and_copy_reply.py`。

## 参数说明

### `question`

要提交给 Notion AI 的问题。使用 `--from-stdin` 或 `--from-clipboard` 时可以省略。
AI/自动化调用方默认使用 `--from-stdin`，此参数主要用于人工临时调试。

人工临时调试时可以直接传入：

```bash
./venv/bin/python ask_and_copy_reply.py "用中文解释一下 Accessibility API"
```

AI 调用方默认推荐：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[任意长代码 / 任意长提示词 / 短问题]
NOTION_AI_AGENT_EOF
```

### `--from-stdin`

可选。从 stdin 读取问题文本。AI/自动化调用方默认应该使用它，即使是短问题也保持同一种格式：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --json << 'NOTION_AI_AGENT_EOF'
你好
NOTION_AI_AGENT_EOF
```

它只负责从 stdin 获取问题；后续写入 Notion AI 输入框仍然使用脚本内部的剪贴板粘贴流程。

适合：

- 简单问题和复杂问题
- 问题包含 shell 代码里的 `'single quotes'`
- 问题包含未配对引号、反斜杠、Markdown 代码块
- 问题来自上游代理生成的长文本
- 不想让调用方先手动执行 `pbcopy`

### `--from-clipboard`

可选。从系统剪贴板读取问题文本。保留给人工调试和旧自动化兼容。

适合：

- 已经在编辑器或其他 App 里复制好的内容
- 人工临时调试
- 旧脚本兼容

### Agent 如何写入剪贴板

正常情况下，agent 不需要自己写剪贴板；优先使用 `--from-stdin`。如果必须兼容旧调用方，可以用 `pbcopy` 加单引号 heredoc：

```bash
pbcopy << 'NOTION_AI_AGENT_EOF'
你好
NOTION_AI_AGENT_EOF

./venv/bin/python ask_and_copy_reply.py --from-clipboard --json
```

Python 旧调用方可以用 `subprocess.run(["pbcopy"], input=...)`，不要用 `shell=True` 拼接问题文本：

```python
import json
import subprocess

question = "请解释一下 MCP，并给一个例子"
subprocess.run(["pbcopy"], input=question, text=True, check=True)

cmd = [
    "./venv/bin/python",
    "ask_and_copy_reply.py",
    "--from-clipboard",
    "--timeout",
    "300",
    "--json",
]

completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
result = json.loads(completed.stdout)
```

### `--new_conversation`

可选。先开始新对话，再提交问题。

只推荐在独立任务中使用它，避免受到旧上下文影响。

适合：

- 单次问答
- 让 Notion AI 处理一段独立输入
- 需要可复现结果

不适合：

- 连续相关问题
- 对上一轮回复继续追问、扩写、修正或让它换格式
- 明确要延续当前对话
- 要让 Notion AI 继续上一轮回答

### `--timeout`

可选。等待生成完成的最长秒数，默认 `300`。

在 `--assign_task` 模式下，它表示等待 AI 进入 `generating` 的最长秒数。

建议：

- 短问题：通常不用设置，默认会在生成完成后立刻返回
- 很长的故事、总结或复杂分析：`300` 到 `600`

示例：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --new_conversation --timeout 600 --json << 'NOTION_AI_AGENT_EOF'
[独立长问题]
NOTION_AI_AGENT_EOF
```

### `--assign_task`

可选。发布任务模式。

适合把长任务交给 Notion AI 后立刻释放本地代理，例如让远端 AI 写长文、做复杂整理或执行
预计会等待很久的任务。脚本只确认 AI 已经进入 `generating`，不等待最终回复，也不会输出回复文本。

示例：

```bash
./venv/bin/python ask_and_copy_reply.py --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
[任意长任务]
NOTION_AI_AGENT_EOF
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
2. 先判断是否同一系列问题：连续相关问题不要加 --new_conversation。
3. 独立问题才加 --new_conversation。
4. 长任务把 --timeout 提高到 600。
5. 自动化场景使用 --json。
6. 只在 success=true 时读取 text。
7. 如果 success=false，读取 step 和 error 判断失败点。
8. 不要直接用鼠标点击 Notion UI。
9. 不要直接改 AXValue 试图输入文本。
10. 不要用 Shift+Tab 来找复制按钮。
```

推荐伪代码：

```python
import json
import subprocess

question = "请解释一下 MCP，并给一个例子"
cmd = [
    "./venv/bin/python",
    "ask_and_copy_reply.py",
    "--from-stdin",
    "--timeout",
    "300",
    "--json",
]

completed = subprocess.run(cmd, input=question, capture_output=True, text=True, check=False)
result = json.loads(completed.stdout)

if result["success"]:
    answer = result["text"]
else:
    raise RuntimeError(f"{result.get('step')}: {result.get('error')}")
```

不要使用 `shell=True` 或把问题插入一整段 shell 命令字符串。`subprocess.run([...])`
会把每个参数原样传给 Python 脚本，是最稳的调用方式。

当前版本在 `--json` 下只输出 JSON。若需要兼容旧版本里 stdout 混入过程日志的情况，
不要用 `stdout.splitlines()[-1]`，应该从 stdout 中扫描可解析的 JSON 对象：

```python
def extract_json_object(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    last = None
    for i, ch in enumerate(stdout):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(stdout[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "success" in obj and "text" in obj:
            last = obj
    if last is None:
        raise ValueError("stdout 中没有找到 ask_and_copy_reply 的 JSON 结果")
    return last
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
./venv/bin/python ask_and_copy_reply.py --from-stdin --new_conversation --timeout 600 --json << 'NOTION_AI_AGENT_EOF'
[独立长问题]
NOTION_AI_AGENT_EOF
```

### 复制后剪贴板为空

脚本会返回失败。

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
