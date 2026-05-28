#!/usr/bin/env python3
"""Beta CDP input path for Notion AI.

This module intentionally stays separate from the stable AX/clipboard flow.
It only drives the renderer DOM for the Notion AI quick-search window and
does not call Notion's private network APIs.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_PORT = 9222
NOTION_BUNDLE_ID = "notion.id"
QUICK_SEARCH_URL = "https://www.notion.so/quick-search"
AI_URL = "https://www.notion.so/ai"
TEXTBOX_SELECTOR = '[contenteditable="true"][role="textbox"]'
DEFAULT_WAIT_TEXTBOX_TIMEOUT = 10.0
DEFAULT_WAIT_TEXTBOX_INTERVAL = 0.2
STOP_BUTTON_LABELS = ("停止 AI 消息", "Stop AI message")
SUBMIT_BUTTON_LABELS = ("Submit AI message", "提交 AI 消息")
COPY_REPLY_LABELS = ("拷贝回复", "Copy reply")
NEW_CONVERSATION_LABELS = ("开始新对话", "New chat", "New conversation")
ALLOW_UPLOAD_LABELS = ("允许上传", "Allow upload")
ATTACHMENT_REMOVE_PREFIXES = ("从上下文中移除", "Remove from context")
SUPPORTED_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".pdf",
    ".csv",
    ".md",
    ".markdown",
    ".txt",
    ".log",
    ".html",
    ".htm",
    ".xml",
    ".css",
    ".yaml",
    ".yml",
    ".py",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".sh",
    ".bash",
    ".zsh",
    ".js",
    ".jsx",
    ".mjs",
    ".ts",
    ".tsx",
    ".json",
    ".patch",
}


class CdpError(RuntimeError):
    """Raised when CDP is unavailable or returns an unexpected response."""


def _json_url(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def cdp_is_running(port: int = DEFAULT_PORT) -> bool:
    try:
        _json_url(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
    except (OSError, urllib.error.URLError):
        return False
    return True


def list_targets(port: int = DEFAULT_PORT) -> list[dict]:
    try:
        return _json_url(f"http://127.0.0.1:{port}/json/list")
    except (OSError, urllib.error.URLError) as exc:
        raise CdpError(f"CDP is not reachable on 127.0.0.1:{port}: {exc}") from exc


def _read_ws_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = sock.recv(2)
    if len(header) != 2:
        raise CdpError("WebSocket closed while reading frame header")

    first, second = header
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]

    mask = sock.recv(4) if second & 0x80 else None
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise CdpError("WebSocket closed while reading frame payload")
        payload += chunk

    if mask is not None:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def _send_ws_text(sock: socket.socket, payload: bytes) -> None:
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)

    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(header + mask + masked)


class CdpSession:
    """Small persistent CDP websocket session.

    Some CDP values, such as Runtime object ids, are scoped to one websocket
    session. Keeping a tiny session wrapper also lets multi-step DOM operations
    like file input injection share node ids reliably.
    """

    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.sock: socket.socket | None = None
        self.next_message_id = 1

    def __enter__(self) -> "CdpSession":
        parsed = urllib.parse.urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise CdpError(f"Only ws:// CDP URLs are supported: {self.websocket_url}")

        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        self.sock = socket.create_connection((host, port), timeout=5.0)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))

        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CdpError(f"WebSocket handshake failed: {response[:200]!r}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def call(self, method: str, params: dict | None = None):
        if self.sock is None:
            raise CdpError("CDP session is not open")

        message_id = self.next_message_id
        self.next_message_id += 1
        payload = json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        _send_ws_text(self.sock, payload)

        while True:
            opcode, frame_payload = _read_ws_frame(self.sock)
            if opcode == 1:
                message = json.loads(frame_payload.decode("utf-8"))
                if message.get("id") == message_id:
                    if "error" in message:
                        raise CdpError(json.dumps(message["error"], ensure_ascii=False))
                    return message.get("result")
            if opcode == 8:
                raise CdpError("WebSocket closed before CDP response")

    def wait_for_event(self, method: str, timeout: float = 5.0) -> dict | None:
        if self.sock is None:
            raise CdpError("CDP session is not open")

        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(min(timeout, 5.0))
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    opcode, frame_payload = _read_ws_frame(self.sock)
                except socket.timeout:
                    return None
                if opcode == 1:
                    message = json.loads(frame_payload.decode("utf-8"))
                    if message.get("method") == method:
                        return message.get("params") or {}
                if opcode == 8:
                    raise CdpError("WebSocket closed while waiting for CDP event")
        finally:
            self.sock.settimeout(old_timeout)
        return None


def cdp_call(websocket_url: str, method: str, params: dict | None = None,
             message_id: int = 1):
    del message_id
    with CdpSession(websocket_url) as session:
        return session.call(method, params)


def _legacy_cdp_call(websocket_url: str, method: str, params: dict | None = None,
                     message_id: int = 1):
    parsed = urllib.parse.urlparse(websocket_url)
    if parsed.scheme != "ws":
        raise CdpError(f"Only ws:// CDP URLs are supported: {websocket_url}")

    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    with socket.create_connection((host, port), timeout=5.0) as sock:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))

        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise CdpError(f"WebSocket handshake failed: {response[:200]!r}")

        payload = json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8")
        _send_ws_text(sock, payload)

        while True:
            opcode, frame_payload = _read_ws_frame(sock)
            if opcode == 1:
                message = json.loads(frame_payload.decode("utf-8"))
                if message.get("id") == message_id:
                    if "error" in message:
                        raise CdpError(json.dumps(message["error"], ensure_ascii=False))
                    return message.get("result")
            if opcode == 8:
                raise CdpError("WebSocket closed before CDP response")


def find_target(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL) -> dict:
    targets = list_targets(port)
    for target in targets:
        if target.get("type") == "page" and target.get("url") == url:
            return target
    available = [
        {"title": item.get("title"), "url": item.get("url"), "type": item.get("type")}
        for item in targets
        if item.get("type") == "page"
    ]
    raise CdpError(f"Target not found for {url}. Available page targets: {available}")


def evaluate_js(target: dict, expression: str):
    result = cdp_call(
        target["webSocketDebuggerUrl"],
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    return result.get("result", {}).get("value")


def textbox_status(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL) -> dict:
    target = find_target(port, url)
    expression = f"""
(() => {{
  const nodes = [...document.querySelectorAll({json.dumps(TEXTBOX_SELECTOR)})];
  const textboxes = nodes.map((el, index) => {{
    const rect = el.getBoundingClientRect();
    return {{
      index,
      text: el.innerText || el.textContent || "",
      placeholder: el.getAttribute("placeholder"),
      active: document.activeElement === el,
      visible: rect.width > 0 && rect.height > 0,
      rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
    }};
  }});
  const submit = [...document.querySelectorAll("button,[role='button']")]
    .map((button, index) => {{
      const rect = button.getBoundingClientRect();
      const label = button.innerText || button.getAttribute("aria-label") || button.getAttribute("data-testid") || "";
      return {{
        index,
        label,
        disabled: !!button.disabled || button.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }})
    .find((button) => button.visible && /submit ai message/i.test(button.label));
  return {{ targetUrl: location.href, textboxes, submit: submit || null }};
}})()
"""
    return evaluate_js(target, expression)


def dom_status(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL,
               body_limit: int = 4000) -> dict:
    target = find_target(port, url)
    expression = f"""
(() => {{
  const labelFor = (node) => (
    node.innerText ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const buttons = [...document.querySelectorAll("button,[role='button']")]
    .map((button, index) => {{
      const rect = button.getBoundingClientRect();
      return {{
        index,
        label: labelFor(button),
        disabled: !!button.disabled || button.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }})
    .filter((button) => button.visible);
  const textboxes = [...document.querySelectorAll({json.dumps(TEXTBOX_SELECTOR)})]
    .map((el, index) => {{
      const rect = el.getBoundingClientRect();
      return {{
        index,
        text: el.innerText || el.textContent || "",
        placeholder: el.getAttribute("placeholder"),
        active: document.activeElement === el,
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }});
  const bodyText = document.body.innerText || "";
  const hasStop = buttons.some((button) => (
    !button.disabled && {json.dumps(list(STOP_BUTTON_LABELS))}.includes(button.label)
  ));
  const hasGeneratingText = /Notion AI\\s+正在生成回复|generating reply|is generating/i.test(bodyText);
  const enabledSubmit = buttons.find((button) => (
    !button.disabled && {json.dumps(list(SUBMIT_BUTTON_LABELS))}.includes(button.label)
  )) || null;
  const copyReplies = buttons.filter((button) => (
    !button.disabled && {json.dumps(list(COPY_REPLY_LABELS))}.includes(button.label)
  ));
  return {{
    targetUrl: location.href,
    textboxes,
    buttons,
    hasStop,
    hasGeneratingText,
    enabledSubmit,
    copyReplyCount: copyReplies.length,
    bodyTextTail: bodyText.slice(-{int(body_limit)}),
  }};
}})()
"""
    return evaluate_js(target, expression)


def _has_visible_textbox(status: dict) -> bool:
    return any(item.get("visible") for item in status.get("textboxes", []))


def wait_for_textbox(
    port: int = DEFAULT_PORT,
    url: str = QUICK_SEARCH_URL,
    timeout: float = DEFAULT_WAIT_TEXTBOX_TIMEOUT,
    interval: float = DEFAULT_WAIT_TEXTBOX_INTERVAL,
) -> dict:
    deadline = time.monotonic() + max(timeout, 0)
    last_error: Exception | None = None

    while True:
        try:
            status = textbox_status(port, url)
            if _has_visible_textbox(status):
                return status
            last_error = None
        except CdpError as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            details = f" Last CDP error: {last_error}" if last_error else ""
            raise CdpError(
                f"Timed out waiting for visible textbox on {url} "
                f"after {timeout:.1f}s.{details}"
            )
        time.sleep(max(interval, 0.05))


def write_text(text: str, port: int = DEFAULT_PORT,
               url: str = QUICK_SEARCH_URL) -> dict:
    target = find_target(port, url)
    expression = f"""
(() => {{
  const el = document.querySelector({json.dumps(TEXTBOX_SELECTOR)});
  if (!el) return {{ ok: false, error: "textbox not found" }};

  el.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);

  let execOk = false;
  try {{
    execOk = document.execCommand("insertText", false, {json.dumps(text)});
  }} catch (error) {{
    execOk = false;
  }}

  if (!execOk) {{
    el.textContent = {json.dumps(text)};
    el.dispatchEvent(new InputEvent("beforeinput", {{
      bubbles: true,
      cancelable: true,
      inputType: "insertText",
      data: {json.dumps(text)},
    }}));
    el.dispatchEvent(new InputEvent("input", {{
      bubbles: true,
      inputType: "insertText",
      data: {json.dumps(text)},
    }}));
  }}
  el.dispatchEvent(new Event("change", {{ bubbles: true }}));

  const submit = [...document.querySelectorAll("button,[role='button']")]
    .map((button, index) => {{
      const rect = button.getBoundingClientRect();
      const label = button.innerText || button.getAttribute("aria-label") || button.getAttribute("data-testid") || "";
      return {{
        index,
        label,
        disabled: !!button.disabled || button.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
      }};
    }})
    .find((button) => button.visible && /submit ai message/i.test(button.label));

  return {{
    ok: true,
    execOk,
    text: el.innerText || el.textContent || "",
    active: document.activeElement === el,
    submit: submit || null,
  }};
}})()
"""
    return evaluate_js(target, expression)


def clear_text(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL) -> dict:
    target = find_target(port, url)
    expression = f"""
(() => {{
  const el = document.querySelector({json.dumps(TEXTBOX_SELECTOR)});
  if (!el) return {{ ok: false, error: "textbox not found" }};
  el.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);

  let execOk = false;
  try {{
    execOk = document.execCommand("delete");
  }} catch (error) {{
    execOk = false;
  }}
  if (!execOk) {{
    el.textContent = "";
    el.dispatchEvent(new InputEvent("input", {{
      bubbles: true,
      inputType: "deleteContentBackward",
    }}));
  }}
  el.dispatchEvent(new Event("change", {{ bubbles: true }}));
  return {{ ok: true, execOk, text: el.innerText || el.textContent || "" }};
}})()
"""
    return evaluate_js(target, expression)


def normalize_attachment_paths(file_paths: list[str]) -> tuple[list[str], str | None]:
    normalized = []
    for raw_path in file_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            return [], f"附件不存在或不是文件: {raw_path}"
        if path.suffix.lower() not in SUPPORTED_ATTACHMENT_EXTENSIONS:
            return [], f"CDP 附件类型暂不支持: {path.name}"
        normalized.append(str(path))
    return normalized, None


def _dispatch_mouse_click(session: CdpSession, x: float, y: float) -> None:
    for event_type in ("mousePressed", "mouseReleased"):
        session.call("Input.dispatchMouseEvent", {
            "type": event_type,
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })


def _attachment_click_points(session: CdpSession) -> dict:
    result = session.call("Runtime.evaluate", {
        "expression": """
(() => {
  const labelFor = (node) => (
    node.innerText ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const describe = (node, index) => {
    const rect = node.getBoundingClientRect();
    return {
      index,
      label: labelFor(node),
      role: node.getAttribute("role"),
      visible: rect.width > 0 && rect.height > 0,
      x: rect.x + rect.width / 2,
      y: rect.y + rect.height / 2,
      width: rect.width,
      height: rect.height,
    };
  };
  const buttons = [...document.querySelectorAll("button,[role='button']")].map(describe);
  const plus = buttons.find((item) => (
    item.visible && item.label === "提供背景信息"
  ));
  const menuItems = [...document.querySelectorAll("*")].map(describe);
  const upload = menuItems.find((item) => (
    item.visible &&
    item.role === "menuitem" &&
    item.label === "添加图片、PDF 或 CSV"
  ));
  return { plus: plus || null, upload: upload || null };
})()
""",
        "returnByValue": True,
    })
    return result.get("result", {}).get("value") or {}


def _set_files_through_file_chooser(session: CdpSession,
                                    normalized_paths: list[str]) -> dict:
    session.call("Page.enable")
    session.call("Page.setInterceptFileChooserDialog", {
        "enabled": True,
        "cancel": True,
    })

    points = _attachment_click_points(session)
    plus = points.get("plus")
    if not plus:
        raise CdpError("attachment menu button not found")
    _dispatch_mouse_click(session, float(plus["x"]), float(plus["y"]))
    time.sleep(0.25)

    points = _attachment_click_points(session)
    upload = points.get("upload")
    if not upload:
        raise CdpError("attachment upload menu item not found")
    _dispatch_mouse_click(session, float(upload["x"]), float(upload["y"]))

    chooser = session.wait_for_event("Page.fileChooserOpened", timeout=5.0)
    if not chooser:
        raise CdpError("file chooser was not opened")

    params: dict = {"files": normalized_paths}
    if chooser.get("backendNodeId"):
        params["backendNodeId"] = chooser["backendNodeId"]
    elif chooser.get("nodeId"):
        params["nodeId"] = chooser["nodeId"]
    else:
        raise CdpError(f"file chooser did not expose a node id: {chooser}")

    session.call("DOM.setFileInputFiles", params)
    return {
        "method": "file_chooser_intercept",
        "chooser": chooser,
        "uploadMenuItem": upload,
    }


def set_file_input_files(file_paths: list[str], port: int = DEFAULT_PORT,
                         url: str = QUICK_SEARCH_URL) -> dict:
    normalized_paths, error = normalize_attachment_paths(file_paths)
    if error:
        return {"ok": False, "files": [], "error": error}

    target = find_target(port, url)
    try:
        with CdpSession(target["webSocketDebuggerUrl"]) as session:
            chooser_result = _set_files_through_file_chooser(session, normalized_paths)
            return {
                "ok": True,
                "files": normalized_paths,
                **chooser_result,
            }
    except CdpError as chooser_error:
        fallback_error = chooser_error

    with CdpSession(target["webSocketDebuggerUrl"]) as session:
        document = session.call("DOM.getDocument", {"depth": 1, "pierce": True})
        root_id = document["root"]["nodeId"]
        query = session.call(
            "DOM.querySelector",
            {"nodeId": root_id, "selector": "input[type=file]"},
        )
        node_id = query.get("nodeId")
        if not node_id:
            return {
                "ok": False,
                "files": normalized_paths,
                "error": (
                    f"file input not found; chooser path failed: {fallback_error}"
                ),
            }

        session.call("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": [],
        })
        session.call("Runtime.evaluate", {
            "expression": """
(() => {
  const input = document.querySelector('input[type=file]');
  if (!input) return { ok: false, error: 'file input not found' };
  input.value = '';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true };
})()
""",
            "returnByValue": True,
        })
        session.call("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": normalized_paths,
        })
        changed = session.call("Runtime.evaluate", {
            "expression": """
(() => {
  const input = document.querySelector('input[type=file]');
  if (!input) return { ok: false, error: 'file input not found' };
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return {
    ok: true,
    fileCount: input.files ? input.files.length : null,
    names: input.files ? [...input.files].map((file) => file.name) : [],
  };
})()
""",
            "returnByValue": True,
        })

    return {
        "ok": True,
        "files": normalized_paths,
        "method": "direct_file_input",
        "nodeId": node_id,
        "change": changed.get("result", {}).get("value"),
    }


def attachment_status(file_paths: list[str], port: int = DEFAULT_PORT,
                      url: str = QUICK_SEARCH_URL) -> dict:
    filenames = [Path(path).name for path in file_paths]
    target = find_target(port, url)
    expression = f"""
(() => {{
  const filenames = {json.dumps(filenames)};
  const removePrefixes = {json.dumps(list(ATTACHMENT_REMOVE_PREFIXES))};
  const allowUploadLabels = {json.dumps(list(ALLOW_UPLOAD_LABELS))};
  const labelFor = (node) => (
    node.innerText ||
    node.getAttribute("aria-label") ||
    node.getAttribute("data-testid") ||
    node.getAttribute("title") ||
    ""
  ).trim();
  const visible = (node) => {{
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }};
  const nodes = [...document.querySelectorAll("*")];
  const labels = nodes.map((node, index) => {{
    const rect = node.getBoundingClientRect();
    return {{
      index,
      tag: node.tagName,
      role: node.getAttribute("role"),
      label: labelFor(node),
      visible: visible(node),
      rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
    }};
  }});
  const removeButtons = labels.filter((item) => (
    item.visible &&
    item.role === "button" &&
    removePrefixes.some((prefix) => item.label.startsWith(prefix))
  ));
  const seen = filenames.filter((filename) => (
    removeButtons.some((button) => button.label.includes(filename))
  ));
  const allowUpload = labels.find((item) => (
    item.visible && item.role === "button" && allowUploadLabels.includes(item.label)
  )) || null;
  const fileInput = document.querySelector("input[type=file]");
  return {{
    filenames,
    seen,
    complete: filenames.every((filename) => seen.includes(filename)),
    removeButtons,
    allowUpload,
    fileInput: fileInput ? {{
      fileCount: fileInput.files ? fileInput.files.length : null,
      names: fileInput.files ? [...fileInput.files].map((file) => file.name) : [],
    }} : null,
    bodyTextTail: (document.body.innerText || "").slice(-2000),
  }};
}})()
"""
    return evaluate_js(target, expression)


def wait_for_attachments_ready_cdp(
    file_paths: list[str],
    port: int = DEFAULT_PORT,
    url: str = QUICK_SEARCH_URL,
    timeout: float = 120.0,
    interval: float = 0.25,
) -> dict:
    normalized_paths, error = normalize_attachment_paths(file_paths)
    if error:
        return {"success": False, "files": [], "error": error}

    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        status = attachment_status(normalized_paths, port, url)
        last_status = status
        if status.get("allowUpload"):
            click_button_by_label(ALLOW_UPLOAD_LABELS, port, url, prefer_bottom=True)
            time.sleep(0.2)
            continue
        if status.get("complete"):
            return {
                "success": True,
                "files": normalized_paths,
                "status": status,
                "error": None,
            }
        time.sleep(interval)

    return {
        "success": False,
        "files": normalized_paths,
        "status": last_status,
        "error": f"等待 CDP 附件进入上下文超时 ({timeout}s)",
    }


def click_button_by_label(
    labels: tuple[str, ...] | list[str] | set[str],
    port: int = DEFAULT_PORT,
    url: str = QUICK_SEARCH_URL,
    prefer_bottom: bool = True,
) -> dict:
    target = find_target(port, url)
    label_list = list(labels)
    expression = f"""
(() => {{
  const labels = new Set({json.dumps(label_list)});
  const candidates = [...document.querySelectorAll("button,[role='button']")]
    .map((button, index) => {{
      const rect = button.getBoundingClientRect();
      const label = (
        button.innerText ||
        button.getAttribute("aria-label") ||
        button.getAttribute("data-testid") ||
        button.getAttribute("title") ||
        ""
      ).trim();
      return {{
        node: button,
        index,
        label,
        disabled: !!button.disabled || button.getAttribute("aria-disabled") === "true",
        visible: rect.width > 0 && rect.height > 0,
        rect: {{ x: rect.x, y: rect.y, width: rect.width, height: rect.height }},
      }};
    }});
  let matches = candidates.filter((item) => (
    item.visible && !item.disabled && labels.has(item.label)
  ));
  if (!matches.length) {{
    return {{
      ok: false,
      error: "button not found",
      labels: [...labels],
      buttons: candidates
        .filter((item) => item.visible && item.label)
        .map(({{node, ...item}}) => item),
    }};
  }}
  matches.sort((a, b) => (
    {str(bool(prefer_bottom)).lower()}
      ? (b.rect.y - a.rect.y) || (b.rect.x - a.rect.x)
      : (a.rect.y - b.rect.y) || (a.rect.x - b.rect.x)
  ));
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
    return evaluate_js(target, expression)


def submit_message(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL) -> dict:
    return click_button_by_label(SUBMIT_BUTTON_LABELS, port, url, prefer_bottom=True)


def copy_reply(port: int = DEFAULT_PORT, url: str = QUICK_SEARCH_URL) -> dict:
    return click_button_by_label(COPY_REPLY_LABELS, port, url, prefer_bottom=True)


def start_new_conversation_cdp(port: int = DEFAULT_PORT,
                               url: str = QUICK_SEARCH_URL) -> dict:
    return click_button_by_label(NEW_CONVERSATION_LABELS, port, url, prefer_bottom=False)


def wait_for_cdp_ready(port: int = DEFAULT_PORT,
                       url: str = QUICK_SEARCH_URL,
                       timeout: float = DEFAULT_WAIT_TEXTBOX_TIMEOUT,
                       interval: float = DEFAULT_WAIT_TEXTBOX_INTERVAL) -> dict:
    if not cdp_is_running(port):
        raise CdpError(
            f"CDP is not running on port {port}. "
            "Start Notion with --remote-debugging-port=9222 first."
        )
    return wait_for_textbox(port, url, timeout, interval)


def _run_cua_driver(args: dict) -> dict:
    command = ["cua-driver", args.pop("_tool"), json.dumps(args)]
    completed = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def restart_notion_with_cdp(port: int = DEFAULT_PORT, settle: float = 2.0) -> dict:
    launched = _run_cua_driver({"_tool": "launch_app", "bundle_id": NOTION_BUNDLE_ID})
    pid = launched.get("pid")
    if pid:
        subprocess.run(
            ["cua-driver", "hotkey", json.dumps({"pid": pid, "keys": ["cmd", "q"]})],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(settle)
    return _run_cua_driver({
        "_tool": "launch_app",
        "bundle_id": NOTION_BUNDLE_ID,
        "electron_debugging_port": port,
    })


def open_ai_window(pid: int) -> None:
    subprocess.run(
        ["cua-driver", "hotkey", json.dumps({"pid": pid, "keys": ["cmd", "shift", "j"]})],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Beta CDP input tester for the Notion AI quick-search window."
    )
    parser.add_argument("text", nargs="?", help="Text to write into Notion AI.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--url", default=QUICK_SEARCH_URL,
                        choices=[QUICK_SEARCH_URL, AI_URL])
    parser.add_argument("--restart-with-cdp", action="store_true",
                        help="Quit Notion and relaunch it with the CDP port.")
    parser.add_argument("--open-ai", action="store_true",
                        help="Send Cmd+Shift+J to Notion after launch.")
    parser.add_argument("--status", action="store_true",
                        help="Print target/input status only.")
    parser.add_argument("--clear", action="store_true",
                        help="Clear the beta target textbox.")
    parser.add_argument("--wait-textbox-timeout", type=float,
                        default=DEFAULT_WAIT_TEXTBOX_TIMEOUT,
                        help="Seconds to wait for the quick-search textbox.")
    parser.add_argument("--wait-textbox-interval", type=float,
                        default=DEFAULT_WAIT_TEXTBOX_INTERVAL,
                        help="Polling interval while waiting for the textbox.")
    args = parser.parse_args()

    try:
        launch_info = None
        if args.restart_with_cdp:
            launch_info = restart_notion_with_cdp(args.port)
            if args.open_ai and launch_info.get("pid"):
                open_ai_window(int(launch_info["pid"]))
                time.sleep(0.8)
        elif not cdp_is_running(args.port):
            raise CdpError(
                f"CDP is not running on port {args.port}. "
                "Use --restart-with-cdp to relaunch Notion for beta testing."
            )

        wait_status = None
        if args.clear or args.status or args.text:
            wait_status = wait_for_textbox(
                args.port,
                args.url,
                args.wait_textbox_timeout,
                args.wait_textbox_interval,
            )

        result: dict = {
            "success": True,
            "launch_info": launch_info,
            "port": args.port,
            "target_url": args.url,
        }
        if args.clear:
            result["clear"] = clear_text(args.port, args.url)
        if args.status or not args.text:
            result["status"] = wait_status or textbox_status(args.port, args.url)
        if args.text:
            result["write"] = write_text(args.text, args.port, args.url)
            result["status"] = textbox_status(args.port, args.url)
        print_json(result)
        return 0
    except (CdpError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print_json({"success": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
