from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


# #8060: shipped reads live in _support; the markup and source checks stay.
from _support import lifecycle_contract_source as sheets


def _run_node(script: str) -> dict:
    # The script runs from a temporary file. An inline argument would hit the
    # Windows command-line limit as soon as the module it exercises grows.
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8", newline="\n") as handle:
        handle.write(script)
        path = handle.name
    try:
        completed = subprocess.run(
            ["node", path],
            check=True,
            capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        os.unlink(path)
    return json.loads(completed.stdout)


def test_lifecycle_helper_load_order_and_app_ownership() -> None:
    html = sheets.sheet("index.html")
    app = sheets.sheet("app.js")
    stream = sheets.sheet("chat-streaming-module.js")
    conv = sheets.sheet("chat-conversation-module.js")

    assert html.index('<script src="./conversation-state.js"></script>') < html.index('<script src="./message-lifecycle.js"></script>')
    assert html.index('<script src="./message-lifecycle.js"></script>') < html.index('<script src="./app.js"></script>')
    assert 'const MESSAGE_LIFECYCLE = window.PadiemChatLifecycle.states;' in app
    assert 'window.PadiemChatLifecycle = Object.freeze' not in app
    assert 'let inFlight = false;' in app
    assert 'let activeRequestController = null;' in app
    assert 'let activeRequestCancelReason = null;' in app
    assert 'let conversationEpoch = 0;' in app
    assert 'deps.activeRequestCancelReason = "user_cancel"' in stream
    assert 'PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING)' in conv
    assert 'PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING)' in stream
    assert 'PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED)' in conv
    assert 'PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED)' in stream
    assert 'PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.CANCELLED)' in conv


def test_lifecycle_helper_runtime_contract() -> None:
    source = sheets.sheet("message-lifecycle.js")
    script = r'''
global.window = globalThis;
global.CustomEvent = class CustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
    this.detail = options.detail;
  }
};
''' + source + r'''
const events = [];
const article = {
  dataset: {},
  dispatchEvent(event) {
    events.push({ type: event.type, bubbles: event.bubbles, detail: event.detail });
  },
};
const api = PadiemChatLifecycle;
const before = api.isCompleted(article);
api.set(article, api.states.STREAMING);
const streaming = api.isCompleted(article);
api.set(article, "not-a-state");
const afterInvalid = article.dataset.lifecycle;
api.set(article, api.states.COMPLETED);
const completed = api.isCompleted(article);
console.log(JSON.stringify({
  states: api.states,
  before,
  streaming,
  afterInvalid,
  completed,
  events,
}));
'''
    result = _run_node(script)

    assert result["states"] == {
        "STREAMING": "streaming",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "CANCELLED": "cancelled",
        "TIMED_OUT": "timed_out",
        "WAITING_APPROVAL": "waiting_for_approval",
    }
    assert result["before"] is False
    assert result["streaming"] is False
    assert result["afterInvalid"] == "streaming"
    assert result["completed"] is True
    assert result["events"] == [
        {"type": "padiem:message-lifecycle", "bubbles": True, "detail": {"state": "streaming"}},
        {"type": "padiem:message-lifecycle", "bubbles": True, "detail": {"state": "completed"}},
    ]


def test_outputs_and_export_keep_lifecycle_consumers() -> None:
    outputs = sheets.sheet("outputs.js")
    export = sheets.sheet("conversation-export.js")

    assert 'window.PadiemChatLifecycle ||' in outputs
    assert 'if (!lifecycleApi().isCompleted(article))' in outputs
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in outputs
    assert 'window.PadiemChatLifecycle ||' in export
    assert 'if (hasIncompleteAssistant()) return [];' in export
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in export
