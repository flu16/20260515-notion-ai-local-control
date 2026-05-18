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
