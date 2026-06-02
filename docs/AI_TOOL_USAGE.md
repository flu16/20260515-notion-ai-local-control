# Notion AI Tool Usage

本文档给 AI agent / 自动化调用方使用。当前项目只保留 CDP 路线。

## 首选命令

```bash
./venv/bin/notion-ai ask --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[问题文本]
NOTION_AI_AGENT_EOF
```

## 对话上下文

默认行为：先开始新对话，再提交问题。

如果问题是独立任务，直接使用默认流程：

```bash
./venv/bin/notion-ai ask --from-stdin --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[独立问题]
NOTION_AI_AGENT_EOF
```

如果问题是在继续、追问、改写、扩展或引用当前 Notion AI 对话，显式使用 `--continue_conversation`：

```bash
./venv/bin/notion-ai ask --from-stdin --continue_conversation --timeout 180 --json << 'NOTION_AI_AGENT_EOF'
[连续追问]
NOTION_AI_AGENT_EOF
```

## 发布长任务

`--assign_task` 会在提交后只等待 AI 进入生成中，然后返回；不会等待完成，也不会复制回复。

```bash
./venv/bin/notion-ai ask --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
[长任务]
NOTION_AI_AGENT_EOF
```

## 附件

`--attach-file` 可重复传入多个文件：

```bash
./venv/bin/notion-ai ask --attach-file ./report.pdf --attach-file ./notes.md --json "总结这些文件"
```

## JSON 输出

成功时：

```json
{
  "success": true,
  "text": "...",
  "elapsed": 4.2,
  "error": null
}
```

失败时：

```json
{
  "success": false,
  "text": "",
  "step": "cdp",
  "error": "..."
}
```

调用方只应在 `success=true` 时读取 `text`。

## CDP 调试

检查 quick-search target 和输入框状态：

```bash
./venv/bin/notion-ai beta-cdp-input --status
```

写入输入框：

```bash
./venv/bin/notion-ai beta-cdp-input "测试文本"
```

清空输入框：

```bash
./venv/bin/notion-ai beta-cdp-input --clear
```

## Agent 调用建议

1. 优先使用 `./venv/bin/notion-ai ask`。
2. 独立问题使用默认流程。
3. 连续追问才加 `--continue_conversation`。
4. 长任务可加 `--timeout 600`。
5. 自动化场景使用 `--json`。
6. 只在 `success=true` 时读取 `text`。
7. 如果 `success=false`，读取 `step` 和 `error` 判断失败点。
8. 不要直接操作 Notion UI。
9. 不要调用已删除的 AX legacy 命令。
