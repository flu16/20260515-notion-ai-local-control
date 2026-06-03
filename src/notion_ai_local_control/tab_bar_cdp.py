#!/usr/bin/env python3
"""CDP helpers for Notion desktop's tab bar."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

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
  const hasGeneratingText = /Notion AI\\s+正在生成回复|generating reply|is generating|正在/.test(bodyText);
  const enabledSubmit = buttons.find((button) => (
    !button.disabled &&
    (button.dataTestid === "agent-send-message-button" ||
      button.label === "提交 AI 消息" ||
      button.label === "Submit AI message")
  )) || null;
  return {
    targetUrl: location.href,
    title: document.title,
    textboxes,
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
    result = _runtime_value(session, expression)
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
    result = _runtime_value(session, expression)
    return result if isinstance(result, dict) else {"submit": None, "textboxText": None}


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


def set_main_app_text_and_submit(target: dict, text: str) -> dict:
    with CdpSession(target["webSocketDebuggerUrl"]) as session:
        focused = _focus_main_app_textbox(session)
        if not focused.get("ok"):
            return focused
        _clear_focused_textbox(session)
        session.call("Input.insertText", {"text": text})
        state = None
        for _ in range(40):
            state = _main_app_submit_state(session)
            submit = state.get("submit") if isinstance(state, dict) else None
            if submit and not submit.get("disabled"):
                break
            time.sleep(0.05)
        else:
            return {
                "ok": False,
                "error": "submit button not found or disabled",
                "inputMethod": "Input.insertText",
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


def ask_main_app_target(
    target_id: str,
    question: str,
    port: int = DEFAULT_PORT,
    timeout: float = 300.0,
) -> dict:
    started_at = time.time()
    target = find_page_target_by_id(target_id, port)
    if not is_notion_ai_target(target):
        return {
            "success": False,
            "step": "validate_target",
            "error": "target is not a Notion AI main app page",
            "target": target_summary(target),
        }
    before_status = main_app_status(target)
    submitted = set_main_app_text_and_submit(target, question)
    if not submitted.get("ok"):
        return {
            "success": False,
            "step": "input_submit",
            "text": "",
            "error": submitted.get("error"),
            "target": target_summary(target),
            "details": submitted,
            "initial_state": before_status,
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
            "final_state": finished.get("state"),
        }
    return {
        "success": True,
        "text": copied.get("text"),
        "elapsed": round(time.time() - started_at, 2),
        "target": target_summary(target),
        "input": submitted,
        "final_state": finished.get("state"),
        "copy_button_info": copied.get("copy_button_info"),
        "error": None,
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


def click_close_conversation_tab_button(target_to_close: dict, port: int = DEFAULT_PORT) -> dict:
    target = find_tab_bar_target(port)
    tab_label = _tab_label_for_target(target_to_close)
    expression = f"""
(() => {{
  const tabLabel = {json.dumps(tab_label)};
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
  if (matchingTabs.length !== 1) {{
    return {{
      ok: false,
      error: `expected exactly one tab labelled "${{tabLabel}}", found ${{matchingTabs.length}}`,
      tabLabel,
      tabs: tabs.map((item) => ({{
        index: item.index,
        label: item.label,
        rect: item.rect,
      }})),
    }};
  }}
  const tab = matchingTabs[0];
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
    target_id: str,
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
    interval: float = 0.2,
    force: bool = False,
) -> dict:
    before_targets = page_targets(port)
    before_ai_targets = [target for target in before_targets if is_notion_ai_target(target)]
    before_tab_bar = tab_bar_state(port)
    target = find_page_target_by_id(target_id, port)

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

        target_closed = not any(target.get("id") == target_id for target in current_targets)
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

    create = subparsers.add_parser(
        "new-conversation",
        help="Create a new Notion AI conversation tab through the Tab Bar new-tab button.",
    )
    create.add_argument("--port", type=int, default=DEFAULT_PORT)
    create.add_argument("--timeout", type=float, default=10.0)
    create.add_argument("--json", action="store_true")

    close = subparsers.add_parser(
        "close-conversation",
        help="Close a Notion AI conversation tab by CDP target id.",
    )
    close.add_argument("--target-id", required=True, help="CDP page target id to close")
    close.add_argument("--port", type=int, default=DEFAULT_PORT)
    close.add_argument("--timeout", type=float, default=10.0)
    close.add_argument("--force", action="store_true", help="Allow closing the last Notion AI tab")
    close.add_argument("--json", action="store_true")

    ask = subparsers.add_parser(
        "ask",
        help="Ask a question in a specific Notion AI main-app target.",
    )
    ask.add_argument("question", nargs="?", help="Question to submit")
    ask.add_argument("--target-id", required=True, help="CDP page target id to operate")
    ask.add_argument("--from-stdin", action="store_true", help="Read question from stdin")
    ask.add_argument("--from-clipboard", action="store_true", help="Read question from the system clipboard")
    ask.add_argument("--port", type=int, default=DEFAULT_PORT)
    ask.add_argument("--timeout", type=float, default=300.0)
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "tab-bar-state":
            result = tab_bar_state(args.port)
        elif args.command == "new-conversation":
            result = create_new_conversation_tab(args.port, timeout=args.timeout)
        elif args.command == "close-conversation":
            result = close_conversation_target(
                args.target_id,
                port=args.port,
                timeout=args.timeout,
                force=args.force,
            )
        elif args.command == "ask":
            source_count = sum([
                bool(args.from_stdin),
                bool(args.from_clipboard),
                args.question is not None,
            ])
            if source_count > 1:
                raise CdpError("--from-stdin, --from-clipboard, and question are mutually exclusive")
            if args.from_stdin:
                question = sys.stdin.read()
            elif args.from_clipboard:
                question = get_clipboard_text()
            else:
                question = args.question
            if not question:
                raise CdpError("question is required")
            result = ask_main_app_target(
                args.target_id,
                question,
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
        elif args.command == "new-conversation":
            print(result.get("newTargetId") or result.get("newTarget"))
        elif args.command == "close-conversation":
            print(f"已关闭对话 tab: {result.get('closedTargets')}")
        elif args.command == "ask":
            print(result.get("text", ""))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
