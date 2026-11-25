"""R5 step 4 로그인 세션 모듈 실행 하네스 (#7186 R2).

`chat-auth-module.js`(R5 #7275가 app.js에서 옮긴 로그인 세션 구역)를 Node vm에서
실제로 실행해 관찰한다. 문자열 검사 대신:

- 선박 표(`SESSION_PRESENTATION`, app.js의 실제 리터럴)를 주입한 뒤 인증 상태
  값별로 어떤 요소가 보이고 숨는지, 문구·aria가 무엇인지
- 로그인·로그아웃이 보내는 요청의 method·경로·본문과 부수 호출
- 응답 봉투가 없는 실패를 재시도하는 정책(재설정 확인만 1회 재시도)
- applyAuthState가 세션을 `window.PadiemAuthSession`에 발행하는지

를 돌려준다. 여러 시험 파일이 같은 관찰을 공유한다(_r5_strict_deps.js 계열의
헬퍼 모듈). 값·토큰은 만들지 않는다: 폼 값은 합성 문자열이다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-auth-module.js").read_text(encoding="utf-8")
ACCOUNT = (STATIC / "chat-account-module.js").read_text(encoding="utf-8")
DIALOG = (STATIC / "chat-login-dialog-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")


def presentation_table() -> dict:
    """선박 표를 auth 모듈 리터럴에서 읽는다(복제가 아니라 실제 값)."""

    source = APP + MODULE
    start = source.index("const SESSION_PRESENTATION = {")
    start = source.index("{", start)
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(source[start : index + 1])
    raise AssertionError("SESSION_PRESENTATION literal is not closed")


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
    click() { this.clicks = (this.clicks || 0) + 1; (this.listeners.click || []).forEach((fn) => fn()); },
    appendChild(child) { (this.children ||= []).push(child); child.isConnected = true; return child; },
    append(...nodes) { nodes.forEach((n) => this.appendChild(n)); },
    replaceChildren(...nodes) { this.children = []; nodes.forEach((n) => this.appendChild(n)); },
    replaceWith() {},
    replaceChild(next, old) {
      const at = (this.children || []).indexOf(old);
      if (at >= 0) this.children[at] = next;
    },
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
  SESSION_PRESENTATION: SHIPPED_PRESENTATION,
  shell: { dataset: {} },
  projects: [],
  historySection: makeElement("historySection"),
  historyList: makeElement("historyList"),
  historyEmpty: makeElement("historyEmpty"),
  historyActionStatus: makeElement("historyActionStatus"),
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
  settingsAccountEmail: makeElement("settingsAccountEmail"),
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
  passwordLoginContinue: makeElement("passwordLoginContinue"),
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
  clearProjectsUI: () => { live.clearedProjects = (live.clearedProjects || 0) + 1; },
  loadProjects: () => { live.loadedProjects = true; },
  loadRecentConversations: () => { live.loadedHistory = true; },
  scheduleSharedRefresh: () => { live.scheduled = (live.scheduled || 0) + 1; },
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
  loadAuthCount: 0,
  // The sign-in/sign-out paths await deps.loadAuthStatus(); count the call
  // here (a stub: the definitive answer is applied by the state matrix).
  loadAuthStatus: async () => { live.loadAuthCount += 1; },
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
    getElementById: (id) => live[id] || null,
    createElement: () => makeElement("created"),
    createTextNode: (text) => ({ textContent: text }),
  },
  console,
  window: {
    PadiemAuthSession: { update: (state, epoch) => { live.sessionUpdates.push({ state, epoch }); },
                         get: () => live.sessionGet || null },
    PadiemSharedTooltip: null,
    location: { search: "", hash: "", pathname: "/", assign: () => {} },
    history: { replaceState: () => {} },
  },
  fetch: live.fetch,
  URL,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {},
  Map, Set, Array, JSON, Promise, Date, Error, TypeError, encodeURIComponent,
  decodeURIComponent, String, Object, Boolean, Number,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
const source = fs.readFileSync(process.argv[2], "utf8");
vm.runInContext(source, ctx, { filename: "chat-auth-module.js" });
vm.runInContext(fs.readFileSync(process.argv[3], "utf8"), ctx, { filename: "chat-account-module.js" });
vm.runInContext(fs.readFileSync(process.argv[4], "utf8"), ctx, { filename: "chat-login-dialog-module.js" });
live.sessionUpdates = [];
const INTERNAL = ["applyAuthState", "authMethodEnabled",
  "authServerUnreachableError", "closeAuthDialog", "emailContinueElement",
  "openAuthDialog", "passwordAuthAnswer", "passwordAuthRequest",
  "setAuthFormError", "setAuthStatusMessage", "syncAuthDialogMethods",
  "clearPasswordResetFragment", "closePasswordChangeDialog",
  "closeProfilePanel", "hidePasswordResetViews", "invalidateClawApprovalSession",
  "passwordResetTokenFromLocation", "resetAccountDeleteConfirm",
  "resetAccountSharedDeleteConfirm", "resolveSessionPresentation",
  "setLoginButtonCopy", "showPasswordResetView"];
// #7812 B4-2: dialog functions now live in chat-login-dialog-module.js. The
// INTERNAL getters above keep the shared surface for the account module; the
// dialog module is created first so its API can be merged into `api` below.
let api;
for (const name of INTERNAL) {
  Object.defineProperty(deps, name, { get() { return api[name]; } });
}
const dialogApi = ctx.window.PadiemChatLoginDialogModule.create(r5StrictDeps(deps, "step4.dialog.deps"));
const authApi = ctx.window.PadiemChatAuthModule.create(r5StrictDeps(deps, "step4.deps"));
// #7812 R5 B4-1: password reset/change and account deletion live in the account
// module; the harness keeps one surface so the existing expectations still run.
const accountDeps = {};
for (const key of ["uiT", "authMethodEnabled", "passwordAuthRequest", "setAuthFormError",
  "setAuthStatusMessage", "syncAuthDialogMethods", "loadAuthStatus", "openAuthDialog",
  "closeAuthDialog", "closeSettings", "authState", "authDialog", "passwordResetToken",
  "authDialogView", "passwordResetOpen", "passwordResetPanel", "passwordResetRequestView",
  "passwordResetConfirmView", "passwordResetEmail", "passwordResetNew", "passwordResetConfirm",
  "passwordLoginContinue",
  "passwordResetRequestError", "passwordResetRequestStatus", "passwordResetConfirmError",
  "passwordResetConfirmStatus", "passwordResetRequestSubmit", "passwordResetConfirmSubmit",
  "accountDeleteConfirm", "passwordLoginError"]) {
  Object.defineProperty(accountDeps, key, {
    get() { return key in live ? live[key] : (dialogApi[key] || authApi[key]); },
    set(value) { live[key] = value; },
  });
}
const accountApi = ctx.window.PadiemChatAccountModule.create(r5StrictDeps(accountDeps, "step4.account.deps"));
api = Object.assign({}, dialogApi, authApi, accountApi);

const results = { states: {}, requests: {}, replay: {} };
function surfaces() {
  return {
    loginHidden: live.loginButton.hidden,
    loginDisabled: live.loginButton.disabled,
    loginAriaDisabled: live.loginButton.getAttribute("aria-disabled"),
    loginText: live.loginButton.textContent,
    loginTitle: live.loginButton.getAttribute("title"),
    loginClicks: live.loginButton.clicks || 0,
    accountHidden: live.accountContainer.hidden,
    accountState: live.accountContainer.dataset.accountState || "",
    accountName: live.accountName.textContent,
    accountNameHidden: live.accountName.hidden,
    avatar: live.accountAvatar.textContent,
    historyHidden: live.historySection.hidden,
    historyEmptyHidden: live.historyEmpty.hidden,
    settingsHidden: live.accountSettingsSection.hidden,
    settingsEmail: live.settingsAccountEmail.textContent,
    settingsEmailHidden: live.settingsAccountEmail.hidden,
    passwordActionsHidden: live.accountPasswordActions.hidden,
    deleteActionsHidden: live.accountDeleteActions.hidden,
  };
}

(async () => {
  // 1. accountInitial keeps the avatar letter rule; the error and answer
  //    predicates keep their closed-over shapes.
  results.initial = [api.accountInitial("Kim"), api.accountInitial(""), api.accountInitial(null)];
  const unreachableError = api.authServerUnreachableError();
  results.unreachable = { code: unreachableError.code, message: unreachableError.message };
  results.answer = [api.passwordAuthAnswer({ ok: true }), api.passwordAuthAnswer(null),
    api.passwordAuthAnswer([1]), api.passwordAuthAnswer("x")];

  // 2. Every session state projects the SHIPPED table onto the surfaces.
  const signedIn = { ready: true, authenticated: true,
    user: { name: "Kim", email: "member@example.com" },
    history_ready: true, account_method: "password", methods: { password: true, google: false } };
  const guest = { ready: true, authenticated: false, user: null, account_method: "password",
    session_state: "guest", model_requires_session: true,
    methods: { password: true, google: false } };
  const expired = { ready: true, authenticated: false, user: null, account_method: "password",
    session_state: "expired", model_requires_session: true,
    methods: { password: true, google: false } };
  const unavailable = { ready: false, authenticated: false, user: null,
    status_reachable: true, model_requires_session: true,
    methods: { password: true, google: false } };
  const unreachable = { ready: false, authenticated: false, user: null,
    status_reachable: false, model_requires_session: true,
    methods: { password: true, google: false } };
  const pending = { ready: false, authenticated: false, user: null,
    methods: { password: true, google: false } };
  // A stale "authenticated: true" that never became ready must not project a
  // signed-in account: the derivation is `ready && authenticated`.
  const staleSignedIn = { ready: false, authenticated: true, user: { name: "Kim" },
    methods: { password: true, google: false } };
  for (const [label, value] of Object.entries({ signed_in: signedIn, guest, expired,
      unavailable, unreachable, pending, stale_signed_in: staleSignedIn })) {
    api.applyAuthState(value);
    results.states[label] = surfaces();
  }
  results.fallback = (() => {
    api.applyAuthState(null);
    results.states.null_fallback = surfaces();
    return { authenticated: live.authState.authenticated, ready: live.authState.ready };
  })();
  // An unknown state falls back to the "unreachable" row of the shipped table.
  results.presentationFallback = api.resolveSessionPresentation("unknown_state");

  // 3. The dialog opens on the enabled methods only, and closes the same node.
  api.applyAuthState({ ...guest, methods: { password: true, google: false } });
  api.openAuthDialog();
  results.openDialog = { shown: live.authDialog.shown, view: live.authDialogView,
    focused: live.passwordLoginContinue.focused,
    googleHidden: live.googleLoginButton.hidden,
    dividerHidden: live.authDivider.hidden,
    emailContinueHidden: live.passwordLoginContinue.hidden,
    resetPanelHidden: live.passwordResetPanel.hidden };
  api.closeAuthDialog();
  results.closeDialog = { closed: live.authDialog.closed };

  // 4. The guest gate: signed-in passes, flagged guest is refused with the copy
  //    key and the visible login entry is clicked. An unread state keeps that
  //    entry clickable (it retries the status); an "unavailable" answer hides
  //    and disables it, so the gate opens the dialog instead.
  api.applyAuthState({ ...guest });
  const guestClicks = live.loginButton.clicks || 0;
  results.gateBlocked = api.requireSessionForModelUse();
  results.gateNote = live.note;
  results.gateClicked = (live.loginButton.clicks || 0) - guestClicks;
  api.applyAuthState({ ...guest, model_requires_session: false });
  results.gateAllowed = api.requireSessionForModelUse();
  api.applyAuthState(signedIn);
  results.gateSignedIn = api.requireSessionForModelUse();
  api.applyAuthState(unreachable);
  const unreadClicks = live.loginButton.clicks || 0;
  results.gateUnreadBlocked = api.requireSessionForModelUse();
  results.gateUnreadClicked = (live.loginButton.clicks || 0) - unreadClicks;
  api.applyAuthState(unavailable);
  const unavailableDialogBefore = live.authDialog.shown;
  results.gateUnavailableBlocked = api.requireSessionForModelUse();
  results.gateUnavailableDialog = live.authDialog.shown - unavailableDialogBefore;

  // 5. The email entry in this dialog is a link to the common login, not a
  //    form: opening the dialog never posts a password body, and a deployment
  //    without the password method hides the entry.
  api.applyAuthState({ ...guest, methods: { password: true, google: false } });
  api.openAuthDialog();
  results.requests.login = {
    fetchCalls: live.fetchCalls.length,
    emailContinueHidden: live.passwordLoginContinue.hidden,
    googleHidden: live.googleLoginButton.hidden,
    dividerHidden: live.authDivider.hidden,
  };
  api.applyAuthState({ ...guest, methods: { password: false, google: true } });
  results.requests.login.googleOnlyEmailContinueHidden = live.passwordLoginContinue.hidden;
  results.requests.login.googleOnlyGoogleHidden = live.googleLoginButton.hidden;
  api.applyAuthState({ ...guest, methods: { password: true, google: true } });
  results.requests.login.bothEmailContinueHidden = live.passwordLoginContinue.hidden;
  results.requests.login.bothDividerHidden = live.authDivider.hidden;
  api.closeAuthDialog();

  // 6. Sign-out posts the reviewed endpoint and drops the surfaces through the
  //    same status refresh; a guest answer then shows the login entry again.
  live.fetchCalls = [];
  const outBefore = live.loadAuthCount;
  await api.signOutCurrentAccount();
  results.requests.logout = {
    url: live.fetchCalls[0][0], method: live.fetchCalls[0][1].method,
    resetView: live.resetView,
    projectsCleared: live.clearedProjects || 0,
    statusRefreshed: live.loadAuthCount - outBefore,
  };
  api.applyAuthState({ ...guest });
  results.requests.logoutSurfaces = surfaces();

  // 7. Replay policy: only the reset confirm replays an answerless failure.
  const answerless = async () => ({ ok: false, status: 500,
    json: async () => { throw new Error("no json envelope"); } });
  api.applyAuthState({ ...guest });
  live.passwordResetToken = "synthetic-token";
  live.passwordResetNew.value = "synthetic-new";
  live.passwordResetConfirm.value = "synthetic-new";
  live.fetchCalls = [];
  live.fetchImpl = answerless;
  await api.submitPasswordResetConfirm({ preventDefault() {} });
  results.replay.resetConfirmAttempts = live.fetchCalls.length;
  results.replay.resetConfirmUrl = live.fetchCalls[0][0];
  results.replay.resetConfirmError = live.passwordResetConfirmError.textContent;
  live.passwordResetEmail.value = "synthetic-register@test.dev";
  live.fetchCalls = [];
  live.fetchImpl = answerless;
  await api.submitPasswordResetRequest({ preventDefault() {} });
  results.replay.resetRequestAttempts = live.fetchCalls.length;
  live.passwordChangeCurrent.value = "synthetic-pass";
  live.passwordChangeNew.value = "synthetic-next";
  live.passwordChangeConfirm.value = "synthetic-next";
  live.fetchCalls = [];
  live.fetchImpl = answerless;
  await api.submitPasswordChange({ preventDefault() {} });
  results.replay.changeAttempts = live.fetchCalls.length;
  live.fetchCalls = [];
  live.fetchImpl = async () => ({ ok: true, status: 200,
    json: async () => { throw new Error("no json envelope"); } });
  await api.submitPasswordResetRequest({ preventDefault() {} });
  results.replay.twoHundredWithoutAnswer = {
    attempts: live.fetchCalls.length, error: live.passwordResetRequestError.textContent,
  };

  // 8. Getter contract: the dialog replaced before the first call is the one shown.
  const lateDialog = makeElement("lateDialog");
  live.authDialog = lateDialog;
  api.openAuthDialog("login");
  results.getter = { shown: lateDialog.shown };

  // 9. Setter contract: the generation bump writes back through deps.
  const before = live.clawApprovalEpoch;
  api.invalidateClawApprovalSession();
  results.setter = { bumped: live.clawApprovalEpoch === before + 1,
    token: live.clawApprovalSessionToken, inFlight: live.clawApprovalInFlight };

  // 10. noteClawApprovalSession stores a fresh token only when it changes.
  api.noteClawApprovalSession(true);
  const firstToken = live.clawApprovalSessionToken;
  api.noteClawApprovalSession(true);
  results.noteToken = { first: firstToken !== "",
    stable: live.clawApprovalSessionToken === firstToken };

  // 11. reviewedGoogleAuthorizationUrl enforces the reviewed origin rules.
  results.policy = [
    api.reviewedGoogleAuthorizationUrl("https://accounts.google.com/o/oauth2/v2/auth?x=1"),
    api.reviewedGoogleAuthorizationUrl("http://accounts.google.com/o/oauth2/v2/auth"),
    api.reviewedGoogleAuthorizationUrl("https://evil.example/o/oauth2/v2/auth"),
    api.reviewedGoogleAuthorizationUrl("https://accounts.google.com/o/oauth2/v2/auth#f"),
  ];

  // 12. applyAuthState publishes (state, epoch) to the shared session, and the
  //     epoch grows by exactly one per call.
  const published = live.sessionUpdates.slice(-3).map((row) => ({
    authenticated: row.state && row.state.authenticated === true,
    ready: row.state && row.state.ready === true,
    epoch: row.epoch,
  }));
  results.publication = { tail: published,
    monotonic: published.every((row, i) => i === 0 || row.epoch === published[i - 1].epoch + 1) };

  // 13. #8699: the first session check must not project a sign-out screen.
  //     A not-ready answer or a failed attempt is retried once while the
  //     pending (neutral) presentation stays on screen.
  async function statusFlight(answers) {
    // The module reads status through its local fetchAuthStatusOnce, which
    // uses the global fetch; the harness routes that through live.fetchImpl.
    const original = live.fetchImpl;
    let index = 0;
    const snapshots = [];
    live.accountContainer.dataset.accountState = "pending";
    live.loginButton.hidden = true;
    live.loginButton.disabled = true;
    live.accountName.hidden = true;
    live.fetchImpl = async () => {
      const answer = answers[index++];
      snapshots.push({ attempt: index, before: surfaces() });
      if (answer instanceof Error) throw answer;
      return { ok: true, status: 200, json: async () => answer };
    };
    try {
      await api.loadAuthStatus();
    } finally {
      live.fetchImpl = original;
    }
    snapshots.push({ attempt: index, after: surfaces() });
    return { calls: index, snapshots, final: surfaces() };
  }
  // 골든 스냅샷(observations())의 키 집합은 그대로 둔다. 이 관찰은 별도 모드로만
  // 출력해 #8699 회귀 시험이 쓴다.
  if (process.argv[5] === "status-flight") {
    const signedInAnswer = { ready: true, authenticated: true,
      user: { name: "Kim", email: "member@example.com" },
      session_state: "signed_in", history_ready: true, account_method: "password",
      methods: { password: true, google: false } };
    const notReadyAnswer = { ready: false, authenticated: false, user: null,
      methods: { password: true, google: false } };
    process.stdout.write(JSON.stringify({
      lateFirst: await statusFlight([notReadyAnswer, signedInAnswer]),
      failedFirst: await statusFlight([new Error("auth status unavailable"), signedInAnswer]),
      twiceNotReady: await statusFlight([notReadyAnswer, notReadyAnswer]),
    }));
  } else {
    process.stdout.write(JSON.stringify(results));
  }
})().catch((error) => { console.error(error); process.exit(1); });
"""


def _run_harness(mode: str = "") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the module harness")
    table = json.dumps(presentation_table(), ensure_ascii=False)
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        harness.write_text(
            STRICT + "\nconst SHIPPED_PRESENTATION = " + table + ";\n" + _HARNESS,
            encoding="utf-8", newline="\n",
        )
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-auth-module.js"), str(STATIC / "chat-account-module.js"),
             str(STATIC / "chat-login-dialog-module.js")] + ([mode] if mode else []),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def observations() -> dict:
    """모듈을 실제 실행해 얻은 한 번의 관찰(시험 파일 간 공유)."""

    return _run_harness()


@lru_cache(maxsize=1)
def status_observations() -> dict:
    """#8699: 상태 확인 시퀀스 관찰만 별도로 실행한다(골든 키 집합 유지)."""

    return _run_harness("status-flight")
