# Session Handoff

## 本次改动概要

对 `src/notion_ai_local_control/tab_bar_cdp.py` 做了大幅扩展，核心改动是引入 **conversation token** 作为对话标识，替代用户层的 CDP target id。

## 新增功能

### conversation token 机制

- `extract_conversation_token(url)` — 从 Notion AI URL 的 `t` 查询参数提取 token
- `find_target_by_token(token, port)` — 按 token 查找 AI target
- `_resolve_or_create_ai_target(token=)` — 用户层入口；有 token 继续对话，无 token 自动新建 tab
- `target_summary()` 输出新增 `conversationToken` 字段

### 命令行改动

| 命令 | 说明 |
|------|------|
| `app ask` | **只提交问题，立刻返回 token**；无 `--token` 时自动新建对话并等 token 出现 |
| `app ask-and-reply` | **完整流程**：提交 + 等生成完 + 复制回复；无 `--token` 时自动新建对话 |
| `app ask --model "GPT-5.5"` | 提交前通过 Notion 模型菜单选择指定模型，按可见 label 匹配；不传则沿用当前模型 |
| `app ask --model A B C "问题"` | 创建多个新对话，用多个模型问同一个问题 |
| `app get-reply --token XXX` | 等生成完毕，复制回复 |
| `app get-reply --token A B C` | 按多个 token 逐个获取回复，适合多模型 fan-out 后收结果 |
| `app get-reply --all` | 查看所有 AI tab 状态，idle 的自动复制回复 |
| `app status --token XXX` | 查看单个对话生成状态 |
| `app status --all` | 查看所有 AI tab 生成状态 |
| `app restore-conversation --token XXX` | 通过 token 恢复对话（新建 tab + Page.navigate） |
| `app close-conversation --token XXX` | 通过 token 关闭对话 |

### CLI 非JSON输出优先打印 token

- `ask` 非JSON输出：打印 conversation token，方便后续 `get-reply/status/close`
- `restore-conversation` 非JSON输出：同上

## 已验证的功能

- `ask` 无 token 自动新建对话、提交问题、返回 token ✅
- `ask --model` 提交前切换模型 ✅
- `ask` 不传 `--model` 时沿用当前模型，并在返回中包含实际模型 ✅
- `ask --token` 提交问题 ✅
- `ask-and-reply --token` 完整流程 ✅
- `get-reply --token` 等待并复制回复 ✅
- `get-reply --token A B C` 多 token 获取回复 ✅
- `get-reply --all` 查看所有 tab 状态并复制 ✅
- `status --all` 显示所有 tab ✅
- `status --token` 显示单个 tab ✅
- `close-conversation --token` ✅
- `restore-conversation --token` 恢复已关闭的对话 ✅（Tab Bar 新建 tab + CDP Page.navigate）
- 并行 `ask` 两个 token 提交 ✅（同时发出，0.05s 内返回）
- `get-reply --all` 扫一遍所有 tab，idle 的复制回复 ✅
- 多模型 fan-out：`GPT-5.5` + `Opus 4.8` 可创建两个对话并返回各自 token ✅
- `get-reply` 多 token 路径会先点击 Notion Tab Bar 对应 tab，再 CDP activate，避免后台 tab DOM 状态误判 ✅

## 已知问题 / 待改进

### 并行生成时 Notion AI 可能长时间卡在 generating

两个 tab 同时 `ask` 提交后，Notion AI 在处理并行请求时可能出现 `hasStop=True, copyReplyCount=0` 持续数分钟的情况。已验证 foreground 步骤会点击 Notion 自己的 Tab Bar 并调用 `/json/activate/<targetId>`；如果仍卡住，更像是该会话自身仍处于 Notion 生成状态。`get-reply --token` 命令的 `--timeout` 可以控制等待时长；`get-reply --all` 只扫一遍，不等待 generating tab。

### 空白新对话的 token 初始为 null

空白新 tab URL 是 `app.notion.com/ai`，没有 `t` 参数。只有发送第一条消息后 URL 才变成 `chat?t=xxx`，token 才出现。因此用户层入口不再暴露 `new-conversation`；`app ask` 无 `--token` 时会自动新建 tab、提交问题，并等待 token 出现后返回。

### `get-reply --all` 剪贴板串扰风险

`get-reply --all` / 多 token 获取逐个 tab 复制回复时，每个 tab 的"拷贝回复"按钮写入同一个系统剪贴板，目前是串行复制的（逐个 copy + pbpaste），不会串扰。但如果外部程序同时读写剪贴板可能冲突。

### `Target.createTarget` 不支持

Notion Electron 返回 `"Not supported"`，无法通过 CDP 直接创建新页面。恢复对话只能走 Tab Bar 新建 tab + Page.navigate 的路线。

## 文件变更

- `src/notion_ai_local_control/tab_bar_cdp.py` — 主要改动文件
- `src/notion_ai_local_control/cli.py` — 顶层帮助示例更新
- `README.md` / `PROJECT.md` — app token、model、get-reply 示例更新
- `docs/SESSION_HANDOFF.md` — 本文件

## 架构说明

```
tab_bar_cdp.py 结构:

工具函数:
  extract_conversation_token(url)   — 从 URL 提取 t 参数
  find_target_by_token(token, port)  — 按 token 查找 target
  _resolve_ai_target(target_id=, token=) — 统一定位
  _conversation_url(token, space_id=, port=) — 构造对话 URL
  foreground_target(target, port) — 点击 Notion Tab Bar + CDP activate

核心流程:
  ask_main_app_target()        — 提交问题，立刻返回
  ask_and_reply_main_app_target() — 提交 + 等生成 + 复制回复（完整流程）
  reply_main_app_target()       — 等 + 复制回复
  reply_all_main_app()          — 遍历所有 tab，idle 则复制
  get_replies_main_app()        — 多 token 串行收集回复
  restore_conversation()        — 新建 tab + Page.navigate 恢复对话

底层能力（未改动）:
  set_main_app_text_and_submit()  — DOM 写入 + 点击提交
  wait_main_app_generation_finished() — 等生成完成
  copy_main_app_latest_reply()    — 点击"拷贝回复" + pbpaste
```
