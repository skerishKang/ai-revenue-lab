"""T2: the document formats listeners stay in the conversation module."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
MODULE = STATIC / "chat-conversation-module.js"
APP = STATIC / "app.js"


def test_document_formats_listener_contract() -> None:
    node = shutil.which("node")
    assert node, "Node.js is required"
    source = json.dumps(MODULE.read_text(encoding="utf-8"))
    harness = """
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = SOURCE;
const listeners = [];
const toggle = {
  attrs: {},
  setAttribute(key, value) { this.attrs[key] = value; },
  addEventListener(type, cb) { listeners.push(['toggle', type, cb]); }
};
const panel = { hidden: true };
const doc = {
  getElementById(id) {
    return id === 'documentFormatsToggle' ? toggle :
      id === 'documentFormatsPanel' ? panel : null;
  },
  addEventListener(type, cb) { listeners.push(['document', type, cb]); }
};
const win = {};
vm.runInNewContext(source, {window: win, document: doc});
const module = win.PadiemChatConversationModule.create(new Proxy({}, {
  get() { throw new Error('create read deps'); }
}));
assert.equal(listeners.length, 0, 'create() must not wire listeners');
assert.equal(typeof module.wireDocumentFormats, 'function');
module.wireDocumentFormats();
assert.deepEqual(listeners.map(([target, type]) => [target, type]),
  [['toggle', 'click'], ['document', 'click']]);
listeners[0][2]();
assert.equal(panel.hidden, false);
assert.equal(toggle.attrs['aria-expanded'], 'true');
listeners[1][2]({target: {closest: () => null}});
assert.equal(panel.hidden, true);
assert.equal(toggle.attrs['aria-expanded'], 'false');
listeners[0][2]();
listeners[1][2]({target: {closest: () => ({})}});
assert.equal(panel.hidden, false, 'inside click must retain open panel');
listeners[0][2]();
assert.equal(panel.hidden, true);
console.log('PASS');
""".replace("SOURCE", source)
    result = subprocess.run(
        [node, "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def test_wire_is_relocated_not_duplicated() -> None:
    app = APP.read_text(encoding="utf-8")
    module = MODULE.read_text(encoding="utf-8")
    assert app.count("conversationModule().wireDocumentFormats();") == 1
    assert "document.getElementById(\"documentFormatsToggle\")" not in app
    assert module.count("document.getElementById(\"documentFormatsToggle\")") == 1
    assert module.count("document.getElementById(\"documentFormatsPanel\")") == 1
