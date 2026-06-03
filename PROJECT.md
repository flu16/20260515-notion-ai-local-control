# Project Notes

This project controls Notion desktop Notion AI locally through Electron CDP.

It does not call Notion private AI APIs, does not reuse session tokens, and does not depend on macOS Accessibility for the current main paths.

## Runtime Assumptions

- Notion desktop is launched with `--remote-debugging-port=9222`.
- CDP targets are discovered from `http://127.0.0.1:9222/json/list`.
- CDP readiness is checked with `http://127.0.0.1:9222/json/version`.
- System clipboard reads use `pbpaste`.

## Supported Paths

### Quick-Search Flow

Entry:

```bash
notion-ai start
notion-ai ask_and_reply ...
notion-ai cdp-debug ...
```

Core files:

- `src/notion_ai_local_control/ask_cdp.py`
- `src/notion_ai_local_control/beta_cdp_input.py`

Flow:

1. Ensure the quick-search target is available.
2. Optionally start a new quick-search conversation.
3. Write text into the visible contenteditable textbox.
4. Submit with CDP.
5. Wait until the reply is actually complete.
6. Trigger the latest copy-reply React handler.
7. Read the system clipboard.

The quick-search completion check is intentionally stricter than `copyReplyCount > 0`. Old copy buttons can remain visible while a new answer is streaming. The current check waits for an enabled copy button below the current question after generation activity has been observed.

### Main-App Token Flow

Entry:

```bash
notion-ai app ask ...
notion-ai app get-reply ...
notion-ai app status ...
notion-ai app close-conversation ...
notion-ai app restore-conversation ...
```

Core file:

- `src/notion_ai_local_control/tab_bar_cdp.py`

Flow for new conversations:

1. Serialize new-conversation creation with a local lock.
2. Create or reuse a Notion page target.
3. Bind the operation to the CDP target id.
4. If the target is blank, navigate that same target id to `https://app.notion.com/ai`.
5. Verify the textbox is empty before writing.
6. Submit the question in that target.
7. Wait for the same target URL to become `chat?t=...`.
8. Return the conversation token; later operations resolve by token.

Flow for existing conversations:

1. Resolve the target from the token.
2. Activate/foreground if needed.
3. Submit or copy reply in that target.

## Important Findings

- The stop button is not a reliable "still generating" signal by itself. It may remain visible after completion.
- `copyReplyCount > 0` is also not enough. It can count an old reply while the current reply is still streaming.
- The copy-reply button may have `aria-disabled="true"` even when the React handler can copy; native `button.disabled` is the useful enabled/disabled signal.
- Notion's copy action does not go through `navigator.clipboard`; the project invokes the React parent fiber `onClick` and then waits for `pbpaste`.
- New Notion tabs can first appear as blank or `app.notion.com/ai` targets with a generic title before becoming fully hydrated.
- Some empty URL targets can navigate to `/ai` successfully; others redirect to `/login`, so direct navigation must verify the textbox.

## Current Known Issues

- `app ask --model ...` and multi-model fan-out currently timeout in `_select_main_app_model`.
- Tab Bar click matching can be stale when titles have not hydrated. `/json/activate/<targetId>` often succeeds even when the Tab Bar click report says false.
- Closing main-app AI tabs through the Tab Bar can fail to remove the CDP target; `/json/close/<targetId>` works as a stronger fallback.
- There are no formal pytest/unittest tests yet. Verification is currently command-based.

## Module Responsibilities

### `cli.py`

Thin command router for:

- `start`
- `ask_and_reply`
- `app`
- `cdp-debug`

### `start_cdp.py`

Starts or restarts Notion desktop with `--remote-debugging-port=<port>`, waits for `/json/version`, and reports the CDP browser version.

### `ask_cdp.py`

User-facing quick-search ask_and_reply flow: readiness, optional attachment context, submit, wait, copy.

### `beta_cdp_input.py`

Low-level quick-search CDP helpers:

- target discovery
- Runtime evaluation
- textbox status/write/clear
- submit and new conversation buttons
- generation wait observers
- file chooser handling
- React fiber copy-reply handling

### `tab_bar_cdp.py`

Main app and Tab Bar helpers:

- page and Tab Bar target discovery
- conversation token extraction
- target id and token resolution
- new conversation creation with local locking
- blank target navigation to `/ai`
- main-app textbox submission
- multi-token reply collection
- restore and close helpers

## Housekeeping

Ignored generated files:

- `venv/`
- `__pycache__/`
- `.DS_Store`
- `*.pyc`
- `*.egg-info/`
- `.pytest_cache/`
- `.claude/`
