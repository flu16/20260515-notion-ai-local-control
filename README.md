# Notion AI Local Control

Local control helpers for Notion desktop Notion AI through Electron CDP.

The project exposes one CLI:

```bash
./venv/bin/notion-ai <command> [args...]
```

If the editable package is not installed, use:

```bash
PYTHONPATH=src ./venv/bin/python -m notion_ai_local_control.cli <command> [args...]
```

## Setup

```bash
./venv/bin/python -m pip install -e .
```

Start Notion with CDP enabled:

```bash
./venv/bin/notion-ai start --json
```

Check CDP:

```bash
curl -fsS http://127.0.0.1:9222/json/version
curl -fsS http://127.0.0.1:9222/json/list
```

## Main Commands

Quick-search flow: ask Notion AI and copy the final reply.

```bash
./venv/bin/notion-ai start
./venv/bin/notion-ai ask_and_reply "请只回复：OK" --json
./venv/bin/notion-ai ask_and_reply --from-stdin --json < prompt.txt
./venv/bin/notion-ai ask_and_reply "继续刚才的话题" --continue_conversation --json
```

Debug the quick-search CDP target:

```bash
./venv/bin/notion-ai cdp-debug --status
./venv/bin/notion-ai cdp-debug --clear
```

Main app tab flow: create or reuse Notion AI conversations and work by token.

```bash
./venv/bin/notion-ai app ask "请只回复：OK" --json
./venv/bin/notion-ai app get-reply --token <token> --json
./venv/bin/notion-ai app get-reply --token <token-1> <token-2> <token-3> --json
./venv/bin/notion-ai app ask --token <token> "继续刚才的话题" --json
./venv/bin/notion-ai app close-conversation --token <token> --json
./venv/bin/notion-ai app status --all --json
```

## Current Behavior

- `ask_and_reply` controls the quick-search target (`https://app.notion.com/quick-search`), waits for completion, and copies the final reply.
- `app ask` creates or resolves a main-app Notion AI page, submits the question, and returns the conversation token.
- `app get-reply` can collect multiple tokens in one command.
- New main-app conversations are serialized with a local lock so concurrent `app ask` calls do not write into the same tab.
- New main-app conversations are bound by CDP target id first; after submit, the user-facing handle is the URL token (`t=...`).
- If a new Notion tab first appears as a blank page, the code navigates that same target id to `https://app.notion.com/ai` and then submits there.

## Known Limits

- `app ask --model ...` / multi-model fan-out currently times out in the model selector UI path.
- Tab Bar label matching can report `activation.ok=false` while `/json/activate/<targetId>` succeeds; CDP input can still work.
- Not every empty URL target has the logged-in Notion context. Direct navigation to `/ai` must verify that the target reaches an AI textbox rather than `/login`.
- Notion copy uses app internals/Electron behavior, so the project triggers React handlers and then reads `pbpaste`.

## Project Map

```text
.
├── README.md
├── PROJECT.md
├── HANDOFF.md
├── docs/
├── pyproject.toml
└── src/notion_ai_local_control/
    ├── __init__.py
    ├── cli.py
    ├── ask_cdp.py
    ├── beta_cdp_input.py
    └── tab_bar_cdp.py
```

## Verification

```bash
./venv/bin/python -m compileall -q src
./venv/bin/notion-ai --help
./venv/bin/notion-ai start --json
./venv/bin/notion-ai cdp-debug --status
./venv/bin/notion-ai ask_and_reply "请只回复：OK" --json --timeout 60
./venv/bin/notion-ai app ask "请只回复：OK" --json
./venv/bin/notion-ai app get-reply --token <token> --json
```
