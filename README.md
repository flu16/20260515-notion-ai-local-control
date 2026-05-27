# Notion AI Local Control

用 macOS Accessibility API 控制 Notion 桌面端的 Notion AI 浮动窗口。正式入口是统一 CLI：

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

发布任务后只等待 AI 开始生成：

```bash
./venv/bin/notion-ai ask --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
请分析这份长任务
NOTION_AI_AGENT_EOF
```

调试命令：

```bash
./venv/bin/notion-ai state --json
./venv/bin/notion-ai search "拷贝回复"
./venv/bin/notion-ai input --read
./venv/bin/notion-ai model --current
./venv/bin/notion-ai open --check
```

## 能力边界

- `--attach-file` 支持 Notion AI 当前可上传的文件类型：图片、PDF、CSV、Markdown、纯文本。
- 图片按常见扩展名识别：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`、`.heic`、`.heif`。
- Markdown / 纯文本按扩展名识别：`.md`、`.markdown`、`.txt`。
- 其他文件会在粘贴到 Notion AI 之前被拦截，并返回明确错误。

## 项目地图

```text
.
├── README.md                    # 快速上手
├── PROJECT.md                   # 项目结构和维护原则
├── docs/                        # 深入说明和历史记录
├── pyproject.toml               # package 与 CLI 配置
└── src/notion_ai_local_control/  # 实现代码
```

包内模块按职责看：

```text
CLI
  cli.py                         # notion-ai 统一入口
  ask_and_copy_reply.py          # ask 参数解析与输出格式

Ask workflow
  ask_flow.py                    # 主提问流程编排
  conversation_actions.py        # 窗口、扫描、按钮动作
  generation_wait.py             # 生成完成与贴底等待
  reply_copy.py                  # 复制最新回复
  attachment_flow.py             # 附件上传等待

AX primitives
  notion_ax.py                   # macOS AX / Quartz / 剪贴板底层能力
  input_box.py                   # 输入框读写和文件粘贴
  check_ai_state.py              # Notion AI 状态判断
  search_element.py              # AX 元素搜索和列表扫描

Tools
  model_selector.py              # 模型读取和切换
  open_ai_window.py              # 打开/检查 AI 窗口
  click_element.py               # 调试点击
  focus_element.py               # 调试聚焦
  watch_state.py                 # 状态监听
  watch_focus.py                 # 焦点监听
```

## 文档索引

- `PROJECT.md`：项目目标、原则、模块职责。
- `docs/AI_TOOL_USAGE.md`：给 AI agent 的调用规范。
- `docs/ASK_FLOW_REFACTOR.md`：ask 流程拆分思路。
- `docs/PROBLEM_SOLUTIONS.md`：关键问题和解决方案记录。
- `docs/AX_ELEMENTS.md`：已观察到的 Accessibility 元素样本。

## 验证

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai --help
./venv/bin/notion-ai ask --help
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask --help
```

真实流程抽测：

```bash
./venv/bin/notion-ai ask "1+1" --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask "1+1" --json
```
