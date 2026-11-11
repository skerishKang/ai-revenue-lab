"""#7459 - the account row must not flash a guest sign-in entry on first load.

**The defect this pins.** The auth status is read after the shell renders. The
old markup drew an unconfirmed "?" avatar immediately, and a browser that had
just been signed in could present the guest sign-in entry before the confirmed
answer replaced it. The account row is now neutral until the status is
confirmed, and the only thing remembered between loads is a boolean hint so a
signed-in browser starts from the profile shape instead of the sign-in shape.

**The contract.**

1. the first paint draws neither the login button nor an unconfirmed initial,
2. a previous signed-in visit is remembered as a boolean only (no name/email),
3. localStorage reads and writes are optional: unavailable storage still works,
4. only a confirmed answer changes the hint, and a confirmed sign-out clears it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
INDEX = (BASE / "index.html").read_text(encoding="utf-8")
AUTH = (BASE / "auth-session.js").read_text(encoding="utf-8")
CAPABILITIES = (BASE / "product-capabilities.js").read_text(encoding="utf-8")
CSS = (BASE / "sidebar-utility.css").read_text(encoding="utf-8")


def test_first_paint_claims_neither_a_guest_entry_nor_an_initial() -> None:
    container = re.search(r'<div class="sidebar-account[^"]*"[^>]*>', INDEX)
    assert container is not None
    assert 'data-account-state="pending"' in container.group(0)

    avatar = re.search(
        r'<span class="account-avatar" id="accountAvatar"[^>]*>([^<]*)</span>', INDEX
    )
    assert avatar is not None
    assert " hidden" in avatar.group(0)
    assert avatar.group(1).strip() == ""

    login = re.search(
        r'<button class="login-button" id="loginButton"[^>]*>', INDEX
    )
    assert login is not None
    assert " hidden" in login.group(0)
    assert 'id="loginPending"' in INDEX


def test_the_projection_starts_pending_with_a_neutral_placeholder() -> None:
    # "not read yet" keeps the row visible with reserved space, while both the
    # sign-in entry and the unconfirmed initial stay undrawn.
    assert "function firstPaintSignedInHint()" in CAPABILITIES
    assert "window.PadiemAuthSession" in CAPABILITIES
    assert "lastKnownAuthenticated" in CAPABILITIES
    assert "if (state === \"pending\")" in CAPABILITIES
    assert (
        'return { accountHidden: false, loginHidden: true, loginDisabled: true, accountNameHidden: true };'
        in CAPABILITIES
    )
    assert "pendingLogin.hidden = !pending || signedInHint" in CAPABILITIES
    assert "accountAvatar.hidden = !signedInHint" in CAPABILITIES
    # The projection keeps its reviewed rule: it never touches storage itself.
    assert "localStorage" not in CAPABILITIES
    assert '[data-account-state="pending"] #loginPending' in CSS
    assert '[data-account-hint="signed_in"]' in CSS


def test_storage_hint_is_boolean_only_and_survives_missing_storage(tmp_path) -> None:
    harness = tmp_path / "first-paint-hint.cjs"
    harness.write_text(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeCustomEvent {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
}

function run(storage) {
  const sandbox = {
    CustomEvent: FakeCustomEvent,
    dispatchEvent: () => {},
  };
  sandbox.window = sandbox;
  if (storage) sandbox.window.localStorage = storage;
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), sandbox);
  return sandbox;
}

const backed = new Map();
const storage = {
  getItem(key) { return backed.has(key) ? backed.get(key) : null; },
  setItem(key, value) { backed.set(key, String(value)); },
  removeItem(key) { backed.delete(key); },
};
const store = run(storage).PadiemAuthSession;
assert.equal(store.lastKnownAuthenticated(), false);

// An unconfirmed read changes nothing.
store.update({ ready: false, authenticated: false }, 1);
assert.equal(backed.size, 0);

// A confirmed signed-in answer remembers exactly one boolean value.
store.update({
  ready: true,
  authenticated: true,
  project_files_ready: true,
  user: { email: "person@example.test", name: "Real Person" },
}, 2);
assert.equal(store.lastKnownAuthenticated(), true);
assert.deepEqual([...backed.entries()], [["padiem.chat.auth.lastSignedIn", "1"]]);
const stored = JSON.stringify([...backed.entries()]);
assert(!stored.includes("example"), "storage must not hold an email");
assert(!stored.includes("Real Person"), "storage must not hold a name");

// A failed/unknown read keeps the previous visit's hint for the retry.
store.update({ ready: false, authenticated: false, status_reachable: false }, 3);
assert.equal(store.lastKnownAuthenticated(), true);

// A confirmed sign-out clears the hint.
store.update({ ready: true, authenticated: false }, 4);
assert.equal(store.lastKnownAuthenticated(), false);
assert.equal(backed.size, 0);

// Storage that always throws must not break the screen.
const throwing = {
  getItem() { throw new Error("read blocked"); },
  setItem() { throw new Error("write blocked"); },
  removeItem() { throw new Error("remove blocked"); },
};
const guarded = run(throwing).PadiemAuthSession;
assert.equal(guarded.lastKnownAuthenticated(), false);
guarded.update({ ready: true, authenticated: true, user: { name: "Owner" } }, 5);
guarded.update({ ready: true, authenticated: false }, 6);

// No storage object at all is also fine (server-side/static harnesses).
const bare = run(null).PadiemAuthSession;
assert.equal(bare.lastKnownAuthenticated(), false);
bare.update({ ready: true, authenticated: true }, 7);
''', encoding="utf-8")
    result = subprocess.run(
        [shutil.which("node") or "node", str(harness), str(BASE / "auth-session.js")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_source_keeps_every_storage_access_guarded() -> None:
    assert 'const LAST_SIGNED_IN_KEY = "padiem.chat.auth.lastSignedIn";' in AUTH
    assert 'window.localStorage.getItem(LAST_SIGNED_IN_KEY) === "1"' in AUTH
    assert 'window.localStorage.setItem(LAST_SIGNED_IN_KEY, "1")' in AUTH
    assert "window.localStorage.removeItem(LAST_SIGNED_IN_KEY)" in AUTH
    # Every localStorage use sits inside a try/catch, and the confirmed answer
    # is the only thing that can change the stored hint.
    assert AUTH.count("try {") >= 2
    assert "if (data.ready === true) rememberSignedIn(authenticated);" in AUTH
    remember = AUTH.split("function rememberSignedIn", 1)[1].split("// Before the auth status", 1)[0]
    assert "user" not in remember and "email" not in remember and "name" not in remember
