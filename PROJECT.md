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

### 保持脚本单一职责

每个脚本只做一件事。公共 AX/Quartz/剪贴板能力放在 `notion_ax.py`，业务脚本不要复制底层 helper。

## 项目结构

```text
.
├── PROJECT.md
├── AX_ELEMENTS.md
├── notion_ax.py
├── open_ai_window.py
├── search_element.py
├── click_element.py
├── type_text.py
├── check_ai_state.py
├── copy_reply.py
├── watch_focus.py
├── .claude/settings.local.json
└── venv/
```

`venv/` 是本地 Python 虚拟环境，不属于项目逻辑。

## 文件说明

### `AX_ELEMENTS.md`

记录 Notion AI 浮动窗口中已观察到的 AX 元素属性样本。

主要用于：

- 辅助状态判断设计
- 对比不同页面状态的稳定元素
- 记录按钮、正文、输入区、容器等元素的 `role` / `roleDesc` / `description` / `title` / `value` / `actions`
- 为后续测试和问题修复提供参考

坐标和尺寸只作为样本参考，不作为稳定判断依据。

### `notion_ax.py`

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

### `open_ai_window.py`

负责检查和打开 Notion AI 浮动窗口。

命令：

```bash
./venv/bin/python open_ai_window.py
./venv/bin/python open_ai_window.py --check
./venv/bin/python open_ai_window.py --open
```

行为：

- `--check`：只检测窗口是否已打开
- `--open`：确保窗口打开；如果已打开，不再发送 `Cmd+Shift+J`
- 无参数：先检查，未打开则发送 `Cmd+Shift+J`

窗口识别依赖 `notion_ax.find_ai_window()`。

### `search_element.py`

负责在 Notion AI 窗口中搜索和列出 AX 元素。

它有两类能力：

- 目标搜索：传入一个目标文字，寻找 `AXDescription`、`AXTitle` 或 `AXValue` 等于该文字的元素
- 列表扫描：使用 `--list` 列出当前窗口或指定区域里扫描到的唯一元素

命令：

```bash
./venv/bin/python search_element.py "提交 AI 消息"
./venv/bin/python search_element.py "添加图片、PDF 或 CSV"
./venv/bin/python search_element.py "在下乐意为你效劳。"
./venv/bin/python search_element.py "提供背景信息" --timeout 5
./venv/bin/python search_element.py "拷贝回复" --region 0,55,60,90 --timeout 5
./venv/bin/python search_element.py --list
./venv/bin/python search_element.py --list --include-empty
./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty
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

`--list` 的 label 来源是：

- `AXDescription`
- `AXTitle`

如果元素没有 `AXDescription` / `AXTitle`，但有 `AXValue`，目标搜索仍然可以匹配它。
例如初始页问候语 `在下乐意为你效劳。` 是 `AXStaticText` 的 `AXValue`。

这样可以显示菜单项这类只有 `AXTitle` 的元素，例如：

- `添加图片、PDF 或 CSV`
- `提及页面或人员`

也可以配合 `--include-empty` 找无 label 的图标按钮，例如“回到底部”按钮。

### `click_element.py`

负责点击指定 AXDescription 对应的元素。

命令：

```bash
./venv/bin/python click_element.py "提供背景信息"
./venv/bin/python click_element.py "拷贝回复" --timeout 30
```

流程：

1. 调用 `search_element.search_element(...)` 定位元素
2. 对元素执行 `AXPressAction`

已验证：

- `提供背景信息` 可被点击，并会打开菜单
- 菜单焦点可变成 `AXMenuItem`，例如 `添加图片、PDF 或 CSV`

不要用 `提交 AI 消息` 作为点击功能测试目标，除非输入框里已经有真实可提交文本。

### `type_text.py`

负责读取、设置和清空 Notion AI 输入框。

命令：

```bash
./venv/bin/python type_text.py --read
./venv/bin/python type_text.py "你好"
./venv/bin/python type_text.py --clear
```

当前实现：

- 定位输入框 `AXTextArea`
- 对输入框设置 `AXFocusedAttribute=True`
- 写入系统剪贴板
- 发送 `Cmd+V`
- 读取 `AXValue` 验证结果

当前限制：

- `--read` 可以读取输入框 `AXValue`
- 文本写入在当前 Notion/Electron 环境下不稳定或失败
- 已测试过 `AXValue`、`AXSelectedText`、`AXSelectedTextRange`、`AXReplaceRangeWithText` 等纯 AX 写入路径，返回值可能成功但实际内容不变
- 鼠标点击输入框后再 `Cmd+V` 曾被实验证实可行，但违反项目原则，不能接入程序

后续研究重点：寻找不依赖鼠标事件的真实编辑上下文激活方法。

### `check_ai_state.py`

负责检测 Notion AI 当前状态。

命令：

```bash
./venv/bin/python check_ai_state.py
./venv/bin/python check_ai_state.py --json
```

输出核心字段：

- `conversation_state`：对话框状态
- `input_state`：输入框状态
- `model`：当前模型名

`conversation_state` 取值：

- `new_conversation`：对话框区域只有初始问候语，且没有完成回复信号按钮
- `generating`：输入框区域出现 `停止 AI 消息`
- `detach_to_bottom`：对话框区域出现无 label 的 32x32 回到底部按钮
- `attach_to_bottom`：未生成、没有回到底部按钮，且出现完成态操作按钮
- `unknown`：无法判断为上述状态

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
  - `detach_to_bottom`：对话框区域出现无 label 的 32x32 回到底部按钮
  - `attach_to_bottom`：没有生成、没有回到底部按钮，且出现完成态操作按钮
- 当前模型通过输入框区域中的模型选择 `AXPopUpButton` 检测，并返回为 `model`
- 完成态操作按钮包括：`拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`
- 右下角输入按钮文字仍会作为 `input_button_desc` 原始信息返回，但不参与 `typing` 判断，也不主导对话框状态

当前注意事项：

- 有时输入框 `AXValue` 为空，但状态按钮仍可能显示 `提交 AI 消息`
- 因此右下角按钮只能代表 UI 按钮状态，不等同于“输入框一定有可提交文本”

### `copy_reply.py`

目标是等待并复制 Notion AI 最新回复；当前实现只会复制搜索到的
`拷贝回复` 按钮对应内容，尚不能保证一定是最新回复。

命令：

```bash
./venv/bin/python copy_reply.py
./venv/bin/python copy_reply.py --timeout 60
```

流程：

1. 搜索 `拷贝回复`
2. 找到后执行 `AXPressAction`
3. 从系统剪贴板读取回复文本

当前限制：

- 只有当 Notion AI 已经完成生成，并且 UI 中出现 `拷贝回复` 时才可用
- 当前搜索策略可能复制历史回复，不能保证命中最新回复
- 当前输入发送能力未稳定前，无法完整验证“输入 -> 生成 -> 复制”的闭环

### `watch_focus.py`

调试工具。持续监听当前焦点元素，并打印 AX 属性。

命令：

```bash
./venv/bin/python watch_focus.py
./venv/bin/python watch_focus.py "Google Chrome"
./venv/bin/python watch_focus.py com.apple.Safari
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
- 读取输入框内容：`type_text.py --read`
- 监听焦点元素并同时看到 `AXTitle` / `AXDescription`：`watch_focus.py`

### 未稳定或失败

- 无鼠标输入文本：`type_text.py "..."` 当前不能可靠写入 Notion AI 输入框
- `提交 AI 消息` 的实际提交：依赖真实输入文本，不能作为通用点击测试
- 完整问答闭环：受输入写入问题阻塞

## 常用调试流程

### 打开窗口并列出元素

```bash
./venv/bin/python open_ai_window.py --open
./venv/bin/python search_element.py --list
```

### 测试“提供背景信息”菜单

```bash
./venv/bin/python click_element.py "提供背景信息"
./venv/bin/python search_element.py --list
```

预期能看到：

```text
添加图片、PDF 或 CSV
提及页面或人员
```

### 观察焦点元素

```bash
./venv/bin/python watch_focus.py
```

然后在 Notion AI 中用 Tab 或手动操作切换焦点，查看 `title=` 和 `desc=`。

## 后续优先级

1. 收紧 `find_ai_window()` 的窗口识别，避免把非 AI 的 Notion 搜索/筛选窗口误识别为 AI 窗口。
2. 研究无鼠标文本输入方案。
3. 改善 `search_element` 对菜单/弹窗的扫描范围和元素展示。
4. 在输入能力稳定后，再考虑封装完整流程函数。
5. 完整流程稳定后，才考虑 MCP 化。
