"""#7812 B4-1 — account request/copy golden, using synthetic responses only.

The same executable fixture runs against the pre-split auth module and the
post-split account + auth modules. Every destructive or credential-changing
response is supplied by this harness; no account or production route is used.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

function element(id) {
  return {
    id, hidden: false, disabled: false, value: "", textContent: "", open: false,
    focused: 0,
    addEventListener() {},
    focus() { this.focused += 1; },
    showModal() { this.open = true; },
    close() { this.open = false; },
    setAttribute(name, value) { this[name] = String(value); },
    removeAttribute(name) { delete this[name]; },
  };
}

const ids = [
  "accountDeleteOpen", "accountSharedDeleteOpen", "accountDeleteConfirmEmail",
  "accountDeleteButton", "accountDeleteError", "accountSharedDeleteConfirm",
  "accountSharedDeleteConfirmEmail", "accountSharedDeleteButton", "accountSharedDeleteError",
  "passwordChangeOpen", "passwordChangeDialog", "passwordChangeDialogClose",
  "passwordChangeForm", "passwordChangeCurrent", "passwordChangeNew", "passwordChangeConfirm",
  "passwordChangeError", "passwordChangeSubmit", "passwordResetRequestForm",
  "passwordResetRequestSubmit", "passwordResetConfirmForm", "passwordResetConfirm",
  "passwordResetConfirmSubmit", "passwordResetBack", "passwordResetConfirmBack",
  "accountDeleteConfirm", "authDialog", "authDivider", "googleLoginButton",
  "passwordLoginContinue", "passwordLoginError", "passwordResetOpen", "passwordResetPanel",
  "passwordResetRequestView", "passwordResetConfirmView", "passwordResetEmail",
  "passwordResetRequestError", "passwordResetRequestStatus", "passwordResetNew",
  "passwordResetConfirmError", "passwordResetConfirmStatus",
];
const live = Object.fromEntries(ids.map((id) => [id, element(id)]));
Object.assign(live, {
  authState: {
    ready: true, authenticated: true, user: { name: "Synthetic", email: "owner@example.invalid" },
    methods: { password: true, google: false },
  },
  authDialogView: "login",
  passwordResetToken: "",
  sharedRefreshTimer: null,
  uiT: (key) => key,
  closeSettings() { live.settingsClosed = (live.settingsClosed || 0) + 1; },
  async loadAuthStatus() { live.statusLoads = (live.statusLoads || 0) + 1; },
  openAuthDialog() { live.dialogOpens = (live.dialogOpens || 0) + 1; },
});
live.authDialog.open = true;

const sent = [];
let answer = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}

const ctx = {
  window: {
    location: { hash: "", search: "", pathname: "/", assign() {} },
    history: { replaceState() {} },
  },
  document: {
    documentElement: { lang: "en" },
    getElementById: (id) => live[id] || null,
  },
  async fetch(url, init) {
    sent.push({ url, method: init.method, bodyKeys: Object.keys(JSON.parse(init.body)).sort() });
    return answer();
  },
  console, URL, Error, Object, Array, String, Number, Boolean, Promise, Map, Set, JSON, Date,
  setTimeout: (fn) => fn(), clearTimeout() {},
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx, { filename: "chat-auth-module.js" });
if (process.argv[3]) {
  vm.runInContext(fs.readFileSync(process.argv[3], "utf8"), ctx, { filename: "chat-account-module.js" });
}

const liveGetters = Object.keys(live);
const depsForAuthAndAccount = {};
for (const key of liveGetters) Object.defineProperty(depsForAuthAndAccount, key, Object.getOwnPropertyDescriptor(deps, key));
let api;
for (const key of ["authMethodEnabled", "authServerUnreachableError", "passwordAuthAnswer", "passwordAuthRequest", "setAuthFormError", "setAuthStatusMessage", "syncAuthDialogMethods", "passwordResetTokenFromLocation", "clearPasswordResetFragment", "showPasswordResetView", "hidePasswordResetViews", "closePasswordChangeDialog", "resetAccountDeleteConfirm", "resetAccountSharedDeleteConfirm"]) {
  Object.defineProperty(depsForAuthAndAccount, key, { get() { return api[key]; }, configurable: true });
}
const authApi = ctx.window.PadiemChatAuthModule.create(depsForAuthAndAccount);
const accountApi = ctx.window.PadiemChatAccountModule
  ? ctx.window.PadiemChatAccountModule.create(depsForAuthAndAccount)
  : {};
api = Object.assign({}, authApi, accountApi);

function requests() {
  return sent.splice(0).map(({ url, method, bodyKeys }) => ({ url, method, bodyKeys }));
}
function screen(node, extra = {}) {
  return { node, message: live[node].textContent, hidden: live[node].hidden, ...extra };
}

(async () => {
  const golden = [];

  live.passwordResetEmail.value = "owner@example.invalid";
  await api.openPasswordResetRequest();
  await api.submitPasswordResetRequest({ preventDefault() {} });
  golden.push({
    path: "reset_request", requests: requests(),
    screen: screen("passwordResetRequestStatus"),
  });

  answer = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });
  await api.openPasswordChangeDialog();
  live.passwordChangeCurrent.value = "synthetic-current";
  live.passwordChangeNew.value = "synthetic-new";
  live.passwordChangeConfirm.value = "synthetic-new";
  await api.submitPasswordChange({ preventDefault() {} });
  golden.push({
    path: "password_change_success", requests: requests(),
    screen: screen("passwordLoginError"),
  });

  answer = async () => ({ ok: false, status: 403, json: async () => ({
    error: { code: "invalid_current_password", message: "synthetic-current-password-refused" },
  }) });
  await api.openPasswordChangeDialog();
  live.passwordChangeCurrent.value = "synthetic-current";
  live.passwordChangeNew.value = "synthetic-new";
  live.passwordChangeConfirm.value = "synthetic-new";
  await api.submitPasswordChange({ preventDefault() {} });
  golden.push({
    path: "password_change_failure", requests: requests(),
    screen: screen("passwordChangeError"),
  });

  answer = async () => ({ ok: true, status: 200, json: async () => ({
    ok: true, cleanup: { complete: true, pending: 0, shared_login_pending: false },
  }) });
  await api.openAccountDeleteConfirm();
  live.accountDeleteConfirmEmail.value = "different@example.invalid";
  await api.syncAccountDeleteButton();
  await api.submitAccountDelete(false);
  golden.push({
    path: "account_delete_cancel_unconfirmed", requests: requests(),
    screen: screen("accountDeleteError", { buttonDisabled: live.accountDeleteButton.disabled }),
  });

  await api.openAccountDeleteConfirm();
  live.accountDeleteConfirmEmail.value = "owner@example.invalid";
  await api.syncAccountDeleteButton();
  await api.submitAccountDelete(false);
  golden.push({
    path: "account_delete_confirmed", requests: requests(),
    screen: screen("passwordLoginError"),
  });

  process.stdout.write(JSON.stringify(golden));
})().catch((error) => { console.error(error); process.exit(1); });
"""

EXPECTED = [
    {
        "path": "reset_request",
        "requests": [{"url": "/api/auth/password/reset/request", "method": "POST", "bodyKeys": ["email"]}],
        "screen": {"node": "passwordResetRequestStatus", "message": "auth-reset-request-sent", "hidden": False},
    },
    {
        "path": "password_change_success",
        "requests": [{"url": "/api/auth/password/change", "method": "POST", "bodyKeys": ["current_password", "new_password"]}],
        "screen": {"node": "passwordLoginError", "message": "password-change-done", "hidden": False},
    },
    {
        "path": "password_change_failure",
        "requests": [{"url": "/api/auth/password/change", "method": "POST", "bodyKeys": ["current_password", "new_password"]}],
        "screen": {"node": "passwordChangeError", "message": "synthetic-current-password-refused", "hidden": False},
    },
    {
        "path": "account_delete_cancel_unconfirmed",
        "requests": [],
        "screen": {"node": "accountDeleteError", "message": "", "hidden": True, "buttonDisabled": True},
    },
    {
        "path": "account_delete_confirmed",
        "requests": [{"url": "/api/account/delete", "method": "POST", "bodyKeys": ["confirm"]}],
        "screen": {"node": "passwordLoginError", "message": "account-delete-done", "hidden": False},
    },
]


def account_golden() -> list[dict]:
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required for the account golden harness")
    account = STATIC / "chat-account-module.js"
    with tempfile.TemporaryDirectory() as temp:
        harness = Path(temp) / "harness.js"
        harness.write_text(HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-auth-module.js"), str(account) if account.exists() else ""],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    golden = json.loads(completed.stdout)
    output = os.environ.get("R5_B4_ACCOUNT_GOLDEN_OUT")
    if output:
        Path(output).write_text(json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return golden


def test_account_golden_paths_preserve_requests_and_screen_copy() -> None:
    assert account_golden() == EXPECTED
