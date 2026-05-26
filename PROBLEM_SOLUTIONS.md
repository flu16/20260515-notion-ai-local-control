# 难点与解决方案记录

这个文件记录项目里遇到的关键难点、误判原因、验证过程和最终解决方案。

用途：

- 避免重复踩坑。
- 保存已经验证失败的路径。
- 记录真正稳定的判断信号。
- 给后续修复、测试和重构提供依据。

## 1. 不使用鼠标、也不使用 Shift+Tab 的输入框写入

### 问题

目标是在 Notion AI 输入框中输入文本，同时满足：

- 不使用鼠标点击。
- 不依赖 `Shift+Tab` 焦点链。
- 不把 `AXValue` 假写入当作真实输入。
- 输入后 Notion/Electron 真实编辑器必须能接收文本。

### 曾经误判的现象

最初以为只要当前焦点是输入框，就可以粘贴：

```text
AXFocusedUIElement.role = AXTextArea
AXFocusedUIElement.roleDesc = 文本输入区
```

但实测发现这只是 AX 层焦点，并不等于 Electron 内部编辑器已经激活。

还观察到 `AXValue` 可以被设置并读回，但这也是假阳性：

```text
AXUIElementSetAttributeValue(text_area, AXValue, "text") -> 返回 0
随后读取 AXValue -> "text"
```

这不代表真实输入框里有可提交内容，可能只是改了 AX 层暴露值或灰色提示相关状态。

### 失败路径

以下路径都不能稳定触发真实输入：

```text
AXFocusedAttribute=True -> Cmd+V
AXFocusedAttribute=True -> AXPress -> Cmd+V
AXScrollToVisible -> AXPress -> AXFocusedAttribute=True -> Cmd+V
AXShowMenu -> Escape -> AXPress -> Cmd+V
CGEventPostToPid(Cmd+V)
AXUIElementPostKeyboardEvent(...)
CGEventKeyboardSetUnicodeString(...)
菜单栏 编辑 -> 粘贴
AppleScript / System Events keystroke
直接设置 AXValue
```

这些路径失败时，`AXFocusedUIElement` 仍可能显示为输入框，因此不能只靠它判断。

### 真正的关键差异

输入框存在两种状态。

假焦点、未激活真实输入：

```text
AXFocusedUIElement = AXTextArea / 文本输入区
AXInsertionPointLineNumber = 9223372036854775807
AXSelectedText 读取失败，错误码 -25212
Cmd+V 不能进入真实输入框
```

真焦点、真实可输入：

```text
AXFocusedUIElement = AXTextArea / 文本输入区
AXInsertionPointLineNumber = 0
AXSelectedText = ""
Cmd+V 可以进入真实输入框
```

因此，`AXInsertionPointLineNumber` 和 `AXSelectedText` 才是判断真实编辑器是否激活的关键辅助信号。

### 最终有效路径

从冷状态复测成功的路径：

```text
1. 找到输入框 AXTextArea。
2. 设置 AXFocusedAttribute=True。
3. 设置 AXSelectedTextRange = location:0 length:0。
4. 确认 AXInsertionPointLineNumber 从 9223372036854775807 变成 0。
5. 确认 AXSelectedText 可以读取，且值为 ""。
6. 写入系统剪贴板。
7. 发送 Cmd+V。
8. 读取 AXValue 验证输入框真实内容。
```

核心代码概念：

```python
range_value = AXValueCreate(kAXValueCFRangeType, NSRange(0, 0))
AXUIElementSetAttributeValue(text_area, "AXSelectedTextRange", range_value)
```

### 冷状态复测记录

一次干净复测的结果：

```text
focused_after_escape:
  role=AXWebArea
  roleDesc=HTML 内容

line_before_setup:
  AXInsertionPointLineNumber = 9223372036854775807

selected_before_setup:
  AXSelectedText 读取失败，错误码 -25212

执行：
  AXFocusedAttribute=True
  AXSelectedTextRange=(0,0)
  Cmd+V

line_after_range:
  AXInsertionPointLineNumber = 0

selected_after_range:
  AXSelectedText = ""

actual:
  RANGE_RETEST_OK

success:
  True
```

### 结论

真正的解决点不是 `AXPress`，也不是普通 AX 焦点，而是设置 `AXSelectedTextRange` 来创建真实插入点。

后续 `input_box.py` 的输入函数应以这个路径为主：

```text
AXFocus -> AXSelectedTextRange=(0,0) -> Cmd+V -> AXValue 验证
```

实际写入代码中的补充细节：

```text
替换已有文本时，不使用 Cmd+A。
原因：Cmd+A 可能破坏刚创建的真实插入点。

正确做法：
1. 读取 AXNumberOfCharacters。
2. 设置 AXSelectedTextRange=(0, 字符数)。
3. Cmd+V 粘贴目标文本，直接替换选区。
```

`Shift+Tab` 路径已从 `input_box.py` 主实现中移除，只作为历史实验结论保留在记录里。

## 长文本粘贴与 Notion 富文本规范化

### 问题

`notion-ai ask --from-clipboard --new_conversation --json` 在提交一个 6000 字左右、
包含 shell 代码、文件名、引号和 Markdown-like 标记的长问题时，曾经失败返回：

```json
{
  "success": false,
  "step": "input",
  "error": "粘贴验证不匹配"
}
```

一开始看起来像是 `--from-clipboard` 取剪贴板失败，或长文本没有粘进 Notion AI 输入框。
实际读取输入框后发现，问题文本已经基本完整进入输入框。

### 观察到的现象

剪贴板原文片段：

```text
=== run-task.sh ===
```

粘贴进 Notion 后，通过 AXValue 读回的片段变成：

```text
===
run-task.sh
===
```

类似地，正文中的 `run-task.sh` 也可能因为 Notion 自动识别为链接或富文本 token，
在 AXValue 中被拆出额外换行。

一次复现数据：

```text
expected_len = 6075
actual_len   = 6079
equal        = False
first_diff   = 139
```

也就是说，真实问题已经粘贴成功，但 `input_box.py` 原来的严格校验：

```python
actual == text
```

把 Notion/Electron 富文本编辑器产生的轻微 AXValue 规范化误判成失败。

### 根因

Notion 输入框不是纯文本框，而是富文本编辑器。Cmd+V 后，编辑器可能把部分内容自动识别为：

- 链接文本
- 文件名样式 token
- Markdown-like 标题或分隔片段
- 内部富文本节点

这些富文本节点在可见内容上仍然正确，但 Accessibility 暴露的 `AXValue` 会插入额外换行或
做轻微文本规范化。因此，`AXValue` 不能作为长文本粘贴的字节级相等依据。

### 解决方法

当前已经移除粘贴后的 AXValue 内容验证，不再用逐字符一致或长度近似来拦截输入流程。
保留的重点是通过双粘贴覆盖策略减少旧输入框残留。

当前策略：

```text
1. 粘贴前读取输入框现有 AXValue，记为 before_text。
2. 先设置 AXSelectedTextRange=(0,0)，把真实插入点放到输入框开头。
3. 先 Cmd+V 粘贴一次新问题，用于唤醒 Electron 富文本编辑器的真实键盘接管。
4. 无论 before_text 是否为空，都再 Cmd+A 全选当前输入框内容。
5. 再 Cmd+V 粘贴同一个新问题，用第二次粘贴覆盖所有旧内容和第一次临时内容。
```

后续复现发现，Notion 对 Markdown-like 代码块做富文本格式化后，
长度可能只差 2 个字符，但 `SequenceMatcher` similarity 会下降到约 `0.916`。
因此不应把 AXValue 读回内容作为长文本成功与否的核心门槛。

### 结论

对 Notion AI 输入框，校验目标应是“用户问题是否语义完整进入编辑器”，
而不是 AXValue 与剪贴板文本逐字符相同。

最危险的问题是输入框已经有旧文本，但自动化没有发现，最终把旧文本和新问题一起提交。
因此实现上用“先粘贴唤醒编辑器，再全选覆盖粘贴”的笨办法，
比直接 Delete 清空更适配 Notion 富文本输入框。

## ask_and_copy_reply 的完成态复制

### 问题

`notion-ai ask` 的流程里，输入问题时会先把问题写入系统剪贴板，
然后通过 Cmd+V 粘贴到 Notion AI 输入框。

因此在提交之后、复制回复之前，剪贴板里很可能仍然是刚刚提交的问题。

如果按下 `拷贝回复` 后立刻读取剪贴板，可能读到旧值，看起来就像复制到了用户问题，
而不是 AI 回复。

### 观察到的现象

失败表现：

```text
输入问题：请只回答：苹果
按下：拷贝回复
立刻读取剪贴板：请只回答：苹果
稍后剪贴板实际变成：苹果
```

也就是说，`拷贝回复` 的 AXPress 已经成功，但剪贴板更新存在短暂延迟。

### 解决方法

当前已经移除“剪贴板必须变化”的验证逻辑。

按下 `拷贝回复` 前先清空剪贴板，然后等待当前剪贴板变为非空并读取。
如果仍为空，返回失败。

### 相关状态判断

生成过程中 `拷贝回复` 按钮可能短暂出现，不能作为完成信号直接点击。
正确顺序是：

```text
1. 提交问题。
2. 等待 conversation_state 进入 generating。
3. 等待 conversation_state 稳定到 complete。
4. 如果 is_attach_to_bottom=false，先按无 label 的 32x32 回到底部按钮。
5. 等到 is_attach_to_bottom=true。
6. 再按最靠下的 `拷贝回复`。
7. 清空剪贴板后等待复制结果写入，并读取当前剪贴板内容作为回复。
```

## 附件上传的瞬时失败态

### 问题

Notion AI 输入框支持先输入文字，再把本地文件写入系统剪贴板并 Cmd+V 粘贴为附件。

实测发现，文件上传并不总是稳定成功。偶发情况下，文件卡片会先出现，约 1 秒后短暂显示：

```text
上传失败请重试
```

随后这段文案很快消失。

### 关键判断

`上传失败请重试` 是瞬时 UI 提示，不适合作为稳定 AX 扫描目标。

原因：

- 文案可见时间很短，轮询很可能错过。
- 文案消失后，AX 树里不一定保留可检测元素。
- 依赖它会让失败判断本身变得不稳定。

### 当前策略

附件上传只使用成功信号做稳定判断：

```text
AXButton description/title 以 “从上下文中移除” 开头
且包含完整文件名
且 actions 包含 AXPress
```

如果在等待时间内始终没有看到这个按钮，则返回 `wait_attachments` 失败。
这类失败可能表示：

- 文件上传确实失败并闪过了 `上传失败请重试`。
- 文件仍在上传但超过等待窗口。
- Notion UI/网络状态异常。

调用方应把 `wait_attachments` 失败视为附件未进入上下文，重试整个上传提交流程，
而不是继续按 `提交 AI 消息`。

### 上传中的可见信号

上传中时，输入框附件卡片左侧会出现一个正方形框和转圈进度标记。

AX 扫描中它不是文本，也不是按钮，而是多个无 label 的状态组：

```text
role=AXGroup
roleDesc=状态
label=""
size 约 24x24 到 32x32
position 位于附件卡片左侧图标区域
actions 包含 AXShowMenu / AXScrollToVisible
```

这个元素可以辅助判断“附件仍在上传中”，但不能作为成功信号。

原因：

- 它没有文件名或唯一 label。
- 只说明有上传/处理中的视觉状态，不说明最终进入上下文。
- 上传失败时它可能短暂出现后消失。

因此当前仍以 `从上下文中移除{文件名}` 按钮作为唯一稳定成功信号。
