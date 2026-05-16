# Codex Handoff

本文档给新的 Codex 窗口使用，用于快速接上当前项目状态。

## 当前项目路径

```text
/Users/fanlu/Library/Mobile Documents/com~apple~CloudDocs/code-storage/20260515-notion-ai-local-control
```

## 本地 Git 状态

本地已经初始化 git 仓库，分支是 `main`。

已有本地提交：

```text
3a901be Initial Notion AI local control scripts
5dd6485 Add region scanning to element search
```

当前最后一次提交包含 `search_element.py` 的区域扫描能力。

GitHub 仓库：

```text
https://github.com/flu16/20260515-notion-ai-local-control
```

注意：

- 本地 commit 是完整的，项目不会因为后续改动丢失当前版本。
- GitHub 上传曾尝试过，但只通过 GitHub connector 上传了部分文件：
  - `.gitignore`
  - `notion_ax.py`
  - `open_ai_window.py`
- 不要继续使用用户曾在聊天里发出的 GitHub token。那个 token 已暴露，建议用户之后撤销。

## 重要原则

### 不接入鼠标事件

用户明确要求：程序里不能接入鼠标点击。

不要使用：

- `CGEventCreateMouseEvent`
- `kCGEventLeftMouseDown`
- `kCGEventLeftMouseUp`
- 任何坐标鼠标点击方案

所有自动化应优先走：

- macOS Accessibility API
- AXPressAction
- 键盘事件
- 剪贴板
- AX 坐标命中扫描

### 暂时不 MCP 化

当前阶段不是 MCP server 阶段。目标是先把 Notion AI UI 控制能力做干净、稳定、可测试。

## 文件概览

详细项目结构见 `PROJECT.md`。

核心文件：

- `notion_ax.py`：公共 AX/Quartz/剪贴板 helper
- `open_ai_window.py`：打开/检测 Notion AI 窗口
- `search_element.py`：搜索元素、列元素、区域扫描
- `click_element.py`：对指定元素执行 AXPress
- `type_text.py`：读/写输入框，目前写入不稳定
- `check_ai_state.py`：扫描右下角状态按钮
- `copy_reply.py`：复制回复，当前策略还需要改进
- `watch_focus.py`：监听焦点 AX 属性
- `PROJECT.md`：项目说明文档

## 已完成/可用能力

### 打开窗口

```bash
./venv/bin/python open_ai_window.py --open
./venv/bin/python open_ai_window.py --check
```

可以打开 Notion AI 浮动窗口并检测窗口位置。

### 列出可见元素

```bash
./venv/bin/python search_element.py --list
```

会列出当前可见区域里有 `AXDescription` 或 `AXTitle` 的元素。

### 区域扫描

新增能力：

```bash
./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty --step 1
```

参数说明：

- `--region X1,Y1,X2,Y2`：扫描窗口百分比区域
- `--include-empty`：列出没有 `AXDescription` / `AXTitle` 的元素
- `--step N`：扫描步长百分比

这个功能用于找没有 label 的图标按钮，比如“回到底部”按钮。

### 点击“提供背景信息”

已验证：

```bash
./venv/bin/python click_element.py "提供背景信息"
```

可打开菜单。打开后：

```bash
./venv/bin/python search_element.py --list
```

可看到菜单项：

- `添加图片、PDF 或 CSV`
- `提及页面或人员`

这些菜单项主要暴露在 `AXTitle`。

### 复制回复基础功能

当 `拷贝回复` 当前可见时：

```bash
./venv/bin/python copy_reply.py --timeout 20
```

曾成功复制到剪贴板。

但当前 `copy_reply.py` 的策略仍不够可靠，因为它可能复制历史回复，不能保证最新回复。

## 关键实验结果

### 1. 文本输入未打通

`type_text.py --read` 可以读取输入框。

但 `type_text.py "..."` 在当前 Notion/Electron 环境下无法可靠写入。

已测试失败或不可靠的方式：

- `AXFocusedAttribute=True` 后 `Cmd+V`
- `AXValue`
- `AXSelectedText`
- `AXSelectedTextRange`
- `AXReplaceRangeWithText`
- `AXFocused=False`

鼠标点击输入框后再 `Cmd+V` 曾实验成功，但违反用户原则，不能接入。

### 2. Shift+Tab 锚点策略有状态问题

曾验证：

从底部 `提供背景信息` 开始 `Shift+Tab`，在某些状态下第一个遇到的 `拷贝回复` 是最新回复，并能复制到：

```text
最后回复内容
```

但当真实焦点仍在文本框时，会出现“AX 焦点在按钮，真实编辑焦点仍在文本框”的双焦点状态。

这种状态下按 `Shift+Tab` 会在 Notion AI 的模式之间循环切换，例如：

- 计划模式
- 询问模式
- 默认模式

不会沿着按钮焦点链向上移动。

所以 Shift+Tab 策略不能作为主策略。

### 3. “回到底部”按钮可用

当回复很长，页面中下方会出现一个无 label 的圆形向下按钮。

watch_focus 观察过：

```text
role=AXButton
title=
desc=
value=
pos=741,690
size=32x32
actions=AXPress,AXShowMenu,AXScrollToVisible
```

区域扫描可以找到类似按钮：

```text
role=AXButton
description=''
title=''
position=(421,574)
size=(32,32)
actions=['AXPress', 'AXShowMenu', 'AXScrollToVisible']
```

直接对扫描到的 AXButton 对象执行：

```python
press(button)
```

可以让页面滚到回复底部附近。

重要：不要用按钮中心点重新 `element_at_position` 后再 press，因为中心点可能命中正文 `AXStaticText`。必须保存扫描得到的 `AXButton` 对象并直接 press。

### 4. 回到底部后不一定能直接看到“拷贝回复”

press 回到底部按钮后，曾看到底部操作区：

```text
保存到私人页面
提供正面反馈
提供负面反馈
```

但 `拷贝回复` 未必出现在 `--list` 中。

观察：回到底部按钮的 y 位置和底部操作按钮组 y 位置很接近。

下一步需要围绕这个 y 区间扩大/加密扫描，确认 `拷贝回复` 是否在附近，只是被漏扫、隐藏或 label 不同。

## 当前最重要的下一步

建议继续围绕“复制最新回复”推进，而不是先解决文本输入。

推荐下一步实验：

1. 使用区域扫描找到回到底部按钮。
2. 直接 `press(button)`。
3. 等待 0.8-1.2 秒。
4. 在底部操作区附近做高密度区域扫描：

```bash
./venv/bin/python search_element.py --list --region 0,55,50,85 --include-empty --step 1
```

也可以试：

```bash
./venv/bin/python search_element.py --list --region 0,50,60,90 --include-empty --step 1
```

目标是找：

- `拷贝回复`
- `拷贝文本`
- 或没有 label 但 size/position 像复制按钮的 AXButton

如果能稳定找到复制按钮，就把 `copy_reply.py` 改成：

```text
1. 如果回到底部按钮存在，press 它
2. 扫描底部操作区
3. 找最新回复的复制按钮
4. AXPress
5. 读取剪贴板
```

## 常用命令

打开窗口：

```bash
./venv/bin/python open_ai_window.py --open
```

列全窗口可见元素：

```bash
./venv/bin/python search_element.py --list
```

区域扫描并显示空元素：

```bash
./venv/bin/python search_element.py --list --region 25,45,75,92 --include-empty --step 1
```

测试提供背景信息菜单：

```bash
./venv/bin/python click_element.py "提供背景信息"
./venv/bin/python search_element.py --list
```

监听焦点：

```bash
./venv/bin/python watch_focus.py
```

语法检查：

```bash
./venv/bin/python -m py_compile notion_ax.py open_ai_window.py search_element.py click_element.py type_text.py check_ai_state.py copy_reply.py watch_focus.py
```

## 注意事项

- 当前工作目录已经改名。旧目录 `20260515-MCP-talk-with-notion-AI` 不再是当前项目。
- 新 Codex 窗口请优先读取 `PROJECT.md` 和本文件。
- 不要恢复鼠标点击方案。
- 不要把 GitHub token 写进 shell 命令、git remote、文件或日志。
- 如果要 push GitHub，建议用户先用 `gh auth login` 或配置 SSH。
