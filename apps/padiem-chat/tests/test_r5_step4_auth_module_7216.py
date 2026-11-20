"""#7216 R5 step 4 — 로그인 세션 모듈 계약(#7186 R2).

app.js의 로그인 세션 41개 함수가 chat-auth-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. R2(#7186) 4단계: 이 구역의 동작 계약을
소스 문자열이 아니라 `_r5_auth_module_harness.py`의 실제 모듈 실행으로 고정한다 —
선박 표를 주입한 인증 상태별 표면(보임/숨김·문구·aria), 이메일 진입의
공통 로그인 이동(입력값 전송이 없음), 로그아웃 요청의 method·경로,
재시도 정책, 세션 발행.

문자열로 남기는 것은 구조·경계 계약뿐이다(이유를 각 시험에 적는다): app.js의
한 줄 전달 함수(B7 16차+17차부터 account 19개 전체는 등록부 경유),
이동 본문의 이중 소유 금지, 팩토리 하나, index 로드 순서는 HTMLParser로 판정.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

from _r5_b4_account_golden import EXPECTED as ACCOUNT_GOLDEN_EXPECTED, account_golden
from _r5_auth_module_harness import (
    ACCOUNT,
    APP,
    DIALOG,
    INDEX,
    MODULE,
    STATIC,
    observations,
    presentation_table,
)

NAMES = (
    "closeProfilePanel", "accountInitial", "resolveSessionPresentation",
    "setLoginButtonCopy", "applyAuthState", "authMethodEnabled", "setAuthFormError",
    "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog",
    "authServerUnreachableError", "passwordAuthAnswer", "passwordAuthRequest",
    "setAuthStatusMessage",
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

ACCOUNT_NAMES = (
    "passwordResetTokenFromLocation", "clearPasswordResetFragment",
    "showPasswordResetView", "hidePasswordResetViews", "openPasswordResetRequest",
    "openPasswordResetConfirm", "closePasswordResetViews", "submitPasswordResetRequest",
    "submitPasswordResetConfirm", "openPasswordChangeDialog", "closePasswordChangeDialog",
    "submitPasswordChange", "resetAccountDeleteConfirm", "resetAccountSharedDeleteConfirm",
    "openAccountDeleteConfirm", "openAccountSharedDeleteConfirm", "syncAccountDeleteButton",
    "syncAccountSharedDeleteButton", "submitAccountDelete",
)

# B7 16차+17차: all 19 account names are on the registry
# (app.provide("account")) — password reset/change 12 + account-deletion 7.
ACCOUNT_REGISTRY_NAMES = (
    "passwordResetTokenFromLocation", "clearPasswordResetFragment",
    "showPasswordResetView", "hidePasswordResetViews", "openPasswordResetRequest",
    "openPasswordResetConfirm", "closePasswordResetViews", "submitPasswordResetRequest",
    "submitPasswordResetConfirm", "openPasswordChangeDialog", "closePasswordChangeDialog",
    "submitPasswordChange", "resetAccountDeleteConfirm", "resetAccountSharedDeleteConfirm",
    "openAccountDeleteConfirm", "openAccountSharedDeleteConfirm", "syncAccountDeleteButton",
    "syncAccountSharedDeleteButton", "submitAccountDelete",
)

DIALOG_NAMES = (
    "setAuthFormError", "emailContinueElement", "syncAuthDialogMethods",
    "openAuthDialog", "closeAuthDialog", "authServerUnreachableError",
    "passwordAuthAnswer", "passwordAuthRequest", "setAuthStatusMessage",
)

AUTH_NAMES = (
    "closeProfilePanel", "accountInitial", "resolveSessionPresentation",
    "setLoginButtonCopy", "applyAuthState", "authMethodEnabled", "loadAuthStatus",
    "requireSessionForModelUse", "signOutCurrentAccount",
    "invalidateClawApprovalSession", "noteClawApprovalSession",
    "reviewedGoogleAuthorizationUrl",
)

MOVED_MARKERS = (
    "deps.authViewEpoch += 1;",
    'error.code = AUTH_SERVER_UNREACHABLE;',
    "deps.loginButton.hidden = presentation.loginHidden;",
    "deps.clawApprovalEpoch += 1;",
    'url.hostname !== "accounts.google.com"',
    "deps.passwordResetToken = token;",
    "await deps.loadAuthStatus();",
)


class _ScriptSrcParser(HTMLParser):
    """index.html의 script src 순서를 문자열 위치가 아니라 마크업에서 읽는다."""

    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        for name, value in attrs:
            if name == "src" and value:
                self.srcs.append(value)


def test_index_loads_the_auth_module_before_app() -> None:
    # R2(#7186): 소스 문자열 위치 대신 실제 script 로드 순서를 판정한다.
    parser = _ScriptSrcParser()
    parser.feed(INDEX)
    order = parser.srcs
    assert order.count("./chat-account-module.js") == 1
    assert order.count("./chat-auth-module.js") == 1
    assert order.count("./chat-login-dialog-module.js") == 1
    assert (order.index("./chat-account-module.js") < order.index("./chat-auth-module.js")
            < order.index("./chat-login-dialog-module.js") < order.index("./app.js"))


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    """구조 계약: 이동한 39개 이름은 app.js에 정의가 없고 각 모듈 조각에 있다(R5).

    모듈 함수의 동작은 하네스가 직접 호출해 증명한다. 이 시험은 app.js 호출부
    호환(이름·인자 전달)이라는 구조 계약이라 문자열로 유지한다.
    B7 16차+17차: account 19개 전체(비밀번호 재설정+변경 12·계정 삭제 7)가
    등록부(app.provide("account")) 경유로 대체됐다 — app.js에 같은 이름 정의가
    없고 등록된 조각에 이름이 있다.
    """
    assert 'app.provide("loginDialog", window.PadiemChatLoginDialogModule.create(' in APP
    assert 'app.provide("auth", window.PadiemChatAuthModule.create(' in APP
    assert 'app.provide("account", window.PadiemChatAccountModule.create(' in APP
    for name in NAMES:
        if name in DIALOG_NAMES:
            assert f"function {name}(" not in APP, name
            assert f"{name}," in DIALOG, name
            continue
        if name in AUTH_NAMES:
            assert f"function {name}(" not in APP, name
            assert f"{name}," in MODULE, name
            continue
        if name in ACCOUNT_REGISTRY_NAMES:
            assert f"function {name}(" not in APP, name
            assert f"{name}," in ACCOUNT, name
            continue
        raise AssertionError(f"unclassified moved name: {name}")
    assert "function authModule() {" in APP
    assert "const accountModule = () => {" in APP
    assert "const loginDialogModule = () => {" in APP
    assert "window.PadiemChatAuthModule.create(Object.setPrototypeOf({" in APP
    assert "window.PadiemChatAccountModule.create(Object.setPrototypeOf({" in APP
    assert "window.PadiemChatLoginDialogModule.create(Object.setPrototypeOf({" in APP


def test_auth_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("auth"))로 12개 이름을 조회한다."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, append() {}, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, append() {}, setAttribute() {} }),
  },
  location: { search: "", hash: "", pathname: "/", href: "https://example.test/" },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-auth-module.js", "utf8"), sandbox,
  { filename: "chat-auth-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("auth", window.PadiemChatAuthModule.create(app));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(AUTH_NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_login_dialog_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("loginDialog"))로 8개 이름을 조회한다."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, append() {}, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, append() {}, setAttribute() {} }),
  },
  location: { search: "", hash: "", pathname: "/", href: "https://example.test/" },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-login-dialog-module.js", "utf8"), sandbox,
  { filename: "chat-login-dialog-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  const deps = Object.assign(Object.create(app), { uiT: (key) => key });
  app.provide("loginDialog", window.PadiemChatLoginDialogModule.create(deps));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(DIALOG_NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_account_password_apis_are_reachable_through_the_registry() -> None:
    """B7 16차+17차 보강: 등록부(app.provide("account"))로 account 19개 이름을 조회한다.

    app.js 전달 함수가 없어도 소비자(loginDialog deps getter·auth deps getter·
    부팅 직접 호출)는 등록된 조각의 같은 이름 API에 도달한다. 실제 모듈 본문을
    node vm에서 문맥에 등록해 19개 이름이 전부 함수로 조회되는지 본다(동작
    단언은 골든 하네스와 브라우저 하네스가 직접 호출로 증명한다).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, append() {}, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, append() {}, setAttribute() {} }),
  },
  location: { search: "", hash: "", pathname: "/", href: "https://example.test/" },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-account-module.js", "utf8"), sandbox,
  { filename: "chat-account-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("account", window.PadiemChatAccountModule.create(Object.setPrototypeOf({}, app)));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(ACCOUNT_REGISTRY_NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_moved_bodies_live_only_in_the_module() -> None:
    """구조 계약: 이동한 본문이 app.js에 다시 생기지 않는다(이중 소유 금지).

    긍정 동작은 하네스가 실제 실행으로 증명한다. 여기서는 부정 계약만 남긴다.
    """
    for marker in MOVED_MARKERS:
        source = DIALOG if marker in (
            'error.code = AUTH_SERVER_UNREACHABLE;', "deps.passwordResetToken = token;",
        ) else MODULE
        assert marker in source, marker
        assert marker not in APP, marker


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    """구조 경계: 전역 팩토리 하나, 로드 시 DOM 조회 없음(R5 모듈 경계).

    본문은 원래의 document 조회를 그대로 유지한다(동작 0 change). 경계는
    create() 시점에 DOM을 찾지 않는다는 것이다 — 전역/팩토리 단일성과 함께
    구조 계약이라 문자열로 유지한다.
    """
    assert "window.PadiemChatAuthModule = {" in MODULE
    assert "window.PadiemChatAccountModule = {" in ACCOUNT
    assert "window.PadiemChatLoginDialogModule = {" in DIALOG
    assert "create(deps) {" in MODULE
    assert "create(deps) {" in ACCOUNT
    assert "document.getElementById" in MODULE
    assert "document.getElementById" in ACCOUNT
    assert "document.getElementById" in DIALOG
    for name in NAMES:
        module = ACCOUNT if name in ACCOUNT_NAMES else (DIALOG if name in DIALOG_NAMES else MODULE)
        assert f"function {name}(" in module, name


def test_session_state_values_project_the_shipped_presentation_table(observed: dict) -> None:
    """인증 상태 값을 넣었을 때 보이고 숨는 요소·문구·aria를 실제 실행으로 본다.

    표는 app.js의 선박 리터럴을 그대로 주입한다(복제 아님).
    """
    table = presentation_table()
    states = observed["states"]
    # The shipped table itself keeps the reviewed values.
    assert table["signed_in"] == {"accountHidden": False, "loginHidden": True,
                                  "loginDisabled": False, "accountNameHidden": False}
    assert table["unavailable"] == {"accountHidden": True, "loginHidden": True,
                                    "loginDisabled": True, "accountNameHidden": True}
    assert table["unreachable"] == {"accountHidden": False, "loginHidden": False,
                                    "loginDisabled": False, "accountNameHidden": True}
    assert table["pending"] == {"accountHidden": True, "loginHidden": True,
                                "loginDisabled": True, "accountNameHidden": True}
    assert table["guest"]["loginHidden"] is False
    assert table["expired"]["loginHidden"] is False

    signed_in = states["signed_in"]
    assert signed_in["loginHidden"] is True
    assert signed_in["loginDisabled"] is False
    assert signed_in["loginAriaDisabled"] == "false"
    assert signed_in["loginText"] == "logout"
    assert signed_in["loginTitle"] == "logout-title"
    assert signed_in["accountHidden"] is False
    assert signed_in["accountState"] == "signed_in"
    assert signed_in["accountName"] == "Kim"
    assert signed_in["accountNameHidden"] is False
    assert signed_in["avatar"] == "K"
    assert signed_in["historyHidden"] is False
    assert signed_in["settingsHidden"] is False
    assert signed_in["passwordActionsHidden"] is False
    assert signed_in["deleteActionsHidden"] is False

    guest = states["guest"]
    assert guest["loginHidden"] is False
    assert guest["loginDisabled"] is False
    assert guest["loginText"] == "login"
    assert guest["loginTitle"] == "login-title"
    assert guest["accountState"] == "guest"
    assert guest["accountName"] == "guest"
    assert guest["accountNameHidden"] is False
    assert guest["avatar"] == "●"

    expired = states["expired"]
    assert expired["loginHidden"] is False
    assert expired["loginText"] == "sign-in-again"
    assert expired["loginTitle"] == "expired-title"
    assert expired["accountName"] == "session-expired"
    assert expired["avatar"] == "!"

    unavailable = states["unavailable"]
    assert unavailable["loginHidden"] is True
    assert unavailable["loginDisabled"] is True
    assert unavailable["loginAriaDisabled"] == "true"
    assert unavailable["loginTitle"] == "login-unavailable-title"
    assert unavailable["accountHidden"] is True
    assert unavailable["accountNameHidden"] is True
    assert unavailable["accountName"] == ""

    unreachable = states["unreachable"]
    assert unreachable["loginHidden"] is False
    assert unreachable["loginDisabled"] is False
    assert unreachable["loginTitle"] == "login-unreachable-title"
    assert unreachable["accountHidden"] is False
    assert unreachable["accountNameHidden"] is True

    pending = states["pending"]
    assert pending["loginHidden"] is True
    assert pending["loginDisabled"] is True

    # applyAuthState(null) keeps the fallback shape and projects "unavailable".
    assert observed["fallback"] == {"authenticated": False, "ready": False}
    assert states["null_fallback"]["loginHidden"] is True


def test_the_logout_request_uses_the_reviewed_method_and_path(observed: dict) -> None:
    # The email entry in this dialog is a link to the common login, so opening
    # the dialog never posts a password body.
    login = observed["requests"]["login"]
    assert login["fetchCalls"] == 0
    assert login["emailContinueHidden"] is False
    assert login["googleHidden"] is True
    assert login["dividerHidden"] is True
    # A deployment without the password method hides the email entry; with
    # both methods the divider stands between Google and the email entry.
    assert login["googleOnlyEmailContinueHidden"] is True
    assert login["googleOnlyGoogleHidden"] is False
    assert login["bothEmailContinueHidden"] is False
    assert login["bothDividerHidden"] is False
    logout = observed["requests"]["logout"]
    assert logout["url"] == "/api/auth/logout"
    assert logout["method"] == "POST"
    assert logout["resetView"] is False
    assert logout["projectsCleared"] == 1
    assert logout["statusRefreshed"] == 1
    # The guest answer that follows the sign-out shows the login entry again.
    after = observed["requests"]["logoutSurfaces"]
    assert after["loginHidden"] is False
    assert after["loginText"] == "login"
    assert after["accountHidden"] is False
    assert after["accountState"] == "guest"


def test_the_guest_gate_uses_the_model_flag_and_the_visible_entry(observed: dict) -> None:
    assert observed["gateBlocked"] is False
    assert observed["gateNote"] == ["model-requires-login", "error"]
    assert observed["gateClicked"] == 1
    assert observed["gateAllowed"] is True
    assert observed["gateSignedIn"] is True
    # An unread state keeps the entry visible and the gate clicks it…
    assert observed["gateUnreadBlocked"] is False
    assert observed["gateUnreadClicked"] == 1
    # …while an "unavailable" answer hides it, so the gate opens the dialog.
    assert observed["gateUnavailableBlocked"] is False
    assert observed["gateUnavailableDialog"] == 1


def test_only_the_reset_confirm_replays_an_answerless_failure(observed: dict) -> None:
    replay = observed["replay"]
    assert replay["resetConfirmUrl"] == "/api/auth/password/reset/confirm"
    assert replay["resetConfirmAttempts"] == 2
    assert replay["resetConfirmError"] == "auth-server-unreachable"
    # A 2xx without a route answer is not success and is never replayed.
    assert replay["twoHundredWithoutAnswer"] == {
        "attempts": 1, "error": "auth-server-unreachable",
    }


def test_the_dialog_opens_the_enabled_methods_only(observed: dict) -> None:
    assert observed["openDialog"] == {
        "shown": 1, "view": "login", "focused": 1,
        "googleHidden": True, "dividerHidden": True,
        "emailContinueHidden": False, "resetPanelHidden": True,
    }
    assert observed["closeDialog"]["closed"] == 1


def test_apply_auth_state_publishes_the_session_with_a_monotonic_epoch(observed: dict) -> None:
    publication = observed["publication"]
    assert len(publication["tail"]) == 3
    assert publication["monotonic"] is True
    last = publication["tail"][-1]
    assert last["authenticated"] is False and last["ready"] is True


def test_the_closed_over_rules_are_unchanged(observed: dict) -> None:
    # The avatar letter rule, the answer predicate and the reviewed origin policy
    # keep their exact closed-over behavior.
    assert observed["initial"] == ["K", "", ""]
    assert observed["answer"] == [True, False, False, False]
    assert observed["unreachable"] == {"code": "auth_server_unreachable",
                                       "message": "auth-server-unreachable"}
    assert observed["policy"] == [
        "https://accounts.google.com/o/oauth2/v2/auth?x=1",
        None, None, None,
    ]


def test_getters_read_the_value_changed_before_the_first_call(observed: dict) -> None:
    # The dialog installed before the open call is the one that opens.
    assert observed["getter"] == {"shown": 1}


def test_setters_write_the_bookkeeping_back_into_the_closure(observed: dict) -> None:
    assert observed["setter"] == {"bumped": True, "token": "", "inFlight": False}


def test_the_approval_session_token_changes_only_with_the_session(observed: dict) -> None:
    assert observed["noteToken"] == {"first": True, "stable": True}


def test_b4_account_golden_paths_preserve_requests_and_screen_copy() -> None:
    assert account_golden() == ACCOUNT_GOLDEN_EXPECTED


@pytest.fixture(scope="module")
def observed() -> dict:
    return observations()
