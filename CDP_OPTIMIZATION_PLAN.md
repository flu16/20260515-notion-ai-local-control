# CDP 模式优化方案

> 基于 Codex 对 `src/notion_ai_local_control/` 下 CDP 相关文件的审查。

---

## 一、总体结论

CDP 模式最大的提速点不是微调 sleep 时长，而是 **减少跨进程 CDP 往返和全量 DOM 扫描**。当前一次提问会反复执行：

1. `find_target` → 新 WebSocket 连接
2. `Runtime.evaluate` → 全 DOM 扫描
3. 生成等待时每 250-350ms 读一次 `document.body.innerText`

这是主要的性能瓶颈。优化方向是：**合并操作、事件驱动替代轮询、缩小扫描范围、条件等待替代固定 sleep**。

---

## 二、五大优化方向

### 1. 合并 clear_text + write_text + submit_message

**现状**
`ask_cdp.py` 依次调用 `wait_for_cdp_ready()`、`clear_text()`、`write_text()`、`submit_message()`，触发多次 target 查找、WebSocket 连接和 DOM 查询。

**方案**
在 `beta_cdp_input.py` 新增 `set_text_and_submit()`，一次 `Runtime.evaluate` 内完成清空、写入、提交。

**收益**
节省 3-4 次 CDP 往返。

---

### 2. MutationObserver 替代生成等待轮询

**现状**
`ask_cdp.py` 每 250-350ms 调用 `dom_status()`，而 `dom_status()` 全量扫描按钮、文本框并读取 `document.body.innerText`。

**方案**
新增 `wait_for_generation_done_cdp()`，将等待逻辑放入浏览器进程，用 MutationObserver 事件触发。

**注意**
需要给 `call()` / `evaluate_js()` 增加可传入 timeout，在等待期间临时设置 socket timeout，避免 `awaitPromise` 因默认 5 秒超时中断。

**收益**
长回复场景从 Python 轮询变为页面内事件触发，消除大量 DOM 全量扫描。

---

### 3. 缩小 DOM 扫描范围

**现状**
`dom_status()` 中的 `document.body.innerText` 读取很贵，触发布局/样式计算。附件状态查询用 `querySelectorAll("*")` 扫描全部节点。

**方案**
- 等待循环中用 `textContent` 替代 `innerText`
- `body_limit` 从 30000 降到 6000-10000
- 附件状态查询将 `querySelectorAll("*")` 改为 `querySelectorAll("button,[role='button']")`

**收益**
减少布局/样式计算触发次数。

---

### 4. 附件流程优化

**现状**
`ask_cdp.py` 用自写的 `wait_for_attachments_in_context_cdp()` 每 350ms 调 `dom_status(body_limit=30000)`。

**方案**
`ask_cdp.py` 直接改用 `beta_cdp_input.py` 中已有的 `wait_for_attachments_ready_cdp()`。

**收益**
消除一次大 body scan。

---

### 5. 去掉固定等待（sleep 改为条件等待）

| 位置 | 当前 | 改为 |
|------|------|------|
| `ask_cdp.py:144` `time.sleep(0.8)` | 固定等待 0.8s | `wait_for_cdp_ready()`，成功即返回 |
| `ask_cdp.py:324` 新对话后 0.5s | 固定等待 0.5s | 等待 textbox 为空或 Notion AI face 出现 |
| `beta_cdp_input.py:624` 附件菜单 0.25s | 固定等待 0.25s | 等待 upload menu item 出现（MutationObserver 或 50ms 快轮询） |

---

## 三、建议实施顺序

1. **合并 clear/write/submit** — 改动小、收益稳定，优先做
2. **生成等待改 MutationObserver** — 同时给 CDP socket call 增加长 timeout
3. **附件流程优化** — `ask_cdp.py` 改用 `wait_for_attachments_ready_cdp()`，附件状态查询缩到按钮集合
4. **清理固定 sleep** — 用条件等待替代

完成以上优化后，常规无附件提问将少掉多次 WebSocket 建连和 3 次以上 DOM 扫描；生成等待期间从 Python 轮询变为页面内事件触发，长回复尤其明显。
