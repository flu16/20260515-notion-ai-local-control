#!/usr/bin/env python3
"""CDP helpers for Notion desktop's tab bar."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from .beta_cdp_input import CdpError, CdpSession, DEFAULT_PORT, evaluate_js, list_targets


TAB_BAR_URL_PREFIX = "file:///Applications/Notion.app/Contents/Resources/app.asar/.webpack/renderer/tabs/"
NEW_TAB_LABELS = ("新选项卡", "New tab")
NOTION_AI_URL_PREFIXES = (
    "https://app.notion.com/ai",
    "https://www.notion.so/ai",
    "https://app.notion.com/chat",
    "https://www.notion.so/chat",
)


def page_targets(port: int = DEFAULT_PORT) -> list[dict]:
    return [target for target in list_targets(port) if target.get("type") == "page"]


def target_summary(target: dict) -> dict:
    return {
        "id": target.get("id"),
        "title": target.get("title"),
        "url": target.get("url"),
        "type": target.get("type"),
        "conversationToken": extract_conversation_token(target.get("url") or ""),
    }


def is_tab_bar_target(target: dict) -> bool:
    return (
        target.get("type") == "page"
        and target.get("title") == "Tab Bar"
        and (target.get("url") or "").startswith(TAB_BAR_URL_PREFIX)
    )


def find_tab_bar_target(port: int = DEFAULT_PORT) -> dict:
    matches = [target for target in page_targets(port) if is_tab_bar_target(target)]
    if len(matches) == 1:
        return matches[0]
    available = [target_summary(target) for target in page_targets(port)]
    if not matches:
        raise CdpError(f"Notion Tab Bar CDP target not found. Page targets: {available}")
    raise CdpError(f"Expected one Tab Bar target, found {len(matches)}. Page targets: {available}")


def is_notion_ai_target(target: dict) -> bool:
    url = target.get("url") or ""
    return (
        target.get("type") == "page"
        and any(url.startswith(prefix) for prefix in NOTION_AI_URL_PREFIXES)
    )


def find_page_target_by_id(target_id: str, port: int = DEFAULT_PORT) -> dict:
    matches = [target for target in page_targets(port) if target.get("id") == target_id]
    if len(matches) == 1:
        return matches[0]
    available = [target_summary(target) for target in page_targets(port)]
    raise CdpError(f"CDP page target id not found: {target_id}. Page targets: {available}")


def activate_target(target: dict, port: int = DEFAULT_PORT, settle: float = 0.4) -> dict:
    """Bring a target to the foreground so Notion hydrates foreground-only UI."""
    target_id = target.get("id")
    if not target_id:
        return {"ok": False, "error": "target has no id", "target": target_summary(target)}
    url = f"http://127.0.0.1:{port}/json/activate/{urllib.parse.quote(target_id, safe='')}"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            body = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "target": target_summary(target)}
    if settle > 0:
        time.sleep(settle)
    return {"ok": True, "targetId": target_id, "response": body}


def extract_conversation_token(url: str) -> str | None:
    """Extract the conversation token (``t`` query param) from a Notion AI URL."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    tokens = params.get("t")
    if tokens:
        return tokens[0]
    return None


def find_target_by_token(token: str, port: int = DEFAULT_PORT) -> dict:
    """Find a Notion AI CDP target by its conversation token."""
    for target in page_targets(port):
        if is_notion_ai_target(target):
            if extract_conversation_token(target.get("url") or "") == token:
                return target
    available = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "url": t.get("url"),
            "conversationToken": extract_conversation_token(t.get("url") or ""),
        }
        for t in page_targets(port)
        if is_notion_ai_target(t)
    ]
    raise CdpError(f"No Notion AI target with token={token}. Available: {available}")


def _resolve_ai_target(
    *,
    target_id: str | None = None,
    token: str | None = None,
    port: int = DEFAULT_PORT,
) -> dict:
    """Resolve a Notion AI target from a user token or an internal CDP target id."""
    if token:
        target = find_target_by_token(token, port)
        if not is_notion_ai_target(target):
            raise CdpError(f"target for token={token} is not a Notion AI target: {target_summary(target)}")
        return target
    if target_id:
        target = find_page_target_by_id(target_id, port)
        if not is_notion_ai_target(target):
            raise CdpError(f"target {target_id} is not a Notion AI target: {target_summary(target)}")
        return target
    raise CdpError("conversation token is required")


def _target_from_new_tab_result(new_tab: dict, port: int = DEFAULT_PORT) -> dict | None:
    new_target_id = new_tab.get("newTargetId")
    if not new_target_id:
        return None
    return find_page_target_by_id(new_target_id, port)


def _create_ai_target(port: int = DEFAULT_PORT, timeout: float = 10.0) -> tuple[dict | None, dict]:
    new_tab = create_new_conversation_tab(port, timeout=timeout)
    if not new_tab.get("success"):
        return None, new_tab
    try:
        target = _target_from_new_tab_result(new_tab, port)
    except CdpError as exc:
        new_tab["success"] = False
        new_tab["step"] = "find_new_target"
        new_tab["error"] = str(exc)
        return None, new_tab
    if not target:
        new_tab["success"] = False
        new_tab["step"] = "find_new_target"
        new_tab["error"] = "new tab created but no target id returned"
        return None, new_tab
    return target, new_tab


def _resolve_or_create_ai_target(
    *,
    token: str | None = None,
    port: int = DEFAULT_PORT,
    create_timeout: float = 10.0,
) -> tuple[dict | None, dict | None]:
    if token:
        return _resolve_ai_target(token=token, port=port), None
    return _create_ai_target(port=port, timeout=create_timeout)


def wait_target_conversation_token(
    target_id: str,
    *,
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> dict:
    deadline = time.monotonic() + max(timeout, 0)
    last_target = None
    while time.monotonic() < deadline:
        for target in page_targets(port):
            if target.get("id") == target_id:
                last_target = target
                token = extract_conversation_token(target.get("url") or "")
                if token:
                    return {
                        "success": True,
                        "conversationToken": token,
                        "target": target_summary(target),
                    }
                break
        time.sleep(max(interval, 0.05))
    return {
        "success": False,
        "error": f"Timed out waiting for conversation token after {timeout:.1f}s",
        "target": target_summary(last_target) if last_target else None,
    }


def _conversation_url(token: str, *, space_id: str | None = None, port: int = DEFAULT_PORT) -> str:
    """Construct a conversation URL from a token, using the domain from existing targets."""
    domain = "app.notion.com"
    for t in page_targets(port):
        url = t.get("url") or ""
        if is_notion_ai_target(t):
            parsed = urllib.parse.urlparse(url)
            if parsed.netloc:
                domain = parsed.netloc
                break
    url = f"https://{domain}/chat?t={token}&wfv=chat"
    if space_id:
        url += f"&spaceId={space_id}"
    return url


def restore_conversation(
    token: str,
    *,
    space_id: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 15.0,
    interval: float = 0.2,
) -> dict:
    """Restore a Notion AI conversation by creating a new tab and navigating to the conversation URL."""
    conversation_url = _conversation_url(token, space_id=space_id, port=port)

    # Step 1: Create a new tab
    new_tab = create_new_conversation_tab(port, timeout=timeout, interval=interval)
    if not new_tab.get("success"):
        new_tab["conversationToken"] = token
        return new_tab

    new_target_id = new_tab.get("newTargetId")
    if not new_target_id:
        return {
            "success": False,
            "step": "create_tab",
            "error": "new tab created but no target id returned",
            "conversationToken": token,
            "newTab": new_tab,
        }

    # Step 2: Find the new target's WebSocket URL
    targets = page_targets(port)
    new_target = None
    for t in targets:
        if t.get("id") == new_target_id:
            new_target = t
            break

    if not new_target:
        return {
            "success": False,
            "step": "find_target",
            "error": f"new target {new_target_id} not found in page targets",
            "conversationToken": token,
            "newTab": new_tab,
        }

    ws_url = new_target.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "success": False,
            "step": "navigate",
            "error": "no WebSocket URL for new target",
            "conversationToken": token,
            "newTab": new_tab,
        }

    # Step 3: Navigate to the conversation URL
    session = CdpSession(ws_url)
    with session:
        nav_result = session.call("Page.navigate", {"url": conversation_url})

    # Step 4: Wait for the page to load and verify token appears in URL
    deadline = time.monotonic() + max(timeout, 0)
    restored_target = None
    while time.monotonic() < deadline:
        for t in page_targets(port):
            if t.get("id") == new_target_id:
                target_token = extract_conversation_token(t.get("url") or "")
                if target_token == token:
                    restored_target = t
                    break
        if restored_target:
            break
        time.sleep(max(interval, 0.05))

    if not restored_target:
        current_target = None
        for t in page_targets(port):
            if t.get("id") == new_target_id:
                current_target = t
                break
        return {
            "success": False,
            "step": "verify_restored",
            "error": f"Timed out waiting for restored conversation token after {timeout:.1f}s",
            "conversationToken": token,
            "conversationUrl": conversation_url,
            "restoredTarget": target_summary(current_target) if current_target else None,
            "newTab": {
                "newTargetId": new_target_id,
                "conversationToken": new_tab.get("conversationToken"),
            },
            "navigateResult": nav_result,
        }

    return {
        "success": True,
        "conversationToken": token,
        "conversationUrl": conversation_url,
        "restoredTarget": target_summary(restored_target) if restored_target else None,
        "newTab": {
            "newTargetId": new_target_id,
            "conversationToken": new_tab.get("conversationToken"),
        },
        "navigateResult": nav_result,
    }


def tab_bar_state(port: int = DEFAULT_PORT) -> dict:
    target = find_tab_bar_target(port)
    expression = """
(() => {
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const buttons = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        index,
        label: labelFor(node),
        ariaLabel: node.getAttribute("aria-label"),
        title: node.getAttribute("title"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .filter((item) => item.visible || item.label || item.ariaLabel || item.title);
  const conversationTabs = buttons.filter((item) => (
    item.visible &&
    item.label &&
    !item.ariaLabel &&
    item.rect.y === 0 &&
    item.rect.height >= 30 &&
    buttons.some((button) => (
      button.visible &&
      button.ariaLabel === "关闭选项卡 " + item.label &&
      button.rect.x >= item.rect.x &&
      button.rect.x < item.rect.x + item.rect.width &&
      button.rect.y >= item.rect.y &&
      button.rect.y < item.rect.y + item.rect.height
    ))
  ));
  return {
    targetUrl: location.href,
    bodyText: (document.body.textContent || "").trim(),
    buttons,
    conversationTabs,
    conversationTabCount: conversationTabs.length,
  };
})()
"""
    state = evaluate_js(target, expression)
    if not isinstance(state, dict):
        state = {"buttons": [], "conversationTabs": []}
    state["notionAiTargets"] = [
        target_summary(target)
        for target in page_targets(port)
        if is_notion_ai_target(target)
    ]
    return state


def _tab_label_for_target(target: dict) -> str:
    title = (target.get("title") or "").strip()
    return title or "Notion AI"


def get_clipboard_text() -> str:
    result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
    return result.stdout


def _runtime_value(session: CdpSession, expression: str, timeout: float | None = None):
    result = session.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
        timeout=timeout,
    )
    return result.get("result", {}).get("value")


def main_app_status(target: dict) -> dict:
    expression = """
(() => {
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const visible = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const buttons = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        index,
        label: labelFor(node),
        ariaLabel: node.getAttribute("aria-label"),
        dataTestid: node.getAttribute("data-testid"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .filter((item) => item.visible);
  const textboxes = [...document.querySelectorAll('[contenteditable="true"][role="textbox"],[role="textbox"],[contenteditable="true"]')]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        index,
        text: node.textContent || "",
        placeholder: node.getAttribute("placeholder"),
        active: document.activeElement === node,
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .filter((item) => item.visible);
  const bodyText = document.body ? document.body.textContent || "" : "";
  const copyReplies = buttons.filter((button) => (
    !button.disabled && (button.label === "拷贝回复" || button.label === "Copy reply")
  ));
  const hasStop = buttons.some((button) => (
    !button.disabled && (button.label === "停止 AI 消息" || button.label === "Stop AI message")
  ));
  const hasGeneratingText = /Notion AI\\s+正在生成回复|正在生成回复|generating reply|is generating/.test(bodyText);
  const enabledSubmit = buttons.find((button) => (
    !button.disabled &&
    (button.dataTestid === "agent-send-message-button" ||
      button.label === "提交 AI 消息" ||
      button.label === "Submit AI message")
  )) || null;
  const modelButton = buttons.find((button) => button.dataTestid === "unified-chat-model-button") || null;
  return {
    targetUrl: location.href,
    title: document.title,
    textboxes,
    currentModel: modelButton ? modelButton.label : null,
    hasStop,
    hasGeneratingText,
    enabledSubmit,
    copyReplyCount: copyReplies.length,
    bodyTextTail: bodyText.slice(-8000),
  };
})()
"""
    status = evaluate_js(target, expression)
    if isinstance(status, dict):
        status["targetId"] = target.get("id")
        status["targetTitle"] = target.get("title")
        return status
    return {"targetId": target.get("id"), "targetTitle": target.get("title")}


def _focus_main_app_textbox(session: CdpSession) -> dict:
    expression = """
(() => {
  const textbox = [...document.querySelectorAll('[contenteditable="true"][role="textbox"],[role="textbox"],[contenteditable="true"]')]
    .find((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
  if (!textbox) return { ok: false, error: "textbox not found" };
  textbox.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(textbox);
  selection.removeAllRanges();
  selection.addRange(range);
  return {
    ok: true,
    text: textbox.textContent || "",
    active: document.activeElement === textbox,
  };
})()
"""
    result = _runtime_value(session, expression, timeout=12.0)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "focus textbox returned no result"}


def _clear_focused_textbox(session: CdpSession) -> None:
    session.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": "Backspace",
            "code": "Backspace",
            "windowsVirtualKeyCode": 8,
            "nativeVirtualKeyCode": 8,
        },
    )
    session.call(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": "Backspace",
            "code": "Backspace",
            "windowsVirtualKeyCode": 8,
            "nativeVirtualKeyCode": 8,
        },
    )


def _main_app_submit_state(session: CdpSession) -> dict:
    expression = """
(() => {
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const textbox = [...document.querySelectorAll('[contenteditable="true"][role="textbox"],[role="textbox"],[contenteditable="true"]')]
    .find((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
  const submit = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        node,
        index,
        label: labelFor(node),
        dataTestid: node.getAttribute("data-testid"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .find((item) => (
      item.visible &&
      (item.dataTestid === "agent-send-message-button" ||
        item.label === "提交 AI 消息" ||
        item.label === "Submit AI message")
    )) || null;
  return {
    textboxText: textbox ? textbox.textContent || "" : null,
    active: textbox ? document.activeElement === textbox : false,
    submit: submit ? {
      index: submit.index,
      label: submit.label,
      dataTestid: submit.dataTestid,
      disabled: submit.disabled,
      rect: submit.rect,
    } : null,
  };
})()
"""
    result = _runtime_value(session, expression, timeout=12.0)
    return result if isinstance(result, dict) else {"submit": None, "textboxText": None}


def _insert_main_app_text_fallback(session: CdpSession, text: str) -> dict:
    expression = f"""
(() => {{
  const text = {json.dumps(text)};
  const textbox = [...document.querySelectorAll('[contenteditable="true"][role="textbox"],[role="textbox"],[contenteditable="true"]')]
    .find((node) => {{
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }});
  if (!textbox) return {{ ok: false, error: "textbox not found" }};
  textbox.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(textbox);
  selection.removeAllRanges();
  selection.addRange(range);
  let execOk = false;
  try {{
    execOk = document.execCommand("insertText", false, text);
  }} catch (error) {{
    execOk = false;
  }}
  if (!execOk) {{
    textbox.textContent = text;
    textbox.dispatchEvent(new InputEvent("beforeinput", {{
      bubbles: true,
      cancelable: true,
      inputType: "insertText",
      data: text,
    }}));
    textbox.dispatchEvent(new InputEvent("input", {{
      bubbles: true,
      inputType: "insertText",
      data: text,
    }}));
  }}
  textbox.dispatchEvent(new Event("change", {{ bubbles: true }}));
  return {{
    ok: true,
    execOk,
    text: textbox.textContent || "",
    active: document.activeElement === textbox,
  }};
}})()
"""
    result = _runtime_value(session, expression)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "fallback insert returned no result"}


def _select_main_app_model(session: CdpSession, model: str) -> dict:
    expression = f"""
(async () => {{
  const requested = {json.dumps(model)};
  const normalize = (value) => (value || "").toLowerCase().replace(/[\\s_-]+/g, "");
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  let modelButton = null;
  for (let attempt = 0; attempt < 50; attempt++) {{
    modelButton = [...document.querySelectorAll("button,[role='button']")]
      .find((node) => {{
        const rect = node.getBoundingClientRect();
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          node.getAttribute("data-testid") === "unified-chat-model-button"
        );
      }});
    if (modelButton) break;
    await sleep(100);
  }}
  if (!modelButton) return {{ ok: false, error: "model button not found", requested }};

  let before = labelFor(modelButton);
  for (let attempt = 0; !before && attempt < 30; attempt++) {{
    await sleep(100);
    before = labelFor(modelButton);
  }}
  const wanted = normalize(requested);
  if (normalize(before) === wanted) {{
    return {{ ok: true, requested, before, after: before, changed: false }};
  }}

  modelButton.click();
  let items = [];
  let selected = null;
  for (let attempt = 0; attempt < 60; attempt++) {{
    await sleep(100);
    items = [...document.querySelectorAll("button,[role='button'],[role='menuitem'],[role='option']")]
      .map((node, index) => {{
        const rect = node.getBoundingClientRect();
        return {{
          node,
          index,
          label: labelFor(node),
          role: node.getAttribute("role"),
          disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
          visible: rect.width > 0 && rect.height > 0,
          rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
        }};
      }})
      .filter((item) => (
        item.visible &&
        !item.disabled &&
        (item.role === "menuitem" || item.role === "option") &&
        item.label
      ));
    const exact = items.find((item) => normalize(item.label) === wanted);
    const partial = items.find((item) => normalize(item.label).includes(wanted) || wanted.includes(normalize(item.label)));
    selected = exact || partial || null;
    if (selected) break;
  }}
  if (!items.length) {{
    return {{ ok: false, error: "model menu items not found", requested, before }};
  }}

  if (!selected) {{
    return {{
      ok: false,
      error: "requested model not found",
      requested,
      before,
      availableModels: items.map((item) => item.label),
    }};
  }}

  selected.node.click();
  await sleep(150);
  const after = labelFor(modelButton);
  return {{
    ok: true,
    requested,
    before,
    selected: selected.label,
    after,
    changed: normalize(before) !== normalize(after),
  }};
}})()
"""
    result = _runtime_value(session, expression)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "model selection returned no result", "requested": model}


def _current_main_app_model(session: CdpSession, timeout: float = 5.0) -> str | None:
    expression = f"""
(async () => {{
  const deadline = Date.now() + {int(timeout * 1000)};
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  while (Date.now() < deadline) {{
    const modelButton = [...document.querySelectorAll("button,[role='button']")]
      .find((node) => {{
        const rect = node.getBoundingClientRect();
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          node.getAttribute("data-testid") === "unified-chat-model-button"
        );
      }});
    const label = modelButton ? labelFor(modelButton) : "";
    if (label) return label;
    await sleep(100);
  }}
  return null;
}})()
"""
    result = _runtime_value(session, expression, timeout=timeout + 1)
    return result if isinstance(result, str) and result else None


def _click_main_app_submit(session: CdpSession) -> dict:
    expression = """
(() => {
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const matches = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        node,
        index,
        label: labelFor(node),
        dataTestid: node.getAttribute("data-testid"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .filter((item) => (
      item.visible &&
      !item.disabled &&
      (item.dataTestid === "agent-send-message-button" ||
        item.label === "提交 AI 消息" ||
        item.label === "Submit AI message")
    ))
    .sort((a, b) => (b.rect.y - a.rect.y) || (b.rect.x - a.rect.x));
  if (!matches.length) return { ok: false, error: "enabled submit button not found" };
  const selected = matches[0];
  selected.node.click();
  return {
    ok: true,
    submitted: {
      index: selected.index,
      label: selected.label,
      dataTestid: selected.dataTestid,
      rect: selected.rect,
    },
  };
})()
"""
    result = _runtime_value(session, expression)
    if isinstance(result, dict):
        return result
    return {"ok": False, "error": "submit click returned no result"}


def set_main_app_text_and_submit(target: dict, text: str, model: str | None = None) -> dict:
    with CdpSession(target["webSocketDebuggerUrl"]) as session:
        model_selection = None
        current_model = None
        if model:
            model_selection = _select_main_app_model(session, model)
            if not model_selection.get("ok"):
                return {
                    "ok": False,
                    "error": model_selection.get("error"),
                    "modelSelection": model_selection,
                }
            current_model = model_selection.get("after") or model_selection.get("selected")
        else:
            current_model = _current_main_app_model(session)
        focused = _focus_main_app_textbox(session)
        if not focused.get("ok"):
            return focused
        _clear_focused_textbox(session)
        session.call("Input.insertText", {"text": text})
        state = None
        fallback_insert = None
        for attempt in range(40):
            state = _main_app_submit_state(session)
            submit = state.get("submit") if isinstance(state, dict) else None
            textbox_text = state.get("textboxText") if isinstance(state, dict) else None
            if attempt == 10 and not textbox_text:
                fallback_insert = _insert_main_app_text_fallback(session, text)
            if submit and not submit.get("disabled"):
                break
            time.sleep(0.05)
        else:
            return {
                "ok": False,
                "error": "submit button not found or disabled",
                "inputMethod": "Input.insertText",
                "fallbackInsert": fallback_insert,
                "state": state,
            }
        clicked = _click_main_app_submit(session)
        if not clicked.get("ok"):
            return {
                "ok": False,
                "error": clicked.get("error"),
                "inputMethod": "Input.insertText",
                "state": state,
                "clicked": clicked,
            }
        return {
            "ok": True,
            "inputMethod": "Input.insertText",
            "currentModel": current_model,
            "modelSelection": model_selection,
            "fallbackInsert": fallback_insert,
            "state": state,
            "submitted": clicked.get("submitted"),
        }


def _question_markers(question: str) -> tuple[str, str]:
    compact = " ".join(question.strip().split())[:120]
    dense = "".join(compact.split())
    return compact, dense


def wait_main_app_generation_finished(
    target: dict,
    question: str,
    before_copy_count: int,
    timeout: float = 300.0,
    interval: float = 0.5,
) -> dict:
    compact_marker, dense_marker = _question_markers(question)
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        status = main_app_status(target)
        last_status = status
        body = status.get("bodyTextTail") or ""
        compact_body = " ".join(body.split())
        dense_body = "".join(body.split())
        saw_question = (
            bool(compact_marker)
            and (compact_marker in compact_body or (dense_marker and dense_marker in dense_body))
        )
        if (
            saw_question
            and not status.get("hasStop")
            and not status.get("hasGeneratingText")
            and status.get("copyReplyCount", 0) > before_copy_count
        ):
            return {"success": True, "state": status, "error": None}
        time.sleep(max(interval, 0.05))
    return {
        "success": False,
        "state": last_status,
        "error": f"Timed out waiting for main app generation to finish after {timeout:.1f}s",
    }


def copy_main_app_latest_reply(target: dict, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last_clicked = None
    while time.monotonic() < deadline:
        expression = """
(() => {
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const matches = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        node,
        index,
        label: labelFor(node),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      };
    })
    .filter((item) => (
      item.visible &&
      !item.disabled &&
      (item.label === "拷贝回复" || item.label === "Copy reply")
    ))
    .sort((a, b) => (b.rect.y - a.rect.y) || (b.rect.x - a.rect.x));
  if (!matches.length) return { ok: false, error: "copy reply button not found" };
  const selected = matches[0];
  selected.node.click();
  return {
    ok: true,
    index: selected.index,
    label: selected.label,
    rect: selected.rect,
  };
})()
"""
        clicked = evaluate_js(target, expression)
        last_clicked = clicked
        if isinstance(clicked, dict) and clicked.get("ok"):
            time.sleep(0.3)
            text = get_clipboard_text().strip()
            if text:
                return {"success": True, "text": text, "copy_button_info": clicked, "error": None}
        time.sleep(0.2)
    return {
        "success": False,
        "text": "",
        "copy_button_info": last_clicked,
        "error": "copy reply timed out or clipboard was empty",
    }


def _model_from_submission(submitted: dict, fallback_status: dict | None = None) -> str | None:
    if isinstance(submitted, dict) and submitted.get("currentModel"):
        return submitted.get("currentModel")
    model_selection = submitted.get("modelSelection") if isinstance(submitted, dict) else None
    if isinstance(model_selection, dict):
        selected_model = model_selection.get("after") or model_selection.get("selected")
        if selected_model:
            return selected_model
    if fallback_status:
        return fallback_status.get("currentModel")
    return None


def ask_and_reply_main_app_target(
    question: str = "",
    *,
    token: str | None = None,
    model: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 300.0,
    token_timeout: float = 10.0,
) -> dict:
    started_at = time.time()
    target, new_tab = _resolve_or_create_ai_target(token=token, port=port)
    if not target:
        return {
            "success": False,
            "step": "create_tab",
            "text": "",
            "error": (new_tab or {}).get("error"),
            "newTab": new_tab,
        }
    if not is_notion_ai_target(target):
        return {
            "success": False,
            "step": "validate_target",
            "error": "target is not a Notion AI main app page",
            "target": target_summary(target),
        }
    activation = foreground_target(target, port=port)
    before_status = main_app_status(target)
    submitted = set_main_app_text_and_submit(target, question, model=model)
    if not submitted.get("ok"):
        return {
            "success": False,
            "step": "input_submit",
            "text": "",
            "error": submitted.get("error"),
            "target": target_summary(target),
            "activation": activation,
            "details": submitted,
            "initial_state": before_status,
        }
    token_result = None
    if not token:
        token_result = wait_target_conversation_token(
            target.get("id"),
            port=port,
            timeout=token_timeout,
        )
        if not token_result.get("success"):
            return {
                "success": False,
                "step": "wait_token",
                "text": "",
                "error": token_result.get("error"),
                "target": target_summary(target),
                "activation": activation,
                "newTab": new_tab,
                "input": submitted,
                "tokenResult": token_result,
            }
    finished = wait_main_app_generation_finished(
        target,
        question,
        before_copy_count=before_status.get("copyReplyCount", 0),
        timeout=timeout,
    )
    if not finished.get("success"):
        return {
            "success": False,
            "step": "wait_finished",
            "text": "",
            "error": finished.get("error"),
            "target": target_summary(target),
            "activation": activation,
            "conversationToken": token or (token_result or {}).get("conversationToken"),
            "tokenResult": token_result,
            "final_state": finished.get("state"),
        }
    copied = copy_main_app_latest_reply(target)
    if not copied.get("success"):
        return {
            "success": False,
            "step": "copy",
            "text": "",
            "error": copied.get("error"),
            "target": target_summary(target),
            "activation": activation,
            "conversationToken": token or (token_result or {}).get("conversationToken"),
            "tokenResult": token_result,
            "final_state": finished.get("state"),
        }
    final_target = find_page_target_by_id(target.get("id"), port)
    conversation_token = token or (token_result or {}).get("conversationToken") or extract_conversation_token(final_target.get("url") or "")
    model_used = _model_from_submission(submitted, finished.get("state"))
    return {
        "success": True,
        "text": copied.get("text"),
        "model": model_used,
        "elapsed": round(time.time() - started_at, 2),
        "conversationToken": conversation_token,
        "target": target_summary(final_target),
        "activation": activation,
        "newTab": new_tab,
        "tokenResult": token_result,
        "input": submitted,
        "final_state": finished.get("state"),
        "copy_button_info": copied.get("copy_button_info"),
        "error": None,
    }


def ask_main_app_target(
    question: str = "",
    *,
    token: str | None = None,
    model: str | None = None,
    port: int = DEFAULT_PORT,
    token_timeout: float = 10.0,
) -> dict:
    """Submit a question to a Notion AI conversation and return immediately."""
    started_at = time.time()
    target, new_tab = _resolve_or_create_ai_target(token=token, port=port)
    if not target:
        return {
            "success": False,
            "step": "create_tab",
            "error": (new_tab or {}).get("error"),
            "newTab": new_tab,
        }
    if not is_notion_ai_target(target):
        return {
            "success": False,
            "step": "validate_target",
            "error": "target is not a Notion AI main app page",
            "target": target_summary(target),
        }
    activation = foreground_target(target, port=port)
    submitted = set_main_app_text_and_submit(target, question, model=model)
    if not submitted.get("ok"):
        return {
            "success": False,
            "step": "input_submit",
            "error": submitted.get("error"),
            "target": target_summary(target),
            "activation": activation,
            "details": submitted,
        }
    token_result = None
    if not token:
        token_result = wait_target_conversation_token(
            target.get("id"),
            port=port,
            timeout=token_timeout,
        )
        if not token_result.get("success"):
            return {
                "success": False,
                "step": "wait_token",
                "error": token_result.get("error"),
                "target": target_summary(target),
                "activation": activation,
                "newTab": new_tab,
                "input": submitted,
                "tokenResult": token_result,
            }
    final_target = find_page_target_by_id(target.get("id"), port)
    current_status = main_app_status(final_target)
    conversation_token = token or (token_result or {}).get("conversationToken") or extract_conversation_token(final_target.get("url") or "")
    model_used = _model_from_submission(submitted, current_status)
    return {
        "success": True,
        "elapsed": round(time.time() - started_at, 2),
        "model": model_used,
        "conversationToken": conversation_token,
        "target": target_summary(final_target),
        "activation": activation,
        "status": {"currentModel": current_status.get("currentModel")},
        "newTab": new_tab,
        "tokenResult": token_result,
        "input": submitted,
        "error": None,
    }


def ask_multi_model_main_app(
    question: str,
    models: list[str],
    *,
    port: int = DEFAULT_PORT,
    token_timeout: float = 10.0,
) -> dict:
    started_at = time.time()
    results = []
    for model in models:
        result = ask_main_app_target(
            question=question,
            model=model,
            port=port,
            token_timeout=token_timeout,
        )
        result["requestedModel"] = model
        results.append(result)
    return {
        "success": all(result.get("success") for result in results),
        "elapsed": round(time.time() - started_at, 2),
        "question": question,
        "models": models,
        "results": results,
    }


def reply_main_app_target(
    target_id: str | None = None,
    *,
    token: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 300.0,
) -> dict:
    """Wait for generation to finish in a Notion AI conversation, then copy the reply."""
    target = _resolve_ai_target(target_id=target_id, token=token, port=port)
    activation = foreground_target(target, port=port)
    if not is_notion_ai_target(target):
        return {
            "success": False,
            "step": "validate_target",
            "error": "target is not a Notion AI main app page",
            "target": target_summary(target),
            "activation": activation,
        }
    status = main_app_status(target)
    if status.get("hasStop") or status.get("hasGeneratingText"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = main_app_status(target)
            if not status.get("hasStop") and not status.get("hasGeneratingText"):
                break
            time.sleep(0.5)
    if status.get("hasStop") or status.get("hasGeneratingText"):
        return {
            "success": False,
            "step": "wait_finished",
            "error": f"still generating after {timeout:.0f}s",
            "target": target_summary(target),
            "activation": activation,
            "status": status,
        }
    copy_count = status.get("copyReplyCount", 0)
    if copy_count <= 0:
        return {
            "success": False,
            "step": "no_reply",
            "error": "no copyable reply found",
            "target": target_summary(target),
            "activation": activation,
            "status": status,
        }
    copied = copy_main_app_latest_reply(target)
    if not copied.get("success"):
        return {
            "success": False,
            "step": "copy",
            "error": copied.get("error"),
            "target": target_summary(target),
            "activation": activation,
            "status": status,
        }
    return {
        "success": True,
        "text": copied.get("text"),
        "model": status.get("currentModel"),
        "target": target_summary(target),
        "activation": activation,
        "copy_button_info": copied.get("copy_button_info"),
        "status": status,
        "error": None,
    }


def reply_all_main_app(port: int = DEFAULT_PORT) -> dict:
    """Sweep all AI conversation tabs once and copy idle replies where available."""
    ai_targets = [t for t in page_targets(port) if is_notion_ai_target(t)]
    tabs = []
    for t in ai_targets:
        token = extract_conversation_token(t.get("url") or "")
        activation = foreground_target(t, port=port)
        status = main_app_status(t)
        tab_info = {
            "conversationToken": token,
            "targetId": t.get("id"),
            "activation": activation,
            "title": status.get("title") or t.get("title"),
            "model": status.get("currentModel"),
            "hasStop": status.get("hasStop"),
            "hasGeneratingText": status.get("hasGeneratingText"),
            "copyReplyCount": status.get("copyReplyCount", 0),
        }
        if status.get("hasStop") or status.get("hasGeneratingText"):
            tab_info["state"] = "generating"
        elif status.get("copyReplyCount", 0) > 0:
            tab_info["state"] = "idle"
        else:
            tab_info["state"] = "empty"
        # Try to copy reply if idle with copyable replies
        if tab_info["state"] == "idle":
            copied = copy_main_app_latest_reply(t)
            tab_info["text"] = copied.get("text") if copied.get("success") else None
            tab_info["copyError"] = copied.get("error") if not copied.get("success") else None
        tabs.append(tab_info)
    return {"success": True, "tabs": tabs}


def get_replies_main_app(tokens: list[str], *, port: int = DEFAULT_PORT, timeout: float = 300.0) -> dict:
    started_at = time.time()
    results = []
    for token in tokens:
        result = reply_main_app_target(token=token, port=port, timeout=timeout)
        result["conversationToken"] = token
        results.append(result)
    return {
        "success": all(result.get("success") for result in results),
        "elapsed": round(time.time() - started_at, 2),
        "results": results,
    }


def click_new_tab_button(port: int = DEFAULT_PORT) -> dict:
    target = find_tab_bar_target(port)
    expression = f"""
(() => {{
  const labels = new Set({json.dumps(list(NEW_TAB_LABELS))});
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const matches = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {{
      const rect = node.getBoundingClientRect();
      return {{
        node,
        index,
        label: labelFor(node),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }})
    .filter((item) => item.visible && !item.disabled && labels.has(item.label))
    .sort((a, b) => (b.rect.x - a.rect.x) || (b.rect.y - a.rect.y));
  if (!matches.length) {{
    return {{ ok: false, error: "new tab button not found or disabled" }};
  }}
  const selected = matches[0];
  selected.node.click();
  return {{
    ok: true,
    index: selected.index,
    label: selected.label,
    rect: selected.rect,
  }};
}})()
"""
    result = evaluate_js(target, expression)
    return result if isinstance(result, dict) else {"ok": False, "error": "click returned no result"}


def click_conversation_tab_button(target_to_select: dict, port: int = DEFAULT_PORT) -> dict:
    target = find_tab_bar_target(port)
    tab_label = _tab_label_for_target(target_to_select)
    same_label_targets = [
        target
        for target in page_targets(port)
        if is_notion_ai_target(target) and _tab_label_for_target(target) == tab_label
    ]
    duplicate_ordinal = next(
        (index for index, target in enumerate(same_label_targets) if target.get("id") == target_to_select.get("id")),
        0,
    )
    expression = f"""
(() => {{
  const tabLabel = {json.dumps(tab_label)};
  const duplicateOrdinal = {duplicate_ordinal};
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const buttons = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {{
      const rect = node.getBoundingClientRect();
      return {{
        node,
        index,
        label: labelFor(node),
        ariaLabel: node.getAttribute("aria-label"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }});
  const tabs = buttons.filter((item) => (
    item.visible &&
    item.label &&
    !item.ariaLabel &&
    item.rect.y === 0 &&
    item.rect.height >= 30 &&
    buttons.some((button) => (
      button.visible &&
      button.ariaLabel === "关闭选项卡 " + item.label &&
      button.rect.x >= item.rect.x &&
      button.rect.x < item.rect.x + item.rect.width &&
      button.rect.y >= item.rect.y &&
      button.rect.y < item.rect.y + item.rect.height
    ))
  ));
  const matchingTabs = tabs.filter((item) => item.label === tabLabel);
  if (!matchingTabs.length) {{
    return {{
      ok: false,
      error: `expected at least one tab labelled "${{tabLabel}}", found 0`,
      tabLabel,
      tabs: tabs.map((item) => ({{
        index: item.index,
        label: item.label,
        rect: item.rect,
      }})),
    }};
  }}
  const tab = matchingTabs[Math.min(duplicateOrdinal, matchingTabs.length - 1)];
  tab.node.click();
  return {{
    ok: true,
    tabLabel,
    duplicateOrdinal,
    index: tab.index,
    rect: tab.rect,
  }};
}})()
"""
    result = evaluate_js(target, expression)
    if isinstance(result, dict) and result.get("ok"):
        time.sleep(0.4)
    return result if isinstance(result, dict) else {"ok": False, "error": "click returned no result"}


def foreground_target(target: dict, port: int = DEFAULT_PORT) -> dict:
    tab_click = click_conversation_tab_button(target, port=port)
    activation = activate_target(target, port=port)
    return {
        "ok": bool(tab_click.get("ok")) and bool(activation.get("ok")),
        "tabClick": tab_click,
        "activation": activation,
    }


def click_close_conversation_tab_button(target_to_close: dict, port: int = DEFAULT_PORT) -> dict:
    target = find_tab_bar_target(port)
    tab_label = _tab_label_for_target(target_to_close)
    same_label_targets = [
        target
        for target in page_targets(port)
        if is_notion_ai_target(target) and _tab_label_for_target(target) == tab_label
    ]
    duplicate_ordinal = next(
        (index for index, target in enumerate(same_label_targets) if target.get("id") == target_to_close.get("id")),
        0,
    )
    expression = f"""
(() => {{
  const tabLabel = {json.dumps(tab_label)};
  const duplicateOrdinal = {duplicate_ordinal};
  const labelFor = (node) => (
    node.textContent ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const buttons = [...document.querySelectorAll("button,[role='button']")]
    .map((node, index) => {{
      const rect = node.getBoundingClientRect();
      return {{
        node,
        index,
        label: labelFor(node),
        ariaLabel: node.getAttribute("aria-label"),
        disabled: !!node.disabled || node.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }});
  const tabs = buttons.filter((item) => (
    item.visible &&
    item.label &&
    !item.ariaLabel &&
    item.rect.y === 0 &&
    item.rect.height >= 30 &&
    buttons.some((button) => (
      button.visible &&
      button.ariaLabel === "关闭选项卡 " + item.label &&
      button.rect.x >= item.rect.x &&
      button.rect.x < item.rect.x + item.rect.width &&
      button.rect.y >= item.rect.y &&
      button.rect.y < item.rect.y + item.rect.height
    ))
  ));
  const matchingTabs = tabs.filter((item) => item.label === tabLabel);
  if (!matchingTabs.length) {{
    return {{
      ok: false,
      error: `expected at least one tab labelled "${{tabLabel}}", found 0`,
      tabLabel,
      tabs: tabs.map((item) => ({{
        index: item.index,
        label: item.label,
        rect: item.rect,
      }})),
    }};
  }}
  const tab = matchingTabs[Math.min(duplicateOrdinal, matchingTabs.length - 1)];
  const closeButton = buttons.find((item) => (
    item.visible &&
    !item.disabled &&
    item.ariaLabel === `关闭选项卡 ${{tab.label}}` &&
    item.rect.x >= tab.rect.x &&
    item.rect.x < tab.rect.x + tab.rect.width &&
    item.rect.y >= tab.rect.y &&
    item.rect.y < tab.rect.y + tab.rect.height
  ));
  if (!closeButton) {{
    return {{
      ok: false,
      error: "close tab button not found or disabled",
      tab: {{ index: tab.index, label: tab.label, rect: tab.rect }},
      closeButtons: buttons
        .filter((item) => item.visible && item.ariaLabel && item.ariaLabel.startsWith("关闭选项卡"))
        .map(({{ node, ...item }}) => item),
    }};
  }}
  closeButton.node.click();
  return {{
    ok: true,
    tabLabel,
    tab: {{ index: tab.index, label: tab.label, rect: tab.rect }},
    closeButton: {{
      index: closeButton.index,
      label: closeButton.label,
      ariaLabel: closeButton.ariaLabel,
      rect: closeButton.rect,
    }},
  }};
}})()
"""
    clicked = evaluate_js(target, expression)
    if isinstance(clicked, dict):
        clicked.setdefault("selectedTarget", target_summary(target_to_close))
        return clicked
    return {"ok": False, "error": "close click returned no result", "selectedTarget": target_summary(target_to_close)}


def create_new_conversation_tab(
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
    interval: float = 0.2,
) -> dict:
    before_targets = page_targets(port)
    before_ids = {target.get("id") for target in before_targets}
    before_ai_ids = {target.get("id") for target in before_targets if is_notion_ai_target(target)}
    before_tab_bar = tab_bar_state(port)

    clicked = click_new_tab_button(port)
    if not clicked.get("ok"):
        return {
            "success": False,
            "step": "click_new_tab",
            "error": clicked.get("error"),
            "clicked": clicked,
            "beforeTargets": [target_summary(target) for target in before_targets],
            "beforeTabBar": before_tab_bar,
        }

    deadline = time.monotonic() + max(timeout, 0)
    last_targets = before_targets
    last_tab_bar = before_tab_bar
    while True:
        current_targets = page_targets(port)
        current_ids = {target.get("id") for target in current_targets}
        new_targets = [target for target in current_targets if target.get("id") not in before_ids]
        new_ai_targets = [target for target in current_targets if is_notion_ai_target(target) and target.get("id") not in before_ai_ids]
        last_targets = current_targets
        try:
            last_tab_bar = tab_bar_state(port)
        except CdpError:
            pass

        if new_ai_targets:
            selected = new_ai_targets[0]
            return {
                "success": True,
                "clicked": clicked,
                "newTargetId": selected.get("id"),
                "newTarget": target_summary(selected),
                "newAiTargets": [target_summary(target) for target in new_ai_targets],
                "newTargets": [target_summary(target) for target in new_targets],
                "beforeTabBar": {
                    "conversationTabCount": before_tab_bar.get("conversationTabCount"),
                    "bodyText": before_tab_bar.get("bodyText"),
                },
                "afterTabBar": {
                    "conversationTabCount": last_tab_bar.get("conversationTabCount"),
                    "bodyText": last_tab_bar.get("bodyText"),
                },
            }

        if time.monotonic() >= deadline:
            return {
                "success": False,
                "step": "wait_new_ai_target",
                "error": f"Timed out waiting for a new Notion AI target after {timeout:.1f}s",
                "clicked": clicked,
                "newTargets": [target_summary(target) for target in last_targets if target.get("id") not in before_ids],
                "pageTargets": [target_summary(target) for target in last_targets],
                "beforeTabBar": {
                    "conversationTabCount": before_tab_bar.get("conversationTabCount"),
                    "bodyText": before_tab_bar.get("bodyText"),
                },
                "afterTabBar": {
                    "conversationTabCount": last_tab_bar.get("conversationTabCount"),
                    "bodyText": last_tab_bar.get("bodyText"),
                },
            }

        time.sleep(max(interval, 0.05))


def close_conversation_target(
    target_id: str | None = None,
    *,
    token: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
    interval: float = 0.2,
    force: bool = False,
) -> dict:
    target = _resolve_ai_target(target_id=target_id, token=token, port=port)
    resolved_target_id = target.get("id")
    before_targets = page_targets(port)
    before_ai_targets = [target for target in before_targets if is_notion_ai_target(target)]
    before_tab_bar = tab_bar_state(port)

    if not is_notion_ai_target(target) and not force:
        return {
            "success": False,
            "step": "validate_target",
            "error": "refusing to close a non-Notion-AI target without --force",
            "target": target_summary(target),
            "beforeTargets": [target_summary(target) for target in before_targets],
            "beforeTabBar": before_tab_bar,
        }
    if len(before_ai_targets) <= 1 and is_notion_ai_target(target) and not force:
        return {
            "success": False,
            "step": "validate_target",
            "error": "refusing to close the last Notion AI target without --force",
            "target": target_summary(target),
            "beforeTargets": [target_summary(target) for target in before_targets],
            "beforeTabBar": before_tab_bar,
        }

    clicked = click_close_conversation_tab_button(target, port=port)
    if not clicked.get("ok"):
        return {
            "success": False,
            "step": "click_close_tab",
            "error": clicked.get("error"),
            "target": target_summary(target),
            "clicked": clicked,
            "beforeTargets": [target_summary(target) for target in before_targets],
            "beforeTabBar": before_tab_bar,
        }

    deadline = time.monotonic() + max(timeout, 0)
    last_targets = before_targets
    last_tab_bar = before_tab_bar
    while True:
        current_targets = page_targets(port)
        current_ai_targets = [target for target in current_targets if is_notion_ai_target(target)]
        last_targets = current_targets
        try:
            last_tab_bar = tab_bar_state(port)
        except CdpError:
            pass

        target_closed = not any(target.get("id") == resolved_target_id for target in current_targets)
        ai_target_count_decreased = len(current_ai_targets) < len(before_ai_targets)
        tab_count_decreased = (
            last_tab_bar.get("conversationTabCount") is not None
            and last_tab_bar.get("conversationTabCount") < before_tab_bar.get("conversationTabCount", 0)
        )
        if target_closed or ai_target_count_decreased or tab_count_decreased:
            before_ids = {target.get("id") for target in before_targets}
            current_ids = {target.get("id") for target in current_targets}
            closed_targets = [target for target in before_targets if target.get("id") not in current_ids]
            return {
                "success": True,
                "closedTarget": target_summary(target),
                "clicked": clicked,
                "closedTargets": [target_summary(target) for target in closed_targets],
                "beforeTabBar": {
                    "conversationTabCount": before_tab_bar.get("conversationTabCount"),
                    "bodyText": before_tab_bar.get("bodyText"),
                },
                "afterTabBar": {
                    "conversationTabCount": last_tab_bar.get("conversationTabCount"),
                    "bodyText": last_tab_bar.get("bodyText"),
                },
            }

        if time.monotonic() >= deadline:
            return {
                "success": False,
                "step": "wait_tab_closed",
                "error": f"Timed out waiting for tab close after {timeout:.1f}s",
                "closedTarget": target_summary(target),
                "clicked": clicked,
                "pageTargets": [target_summary(target) for target in last_targets],
                "beforeTabBar": {
                    "conversationTabCount": before_tab_bar.get("conversationTabCount"),
                    "bodyText": before_tab_bar.get("bodyText"),
                },
                "afterTabBar": {
                    "conversationTabCount": last_tab_bar.get("conversationTabCount"),
                    "bodyText": last_tab_bar.get("bodyText"),
                },
            }

        time.sleep(max(interval, 0.05))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control Notion desktop main app tabs through CDP.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    state = subparsers.add_parser("tab-bar-state", help="Inspect the Notion desktop Tab Bar target.")
    state.add_argument("--port", type=int, default=DEFAULT_PORT)
    state.add_argument("--json", action="store_true")

    restore = subparsers.add_parser(
        "restore-conversation",
        help="Restore a Notion AI conversation by creating a new tab and navigating to the conversation URL.",
    )
    restore.add_argument("--token", required=True, help="Conversation token to restore (from URL t query param)")
    restore.add_argument("--space-id", help="Notion workspace space ID (optional, inferred if omitted)")
    restore.add_argument("--port", type=int, default=DEFAULT_PORT)
    restore.add_argument("--timeout", type=float, default=15.0)
    restore.add_argument("--json", action="store_true")

    status = subparsers.add_parser(
        "status",
        help="Check the generation status of Notion AI conversations.",
    )
    status.add_argument("--token", help="Conversation token to check (from URL t query param)")
    status.add_argument("--all", action="store_true", help="Show status of all open AI conversation tabs")
    status.add_argument("--port", type=int, default=DEFAULT_PORT)
    status.add_argument("--json", action="store_true")

    close = subparsers.add_parser(
        "close-conversation",
        help="Close a Notion AI conversation tab by conversation token.",
    )
    close.add_argument("--token", required=True, help="Conversation token to close (from URL t query param)")
    close.add_argument("--port", type=int, default=DEFAULT_PORT)
    close.add_argument("--timeout", type=float, default=10.0)
    close.add_argument("--force", action="store_true", help="Allow closing the last Notion AI tab")
    close.add_argument("--json", action="store_true")

    ask = subparsers.add_parser(
        "ask",
        help="Submit a question to a Notion AI conversation and return immediately.",
    )
    ask.add_argument("question", nargs="?", help="Question to submit")
    ask.add_argument("--token", help="Conversation token to continue; omitted means create a new conversation")
    ask.add_argument(
        "--model",
        nargs="+",
        help="AI model label(s) to select before submitting; multiple labels create one new conversation per model",
    )
    ask.add_argument("--from-stdin", action="store_true", help="Read question from stdin")
    ask.add_argument("--from-clipboard", action="store_true", help="Read question from the system clipboard")
    ask.add_argument("--port", type=int, default=DEFAULT_PORT)
    ask.add_argument("--token-timeout", type=float, default=10.0, help="Seconds to wait for a new conversation token")
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--quiet", action="store_true")

    ask_and_reply = subparsers.add_parser(
        "ask-and-reply",
        help="Ask a question, wait for generation to finish, and copy the reply.",
    )
    ask_and_reply.add_argument("question", nargs="?", help="Question to submit")
    ask_and_reply.add_argument("--token", help="Conversation token to continue; omitted means create a new conversation")
    ask_and_reply.add_argument(
        "--model",
        nargs="+",
        help="AI model label to select before submitting, e.g. 'GPT-5.5' or 'Opus 4.8'",
    )
    ask_and_reply.add_argument("--from-stdin", action="store_true", help="Read question from stdin")
    ask_and_reply.add_argument("--from-clipboard", action="store_true", help="Read question from the system clipboard")
    ask_and_reply.add_argument("--port", type=int, default=DEFAULT_PORT)
    ask_and_reply.add_argument("--timeout", type=float, default=300.0)
    ask_and_reply.add_argument("--token-timeout", type=float, default=10.0, help="Seconds to wait for a new conversation token")
    ask_and_reply.add_argument("--json", action="store_true")
    ask_and_reply.add_argument("--quiet", action="store_true")

    get_reply = subparsers.add_parser(
        "get-reply",
        aliases=["get_reply"],
        help="Copy replies from Notion AI conversations.",
    )
    get_reply.add_argument("--token", nargs="+", help="Conversation token(s) to get replies from")
    get_reply.add_argument("--all", action="store_true", help="Sweep all AI conversation tabs once and copy idle replies")
    get_reply.add_argument("--port", type=int, default=DEFAULT_PORT)
    get_reply.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for a single --token reply; ignored with --all")
    get_reply.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "tab-bar-state":
            result = tab_bar_state(args.port)
        elif args.command == "restore-conversation":
            result = restore_conversation(
                token=args.token,
                space_id=args.space_id,
                port=args.port,
                timeout=args.timeout,
            )
        elif args.command == "status":
            if args.all:
                ai_targets = [t for t in page_targets(args.port) if is_notion_ai_target(t)]
                tabs = []
                for t in ai_targets:
                    activation = foreground_target(t, port=args.port)
                    s = main_app_status(t)
                    s["activation"] = activation
                    s["conversationToken"] = extract_conversation_token(t.get("url") or "")
                    tabs.append(s)
                result = {"success": True, "tabs": tabs}
            else:
                if not args.token:
                    raise CdpError("either --token or --all is required")
                target = _resolve_ai_target(token=args.token, port=args.port)
                activation = foreground_target(target, port=args.port)
                result = main_app_status(target)
                result["activation"] = activation
                result["success"] = True
        elif args.command == "close-conversation":
            result = close_conversation_target(
                token=args.token,
                port=args.port,
                timeout=args.timeout,
                force=args.force,
            )
        elif args.command == "ask":
            model_values = list(args.model or [])
            question_from_model_tail = None
            if args.question is None and len(model_values) > 1:
                question_from_model_tail = model_values.pop()
            source_count = sum([
                bool(args.from_stdin),
                bool(args.from_clipboard),
                args.question is not None or question_from_model_tail is not None,
            ])
            if source_count > 1:
                raise CdpError("--from-stdin, --from-clipboard, and question are mutually exclusive")
            if args.from_stdin:
                question = sys.stdin.read()
            elif args.from_clipboard:
                question = get_clipboard_text()
            elif question_from_model_tail is not None:
                question = question_from_model_tail
            else:
                question = args.question
            if not question:
                raise CdpError("question is required")
            models = model_values
            if len(models) > 1:
                if args.token:
                    raise CdpError("--token cannot be used with multiple --model values")
                result = ask_multi_model_main_app(
                    question=question,
                    models=models,
                    port=args.port,
                    token_timeout=args.token_timeout,
                )
            else:
                result = ask_main_app_target(
                    question=question,
                    token=args.token,
                    model=models[0] if models else None,
                    port=args.port,
                    token_timeout=args.token_timeout,
                )
        elif args.command == "ask-and-reply":
            model_values = list(args.model or [])
            question_from_model_tail = None
            if args.question is None and len(model_values) > 1:
                question_from_model_tail = model_values.pop()
            source_count = sum([
                bool(args.from_stdin),
                bool(args.from_clipboard),
                args.question is not None or question_from_model_tail is not None,
            ])
            if source_count > 1:
                raise CdpError("--from-stdin, --from-clipboard, and question are mutually exclusive")
            if args.from_stdin:
                question = sys.stdin.read()
            elif args.from_clipboard:
                question = get_clipboard_text()
            elif question_from_model_tail is not None:
                question = question_from_model_tail
            else:
                question = args.question
            if not question:
                raise CdpError("question is required")
            models = model_values
            if len(models) > 1:
                raise CdpError("ask-and-reply supports at most one --model value")
            result = ask_and_reply_main_app_target(
                question=question,
                token=args.token,
                model=models[0] if models else None,
                port=args.port,
                timeout=args.timeout,
                token_timeout=args.token_timeout,
            )
        elif args.command in ("get-reply", "get_reply"):
            if args.all:
                result = reply_all_main_app(port=args.port)
            else:
                if not args.token:
                    raise CdpError("either --token or --all is required")
                if len(args.token) == 1:
                    result = reply_main_app_target(
                        token=args.token[0],
                        port=args.port,
                        timeout=args.timeout,
                    )
                    result["conversationToken"] = args.token[0]
                else:
                    result = get_replies_main_app(
                        tokens=args.token,
                        port=args.port,
                        timeout=args.timeout,
                    )
        else:
            raise CdpError(f"Unsupported command: {args.command}")
    except CdpError as exc:
        result = {"success": False, "error": str(exc)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if result.get("success") is False:
            print(f"失败: {result.get('error')}", file=sys.stderr)
        elif args.command == "restore-conversation":
            restored = result.get("restoredTarget") or {}
            token_out = result.get("conversationToken")
            if token_out:
                print(token_out)
            elif restored.get("id"):
                print(restored.get("id"))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        elif args.command == "status":
            if args.all and isinstance(result.get("tabs"), list):
                for tab in result["tabs"]:
                    state = "generating" if (tab.get("hasStop") or tab.get("hasGeneratingText")) else "idle"
                    copies = tab.get("copyReplyCount", 0)
                    token = tab.get("conversationToken") or "-"
                    title = tab.get("targetTitle") or tab.get("title") or "-"
                    print(f"  {title:<20} token={token[:12]}...  {state}  copies={copies}")
            else:
                has_stop = result.get("hasStop")
                has_gen = result.get("hasGeneratingText")
                copy_count = result.get("copyReplyCount", 0)
                if has_stop or has_gen:
                    print(f"generating  stop={has_stop}  generatingText={has_gen}")
                elif copy_count > 0:
                    print(f"idle  copyable_replies={copy_count}")
                else:
                    print("idle  no_replies")
        elif args.command == "close-conversation":
            print(f"已关闭对话: {args.token}")
        elif args.command == "ask":
            if isinstance(result.get("results"), list):
                for item in result["results"]:
                    model = item.get("model") or item.get("requestedModel") or "-"
                    token = item.get("conversationToken") or "-"
                    print(f"{model}\t{token}")
            else:
                print(result.get("conversationToken") or "")
        elif args.command == "ask-and-reply":
            print(result.get("text", ""))
        elif args.command in ("get-reply", "get_reply"):
            if isinstance(result.get("results"), list):
                for item in result["results"]:
                    token = item.get("conversationToken") or "-"
                    model = item.get("model") or "-"
                    if item.get("success"):
                        text_preview = (item.get("text") or "")[:80].replace("\n", " ")
                        print(f"{token}\t{model}\t{text_preview}")
                    else:
                        print(f"{token}\t{model}\t失败: {item.get('error')}")
            elif args.all and isinstance(result.get("tabs"), list):
                for tab in result["tabs"]:
                    state = tab.get("state", "unknown")
                    token = tab.get("conversationToken") or "-"
                    title = tab.get("title") or "-"
                    if state == "idle" and tab.get("text"):
                        text_preview = tab["text"][:80].replace("\n", " ")
                        print(f"  {title:<20} token={token[:12]}...  {state}  text={text_preview}...")
                    else:
                        copies = tab.get("copyReplyCount", 0)
                        print(f"  {title:<20} token={token[:12]}...  {state}  copies={copies}")
            else:
                print(result.get("text", ""))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
