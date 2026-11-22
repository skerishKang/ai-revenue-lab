"""#7647: the withdrawal answer marks a pending shared-login finish on its own.

The screen picks its copy from the response ``cleanup`` — the reader is
``static/chat-account-module.js`` in ``submitAccountDelete`` (the
``deps.uiT(cleanupMessageKey)`` call) — so the answer must say which kind is
still pending: stored files and connections, the shared-login finish, or both.
The message difference is asserted on the backend flag and, through the real
module in Node, on the copy key the screen picks.
"""
from __future__ import annotations
import locale_bundle

import json
import shutil
import subprocess
from pathlib import Path

from app.account_deletion import _CLEANUP_PENDING_MESSAGE
from _support.account_deletion import BASE, DELETER_EMAIL, call, token_for
from test_bookai_account_deletion_7547 import fixture

STATIC = Path(__file__).resolve().parents[1] / "static"

# The copy keys the screen picks, by what the answer says is pending.
EXPECTED_KEYS = {
    "done": "account-delete-done",
    "filesOnly": "account-delete-cleanup-pending",
    "sharedOnly": "account-delete-cleanup-pending-shared-login-only",
    "filesAndShared": "account-delete-cleanup-pending-shared-login",
    "sharedDeleteDone": "account-shared-delete-done",
    "sharedDeleteSharedOnly": "account-delete-cleanup-pending-shared-login-only",
}

_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
let currentElements = {};
const ctx = {
  window: null,
  document: { documentElement: { lang: "ko" }, getElementById: (id) => currentElements[id] || null },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
  setTimeout, clearTimeout, console, Error, Object, Array, String,
  Number, Boolean, Promise, Map, Set, JSON, Date, URL,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(source, ctx);
async function runDelete(answer, deleteAllServices) {
  const notes = [];
  const deps = {
    accountDeleteButton: { disabled: false },
    accountDeleteConfirmEmail: { value: "owner@example.test" },
    accountDeleteError: null,
    accountSharedDeleteButton: { disabled: false },
    accountSharedDeleteConfirmEmail: { value: "owner@example.test" },
    accountSharedDeleteError: null,
    passwordAuthRequest: async () => answer,
    setAuthFormError: (node, message) => { if (message !== undefined) notes.push(message); },
    uiT: (key) => key,
    resetAccountDeleteConfirm: () => {},
    resetAccountSharedDeleteConfirm: () => {},
    accountDeleteConfirm: { hidden: false },
    accountSharedDeleteConfirm: { hidden: false },
    closeSettings: () => {},
    loadAuthStatus: async () => {},
    authDialog: { open: true },
    openAuthDialog: () => {},
    passwordLoginError: {},
  };
  currentElements = deps;
  const api = ctx.window.PadiemChatAccountModule.create(deps);
  await api.submitAccountDelete(Boolean(deleteAllServices));
  return notes[notes.length - 1];
}
(async () => {
  const results = {};
  results.done = await runDelete(
    { ok: true, cleanup: { complete: true, pending: 0, shared_login_pending: false } }, false);
  results.filesOnly = await runDelete(
    { ok: true, cleanup: { complete: false, pending: 2, shared_login_pending: false } }, false);
  results.sharedOnly = await runDelete(
    { ok: true, cleanup: { complete: false, pending: 1, shared_login_pending: true } }, false);
  results.filesAndShared = await runDelete(
    { ok: true, cleanup: { complete: false, pending: 3, shared_login_pending: true } }, false);
  results.sharedDeleteDone = await runDelete({ ok: true }, true);
  results.sharedDeleteSharedOnly = await runDelete(
    { ok: true, cleanup: { complete: false, pending: 1, shared_login_pending: true } }, true);
  process.stdout.write(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def _withdraw(monkeypatch=None, files_pending: int | None = None, shared_pending: bool = True):
    db, accounts, app, settings, authority, events = fixture(mixed=True)
    if files_pending is not None:
        async def files_left(request, db, targets):
            return {"done": 0, "failed": 0, "waiting": 0, "pending": files_pending}

        monkeypatch.setattr("app.account_deletion._drain_cleanup", files_left)

    if shared_pending:
        async def concurrently_removed(**kwargs):
            # Chat saw more than one live link, so it skipped the preparation and
            # called remove_product_link without a number; the authority deletes
            # the common account anyway (another link died in between).
            assert kwargs["account_deletion_operation_id"] is None
            authority.links.clear()
            return {"removed": False, "common_account_deleted": True, "already_deleted": True}

        authority.remove_product_link = concurrently_removed
    response = call(app, settings, "POST", "/api/account/delete", origin=BASE,
                    token=token_for(settings, accounts["deleter"]),
                    body={"confirm": DELETER_EMAIL})
    return db, app, response


def test_a_pending_shared_login_finish_is_its_own_flag():
    db, app, response = _withdraw()
    body = response.json()
    # Every leftover row — the stored-file items plus the one shared-login
    # finish — is counted, and the answer names the finish on its own.
    rows = db.conn.execute(
        "SELECT COUNT(*) AS n FROM account_deletion_cleanup_pending").fetchone()["n"]
    assert rows >= 1
    assert body["cleanup"] == {
        "complete": False, "pending": rows, "shared_login_pending": True,
    }
    assert body["message"] == _CLEANUP_PENDING_MESSAGE


def test_leftover_files_without_a_shared_finish_keep_the_old_shape(monkeypatch):
    db, app, response = _withdraw(monkeypatch, files_pending=2, shared_pending=False)
    body = response.json()
    assert body["cleanup"] == {
        "complete": False, "pending": 2, "shared_login_pending": False,
    }
    assert body["message"] == _CLEANUP_PENDING_MESSAGE


def test_leftover_files_and_a_shared_finish_are_reported_together(monkeypatch):
    db, app, response = _withdraw(monkeypatch, files_pending=2)
    body = response.json()
    # Two stored-file items plus the one shared-login finish item.
    assert body["cleanup"] == {
        "complete": False, "pending": 3, "shared_login_pending": True,
    }


def test_the_screen_picks_the_copy_by_what_is_pending():
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required to run the auth module harness")
    completed = subprocess.run(
        [node, "-e", _HARNESS, str(STATIC / "chat-account-module.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    results = json.loads(completed.stdout.strip().splitlines()[-1])
    assert results == EXPECTED_KEYS, results


def test_both_languages_name_the_shared_login_finish():
    locale = locale_bundle.SOURCE.read_text(encoding="utf-8")
    for key in ("account-delete-cleanup-pending-shared-login",
                "account-delete-cleanup-pending-shared-login-only"):
        # One Korean entry and one English entry.
        assert locale.count(f'"{key}"') == 2, key
    assert "공통 로그인 마무리가 아직 끝나지 않아 자동으로 다시 시도합니다" in locale
    assert "common login finalization have not finished yet and will be retried automatically" in locale
