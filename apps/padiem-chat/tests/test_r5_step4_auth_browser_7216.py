"""#7216 R5 step 4 — 실제 Chromium에서 app.js 로그인 세션 전달 함수 호출 계약.

app.js에서 추출한 41개 한 줄 전달 함수를 실제 Chromium 페이지에 주입하고, 실제
모듈 소스와 deps를 연결해 각 전달 함수를 직접 호출한다. 전달 함수마다 1개 이상의
호출 검사와 라이브 deps getter 검사를 둔다. 문자열 검사가 아니라 실행 검사다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STRICT = (Path(__file__).resolve().parent / "_r5_strict_deps.js").read_text(encoding="utf-8")

# name -> (js args expression, expected argument count)
CALLS = {
    "closeProfilePanel": ("[true]", 1),
    "accountInitial": (r'["Kim"]', 1),
    "resolveSessionPresentation": (r'["guest"]', 1),
    "setLoginButtonCopy": (r'["in", "in-title"]', 2),
    "applyAuthState": ("[{ready: true, authenticated: false, user: null}]", 1),
    "authMethodEnabled": (r'["password"]', 1),
    "setAuthFormError": ("[null]", 1),
    "syncAuthDialogMethods": ("[]", 0),
    "openAuthDialog": ("[]", 0),
    "closeAuthDialog": ("[]", 0),
    "authServerUnreachableError": ("[]", 0),
    "passwordAuthAnswer": ("[{}]", 1),
    "passwordAuthRequest": (r'["/api/auth/password/login", {}]', 2),
    "submitPasswordLogin": ("[{preventDefault() {}}]", 1),
    "submitPasswordRegister": ("[{preventDefault() {}}]", 1),
    "setAuthStatusMessage": ('[null, "m"]', 2),
    "passwordResetTokenFromLocation": ("[]", 0),
    "clearPasswordResetFragment": ("[]", 0),
    "showPasswordResetView": (r'["confirm"]', 1),
    "hidePasswordResetViews": ("[]", 0),
    "openPasswordResetRequest": ("[]", 0),
    "openPasswordResetConfirm": ("[]", 0),
    "closePasswordResetViews": ("[]", 0),
    "submitPasswordResetRequest": ("[{preventDefault() {}}]", 1),
    "submitPasswordResetConfirm": ("[{preventDefault() {}}]", 1),
    "openPasswordChangeDialog": ("[]", 0),
    "closePasswordChangeDialog": ("[]", 0),
    "submitPasswordChange": ("[{preventDefault() {}}]", 1),
    "resetAccountDeleteConfirm": ("[]", 0),
    "resetAccountSharedDeleteConfirm": ("[]", 0),
    "openAccountDeleteConfirm": ("[]", 0),
    "openAccountSharedDeleteConfirm": ("[]", 0),
    "syncAccountDeleteButton": ("[]", 0),
    "syncAccountSharedDeleteButton": ("[]", 0),
    "submitAccountDelete": ("[{preventDefault() {}}]", 1),
    "loadAuthStatus": ("[]", 0),
    "requireSessionForModelUse": ("[]", 0),
    "signOutCurrentAccount": ("[]", 0),
    "invalidateClawApprovalSession": ("[]", 0),
    "noteClawApprovalSession": ("[true]", 1),
    "reviewedGoogleAuthorizationUrl": (
        r'["https://accounts.google.com/o/oauth2/v2/auth"]', 1),
}

HARNESS = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>R5 auth forwarders</title></head>
<body>
<dialog id="authDialog"><form id="passwordLoginForm"><input id="passwordLoginIdentifier" />
<input id="passwordLoginPassword" /><button id="passwordLoginSubmit"></button>
<div id="passwordLoginError"></div></form></dialog>
<div class="app-shell" id="shell"></div>
<script src="/static/chat-auth-module.js"></script>
<script>
__STRICT__
const el = (id) => {
  const node = document.getElementById(id) || document.createElement("div");
  if (id && !node.id) node.id = id;
  node.value = node.value || "";
  return node;
};
window.PadiemAuthSession = { update() {}, get: () => null };
window.PadiemSharedTooltip = null;
// The moved transport calls the page-global fetch; answer like the routes do.
window.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
window.__calls = [];
const state = {
  authState: { ready: true, authenticated: false, user: null, history_ready: true,
               model_requires_session: true, account_method: "password",
               session_state: "guest", methods: { password: true, google: false } },
  authViewEpoch: 0, authDialogView: null, passwordResetToken: "",
  clawApprovalEpoch: 0, clawApprovalInFlight: false, clawApprovalSessionToken: "",
  pendingNotificationConversationId: "", pendingNotificationRunId: "",
  AUTH_SERVER_UNREACHABLE: "auth_server_unreachable",
  AUTH_UNREACHABLE_RETRY_DELAY_MS: 600,
  SESSION_PRESENTATION: {
    unreachable: { loginHidden: false, loginDisabled: true, accountHidden: true, accountNameHidden: true },
    unavailable: { loginHidden: false, loginDisabled: false, accountHidden: true, accountNameHidden: true },
    guest: { loginHidden: false, loginDisabled: false, accountHidden: true, accountNameHidden: true },
    signed_in: { loginHidden: true, loginDisabled: false, accountHidden: false, accountNameHidden: false },
    expired: { loginHidden: false, loginDisabled: false, accountHidden: false, accountNameHidden: false },
  },
  shell: document.getElementById("shell"),
  projects: [],
  syncDeleteButton: () => {},
  uiT: (key) => key,
  setNote: () => {}, setNavActive: () => {}, closeSettings: () => {},
  clearProjectsUI: () => {}, loadProjects: () => {}, loadRecentConversations: () => {},
  scheduleSharedRefresh: () => {}, syncApprovedMemoryVisibility: () => {},
  syncClawRunHistoryVisibility: () => {}, resetConversation: () => {},
  resetConversationView: () => {}, openSavedConversation: () => {}, openClawRunTarget: () => {},
  renderAndroidHandoff: () => {}, startAndroidHandoff: () => {}, isAndroidWebView: () => false,
  loveTreeHandoffFromLocation: () => null,
  fetchAuthStatusOnce: async () => ({ ready: true, authenticated: false, user: null }),
  fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
};
for (const id of ["historySection", "historyList", "historyEmpty", "historyActionStatus",
  "accountAvatar", "accountName", "accountContainer",
  "accountSettingsSection", "accountPasswordActions", "accountDeleteActions",
  "accountDeleteButton", "accountDeleteConfirm", "accountDeleteConfirmEmail",
  "accountDeleteError", "accountSharedDeleteButton", "accountSharedDeleteConfirm",
  "accountSharedDeleteConfirmEmail", "accountSharedDeleteError", "advancedAccountSection",
  "advancedSettingsView", "authDivider", "authHandoff", "googleLoginButton", "loginButton",
  "passwordLoginIdentifier", "passwordLoginPassword", "passwordLoginError",
  "passwordLoginSubmit", "passwordRegisterSection", "passwordRegisterForm",
  "passwordRegisterName", "passwordRegisterEmail", "passwordRegisterPassword",
  "passwordRegisterError", "passwordRegisterSubmit", "passwordResetOpen",
  "passwordResetPanel", "passwordResetRequestView", "passwordResetRequestForm",
  "passwordResetRequestError", "passwordResetRequestStatus", "passwordResetRequestSubmit",
  "passwordResetEmail", "passwordResetNew", "passwordResetConfirmView",
  "passwordResetConfirmForm", "passwordResetConfirmError", "passwordResetConfirmStatus",
  "passwordResetConfirmSubmit", "passwordResetConfirm", "passwordResetConfirmBack",
  "passwordChangeDialog", "passwordChangeForm", "passwordChangeCurrent",
  "passwordChangeNew", "passwordChangeConfirm", "passwordChangeSubmit",
  "passwordChangeError", "passwordChangeDialogClose", "profilePanel", "profileToggle",
  "projectsBadge", "passwordLoginForm"]) {
  state[id] = el(id);
}
state.authDialog = el("authDialog");
window.__state = state;
window.__deps = {};
for (const key of Object.keys(state)) {
  Object.defineProperty(window.__deps, key, {
    get() { return window.__state[key]; },
    set(value) { window.__state[key] = value; },
  });
}
window.__instance = null;
function authModule() {
  if (!window.__instance) window.__instance = window.PadiemChatAuthModule.create(window.__deps);
  return window.__instance;
}
// The moved functions call each other through deps (the app.js factory serves
// the forwarders there); serve the module's own exports the same way.
for (const key of ["applyAuthState", "authMethodEnabled", "authServerUnreachableError",
  "clearPasswordResetFragment", "closeAuthDialog", "closePasswordChangeDialog",
  "closeProfilePanel", "hidePasswordResetViews", "invalidateClawApprovalSession",
  "loadAuthStatus", "openAuthDialog", "passwordAuthAnswer", "passwordAuthRequest",
  "passwordResetTokenFromLocation", "resetAccountDeleteConfirm",
  "resetAccountSharedDeleteConfirm", "resolveSessionPresentation", "setAuthFormError",
  "setAuthStatusMessage", "setLoginButtonCopy", "showPasswordResetView",
  "syncAuthDialogMethods"]) {
  Object.defineProperty(window.__deps, key, { get() { return window.__instance[key]; } });
}
// Spy: every direct forwarder call must reach the same-named module function
// with the same arguments.
const __real = authModule();
for (const key of Object.keys(__real)) {
  const real = __real[key];
  __real[key] = (...args) => {
    window.__calls.push({ name: key, argc: args.length });
    return real(...args);
  };
}
__FORWARDERS__
window.__call = async (name, args) => {
  window.__calls = [];
  const out = await globalThis[name](...args);
  // The first spy entry is the direct forwarder call; later entries are the
  // module's own calls back through the deps wiring.
  return { last: window.__calls[0] || null, out: String(out) };
};
</script>
</body></html>
"""


def _forwarder_lines() -> str:
    lines = []
    for name in CALLS:
        marker = f"function {name}(...a) {{"
        line = next(line.strip() for line in APP.splitlines() if marker in line)
        lines.append(line)
    return "\n".join(lines)


class _StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC.parent), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def page_url():
    harness = STATIC / "_r5_auth_forwarder_harness.html"
    harness.write_text(HARNESS.replace("__STRICT__", STRICT).replace("__FORWARDERS__", _forwarder_lines()),
                       encoding="utf-8", newline="\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/_r5_auth_forwarder_harness.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        harness.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def browser_page(page_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(page_url)
        yield page
        browser.close()


@pytest.mark.parametrize("name", sorted(CALLS))
def test_forwarder_calls_the_module_function_directly(browser_page, name) -> None:
    args, argc = CALLS[name]
    out = browser_page.evaluate(f"window.__call({json.dumps(name)}, {args})")
    assert out["last"] == {"name": name, "argc": argc}, (name, out)


def test_forwarders_open_and_close_the_real_dialog(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      await window.__call("openAuthDialog", []);
      const dialog = document.getElementById("authDialog");
      const opened = dialog.open === true;
      await window.__call("closeAuthDialog", []);
      return { opened, closed: dialog.open === false };
    }""")
    assert out == {"opened": True, "closed": True}


def test_forwarder_projects_the_session_onto_the_real_dom(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      await window.__call("applyAuthState", [{ ready: true, authenticated: true,
        user: { name: "Kim" }, history_ready: true, account_method: "password" }]);
      const login = window.__state.loginButton;
      return { hidden: login.hidden, avatar: window.__state.accountAvatar.textContent };
    }""")
    assert out == {"hidden": True, "avatar": "K"}


def test_deps_getter_reads_the_dialog_that_changed_before_the_first_call(browser_page) -> None:
    out = browser_page.evaluate("""async () => {
      const late = document.createElement("dialog");
      late.id = "lateAuthDialog";
      document.body.appendChild(late);
      window.__state.authDialog = late;   // live getter, before the first call
      await window.__call("openAuthDialog", []);
      return { open: late.open === true };
    }""")
    assert out == {"open": True}