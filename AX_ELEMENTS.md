# Notion AI AX Element Notes

本文档记录 Notion AI 浮动窗口中已观察到的 macOS Accessibility 元素属性。

它的用途是辅助后续测试、修复和状态判断。坐标、尺寸会随窗口位置、缩放、
滚动位置变化，只作为样本参考；优先依赖 `role`、`roleDesc`、`description`、
`title`、`value`、`actions` 等稳定字段。

## 记录原则

- `AXDescription`、`AXTitle`、`AXValue` 都可能承载可匹配文字。
- 按钮通常用 `AXDescription` 暴露 label。
- 菜单项可能只有 `AXTitle`。
- 正文、用户消息、问候语通常是 `AXStaticText`，文字在 `AXValue`。
- `AXWebArea` 的 `roleDesc=HTML 内容` 代表 Notion 的 Web 内容容器，不等同于具体页面状态。
- 无 label 元素在 `search_element.py --list --include-empty` 中显示为 `<empty>`。

## 常用扫描命令

```bash
./venv/bin/python search_element.py --list --include-empty --step 1
./venv/bin/python search_element.py --list --region 0,35,70,75 --include-empty --step 1
./venv/bin/python search_element.py "在下乐意为你效劳。" --region 0,55,50,85 --step 1
./venv/bin/python search_element.py "拷贝回复" --region 0,35,70,75 --step 1
```

对于很小的正文文本，例如单字符 `2`，百分比 `step=1` 仍可能漏扫。
这类元素可能需要像素级局部扫描。

## 页面状态样本

### 初始/空白页

已观察特征：

- 有 `Notion AI face`
- 有问候语 `AXStaticText value=在下乐意为你效劳。`
- 有输入区 `AXTextArea`
- 有底部工具按钮：`提供背景信息`、`设置`、模型选择、`开始录音`
- 没有回复操作按钮：`拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`

注意：初始/空白页也可能出现 `提交 AI 消息`，所以不能只靠右下角按钮判断是否空白。

### 已完成回复页

已观察特征：

- 有回复操作按钮：`拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`
- 可能有用户消息操作按钮：`编辑消息`、`拷贝文本`
- AI 回复正文通常是多个 `AXStaticText`
- 右下角仍可能显示 `提交 AI 消息`，不能因此简单判为 `ready`

## 元素样本

### Web 内容容器

这是 Notion 页面内容的顶层 Web 容器。它说明窗口里有 HTML/Web 内容，
但不能单独用来区分初始页、生成中或完成页。

```text
role=AXWebArea
roleDesc=HTML 内容
description=Notion – The all-in-one workspace for your notes, tasks, wikis, and databases.
title=
value=
actions=AXShowMenu, AXScrollToVisible
```

### 浮动窗口

```text
role=AXWindow
roleDesc=标准窗口
description=
title=Notion - 命令搜索
value=
actions=AXRaise
```

### 初始页头像

```text
role=AXImage
roleDesc=图像
description=Notion AI face
title=
value=
sample_position=(92,564)
sample_size=50x50
actions=AXShowMenu, AXScrollToVisible
```

### 初始页问候语

该元素没有 `AXDescription` / `AXTitle`，目标搜索需要匹配 `AXValue`。

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=在下乐意为你效劳。
sample_position=(100,633)
sample_size=156x20
actions=AXShowMenu, AXScrollToVisible
```

### 用户提交的问题

示例：用户提交 `1+1` 后，问题文本暴露为 `AXStaticText`。

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=1+1
sample_position=(897,188)
sample_size=21x16
actions=AXShowMenu, AXScrollToVisible
```

### 用户消息操作按钮：编辑消息

```text
role=AXButton
roleDesc=按钮
description=编辑消息
title=
value=
sample_position=(884,216)
sample_size=24x24
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 用户消息操作按钮：拷贝文本

```text
role=AXButton
roleDesc=按钮
description=拷贝文本
title=
value=
sample_position=(908,216)
sample_size=24x24
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### AI 回复正文

示例：AI 回复 `2`。单字符正文尺寸很小，普通百分比网格扫描可能漏掉。

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=2
sample_position=(36,217)
sample_size=9x16
actions=AXShowMenu, AXScrollToVisible
```

较长回复正文也会暴露为多个 `AXStaticText`：

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=收到「1」。请问你想让我做什么？例如：
actions=AXShowMenu, AXScrollToVisible
```

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=请补充内容或贴上新闻/股票名称，我再按既定流程展开分析。
actions=AXShowMenu, AXScrollToVisible
```

### 回复操作按钮：拷贝回复

这是 `ask_and_copy_reply.py` 在完成态、贴住底部后要点击的目标按钮。
它通常出现在最新回复底部操作区。

```text
role=AXButton
roleDesc=按钮
description=拷贝回复
title=
value=
sample_position=(209,276)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 回复操作按钮：保存到私人页面

```text
role=AXButton
roleDesc=按钮
description=保存到私人页面
title=
value=
sample_position=(237,276)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 回复操作按钮：提供正面反馈

```text
role=AXButton
roleDesc=按钮
description=提供正面反馈
title=
value=
sample_position=(265,276)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 回复操作按钮：提供负面反馈

```text
role=AXButton
roleDesc=按钮
description=提供负面反馈
title=
value=
sample_position=(293,276)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 输入框

输入框本身通常没有 label。

```text
role=AXTextArea
roleDesc=文本输入区
description=
title=
value=
sample_position=(209,701)
sample_size=723x56
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 底部按钮：提供背景信息

```text
role=AXPopUpButton
roleDesc=弹出式按钮
description=提供背景信息
title=
value=
sample_position=(217,761)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 底部按钮：设置

```text
role=AXPopUpButton
roleDesc=弹出式按钮
description=设置
title=
value=
sample_position=(245,761)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 模型选择

模型选择按钮和其中的静态文本都可能被扫到。
当前模型检测以输入框区域中的 `AXPopUpButton` 为准，并要求该按钮内部
包含一个同名 `AXStaticText`，避免误把 `提供背景信息` / `设置` 当成模型。

```text
role=AXPopUpButton
roleDesc=弹出式按钮
description=Opus 4.7
title=
value=
sample_position=(759,761)
sample_size=101x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

```text
role=AXStaticText
roleDesc=文本
description=
title=
value=Opus 4.7
sample_position=(789,767)
sample_size=59x16
actions=AXShowMenu, AXScrollToVisible
```

另一个已观察样本：

```text
role=AXPopUpButton
roleDesc=弹出式按钮
description=GPT-5.5
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 底部按钮：开始录音

```text
role=AXButton
roleDesc=按钮
description=开始录音
title=
value=
sample_position=(864,761)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 状态按钮：提交 AI 消息

注意：初始/空白页和完成回复页都可能出现 `提交 AI 消息`。
因此它只能代表右下角 UI 按钮状态，不能单独判断页面状态。

```text
role=AXButton
roleDesc=按钮
description=提交 AI 消息
title=
value=
sample_position=(896,761)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 顶部按钮：返回

```text
role=AXButton
roleDesc=按钮
description=返回
title=
value=
sample_position=(205,124)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 顶部按钮：开始新对话

```text
role=AXButton
roleDesc=按钮
description=开始新对话
title=
value=
sample_position=(880,124)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

### 顶部按钮：关闭

```text
role=AXButton
roleDesc=按钮
description=关闭
title=
value=
sample_position=(908,124)
sample_size=28x28
actions=AXPress, AXShowMenu, AXScrollToVisible
```

## 状态判断启发

### 判断 new_conversation

当前对话框空状态统一叫 `new_conversation`。

先找到 `AXTextArea`，再用它的 y 坐标拆分两个逻辑区域：

- 对话框区域：`position.y < AXTextArea.position.y`
- 输入框区域：`position.y >= AXTextArea.position.y`

推荐规则：

- 对话框区域中 `AXStaticText / roleDesc=文本` 数量为 1
- 唯一文本为 `在下乐意为你效劳。`
- 不存在完成态按钮：`拷贝回复`、`保存到私人页面`、`提供正面反馈`、`提供负面反馈`

输入框里的草稿文本和模型名不计入对话框区域。
不要只依赖 `提交 AI 消息`，因为 new_conversation 状态里也可能出现它。

### 判断完成回复页

推荐信号：

- 存在 `拷贝回复`
- 或存在 `保存到私人页面`
- 或存在 `提供正面反馈`
- 或存在 `提供负面反馈`

完成回复页也可能同时出现 `提交 AI 消息`。

### 判断对话框状态

对话框状态当前按以下优先级判断：

1. `generating`：输入框区域出现 `停止 AI 消息`
2. `new_conversation`：对话框区域只有初始问候语，且没有完成态按钮
3. `complete`：回复已完成，出现完成态操作按钮，或内部检测到脱离底部的回到底部按钮

贴底状态不再作为 `conversation_state` 暴露，而是单独输出：

- `is_attach_to_bottom=true`：完成态操作按钮可见，且没有回到底部按钮
- `is_attach_to_bottom=false`：新对话、生成中、脱离底部或未知状态

### 判断输入框状态

输入框状态独立于对话框状态，当前有三种：

1. `generating`：输入框区域出现 `停止 AI 消息`
2. `typing`：未生成，且 `AXTextArea.value` 非空，或 `AXTextArea` 自身 bounds 内存在草稿 `AXStaticText`
3. `empty`：未生成，且没有草稿文本

注意：输入框里的草稿文本有时不会出现在 `AXTextArea.value`，
而是暴露成落在 `AXTextArea` 矩形范围内的 `AXStaticText / roleDesc=文本`。
模型名、模式标签、工具栏提示等不在 `AXTextArea` bounds 内，不算草稿。
`提交 AI 消息` 在 empty 和 typing 状态都可能出现，因此只作为辅助信息记录。

### 判断正文文本

用户消息和 AI 回复正文通常都是：

```text
role=AXStaticText
roleDesc=文本
value=<可见文本>
```

短文本，尤其是单字符，可能需要像素级局部扫描才能命中。
