# CDP Main Path

本文档说明 Notion AI 的 CDP 后台控制主路线。

当前目标不是调用 Notion 私有网络接口，而是只通过 Electron CDP 操作
Notion 桌面端 renderer 里的 DOM/editor 输入框，替代前台焦点输入；回复复制仍读取系统剪贴板。

## 当前结论

已经验证成功：

- Notion 带 `--remote-debugging-port=9222` 启动后，`127.0.0.1:9222` 可访问。
- CDP target 里存在：
  - `https://www.notion.so/quick-search`
  - `https://www.notion.so/ai`
- 浮动 Notion AI 命令搜索窗口对应的是 `https://www.notion.so/quick-search`。
- `quick-search` target 中可找到输入框：

```css
[contenteditable="true"][role="textbox"]
```

- 对该节点执行：

```js
el.focus()
document.execCommand("insertText", false, text)
```

可以在窗口不在前台时写入 Notion AI 输入框。

- 写入后可通过 AX 或截图验证看到：

```text
AXTextArea = "..."
Submit AI message
```

且提交按钮从 `DISABLED` 变成可用。

重要观察：

- `--restart-with-cdp` 后，`quick-search` target 可能先出现但 DOM 尚未渲染输入框。
- 需要等待 textbox 出现后再写入，否则会得到 `textbox not found`。
- 生成中 `拷贝回复` 按钮会消失，生成完成后才出现，可作为完成信号之一。
- 已验证完整后台链路：
  - CDP 写入
  - CDP 点击提交
  - 等待生成完成
  - CDP 点击最新 `拷贝回复`
  - 读取系统剪贴板

尚未完整验证：

- 关闭/重置会话
- 文件附件

## CDP 主路径文件

文件：

```text
src/notion_ai_local_control/beta_cdp_input.py
src/notion_ai_local_control/ask_cdp.py
```

统一 CLI 已挂载：

```text
notion-ai ask
notion-ai beta-cdp-input
notion-ai ask-cdp
notion-ai ask-ax
```

该文件包含：

- CDP websocket 最小客户端
- 读取 targets
- 定位 `https://www.notion.so/quick-search`
- 写入 `contenteditable` 输入框
- 查询输入框和 submit 按钮状态
- 清空输入框
- DOM click 提交按钮
- 查询 DOM 生成状态
- DOM click 最新 `拷贝回复`
- 读取剪贴板作为最终回复
- CDP `Input.dispatchMouseEvent` 打开附件菜单
- CDP `Page.fileChooserOpened` 拦截文件选择器并通过 `DOM.setFileInputFiles` 注入文件
- 可选重启 Notion 并打开 CDP；主流路径不依赖 CuaDriver

默认行为：

- `notion-ai ask` 默认使用 CDP，`ask-cdp` 是兼容别名。
- 如果 `9222` 没开，`notion-ai ask` 默认会重启 Notion 并带
  `--remote-debugging-port=9222` 启动。
- 如果 quick-search 浮层没有出现，命令会失败并提示打开浮层，不会自动回退 AX。
- `notion-ai ask-ax` 保留旧 AX/剪贴板流程，供人工调试或回退。
- 写入、清空、查询状态前会默认等待 quick-search textbox 可见，避免
  target 已出现但 DOM 尚未渲染导致 `textbox not found`。

## 常用命令

检查帮助：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.beta_cdp_input --help
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli beta-cdp-input --help
```

带 CDP 重启 Notion：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.beta_cdp_input \
  --restart-with-cdp \
  "background CDP input test"
```

如果 Notion 已经带 `--remote-debugging-port=9222` 运行，后续测试不需要重启，
直接复用当前 CDP 端口：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.beta_cdp_input \
  "background CDP input test"
```

等待 quick-search textbox 的默认参数：

```text
--wait-textbox-timeout 10
--wait-textbox-interval 0.2
```

查询状态：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.beta_cdp_input --status
```

成功状态示例：

```json
{
  "textboxes": [
    {
      "text": "background CDP input test",
      "placeholder": "使用 AI 处理各种任务...",
      "active": true,
      "visible": true
    }
  ],
  "submit": {
    "label": "Submit AI message",
    "disabled": false,
    "visible": true
  }
}
```

清空测试文本：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.beta_cdp_input --clear
```

完整 CDP 后台提问并复制回复：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask \
  "请只回复：CDP OK" --json
```

从 stdin 输入，适合自动化长文本：

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask \
  --from-stdin --json <<'EOF'
总结这段文本。
EOF
```

当前 `ask` / `ask-cdp` 链路：

```text
后台写入 -> CDP 点击提交 -> 等待拷贝回复出现 -> CDP 点击最新拷贝回复 -> 读取剪贴板
```

带附件时 `ask` / `ask-cdp` 使用两阶段纯 CDP 流程：

```text
CDP 打开附件菜单 -> 拦截 file chooser -> 注入文件 -> 等附件进入对话上下文
-> 写入用户问题 -> CDP 点击提交 -> 等待完成 -> CDP 点击最新拷贝回复
```

注意：quick-search 的文件选择器上传会把附件先作为一条上下文消息发出。
因此 `ask --attach-file` 会先等附件消息进入上下文，再发送用户问题。

当前限制：

- 附件目前通过 quick-search target 验证；`https://www.notion.so/ai` target
  没有同样的 file input/menu 结构。
- 主流路径只操作 `https://www.notion.so/quick-search`。
- 如果 quick-search 输入框不存在，命令会失败并提示打开浮层；不会通过 CuaDriver
  或系统热键自动打开。

确认 CDP 是否开启：

```bash
curl -fsS http://127.0.0.1:9222/json/version
curl -fsS http://127.0.0.1:9222/json/list
```

恢复普通 Notion：

```bash
pkill -x Notion
/Applications/Notion.app/Contents/MacOS/Notion >/dev/null 2>&1 &
curl -fsS http://127.0.0.1:9222/json/version || true
```

最后一条应连接失败，表示调试端口已关闭。

## 已验证的后台输入流程

测试日期：2026-05-28。

流程：

1. 前台应用为 Codex。
2. 用调试命令带 CDP 重启 Notion；如果 quick-search 没有恢复，手动打开浮层。
3. 第一次写入过早失败，返回 `textbox not found`。
4. 等待 quick-search DOM 渲染后，`--status` 显示 textbox 存在。
5. 前台仍为 Codex。
6. 再次写入成功：

```json
{
  "write": {
    "ok": true,
    "execOk": true,
    "text": "background CDP input test",
    "active": true,
    "submit": {
      "label": "Submit AI message",
      "disabled": false,
      "visible": true
    }
  }
}
```

结论：

```text
Notion 窗口不在前台时，CDP 可以后台写入 quick-search 的 Notion AI 输入框，
并让提交按钮启用。
```

## 关键实现点

CDP target：

```text
https://www.notion.so/quick-search
```

输入框 selector：

```css
[contenteditable="true"][role="textbox"]
```

写入核心 JS：

```js
const el = document.querySelector('[contenteditable="true"][role="textbox"]')
el.focus()

const selection = window.getSelection()
const range = document.createRange()
range.selectNodeContents(el)
selection.removeAllRanges()
selection.addRange(range)

const execOk = document.execCommand("insertText", false, text)
if (!execOk) {
  el.textContent = text
  el.dispatchEvent(new InputEvent("beforeinput", {
    bubbles: true,
    cancelable: true,
    inputType: "insertText",
    data: text,
  }))
  el.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    inputType: "insertText",
    data: text,
  }))
}
el.dispatchEvent(new Event("change", { bubbles: true }))
```

清空核心 JS：

```js
el.focus()
const selection = window.getSelection()
const range = document.createRange()
range.selectNodeContents(el)
selection.removeAllRanges()
selection.addRange(range)
document.execCommand("delete")
```

## 后续建议

### 1. 会话清理/重置

已经验证 DOM click submit button：

```js
const buttons = [...document.querySelectorAll("button,[role='button']")]
const submit = buttons.find((b) => /submit ai message/i.test(
  b.innerText || b.getAttribute("aria-label") || ""
))
submit?.click()
```

下一步可验证：

- CDP 点击 `开始新对话`
- CDP 点击 `关闭`
- 长上下文下最新回复定位是否始终取最靠下的 `拷贝回复`

### 2. 附件路径

已验证纯 CDP 附件路径，不再需要剪贴板或 AX paste：

1. `Page.setInterceptFileChooserDialog(enabled=True, cancel=True)`
2. `Input.dispatchMouseEvent` 点击 `提供背景信息`
3. `Input.dispatchMouseEvent` 点击 `添加图片、PDF 或 CSV`
4. 等 `Page.fileChooserOpened`，取 `backendNodeId`
5. `DOM.setFileInputFiles({ backendNodeId, files })`

验证结果：

```text
ask --attach-file /tmp/notion-cdp-official-1779939924.txt \
  "请读取最新上传的附件，只回复附件第二行原文。"

返回：official second line 1779939924
```

### 3. 风险边界

保持当前边界：

- 只操作本机已登录 Notion renderer DOM。
- 不调用 Notion 内部网络接口。
- 不读取/复用 session token。
- 不抓包逆向 Notion AI endpoint。
- 控制频率，按人类使用节奏。

## 相关文件

```text
src/notion_ai_local_control/beta_cdp_input.py
src/notion_ai_local_control/ask_cdp.py
src/notion_ai_local_control/cli.py
docs/CDP_BETA_HANDOFF.md
```

现有稳定路径仍在：

```text
src/notion_ai_local_control/ask_flow.py
src/notion_ai_local_control/input_box.py
src/notion_ai_local_control/reply_copy.py
```

CDP 路径已成为默认 `ask` 流程；`ask-cdp` 作为兼容别名保留，旧稳定 AX 流程在
`ask-ax` 中保留。
