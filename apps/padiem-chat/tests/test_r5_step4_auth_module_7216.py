"""#7216 R5 step 4 — 로그인 세션 모듈 계약.

app.js의 로그인 세션 41개 함수가 chat-auth-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. 이 시험은 (1) 실제 모듈 본문을 Node vm에서
실행해 동작이 그대로인지, (2) deps getter가 첫 호출 전에 바뀐 클로저 값을
읽는지, (3) setter가 다시 대입하는 변수를 클로저에 쓰는지, (4) app.js가 전달
함수만 남겼고 index.html이 모듈을 app.js보다 먼저 로드하는지를 확인한다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-auth-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

NAMES = (
    "closeProfilePanel", "accountInitial", "resolveSessionPresentation",
    "setLoginButtonCopy", "applyAuthState", "authMethodEnabled", "setAuthFormError",
    "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog",
    "authServerUnreachableError", "passwordAuthAnswer", "passwordAuthRequest",
    "submitPasswordLogin", "submitPasswordRegister", "setAuthStatusMessage",
    "passwordResetTokenFromLocation", "clearPasswordResetFragment",
    "showPasswordResetView", "hidePasswordResetViews", "openPasswordResetRequest",
    "openPasswordResetConfirm", "closePasswordResetViews", "submitPasswordResetRequest",
    "submitPasswordResetConfirm", "openPasswordChangeDialog", "closePasswordChangeDialog",
    "submitPasswordChange", "resetAccountDeleteConfirm", "resetAccountSharedDeleteConfirm",
    "openAccountDeleteConfirm", "openAccountSharedDeleteConfirm", "syncAccountDeleteButton",
    "syncAccountSharedDeleteButton", "submitAccountDelete", "loadAuthStatus",
    "requireSessionForModelUse", "signOutCurrentAccount", "invalidateClawApprovalSession",
    "noteClawApprovalSession", "reviewedGoogleAuthorizationUrl",
)

MOVED_MARKERS = (
    "deps.authViewEpoch += 1;",
    'error.code = deps.AUTH_SERVER_UNREACHABLE;',
    "deps.loginButton.hidden = presentation.loginHidden;",
    "deps.clawApprovalEpoch += 1;",
    'url.hostname !== "accounts.google.com"',
    "deps.passwordResetToken = token;",
    "await deps.loadAuthStatus();",
)


def test_index_loads_the_auth_module_before_app() -> None:
    assert INDEX.index("./chat-auth-module.js") < INDEX.index("./app.js")
    assert INDEX.count("./chat-auth-module.js") == 1


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    for name in NAMES:
        line = f"function {name}(...a) {{ return authModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function authModule() {" in APP
    assert "window.PadiemChatAuthModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    assert "window.PadiemChatAuthModule = {" in MODULE
    assert "create(deps) {" in MODULE
    # The moved bodies keep their original document lookups (behavior 0 change);
    # what matters is that the factory body performs none at create() time.
    assert "document.getElementById" in MODULE
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: false, disabled: false, textContent: "", value: "", dataset: {},
    attrs, listeners: {}, shown: 0, closed: 0, focused: 0,
    showModal() { this.shown += 1; this.open = true; },
    close() { this.closed += 1; this.open = false; },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    focus() { this.focused += 1; }, select() {},
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, contains() { return true; },
  };
}

const live = {
  authState: { ready: true, authenticated: false, user: null, history_ready: true,
               model_requires_session: true, account_method: "password",
               session_state: "guest", methods: { password: true, google: false } },
  authViewEpoch: 0,
  authDialogView: null,
  passwordResetToken: "",
  clawApprovalEpoch: 0,
  clawApprovalInFlight: false,
  clawApprovalSessionToken: "",
  pendingNotificationConversationId: "",
  pendingNotificationRunId: "",
  AUTH_SERVER_UNREACHABLE: "auth_server_unreachable",
  AUTH_UNREACHABLE_RETRY_DELAY_MS: 600,
  SESSION_PRESENTATION: {
    unreachable: { loginHidden: false, loginDisabled: true, accountHidden: true, accountNameHidden: true },
    unavailable: { loginHidden: false, loginDisabled: false, accountHidden: true, accountNameHidden: true },
    guest: { loginHidden: false, loginDisabled: false, accountHidden: true, accountNameHidden: true },
    signed_in: { loginHidden: true, loginDisabled: false, accountHidden: false, accountNameHidden: false },
    expired: { loginHidden: false, loginDisabled: false, accountHidden: false, accountNameHidden: false },
  },
  shell: { dataset: {} },
  projects: [],
  historySection: makeElement("historySection"),
  accountAvatar: makeElement("accountAvatar"),
  accountName: makeElement("accountName"),
  accountContainer: makeElement("accountContainer"),
  accountSettingsSection: makeElement("accountSettingsSection"),
  accountPasswordActions: makeElement("accountPasswordActions"),
  accountDeleteActions: makeElement("accountDeleteActions"),
  accountDeleteButton: makeElement("accountDeleteButton"),
  accountDeleteConfirm: makeElement("accountDeleteConfirm"),
  accountDeleteConfirmEmail: makeElement("accountDeleteConfirmEmail"),
  accountDeleteError: makeElement("accountDeleteError"),
  accountSharedDeleteButton: makeElement("accountSharedDeleteButton"),
  accountSharedDeleteConfirm: makeElement("accountSharedDeleteConfirm"),
  accountSharedDeleteConfirmEmail: makeElement("accountSharedDeleteConfirmEmail"),
  accountSharedDeleteError: makeElement("accountSharedDeleteError"),
  advancedAccountSection: makeElement("advancedAccountSection"),
  advancedSettingsView: makeElement("advancedSettingsView"),
  authDialog: makeElement("authDialog"),
  authDivider: makeElement("authDivider"),
  authHandoff: makeElement("authHandoff"),
  googleLoginButton: makeElement("googleLoginButton"),
  loginButton: makeElement("loginButton"),
  passwordLoginForm: makeElement("passwordLoginForm"),
  passwordLoginIdentifier: makeElement("passwordLoginIdentifier"),
  passwordLoginPassword: makeElement("passwordLoginPassword"),
  passwordLoginError: makeElement("passwordLoginError"),
  passwordLoginSubmit: makeElement("passwordLoginSubmit"),
  passwordRegisterSection: makeElement("passwordRegisterSection"),
  passwordRegisterForm: makeElement("passwordRegisterForm"),
  passwordRegisterName: makeElement("passwordRegisterName"),
  passwordRegisterEmail: makeElement("passwordRegisterEmail"),
  passwordRegisterPassword: makeElement("passwordRegisterPassword"),
  passwordRegisterError: makeElement("passwordRegisterError"),
  passwordRegisterSubmit: makeElement("passwordRegisterSubmit"),
  passwordResetOpen: makeElement("passwordResetOpen"),
  passwordResetPanel: makeElement("passwordResetPanel"),
  passwordResetRequestView: makeElement("passwordResetRequestView"),
  passwordResetRequestForm: makeElement("passwordResetRequestForm"),
  passwordResetRequestError: makeElement("passwordResetRequestError"),
  passwordResetRequestStatus: makeElement("passwordResetRequestStatus"),
  passwordResetRequestSubmit: makeElement("passwordResetRequestSubmit"),
  passwordResetEmail: makeElement("passwordResetEmail"),
  passwordResetNew: makeElement("passwordResetNew"),
  passwordResetConfirmView: makeElement("passwordResetConfirmView"),
  passwordResetConfirmForm: makeElement("passwordResetConfirmForm"),
  passwordResetConfirmError: makeElement("passwordResetConfirmError"),
  passwordResetConfirmStatus: makeElement("passwordResetConfirmStatus"),
  passwordResetConfirmSubmit: makeElement("passwordResetConfirmSubmit"),
  passwordResetConfirm: makeElement("passwordResetConfirm"),
  passwordResetConfirmBack: makeElement("passwordResetConfirmBack"),
  passwordChangeDialog: makeElement("passwordChangeDialog"),
  passwordChangeForm: makeElement("passwordChangeForm"),
  passwordChangeCurrent: makeElement("passwordChangeCurrent"),
  passwordChangeNew: makeElement("passwordChangeNew"),
  passwordChangeConfirm: makeElement("passwordChangeConfirm"),
  passwordChangeSubmit: makeElement("passwordChangeSubmit"),
  passwordChangeError: makeElement("passwordChangeError"),
  passwordChangeDialogClose: makeElement("passwordChangeDialogClose"),
  profilePanel: makeElement("profilePanel"),
  profileToggle: makeElement("profileToggle"),
  projectsBadge: makeElement("projectsBadge"),
  uiT: (key) => key,
  clawT: (key) => key,
  setNote: (message, kind) => { live.note = [message, kind]; },
  setNavActive: () => {},
  closeSettings: () => { live.closedSettings = true; },
  clearProjectsUI: () => { live.clearedProjects = true; },
  loadProjects: () => { live.loadedProjects = true; },
  loadRecentConversations: () => { live.loadedHistory = true; },
  scheduleSharedRefresh: () => { live.scheduled = true; },
  syncApprovedMemoryVisibility: () => {},
  syncClawRunHistoryVisibility: () => {},
  resetConversation: () => { live.resetConversation = true; },
  resetConversationView: (hard) => { live.resetView = hard; },
  openSavedConversation: (id) => { live.opened = id; },
  openClawRunTarget: (id) => { live.runTarget = id; },
  renderAndroidHandoff: () => {},
  startAndroidHandoff: () => { live.handoff = true; },
  isAndroidWebView: () => false,
  loveTreeHandoffFromLocation: () => null,
  fetchAuthStatusOnce: async () => ({ ready: true, authenticated: false, user: null }),
  fetch: async (...a) => { live.fetchCalls.push(a); return live.fetchImpl(...a); },
  fetchCalls: [],
  fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }),
};
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}

const ctx = {
  document: {
    getElementById: () => null,
    createElement: () => makeElement("created"),
    createTextNode: (text) => ({ textContent: text }),
  },
  console,
  window: {
    PadiemAuthSession: { update: (state, epoch) => { live.sessionUpdate = [state, epoch]; },
                         get: () => live.sessionGet || null },
    PadiemSharedTooltip: null,
    location: { search: "", hash: "" },
    history: { replaceState: () => {} },
  },
  fetch: live.fetch,
  URL,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {},
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, encodeURIComponent,
  decodeURIComponent, String, Object, Boolean, Number, Array, Promise,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "chat-auth-module.js" });
// The moved functions call each other through deps (the app.js factory serves
// the forwarders there); the harness serves the module's own exports the same
// way. Lazy getters resolve after create() returns.
const INTERNAL = ["applyAuthState", "authMethodEnabled", "authServerUnreachableError",
  "clearPasswordResetFragment", "closeAuthDialog", "closePasswordChangeDialog",
  "closeProfilePanel", "hidePasswordResetViews", "invalidateClawApprovalSession",
  "loadAuthStatus", "openAuthDialog", "passwordAuthAnswer", "passwordAuthRequest",
  "passwordResetTokenFromLocation", "resetAccountDeleteConfirm",
  "resetAccountSharedDeleteConfirm", "resolveSessionPresentation", "setAuthFormError",
  "setAuthStatusMessage", "setLoginButtonCopy", "showPasswordResetView",
  "syncAuthDialogMethods"];
let api;
for (const name of INTERNAL) {
  Object.defineProperty(deps, name, { get() { return api[name]; } });
}
api = ctx.window.PadiemChatAuthModule.create(r5StrictDeps(deps, "step4.deps"));
const results = {};

// 1. accountInitial keeps the avatar letter rule.
results.initial = [api.accountInitial("Kim"), api.accountInitial(""), api.accountInitial(null)];

// 2. openAuthDialog shows the dialog and offers the enabled methods only.
api.openAuthDialog();
results.openDialog = { shown: live.authDialog.shown, view: live.authDialogView,
  focused: live.passwordLoginIdentifier.focused };

// 3. closeAuthDialog closes the same dialog.
api.closeAuthDialog();
results.closeDialog = { closed: live.authDialog.closed };

// 4. requireSessionForModelUse gates guests when the deployment asks for a session.
live.authState.authenticated = false;
results.gateBlocked = api.requireSessionForModelUse();
results.gateNote = live.note;
live.authState.model_requires_session = false;
results.gateAllowed = api.requireSessionForModelUse();
live.authState.model_requires_session = true;
live.authState.authenticated = true;
results.gateSignedIn = api.requireSessionForModelUse();

// 5. applyAuthState projects the session onto the surfaces through the rule.
live.authDialogView = null;
api.applyAuthState({ ready: true, authenticated: true, user: { name: "Kim" },
  history_ready: true, account_method: "password" });
results.applied = { epoch: live.authViewEpoch, avatar: live.accountAvatar.textContent,
  name: live.accountName.textContent, loginHidden: live.loginButton.hidden,
  accountHidden: live.accountContainer.hidden,
  passwordActions: live.accountPasswordActions.hidden,
  deleteActions: live.accountDeleteActions.hidden,
  sessionEpoch: live.sessionUpdate && live.sessionUpdate[1] };

// 6. the fallback object never invents an authenticated account.
api.applyAuthState(null);
results.fallback = { authenticated: live.authState.authenticated,
  ready: live.authState.ready, loginHidden: live.loginButton.hidden };

// 7. authServerUnreachableError carries the shipped code and copy key.
const error = api.authServerUnreachableError();
results.unreachable = { code: error.code, message: error.message };

// 8. passwordAuthAnswer accepts only a route object.
results.answer = [api.passwordAuthAnswer({ ok: true }), api.passwordAuthAnswer(null),
  api.passwordAuthAnswer([1]), api.passwordAuthAnswer("x")];

// 9. Getter contract: the dialog replaced before the first call is the one shown.
const lateDialog = makeElement("lateDialog");
live.authDialog = lateDialog;
api.openAuthDialog("login");
results.getter = { shown: lateDialog.shown };

// 10. Setter contract: the generation bump writes back through deps.
const before = live.clawApprovalEpoch;
api.invalidateClawApprovalSession();
results.setter = { bumped: live.clawApprovalEpoch === before + 1,
  token: live.clawApprovalSessionToken, inFlight: live.clawApprovalInFlight };

// 11. noteClawApprovalSession stores a fresh token only when it changes.
api.noteClawApprovalSession(true);
const firstToken = live.clawApprovalSessionToken;
api.noteClawApprovalSession(true);
results.noteToken = { first: firstToken !== "", stable: live.clawApprovalSessionToken === firstToken };

// 12. reviewedGoogleAuthorizationUrl enforces the reviewed origin rules.
results.policy = [
  api.reviewedGoogleAuthorizationUrl("https://accounts.google.com/o/oauth2/v2/auth?x=1"),
  api.reviewedGoogleAuthorizationUrl("http://accounts.google.com/o/oauth2/v2/auth"),
  api.reviewedGoogleAuthorizationUrl("https://evil.example/o/oauth2/v2/auth"),
  api.reviewedGoogleAuthorizationUrl("https://accounts.google.com/o/oauth2/v2/auth#f"),
];

process.stdout.write(JSON.stringify(results));
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(STRICT + "\n" + _HARNESS, encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-auth-module.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope="module")
def observed() -> dict:
    return _run_harness()


def test_module_behavior_matches_the_closed_over_originals(observed: dict) -> None:
    assert observed["initial"] == ["K", "", ""]
    assert observed["openDialog"] == {"shown": 1, "view": "login", "focused": 1}
    assert observed["closeDialog"]["closed"] == 1
    assert observed["gateBlocked"] is False
    assert observed["gateNote"] == ["model-requires-login", "error"]
    assert observed["gateAllowed"] is True
    assert observed["gateSignedIn"] is True
    assert observed["applied"] == {"epoch": 1, "avatar": "K", "name": "Kim",
                                   "loginHidden": True, "accountHidden": False,
                                   "passwordActions": False, "deleteActions": False,
                                   "sessionEpoch": 1}
    assert observed["fallback"] == {"authenticated": False, "ready": False,
                                    "loginHidden": False}
    assert observed["unreachable"] == {"code": "auth_server_unreachable",
                                       "message": "auth-server-unreachable"}
    assert observed["answer"] == [True, False, False, False]
    assert observed["policy"] == ["https://accounts.google.com/o/oauth2/v2/auth?x=1",
                                  None, None, None]


def test_getters_read_the_value_changed_before_the_first_call(observed: dict) -> None:
    # The dialog installed before the open call is the one that opens.
    assert observed["getter"] == {"shown": 1}


def test_setters_write_the_bookkeeping_back_into_the_closure(observed: dict) -> None:
    assert observed["setter"] == {"bumped": True, "token": "", "inFlight": False}
    assert observed["noteToken"] == {"first": True, "stable": True}