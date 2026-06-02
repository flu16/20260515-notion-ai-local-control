# Notion AI Local Control Project

本文档面向后续接手本项目的 AI 或开发者，说明当前项目目标、结构和维护原则。

## 项目目标

本项目用于让本地程序通过 Electron CDP 操作 Notion 桌面端的 Notion AI quick-search 浮动窗口。

当前项目只保留 CDP 路线：

- 通过 CDP 定位 Notion quick-search target
- 通过 renderer DOM 写入、提交、等待并复制 Notion AI 回复
- 在 CDP 端口不可用时重启 Notion，并带 `--remote-debugging-port=9222`
- 支持 Notion AI 可上传附件
- 默认先开始新对话；传 `--continue_conversation` 时沿用当前对话

## 核心原则

### 只使用 CDP

`notion-ai ask` 默认调用 CDP 流程。`notion-ai ask-cdp` 是兼容别名。

项目不再包含 macOS Accessibility legacy 代码，也不提供 `ask-ax`、`state`、`search`、`input`、`model`、`open` 等 AX/debug 命令。

### 限定 quick-search

主流程只接受 Notion quick-search target：

- `https://www.notion.so/quick-search`
- `https://app.notion.com/quick-search`

它不操作 `https://www.notion.so/ai` 或 `https://app.notion.com/ai` 主页面。

### 默认新对话

`notion-ai ask` 默认先点击 `开始新对话`，再写入和提交问题。

只有在明确要追问当前 Notion AI 对话时，才使用：

```bash
./venv/bin/notion-ai ask "继续刚才的话题" --continue_conversation --json
```

### 不接入系统鼠标事件

项目不把系统鼠标点击接入程序逻辑。CDP 内部的 `Input.dispatchMouseEvent` 只用于 renderer 内部文件选择器流程，不移动真实鼠标。

### 保持模块单一职责

根目录不保留 Python 入口文件。正式入口是统一 CLI `notion-ai <command>`。

`src/notion_ai_local_control/` 是真正的 Python 包。

## 项目结构

```text
.
├── README.md
├── PROJECT.md
├── docs/
├── pyproject.toml
└── src/notion_ai_local_control/
    ├── __init__.py
    ├── cli.py
    ├── ask_cdp.py
    └── beta_cdp_input.py
```

## 模块说明

### `src/notion_ai_local_control/cli.py`

统一 CLI 入口。当前命令：

- `ask`
- `ask-cdp`
- `beta-cdp-input`

### `src/notion_ai_local_control/ask_cdp.py`

用户级 CDP 提问流程：

1. 确保 CDP 端口可用，必要时重启 Notion。
2. 默认开始新对话，除非传入 `--continue_conversation`。
3. 可选上传附件。
4. 写入并提交问题。
5. 等待生成开始或完成。
6. 点击复制回复，并用 `pbpaste` 读取剪贴板。

### `src/notion_ai_local_control/beta_cdp_input.py`

CDP 底层能力：

- 列出和筛选 Notion CDP targets
- 查找 quick-search 输入框
- DOM 写入、清空、提交
- 点击 `开始新对话` / `拷贝回复`
- 文件上传
- 等待生成状态

## 常用命令

```bash
./venv/bin/notion-ai ask "1+1" --json
./venv/bin/notion-ai ask "继续刚才的话题" --continue_conversation --json
./venv/bin/notion-ai ask --from-stdin --assign_task --json
./venv/bin/notion-ai beta-cdp-input --status
```

## 验证

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai --help
./venv/bin/notion-ai ask --help
./venv/bin/notion-ai beta-cdp-input --status
./venv/bin/notion-ai ask "1+1" --json --timeout 60
```
