# Notion AI Local Control

用 Electron CDP 控制 Notion 桌面端的 Notion AI quick-search 浮动窗口。正式入口是统一 CLI：

```bash
./venv/bin/notion-ai ask "1+1" --json
```

首次使用或重建虚拟环境后，先安装 editable package：

```bash
./venv/bin/python -m pip install -e .
```

未安装时可以直接用模块方式调用：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask "1+1" --json
```

## 常用命令

向 Notion AI 提问并复制回复：

```bash
./venv/bin/notion-ai ask --from-stdin --json << 'NOTION_AI_AGENT_EOF'
解释一下这个项目现在的结构
NOTION_AI_AGENT_EOF
```

`notion-ai ask` 默认会先开始新对话，避免受到上一轮上下文影响。
如果要沿用当前 Notion AI 对话，请加 `--continue_conversation`：

```bash
./venv/bin/notion-ai ask "继续刚才的话题" --continue_conversation --json
```

发布任务后只等待 AI 开始生成：

```bash
./venv/bin/notion-ai ask --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
请分析这份长任务
NOTION_AI_AGENT_EOF
```

CDP 调试命令：

```bash
./venv/bin/notion-ai beta-cdp-input --status
```

## 能力边界

- 只保留 CDP 路线，不再包含 macOS Accessibility legacy 代码。
- `ask` 只操作 Notion quick-search target，支持 `https://www.notion.so/quick-search` 和 `https://app.notion.com/quick-search`。
- 如果 `127.0.0.1:9222` 不可用，默认会重启 Notion 并带 `--remote-debugging-port=9222` 启动。
- `--attach-file` 支持 Notion AI 当前可上传的图片、PDF、CSV、Markdown、纯文本和常见代码/文本文件。

## 项目地图

```text
.
├── README.md
├── PROJECT.md
├── docs/
├── pyproject.toml
└── src/notion_ai_local_control/
    ├── __init__.py
    ├── cli.py              # notion-ai 统一入口
    ├── ask_cdp.py          # ask/ask-cdp 的 CDP 提问流程
    └── beta_cdp_input.py   # CDP target、DOM 输入、提交、附件与复制底层能力
```

## 验证

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai --help
./venv/bin/notion-ai ask --help
./venv/bin/notion-ai ask-cdp --help
./venv/bin/notion-ai beta-cdp-input --status
./venv/bin/notion-ai ask "1+1" --json --timeout 60
```
