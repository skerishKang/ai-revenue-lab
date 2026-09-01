from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "static" / "app.js"
INDEX_PATH = ROOT / "static" / "index.html"
LIFECYCLE_PATH = ROOT / "static" / "message-lifecycle.js"
OUTPUTS_PATH = ROOT / "static" / "outputs.js"
EXPORT_PATH = ROOT / "static" / "conversation-export.js"


def _run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_lifecycle_helper_load_order_and_app_ownership() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    app = APP_PATH.read_text(encoding="utf-8")

    assert html.index('<script src="./conversation-state.js"></script>') < html.index('<script src="./message-lifecycle.js"></script>')
    assert html.index('<script src="./message-lifecycle.js"></script>') < html.index('<script src="./app.js"></script>')
    assert 'const MESSAGE_LIFECYCLE = window.PadiemChatLifecycle.states;' in app
    assert 'window.PadiemChatLifecycle = Object.freeze' not in app
    assert 'let inFlight = false;' in app
    assert 'let activeRequestController = null;' in app
    assert 'let activeRequestCancelReason = null;' in app
    assert 'let conversationEpoch = 0;' in app
    assert 'activeRequestCancelReason = "user_cancel"' in app
    assert 'PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.STREAMING)' in app
    assert 'PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED)' in app
    assert 'PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.CANCELLED)' in app


def test_lifecycle_helper_runtime_contract() -> None:
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
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
    outputs = OUTPUTS_PATH.read_text(encoding="utf-8")
    export = EXPORT_PATH.read_text(encoding="utf-8")

    assert 'window.PadiemChatLifecycle ||' in outputs
    assert 'if (!lifecycleApi().isCompleted(article))' in outputs
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in outputs
    assert 'window.PadiemChatLifecycle ||' in export
    assert 'if (hasIncompleteAssistant()) return [];' in export
    assert 'messageList.addEventListener("padiem:message-lifecycle"' in export
