# Lockscreen Quick Search Research

记录日期：2026-05-29

本文记录围绕 Notion AI quick-search 浮层、CDP、锁屏场景的实验结论，方便后续继续研究。

## 目标

希望在无人值守或锁屏状态下，仍然可以：

1. 启动或重启 Notion。
2. 确保 Notion 以 CDP 模式运行。
3. 打开 Notion AI quick-search 浮层。
4. 通过 CDP 写入问题、提交、等待回复、复制结果。

## 当前项目状态

主流路径：

```text
notion-ai ask
notion-ai ask-cdp
```

默认使用 CDP，目标锁定为：

```text
https://www.notion.so/quick-search
```

如果 `127.0.0.1:9222` 不可用，`ask-cdp` 会尝试重启 Notion 并附加：

```text
--remote-debugging-port=9222
```

但 CDP 只能操作已经存在并渲染完成的 quick-search renderer DOM。它不能凭空让 Notion 主进程显示 quick-search panel。

## 已验证成功

### 普通 CDP 提问

命令形态：

```bash
notion-ai ask-cdp "请只回复：CDP_TEST_OK" --timeout 90 --json
```

结果：

```text
CDP_TEST_OK
```

耗时约 4.91 秒。

### 附件 CDP 提问

第一次附件测试被 macOS / Notion 权限弹窗卡住，耗时约 123 秒，但最终成功。

授权后重测：

```text
CDP_ATTACH_RETEST_OK
```

耗时约 9.15 秒。

### 新对话按钮

命令形态：

```bash
notion-ai ask-cdp "请只回复：CDP_NEW_CHAT_OK" --new-conversation --timeout 90 --json
```

结果：

```text
CDP_NEW_CHAT_OK
```

`copyReplyCount` 变为 1，说明确实进入了新对话结果。

## 自动 CDP 重启实验

测试步骤：

1. 退出当前 CDP 模式 Notion。
2. 用普通 `open -a Notion` 启动 Notion。
3. 确认此时没有 CDP 端口。
4. 调用 `ask-cdp`，让它自动以 CDP 模式重启 Notion。

结果：

- Notion 确实被重启为 CDP 模式。
- 进程参数包含 `--remote-debugging-port=9222`。
- `127.0.0.1:9222` 可访问。
- CDP target 中出现 `https://www.notion.so/quick-search`。
- 但 quick-search DOM 中没有 visible textbox。

临时尝试：

- 将冷启动后等待 textbox 的时间拉到 30 秒。
- 结果仍失败。

结论：

仅仅让 Notion 以 CDP 模式启动，并不等于 quick-search 浮层已经打开。quick-search target 可以存在，但如果 panel 没有进入 visible/open 状态，DOM 里不会有可用输入框。

当前有一个未提交本地改动：

```text
src/notion_ai_local_control/ask_cdp.py
```

内容是冷启动后把 textbox ready timeout 至少拉到 30 秒。这个改动只能改善冷启动等待，不解决浮层未打开的根因。

## 解锁状态下打开浮层

用户观察到关键条件：

如果 Notion 主窗口没有最小化，直接按 `Command+Shift+J/G` 会在主窗口里打开一个内部界面，而不是我们需要的 floating quick-search。

验证结果：

1. 关闭 quick-search。
2. 通过 AX 找到 Notion 主窗口。
3. 调用 `minimize_notion_main_windows(app_element)`。
4. 再发送 Notion AI / quick-search 快捷键。
5. 约 0.25 秒后 textbox 出现。

结论：

解锁状态下，稳定路线是：

```text
最小化 Notion 主窗口
-> 发送全局快捷键
-> Notion 主进程 globalShortcut 回调
-> quick-search panel 显示
-> CDP 操作 quick-search DOM
```

相关代码：

```text
src/notion_ai_local_control/open_ai_window.py
src/notion_ai_local_control/notion_ax.py
```

## 锁屏状态实验

### 未显式最小化主窗口

测试流程：

1. 关闭 quick-search。
2. 等待用户锁屏。
3. 锁屏期间运行 `open_ai_window --open`。

结果：

```text
open_exit=1
after_open_visible_textboxes=0
```

脚本等待超时，未打开 quick-search。

### 锁屏前先最小化主窗口

测试流程：

1. 关闭 quick-search。
2. 锁屏前通过 AX 最小化 Notion 主窗口。
3. 用户锁屏。
4. 锁屏期间运行 `open_ai_window --open`。

结果：

```text
minimized_before_lock=1
open_exit=1
after_open_visible_textboxes=0
```

结论：

最小化主窗口是解锁状态下的必要条件，但不是锁屏状态下的充分条件。锁屏后 macOS 的 loginwindow / locked session 会拦截或隔离普通用户桌面的键盘事件，导致 `CGEventPost`、AppleScript/System Events、AX 快捷键等方式无法可靠触发 Notion 的 Electron `globalShortcut`。

## CDP 打开浮层尝试

尝试方向：

1. 对 main page target 执行 `Page.bringToFront`。
2. 用 CDP `Input.dispatchKeyEvent` 发送 `Command+Shift+J/G`。
3. 从 quick-search renderer 调用 `window.__electronApi` 里可见的 quick-search 相关方法。

结果：

- `Input.dispatchKeyEvent` 只进入 renderer，不会触发 Electron 主进程的 `globalShortcut.register(...)`。
- `quickSearchRefresh` 可以刷新 quick-search controller，但不能打开 panel。
- `quickSearchReady` / `quickSearchSetSearchAssistantMode` 不能从 closed 状态打开 panel。
- `openNotionAiFromQuickSearch` / `openSearchModalFromQuickSearch` 名字像打开入口，但实际是 main-to-renderer emitter，不是 renderer-to-main sender，不能由 CDP 页面 JS 调用来打开浮层。

结论：

CDP 页面侧没有公开的“打开 quick-search 浮层”入口。

## Notion 内部文件只读调查

调查对象：

```text
/Applications/Notion.app/Contents/Resources/app.asar
```

只读解析 `app.asar` 后，关键文件：

```text
.webpack/main/index.js
.webpack/renderer/tab_browser_view/preload.js
.webpack/renderer/tabs/preload.js
```

### preload 暴露的 quick-search API

`tab_browser_view/preload.js` 中可见：

```text
closeQuickSearch -> senderToMain("notion:quick-search-close")
openQuickSearchResult -> senderToMain("notion:quick-search-open-result")
quickSearchReady -> senderToMain("notion:quick-search-ready")
quickSearchRenderCompleted -> senderToMain("notion:quick-search-render-completed")
quickSearchSetSearchAssistantMode -> senderToMain("notion:quick-search-set-search-assistant-mode")
quickSearchRefresh -> senderToMain("notion:quick-search-refresh")
openQuickSearchShortcutSetting -> senderToMain("notion:quick-search-open-shortcut-settings")
quickSearchVisibilityState.isVisible -> invokerInMain("notion:is-quick-search-visible")
```

这些接口没有一个是“打开 quick-search panel”。

另外：

```text
openSearchModalFromQuickSearch -> getSimpleEmitter("quick-search:open-search-modal")
openNotionAiFromQuickSearch -> getSimpleEmitter("quick-search:open-notion-ai")
performShortcut -> getSimpleEmitter("notion:perform-shortcut")
```

这些是 main-to-renderer 方向的 emitter，不能作为 renderer-to-main 的打开命令。

### 主进程里的真实打开路径

`main/index.js` 中 quick-search state 有这些状态：

```text
not-visible
search-waiting-to-open
assistant-waiting-to-open
search-visible
assistant-visible
```

核心 action：

```text
toggleVisibilityStateIfReady({ source, openAssistant })
setQuickSearchVisibleIfReady()
quickSearchSetSearchAssistantMode({ openAssistant })
```

`QuickSearchController` 的关键逻辑：

```text
handleGlobalCommandSearchShortcutPress()
handleGlobalNotionAiShortcutPress()
registerGlobalShortcut(...)
initializeQuickSearch()
```

快捷键路径：

```text
globalShortcut.register(...)
-> handleGlobalCommandSearchShortcutPress()
   或 handleGlobalNotionAiShortcutPress()
-> ensureQuickSearchInitialized()
-> Store.dispatch(toggleVisibilityStateIfReady(...))
-> BrowserWindow.showInactive()
-> macOS makeKeyAndOrderFront(...)
```

如果最近聚焦的是普通 Notion 主窗口，则逻辑会进入：

```text
activeTabController.openSearchModalInNotion()
activeTabController.openNotionAiInNotion()
```

这解释了为什么主窗口未最小化时，快捷键会在主窗口内部打开东西，而不是 floating quick-search。

### Debug 菜单

Debug 菜单里存在：

```text
Command Search -> Toggle Window Visibility
```

其内部也是：

```text
quickSearchController.ensureQuickSearchInitialized()
Store.dispatch(toggleVisibilityStateIfReady({ source: "debug-menu", openAssistant: false }))
```

但 Debug 菜单依赖 Notion 内部调试开关或 notion.com 员工账号域名，不适合作为项目主路径。

### URL scheme

`Info.plist` 显示 Notion 注册了：

```text
notion://
```

主进程 `handleProtocolUrl(...)` 的逻辑是解析 URL 并导航或聚焦页面：

```text
handleProtocolUrl(url)
-> openURLOptionallySurfacingExistingTab(...)
   或 navigateFocusedWindowToUrl(...)
```

没有看到 quick-search / Notion AI 浮层相关 deep link。

## 当前判断

### 可以稳定做的

解锁状态：

```text
最小化 Notion 主窗口
-> 发送系统快捷键
-> 打开 quick-search
-> CDP 提问
```

锁屏前预热：

```text
启动 Notion CDP
-> 打开 quick-search
-> 确认 textbox 存在
-> 用户锁屏
-> 锁屏期间继续用 CDP 操作已有 quick-search DOM
```

这个方向最值得继续测试。

### 目前看不可行或不可靠的

锁屏后从无到有打开 quick-search：

- AX / Quartz / AppleScript 发全局快捷键不可靠。
- CDP `Input.dispatchKeyEvent` 不能触发 Electron 主进程 globalShortcut。
- Notion preload 没有暴露 renderer-to-main 的打开 API。
- `notion://` 没看到 quick-search deep link。

### 理论方向，但不建议作为主线

1. 启动 Electron main process Node inspector，然后调用主进程对象。
   当前 `--remote-debugging-port` 暴露的是 renderer CDP，不是 main process inspector。

2. 修改 Notion `app.asar`，加一个本地 IPC 或 URL 入口来 dispatch `toggleVisibilityStateIfReady`。
   这会很脆，Notion 更新会覆盖，且可能影响签名、权限和安全边界。

3. 依赖 Debug 菜单或内部设置。
   入口存在，但启用条件不适合通用自动化。

## 建议的下一步

优先实现一个显式的预热命令，例如：

```text
notion-ai prepare-cdp-window
```

行为：

1. 确保 Notion 以 CDP 模式运行。
2. 检查 quick-search target。
3. 如果 textbox 不存在，在解锁状态下最小化主窗口并发送快捷键。
4. 等待 textbox 出现。
5. 输出 JSON 状态，告诉调用方是否适合进入锁屏后台任务。

然后单独测试：

```text
锁屏前 prepare 成功
-> 锁屏
-> ask-cdp 是否还能写入、提交、复制回复
```

如果这条成功，项目就可以把“锁屏后打开浮层”问题转化为“锁屏前保持浮层可用”的工程问题。
