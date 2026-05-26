# Notion AI Local Control

用 macOS Accessibility API 控制 Notion 桌面端的 Notion AI 浮动窗口。

正式入口是统一 CLI：

```bash
./venv/bin/notion-ai ask "1+1" --json
```

安装为 editable package 后，也可以使用统一 CLI：

```bash
./venv/bin/python -m pip install -e .
./venv/bin/notion-ai ask "1+1" --json
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

发布任务后只等待 AI 开始生成：

```bash
./venv/bin/notion-ai ask --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
请分析这份长任务
NOTION_AI_AGENT_EOF
```

统一 CLI 调试命令：

```bash
./venv/bin/notion-ai state --json
./venv/bin/notion-ai search "拷贝回复"
./venv/bin/notion-ai input --read
./venv/bin/notion-ai model --current
./venv/bin/notion-ai open --check
```

## 项目结构

```text
.
├── pyproject.toml
├── src/
│   └── notion_ai_local_control/
│       ├── cli.py                 # 统一 CLI
│       ├── ask_and_copy_reply.py  # CLI 参数与输出
│       ├── ask_flow.py            # 主提问流程编排
│       ├── conversation_actions.py
│       ├── attachment_flow.py
│       ├── generation_wait.py
│       ├── reply_copy.py
│       ├── input_box.py
│       ├── check_ai_state.py
│       └── notion_ax.py
└── *.md
```

## 验证

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai ask --help
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli --help
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask --help
```

真实流程抽测：

```bash
./venv/bin/notion-ai ask "1+1" --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask "1+1" --json
```
