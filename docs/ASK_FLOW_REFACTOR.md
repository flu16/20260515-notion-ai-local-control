# ask 流程拆分说明

本文档记录 ask 流程拆分后的逻辑思路，方便后续维护时快速判断：

- 一个行为应该放在哪个文件。
- 主流程如何串起来。
- 修改某个能力时应该优先看哪个模块。
- 哪些对外行为必须保持兼容。

## 为什么拆分

拆分前，`ask_and_copy_reply.py` 同时承担了这些职责：

- 命令行参数解析。
- 打开和识别 Notion AI 窗口。
- 扫描可见 AX 元素并点击按钮。
- 开始新对话。
- 输入问题。
- 粘贴附件并等待上传完成。
- 提交问题。
- 等待生成开始和结束。
- 判断是否贴住底部，并在必要时点击回到底部。
- 复制最新回复。
- 输出文本或 JSON 结果。

这些功能都和“向 Notion AI 提问并复制回复”有关，但变化原因不同。比如附件上传失败、复制按钮找不到、等待生成状态误判，应该分别能在自己的模块里定位，而不是都挤在一个 1300 多行文件里。

本次拆分的原则是：只拆职责，不改行为。

## 拆分后的文件职责

### `src/notion_ai_local_control/ask_and_copy_reply.py`

该模块负责 `notion-ai ask` 的参数解析和输出格式。

它只负责：

- 解析 CLI 参数。
- 从参数、stdin 或系统剪贴板读取问题。
- 调用 `notion_ai_local_control.ask_flow.ask_and_copy_reply(...)`。
- 按原格式输出 JSON 或普通文本。

保持这个文件很薄的原因是：入口要稳定，业务细节要下沉到流程模块。

### `src/notion_ai_local_control/ask_flow.py`

主流程编排层。

它负责把完整流程按顺序串起来：

```text
ensure_ai_window
-> 可选 start_new_conversation
-> input_text
-> 可选 paste_files_at_current_insertion_point + wait_for_attachments_ready
-> press_labeled_button("提交 AI 消息")
-> assign_task ? wait_until_generation_started : wait_until_generation_finished
-> wait_until_attached
-> copy_latest_visible_reply
```

这个文件应该保持“读起来像流程图”。如果某段逻辑开始变复杂，优先放到专门模块里，再从这里调用。

### `src/notion_ai_local_control/conversation_actions.py`

窗口、扫描和按钮动作层。

主要负责：

- `ensure_ai_window(...)`：确保 Notion AI 浮窗打开并返回窗口上下文。
- `scan_visible_element_objects(...)`：扫描当前窗口内可见 AX 元素，并保留可点击的 AX 对象。
- `find_labeled_button(...)` / `press_labeled_button(...)`：通过 label 找按钮并执行 `AXPress`。
- `start_new_conversation(...)`：点击 `开始新对话` 并等待轻量新对话信号。
- `press_back_to_bottom(...)`：点击无 label 的回到底部按钮。

判断一个函数是否该放这里，可以问：它是不是“找到某个窗口/元素，然后按一下或返回 AX 对象”？如果是，大概率属于这里。

### `src/notion_ai_local_control/attachment_flow.py`

附件上传相关逻辑。

主要负责：

- 查找附件卡片上的 `从上下文中移除...` 按钮。
- 查找上传中的 spinner。
- 在出现“不受信任文件”确认时点击 `允许上传`。
- 等待所有附件真正进入上下文。

附件逻辑留在单独文件，是因为它依赖 Notion UI 的多个弱信号：文件名文本、移除按钮、spinner、信任确认弹窗。后续修附件问题时，优先看这个文件。

### `src/notion_ai_local_control/generation_wait.py`

生成状态和贴底状态等待层。

主要负责：

- 通用 `wait_for_state(...)`。
- 等待进入 generating。
- 等待生成完成。
- 结合快速信号和完整状态扫描判断完成态。
- 判断 complete 后是否贴住底部。
- 如果没有贴底，调用 `press_back_to_bottom(...)`，再等待底部复制按钮出现。

这个模块的核心边界是“等状态稳定”。它不负责输入问题，也不负责真正复制回复。

### `src/notion_ai_local_control/reply_copy.py`

复制回复层。

主要负责：

- 等待底部区域出现最新回复的 `拷贝回复` 按钮。
- 清空剪贴板。
- 点击复制按钮。
- 等待剪贴板出现文本。

只把复制逻辑放在这里，可以避免生成中误复制、复制旧回复、剪贴板为空这些问题分散到主流程里。

## 依赖方向

当前依赖关系大致是：

```text
notion-ai ask
  -> src/notion_ai_local_control/cli.py
  -> src/notion_ai_local_control/ask_and_copy_reply.py
  -> src/notion_ai_local_control/ask_flow.py

src/notion_ai_local_control/ask_flow.py
  -> conversation_actions.py
  -> attachment_flow.py
  -> generation_wait.py
  -> reply_copy.py
  -> input_box.py

src/notion_ai_local_control/attachment_flow.py
  -> conversation_actions.py
  -> input_box.py
  -> notion_ax.py
  -> check_ai_state.py

src/notion_ai_local_control/generation_wait.py
  -> conversation_actions.py
  -> reply_copy.py
  -> check_ai_state.py

src/notion_ai_local_control/reply_copy.py
  -> conversation_actions.py
  -> notion_ax.py
  -> check_ai_state.py

src/notion_ai_local_control/conversation_actions.py
  -> notion_ax.py
  -> check_ai_state.py
```

尽量保持这个方向，不要让底层模块反过来导入 `ask_flow.py` 或 CLI 入口。

## 修改时怎么找位置

常见修改入口：

- CLI 参数、输出格式、stdin/clipboard 读取：改 `src/notion_ai_local_control/ask_and_copy_reply.py`。
- 调整完整提问流程顺序：改 `src/notion_ai_local_control/ask_flow.py`。
- 找不到按钮、窗口打开失败、点击失败：改 `src/notion_ai_local_control/conversation_actions.py`。
- 附件上传、信任文件弹窗、附件 ready 判断：改 `src/notion_ai_local_control/attachment_flow.py`。
- 等待生成、状态误判、贴底判断、回到底部：改 `src/notion_ai_local_control/generation_wait.py`。
- 复制按钮、剪贴板为空、复制到旧回复：改 `src/notion_ai_local_control/reply_copy.py`。
- 输入框激活、粘贴文本、粘贴文件的底层能力：改 `src/notion_ai_local_control/input_box.py`。
- AX 底层属性读取、窗口识别、剪贴板和键盘事件：改 `src/notion_ai_local_control/notion_ax.py`。

## 兼容性要求

以下行为不要随意改变：

- `./venv/bin/notion-ai ask ...` 仍然是主入口。
- `--from-stdin`、`--from-clipboard` 和 positional `question` 互斥。
- `--json` 输出字段结构保持稳定，尤其是：
  - `success`
  - `text`
  - `elapsed`
  - `final_state`
  - `copy_button_info`
  - `error`
  - 失败时的 `step`
- `--assign-task` 只等待进入 generating，不等待完成，不复制回复。
- 默认不自动开启新对话，只有显式传入 `--new-conversation` 才开新对话。
- 不引入鼠标点击作为业务路径。

## 验证命令

每次改动这些模块后，至少跑：

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai ask --help
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask --help
```

如果改了主流程、状态等待或复制逻辑，再跑真实流程：

```bash
./venv/bin/notion-ai ask "1+1" --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask "1+1" --json
./venv/bin/notion-ai ask "讲一个短句" --new-conversation --json
```

如果改了附件逻辑，再准备一个明确的测试文件并跑：

```bash
./venv/bin/notion-ai ask --attach-file ./path/to/test-file.md "总结这个文件" --json
```

## 后续整理建议

当前已经迁移到 `src/notion_ai_local_control/` 包结构。根目录不保留 Python 入口文件，业务实现和调试工具都在包内。
统一 CLI 位于 `src/notion_ai_local_control/cli.py`，安装后可用 `notion-ai <command>`。

下一步如果继续整理，可以考虑：

- 新增 `README.md`，把快速使用方式放在仓库首页。
- 新增少量纯逻辑测试，优先覆盖参数解析、状态构造、路径归一化和 JSON 兼容字段。
- 后续可以把各调试模块的 `sys.argv` 解析逐步迁移到统一 CLI 的 argparse 子命令。
