"""Execute the R1 store in a browser-like event target, not source snapshots."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
import shutil
import subprocess

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_auth_session_publishes_only_real_changes_and_keeps_legacy_detail(tmp_path):
    harness = tmp_path / "auth-session.cjs"
    harness.write_text(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const events = [];
const sandbox = { CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
  dispatchEvent: e => events.push(e) };
sandbox.window = sandbox;
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
const store = sandbox.PadiemAuthSession;
assert.equal(store.get(), null);
store.update({ready: true, authenticated: false}, 1);
assert.equal(events.length, 1);
assert.equal(events[0].type, "padiem:auth-state");
assert.equal(events[0].detail.authenticated, false);
assert.equal(events[0].detail.generation, 1);
const status = {ready: true, authenticated: true, project_files_ready: true,
  user: {email: "a@example.test", name: "Same name"}, secret: "must-not-project"};
store.update(status, 2);
const first = store.get();
assert.equal(events.length, 2);
assert.equal(first.authenticated, true);
assert.equal(first.ownerKey, "a@example.test");
assert.equal(first.storage, true);
assert.equal(first.displayName, "Same name");
store.update({...status, user: {...status.user}}, 99);
assert.equal(store.get(), first);
assert.equal(events.length, 2, "generation is metadata, not a session change");
assert(Object.isFrozen(first));
assert(Object.isFrozen(events[1].detail));
assert.deepEqual(Object.keys(first).sort(), ["authenticated", "displayName", "ownerKey", "storage"]);
store.update({...status, user: {...status.user, email: "b@example.test"}}, 3);
assert.equal(events.length, 3, "same display name must not hide an owner switch");
assert.equal(store.get().ownerKey, "b@example.test");
store.update({...status, user: {email: "b@example.test", name: "New name"}}, 4);
assert.equal(events.length, 4);
store.update({...status, project_files_ready: false, user: {email: "b@example.test", name: "New name"}}, 5);
assert.equal(events.length, 5);
assert.equal(store.get().storage, false);
store.update({ready: true, authenticated: false, project_files_ready: false, user: status.user}, 6);
assert.equal(events.length, 6);
assert.equal(store.get().authenticated, false);
assert.equal(store.get().ownerKey, "");
assert.equal(store.get().displayName, "");
store.update({ready: true, authenticated: false}, 7);
assert.equal(events.length, 6);
for (const event of events) {
  assert.deepEqual(Object.keys(event.detail).sort(), ["authenticated", "generation"],
    "the legacy event carries no owner identity, display name, or storage projection");
}
''', encoding="utf-8")
    result = subprocess.run([shutil.which("node") or "node", str(harness), str(STATIC / "auth-session.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_auth_session_loads_before_app_and_app_has_no_mutation_observer():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    class Scripts(HTMLParser):
        paths = []
        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.paths.append(Path(urlsplit(dict(attrs).get("src", "")).path).name)
    scripts = Scripts()
    scripts.feed(html)
    assert scripts.paths.index("auth-session.js") < scripts.paths.index("app.js")
    assert "MutationObserver" not in (STATIC / "app.js").read_text(encoding="utf-8")