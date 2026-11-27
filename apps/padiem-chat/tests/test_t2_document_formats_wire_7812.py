"""T2: the document formats listeners stay in the conversation module."""
from __future__ import annotations

import shutil
import subprocess

from _support.conversation_module_source import static_path



def test_document_formats_listener_contract() -> None:
    node = shutil.which("node")
    assert node, "Node.js is required"
    harness = """
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
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
"""
    result = subprocess.run(
        [node, "-e", harness, static_path("chat-conversation-module.js")], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def test_wire_is_relocated_not_duplicated() -> None:
    # Use the existing parsed-source contract helpers for ownership checks.
    from _support.conversation_module_source import _source, function_counts
    app = "app.js"
    module = "chat-conversation-module.js"
    assert _source(app).count("conversationModule().wireDocumentFormats();") == 1
    assert function_counts(module).get("wireDocumentFormats") == 1
    for name in ("documentFormatsToggle", "documentFormatsPanel"):
        lookup = f'document.getElementById("{name}")'
        assert _source(app).count(lookup) == 0
        assert _source(module).count(lookup) == 1
