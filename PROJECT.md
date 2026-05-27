# Notion AI Local Control Project

本文档面向后续接手本项目的 AI 或开发者，说明项目目标、文件结构、每个脚本职责、当前能力边界和开发原则。

## 项目目标

本项目用于让本地程序通过 macOS Accessibility API 操作 Notion 桌面端的 Notion AI 浮动窗口。

当前阶段不是 MCP 化阶段。项目重点是先把底层 UI 自动化能力做清晰、稳定、可测试：

- 打开和识别 Notion AI 窗口
- 扫描 Notion AI 窗口中的可访问元素
- 点击不依赖文本输入的按钮或弹出控件
- 读取输入框内容
- 探索无鼠标、无 DOM 注入的文本输入方案
- 粘贴 Notion AI 支持的附件：图片、PDF、CSV、Markdown、纯文本
- 等待并复制 Notion AI 回复

## 核心原则

### 不接入鼠标事件

项目原则是不把鼠标点击接入程序逻辑。

不要在业务脚本中使用：

- `CGEventCreateMouseEvent`
- `kCGEventLeftMouseDown`
- `kCGEventLeftMouseUp`
- 任何通过坐标模拟鼠标点击的方案

原因：项目希望依赖可解释、可控的 AX/键盘路径，而不是坐标点击。即使鼠标点击能让 Electron 输入框进入真实编辑状态，也不能作为程序实现路线。

### 不急于 MCP 化

当前代码还在验证 Notion AI UI 控制能力。不要新增 MCP server、HTTP API 或复杂流程层，除非底层能力已经足够稳定。

### 保持模块单一职责

每个模块只做一件事。公共 AX/Quartz/剪贴板能力放在 `src/notion_ai_local_control/notion_ax.py`，业务模块不要复制底层 helper。

根目录不保留 Python 入口文件。正式入口是统一 CLI `notion-ai <command>`；
未安装时可以通过 `PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.<module>` 调用包内模块。

### 附件类型边界

Notion AI 当前支持上传图片、PDF、CSV、Markdown、纯文本。本项目在粘贴附件前做本地扩展名校验，
避免把不支持的文件交给 UI 后再失败。

当前允许：

- 图片：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`、`.heic`、`.heif`
- 文档/数据：`.pdf`、`.csv`
- Markdown / 纯文本：`.md`、`.markdown`、`.txt`

其他文件类型应在调用前转换成上述格式，或者不要通过 `--attach-file` 传入。

## 项目结构

```text
.
├── README.md                    # 快速上手
├── PROJECT.md                   # 项目结构和维护原则
├── docs/                        # 深入说明和历史记录
├── pyproject.toml               # package 与 CLI 配置
├── src/notion_ai_local_control/  # 实现代码
├── .claude/settings.local.json
└── venv/                        # 本地虚拟环境，不属于项目逻辑
```

包内模块按职责分组：

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

`src/notion_ai_local_control/` 是真正的 Python 包。根目录只保留项目配置和文档。

## 统一 CLI

安装为 editable package 后，可以使用 `notion-ai` 统一入口：

```bash
./venv/bin/python -m pip install -e .
./venv/bin/notion-ai ask "1+1" --json
./venv/bin/notion-ai state --json
./venv/bin/notion-ai search "拷贝回复"
./venv/bin/notion-ai input --read
./venv/bin/notion-ai model --current
./venv/bin/notion-ai open --check
```

未安装时可以用模块方式调用：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask "1+1" --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli state --json
```

`notion-ai ask` 是 AI agent 和人工快速调用的正式入口。

## 文件说明

### `docs/AI_TOOL_USAGE.md`

给 OpenClaude、Claude Code、Codex 等 AI/编码代理读取的工具使用说明。

重点说明：

- 首选使用 `notion-ai ask`
- 如何使用 `--new_conversation` / `--timeout` / `--json`
- 如何解析 `success`、`text`、`conversation_state`、`is_attach_to_bottom`
- 哪些底层脚本不建议 AI 直接调用

### `docs/PROBLEM_SOLUTIONS.md`

记录项目关键难点、失败路径、误判原因和最终解决方案。

主要用于：

- 保存已经验证失败的路径，避免重复实验
- 记录真正稳定的判断信号
- 说明问题为什么难、最终突破点在哪里
- 给后续修复、测试和重构提供依据

当前已记录：

- 不使用鼠标、也不使用 `Shift+Tab` 的输入框真实写入方案
- `AXFocusedUIElement == AXTextArea` 的假焦点问题
- `AXInsertionPointLineNumber` / `AXSelectedText` 对真实插入点的判断价值
- `AXSelectedTextRange=(0,0)` 激活真实输入的解决方法

### `docs/AX_ELEMENTS.md`

记录 Notion AI 浮动窗口中已观察到的 AX 元素属性样本。

主要用于：

- 辅助状态判断设计
- 对比不同页面状态的稳定元素
- 记录按钮、正文、输入区、容器等元素的 `role` / `roleDesc` / `description` / `title` / `value` / `actions`
- 为后续测试和问题修复提供参考

坐标和尺寸只作为样本参考，不作为稳定判断依据。

### `src/notion_ai_local_control/notion_ax.py`

底层公共模块。封装所有共享的 macOS Accessibility / Quartz / 剪贴板能力。

主要职责：

- 查找正在运行的 Notion 应用
- 创建 Notion 的 AX application element
- 开启 Electron 必需的 `AXManualAccessibility`
- 识别 Notion AI 浮动窗口
- 读取 AX 属性：字符串、坐标、尺寸、动作
- 获取窗口 bounds
- 发送键盘事件
- 设置和读取系统剪贴板
- 执行 `AXPressAction`
- 读取当前焦点元素

重要导出：

- `get_ai_window_context()`
- `find_ai_window(app_element)`
- `enable_manual_accessibility(app_element)`
- `ax_str(...)`
- `ax_point(...)`
- `ax_size(...)`
- `element_info(...)`
- `element_at_position(...)`
- `focused_element(...)`
- `post_key(...)`
- `post_key_combo(...)`
- `post_open_ai_shortcut()`
- `press(element)`
- `set_clipboard_text(text)`
- `get_clipboard_text()`

注意：该文件不应包含鼠标事件 helper。

### `src/notion_ai_local_control/open_ai_window.py`

负责检查和打开 Notion AI 浮动窗口。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.open_ai_window
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.open_ai_window --check
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.open_ai_window --open
```

行为：

- `--check`：只检测窗口是否已打开
- `--open`：确保窗口打开；如果已打开，不再发送 `Cmd+Shift+J`
- 无参数：先检查，未打开则发送 `Cmd+Shift+J`

窗口识别依赖 `notion_ai_local_control.notion_ax.find_ai_window()`。
发送快捷键前会通过 `notion_ai_local_control.notion_ax.minimize_notion_main_windows()` 先最小化
Notion 主程序窗口，因为主程序窗口存在时可能导致 `Cmd+Shift+J` 无法唤出
AI 命令窗口。若主窗口处于 macOS 全屏模式，会先退出全屏再最小化。

### `src/notion_ai_local_control/search_element.py`

负责在 Notion AI 窗口中搜索和列出 AX 元素。

它有两类能力：

- 目标搜索：传入一个目标文字，寻找 `AXDescription`、`AXTitle` 或 `AXValue` 等于该文字的元素
- 列表扫描：使用 `--list` 列出当前窗口或指定区域里扫描到的唯一元素

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element "提交 AI 消息"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element "添加图片、PDF 或 CSV"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element "在下乐意为你效劳。"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element "提供背景信息" --timeout 5
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element "拷贝回复" --region 0,55,60,90 --timeout 5
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element --list
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element --list --include-empty
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element --list --region 25,45,75,92 --include-empty
```

目标搜索策略：

1. 网格扫描当前 AI 窗口 bounds，使用 `AXUIElementCopyElementAtPosition`
2. 匹配目标元素的 `AXDescription`、`AXTitle` 或 `AXValue`
3. 如果网格扫描找不到，再通过 Tab 导航读取焦点元素
4. 如果传入 `--region`，只在指定窗口百分比区域内做局部网格扫描；不会回退到 Tab 导航
5. 如果局部搜索同时传入 `--timeout`，会在超时时间内重复扫描该区域

列表扫描策略：

- `--list` 默认只列出有 `AXDescription` 或 `AXTitle` 的元素
- `--list --include-empty` 会额外列出无 label 元素，并显示为 `<empty>`
- `--list --region X1,Y1,X2,Y2` 只扫描窗口百分比区域
- `--step N` 控制扫描密度，数字越小越密，越慢也越稳

重要说明：

`search_element.py` 默认输出的是轻量调试字段，不是完整 AX 属性列表。

默认字段包括：

- `role`
- `roleDesc`
- `description`
- `title`
- `value`
- `position`
- `size`
- `actions`

这些字段适合日常定位按钮、菜单、正文、输入框和无 label 图标，输出短、速度快。

但一个 AX 元素实际可能支持更多属性，需要通过
`AXUIElementCopyAttributeNames(element)` 单独枚举。例如输入框还支持：

- `AXFocused`
- `AXSelectedText`
- `AXSelectedTextRange`
- `AXVisibleCharacterRange`
- `AXNumberOfCharacters`
- `AXInsertionPointLineNumber`

这些完整属性不默认展开，原因是：

- 每个元素属性很多，`--list` 输出会非常长
- 有些属性读取会失败、变慢，或返回 `AXUIElement` / `AXValue` 对象
- 日常搜索通常只需要轻量字段

因此，不要把 `--list` 的输出理解为“这个元素只有这些属性”。
遇到疑难问题时，应使用或新增完整属性查看能力。

`--list` 的 label 来源是：

- `AXDescription`
- `AXTitle`

如果元素没有 `AXDescription` / `AXTitle`，但有 `AXValue`，目标搜索仍然可以匹配它。
例如初始页问候语 `在下乐意为你效劳。` 是 `AXStaticText` 的 `AXValue`。

这样可以显示菜单项这类只有 `AXTitle` 的元素，例如：

- `添加图片、PDF 或 CSV`
- `提及页面或人员`

也可以配合 `--include-empty` 找无 label 的图标按钮，例如“回到底部”按钮。

### `src/notion_ai_local_control/click_element.py`

负责点击指定 AXDescription 对应的元素。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提供背景信息"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "拷贝回复" --timeout 30
```

流程：

1. 调用 `search_element.search_element(...)` 定位元素
2. 对元素执行 `AXPressAction`

已验证：

- `提供背景信息` 可被点击，并会打开菜单
- 菜单焦点可变成 `AXMenuItem`，例如 `添加图片、PDF 或 CSV`

不要用 `提交 AI 消息` 作为点击功能测试目标，除非输入框里已经有真实可提交文本。

### `src/notion_ai_local_control/input_box.py`

负责读取、设置和清空 Notion AI 输入框。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.input_box --read
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.input_box "你好"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.input_box --clear
```

当前实现：

- 定位输入框 `AXTextArea`
- 对输入框设置 `AXFocusedAttribute=True`
- 设置 `AXSelectedTextRange=(0,0)`，创建真实插入点
- 替换已有文本时，读取 `AXNumberOfCharacters`，再设置 `AXSelectedTextRange=(0, 字符数)`
- 写入系统剪贴板并发送 `Cmd+V`

当前限制：

- `--read` 可以读取输入框 `AXValue`
- 不能把 `AXFocusedUIElement == AXTextArea` 当作真实可输入；还要看 `AXInsertionPointLineNumber`
- 不能直接写 `AXValue`，那只是 AX 层假写入，不等于真实输入
- 不使用鼠标，不使用 `Shift+Tab`

当前稳定输入路径详见 `docs/PROBLEM_SOLUTIONS.md`。

### `src/notion_ai_local_control/model_selector.py`

负责读取和切换 Notion AI 当前使用的模型。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.model_selector --current
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.model_selector --list
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.model_selector "GPT-5.4"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.model_selector "自动"
```

当前实现：

- 模型识别逻辑集中在 `model_selector.current_model(...)`
- `check_ai_state.py` 复用 `model_selector.current_model(...)` 读取当前模型
- 模型按钮必须满足：
  - `role=AXPopUpButton`
  - 位于输入框 `AXTextArea` 下方
  - 内部包含同名 `AXStaticText`
- 打开模型菜单后，目标模型以 `AXMenuItem` 暴露
- 对目标 `AXMenuItem` 执行 `AXPress`
- 选择后重新读取当前模型验证

已观察到的模型项包括：

- `自动`
- `Sonnet 4.6`
- `Opus 4.6`
- `Opus 4.7`
- `Gemini 3.1 Pro`
- `GPT-5.2`
- `GPT-5.4`
- `GPT-5.5`
- `Kimi K2.6`
- `DeepSeek V4 Pro`

### `src/notion_ai_local_control/check_ai_state.py`

负责检测 Notion AI 当前状态。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.check_ai_state
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.check_ai_state --json
```

输出核心字段：

- `is_new_conversation`：对话框区域是否仍是新对话
- `is_attach_to_bottom`：完成态是否贴住底部
- `conversation_state`：对话框状态
- `input_state`：输入框状态
- `model`：当前模型名

`conversation_state` 取值：

- `new_conversation`：对话框区域只有初始问候语，且没有完成回复信号按钮
- `generating`：输入框区域出现 `停止 AI 消息`
- `complete`：AI 回复已完成
- `unknown`：无法判断为上述状态

`is_attach_to_bottom` 取值：

- `true`：完成态操作按钮可见，且没有出现无 label 的 32x32 回到底部按钮
- `false`：新对话、生成中、脱离底部或未知状态

`input_state` 取值：

- `generating`：输入框区域出现 `停止 AI 消息`
- `typing`：未生成，且 `AXTextArea.value` 非空，或 `AXTextArea` 自身 bounds 内存在草稿 `AXStaticText`
- `empty`：未生成，且没有草稿文本

检测方式：

- 先扫描窗口可见 AX 元素
- 找到底部 `AXTextArea`
- 按 `AXTextArea.position.y` 拆成两个逻辑区域：
  - 对话框区域：输入框上方，用于判断 new_conversation、回复文本、回复操作按钮
  - 输入框区域：输入框及下方工具栏，用于判断输入框、提交/停止按钮、工具按钮
- 对话框状态判断优先级：
  - `generating`：输入框区域出现 `停止 AI 消息`
  - `new_conversation`：对话框区域中 `AXStaticText / roleDesc=文本` 数量为 1，唯一文本为 `在下乐意为你效劳。`，且没有完成态操作按钮
  - `complete`：出现完成态操作按钮，或内部检测到脱离底部的回到底部按钮
- 贴底状态单独用 `is_attach_to_bottom` 输出；脱离底部时 `conversation_state=complete` 且 `is_attach_to_bottom=false`
- 当前模型通过输入框区域中的模型选择 `AXPopUpButton` 检测，并返回为 `model`
- 完成态操作按钮包括：`拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`
- 右下角输入按钮文字仍会作为 `input_button_desc` 原始信息返回，但不参与 `typing` 判断，也不主导对话框状态

当前注意事项：

- 有时输入框 `AXValue` 为空，但状态按钮仍可能显示 `提交 AI 消息`
- 因此右下角按钮只能代表 UI 按钮状态，不等同于“输入框一定有可提交文本”

### `src/notion_ai_local_control/ask_and_copy_reply.py`

目标是完成完整闭环：输入问题、提交、等待生成完成、必要时回到底部、
复制当前最新回复。

命令：

```bash
./venv/bin/notion-ai ask --from-stdin --json << 'NOTION_AI_AGENT_EOF'
[任意长代码 / 任意长提示词 / 短问题]
NOTION_AI_AGENT_EOF

./venv/bin/notion-ai ask --from-stdin --new_conversation --timeout 600 --json << 'NOTION_AI_AGENT_EOF'
[独立问题]
NOTION_AI_AGENT_EOF

./venv/bin/notion-ai ask --from-stdin --assign_task --json << 'NOTION_AI_AGENT_EOF'
[任意长任务]
NOTION_AI_AGENT_EOF
```

AI/自动化调用方无论问题简单还是复杂，都统一使用 `--from-stdin` 加单引号 heredoc，
避免 shell 提前解析引号、换行、代码块、`$()` 或路径空格，也不需要调用方先执行 `pbcopy`。
`--from-stdin` 只是问题来源；写入 Notion AI 输入框时，脚本内部仍会把文本写入系统剪贴板并用 Cmd+V 粘贴。
直接把问题作为命令行参数只适合人工临时调试；`--from-clipboard` 保留给人工调试和旧自动化兼容。

流程：

1. 使用 `input_box.py` 的真实插入点输入方法写入问题
2. 按 `提交 AI 消息`
3. 等待 `conversation_state=complete`
4. 如果 `is_attach_to_bottom=false`，先按 32x32 回到底部按钮
5. 按底部可见的 `拷贝回复`
6. 清空剪贴板后等待复制结果写入，并读取当前剪贴板内容作为回复

发布任务模式：

- 加 `--assign_task` 后，脚本在提交问题后只等待 `conversation_state=generating`
- 一旦确认 AI 开始生成，就返回成功，不等待完整回复、不回到底部、不复制回复
- 适合把长任务交给 Notion AI 后释放本地代理，避免本地代理长时间阻塞

### `src/notion_ai_local_control/watch_focus.py`

调试工具。持续监听当前焦点元素，并打印 AX 属性。

命令：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus "Google Chrome"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus com.apple.Safari
```

输出字段包括：

- `role`
- `roleDesc`
- `title`
- `desc`
- `value`
- `pos`
- `size`
- `actions`

其中：

- `title` 对应 `AXTitle`
- `desc` 对应 `AXDescription`

菜单项经常只出现在 `AXTitle`，例如 `添加图片、PDF 或 CSV`。

该文件是调试探针，可以保留独立实现，不必强制复用 `notion_ax.py`。

### `.claude/settings.local.json`

本地 Claude/Codex 权限配置，记录允许执行的命令。不是核心业务逻辑。

## 当前已验证能力

### 通过

- 打开 Notion AI 窗口：`open_ai_window.py --open`
- 检查 AI 窗口是否打开：`open_ai_window.py --check`
- 列出普通 AI 窗口元素：`search_element.py --list`
- 搜索按钮：`search_element.py "提供背景信息"`
- 点击 `提供背景信息` 并打开菜单：`click_element.py "提供背景信息"`
- 列出菜单态的 title-only 菜单项：`search_element.py --list`
- 读取输入框内容：`input_box.py --read`
- 无鼠标输入文本：`input_box.py "..."`
- 监听焦点元素并同时看到 `AXTitle` / `AXDescription`：`watch_focus.py`

### 未稳定或失败

- `提交 AI 消息` 的实际提交：不要作为通用点击测试目标，只应在明确已有真实可提交文本时使用
- 完整问答闭环：还需要继续验证提交、生成、复制最新回复的串联稳定性

## 常用调试流程

### 打开窗口并列出元素

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.open_ai_window --open
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element --list
```

### 测试“提供背景信息”菜单

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.click_element "提供背景信息"
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.search_element --list
```

预期能看到：

```text
添加图片、PDF 或 CSV
提及页面或人员
```

### 观察焦点元素

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.watch_focus
```

然后在 Notion AI 中用 Tab 或手动操作切换焦点，查看 `title=` 和 `desc=`。

## 后续优先级

1. 收紧 `find_ai_window()` 的窗口识别，避免把非 AI 的 Notion 搜索/筛选窗口误识别为 AI 窗口。
2. 研究无鼠标文本输入方案。
3. 改善 `search_element` 对菜单/弹窗的扫描范围和元素展示。
4. 在输入能力稳定后，再考虑封装完整流程函数。
5. 完整流程稳定后，才考虑 MCP 化。
