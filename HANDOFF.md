# Notion AI Local Control Handoff (2026-06-03)

## Environment

- Notion 7.20.0, Electron 41.3.0, embedded Chrome 146.
- CDP port: `9222`.
- CDP endpoints:
  - `http://127.0.0.1:9222/json/version`
  - `http://127.0.0.1:9222/json/list`
  - `http://127.0.0.1:9222/json/activate/<targetId>`
  - `http://127.0.0.1:9222/json/close/<targetId>`

## Current Target Types

Typical page targets:

- `https://app.notion.com/quick-search`: quick-search Notion AI floating window.
- `https://app.notion.com/ai`: main-app Notion AI start page.
- `https://app.notion.com/chat?t=...`: main-app Notion AI conversation.
- `https://app.notion.com/blank?...`: ordinary Notion blank tab.
- `file://.../renderer/tabs/index.html`: Notion Electron Tab Bar.
- Empty URL targets: sometimes reusable, sometimes redirect to login.

Tab Bar is an Electron internal renderer. It can be stale or slow to hydrate, so target id activation is more reliable than label-only tab matching.

## Generation Completion

### Wrong Signals

`hasStop` is not enough. The stop button can remain visible after the answer is effectively complete.

`copyReplyCount > 0` is also not enough. An old reply's copy button can remain while the current answer is still streaming. This caused `notion-ai ask-and-reply` to return old clipboard text such as `HANDOFF_OK` while a new long story was still generating.

### Current Quick-Search Rule

For quick-search completion, wait for:

- current question appears in the page,
- generation activity has been observed,
- generating text is gone,
- an enabled copy-reply button exists below the current question.

Important fields now exposed by `dom_status()` / wait snapshots:

- `nativeDisabled`
- `ariaDisabled`
- `enabledCopyReplyCount`
- `latestEnabledCopyReply`
- `questionBottom`
- `latestEnabledCopyReplyAfterQuestion`

The useful enabled signal is native `button.disabled === false`. `aria-disabled` can stay true even when React copy works.

### Current Main-App Rule

Main app status exposes the same copy button split:

- `copyReplyCount`
- `enabledCopyReplyCount`
- `latestCopyReply`
- `latestEnabledCopyReply`

Main app waits now require generation activity and a latest enabled copy button instead of raw copy count.

## Copy Reply

Direct DOM click is unreliable. The copy button's own fiber usually does not hold the handler; its parent fiber does.

Current approach:

1. Find visible copy-reply controls.
2. Prefer the latest visible one with `nativeDisabled === false`.
3. Walk to the parent React fiber.
4. Call `memoizedProps.onClick(...)`.
5. Retry `pbpaste` because the copy is asynchronous.

Implemented in:

- `beta_cdp_input.py`: `copy_reply_via_react()`
- `tab_bar_cdp.py`: `copy_main_app_latest_reply()`

## Main-App Conversation Creation

The stable flow is target-id first, token second.

For new `app ask` conversations:

1. Acquire a local lock: `/tmp/notion-ai-local-control-new-tab-<port>.lock`.
2. Create or reuse a new page target.
3. Bind all input work to that CDP target id.
4. If the target is blank, navigate that same id to `https://app.notion.com/ai`.
5. Verify an AI textbox exists and is empty.
6. Insert text and submit.
7. Wait for the same target id to gain `chat?t=...`.
8. Return the conversation token.

This fixed prompt merging under concurrent `app ask`. Verified with 3 concurrent asks:

- `LOCK5_A/B/C`: 3 successful independent target ids and tokens.
- `LOCK6_A/B/C`: 3 successful independent target ids and tokens.

## Direct Navigate To AI

Creating a new tab is not always necessary.

Verified:

- Existing blank target -> `Page.navigate("https://app.notion.com/ai")` -> submit -> token -> reply.
- Empty URL target -> `/ai` can also work.

Counterexample:

- Some empty URL targets redirect to `https://app.notion.com/login?redirectURL=%2Fai`.

Therefore direct navigation is valid only after verifying the target reaches an AI textbox.

## Multi-Token Reply

`notion-ai app get-reply --token A B C --json` works.

Verified multi-token collection:

- all tokens are resolved by URL token,
- tabs are activated by target id,
- replies are copied serially,
- result is a `results` array.

## Known Broken / Risky Paths

### Model Selection

`app ask --model ...` currently times out in `_select_main_app_model`.

Observed:

```json
{
  "success": false,
  "error": "Timed out waiting for CDP response to Runtime.evaluate"
}
```

This affects multi-model fan-out. Without `--model`, `app ask` works and reports the current model, usually `Opus 4.8`.

Also note that CLI `--model` uses `nargs="+"`; use `--from-stdin` when testing to avoid the question being parsed as another model label.

### Tab Bar Close

Tab Bar close buttons can click successfully but leave CDP targets alive. Stronger fallback:

```bash
curl -fsS http://127.0.0.1:9222/json/close/<targetId>
```

This successfully closed all main-app Notion AI page targets during testing.

### Tab Bar Activation Reports

`foreground_target()` can report `activation.ok=false` if Tab Bar labels are stale, even when `/json/activate/<targetId>` succeeds and input works. Treat the nested `/json/activate` result as the more important signal.

## Verified Commands

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli start --json
PYTHONPATH=src ./venv/bin/python -m compileall -q src
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli cdp-debug --status
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli ask-and-reply "请只回复：FIX_OK" --json --timeout 60
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli app ask "只回复：LOCK6_A" --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli app get-reply --token <token-1> <token-2> --json
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli app status --all --json
```

## File Map

- `README.md`: user-facing commands and current limitations.
- `PROJECT.md`: project architecture and maintenance notes.
- `HANDOFF.md`: latest operational findings.
- `src/notion_ai_local_control/cli.py`: command router.
- `src/notion_ai_local_control/start_cdp.py`: start/restart Notion with CDP.
- `src/notion_ai_local_control/ask_cdp.py`: quick-search ask flow.
- `src/notion_ai_local_control/beta_cdp_input.py`: quick-search CDP primitives.
- `src/notion_ai_local_control/tab_bar_cdp.py`: main-app target/token flow and Tab Bar helpers.
