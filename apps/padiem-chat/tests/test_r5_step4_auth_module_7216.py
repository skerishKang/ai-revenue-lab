"""#7216 R5 step 4 — 로그인 세션 모듈 계약(#7186 R2).

app.js의 로그인 세션 41개 함수가 chat-auth-module.js로 이동했고, app.js는 같은
이름의 한 줄 전달 함수를 유지한다. R2(#7186) 4단계: 이 구역의 동작 계약을
소스 문자열이 아니라 `_r5_auth_module_harness.py`의 실제 모듈 실행으로 고정한다 —
선박 표를 주입한 인증 상태별 표면(보임/숨김·문구·aria), 로그인·로그아웃 요청의
method·경로·본문, 재시도 정책, 세션 발행.

문자열로 남기는 것은 구조·경계 계약뿐이다(이유를 각 시험에 적는다): app.js의
한 줄 전달 함수, 이동 본문의 이중 소유 금지, 팩토리 하나, index 로드 순서는
HTMLParser로 판정.
"""
from __future__ import annotations

from html.parser import HTMLParser

import pytest

from _r5_auth_module_harness import (
    APP,
    INDEX,
    MODULE,
    observations,
    presentation_table,
)

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
    assert order.count("./chat-auth-module.js") == 1
    assert order.index("./chat-auth-module.js") < order.index("./app.js")


def test_app_keeps_one_line_forwarders_for_every_moved_function() -> None:
    """구조 계약: app.js는 같은 이름의 전달 함수만 남긴다(R5).

    모듈 함수의 동작은 하네스가 직접 호출해 증명한다. 이 시험은 app.js 호출부
    호환(이름·인자 전달)이라는 구조 계약이라 문자열로 유지한다.
    """
    for name in NAMES:
        line = f"function {name}(...a) {{ return authModule().{name}(...a); }}"
        assert line in APP, name
        assert APP.count(f"function {name}(") == 1, name
    assert "function authModule() {" in APP
    assert "window.PadiemChatAuthModule.create({" in APP


def test_moved_bodies_live_only_in_the_module() -> None:
    """구조 계약: 이동한 본문이 app.js에 다시 생기지 않는다(이중 소유 금지).

    긍정 동작은 하네스가 실제 실행으로 증명한다. 여기서는 부정 계약만 남긴다.
    """
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker


def test_module_exposes_one_factory_and_touches_no_dom_at_load() -> None:
    """구조 경계: 전역 팩토리 하나, 로드 시 DOM 조회 없음(R5 모듈 경계).

    본문은 원래의 document 조회를 그대로 유지한다(동작 0 change). 경계는
    create() 시점에 DOM을 찾지 않는다는 것이다 — 전역/팩토리 단일성과 함께
    구조 계약이라 문자열로 유지한다.
    """
    assert "window.PadiemChatAuthModule = {" in MODULE
    assert "create(deps) {" in MODULE
    assert "document.getElementById" in MODULE
    for name in NAMES:
        assert f"function {name}(" in MODULE, name


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


def test_the_login_and_logout_requests_use_the_reviewed_method_and_path(observed: dict) -> None:
    login = observed["requests"]["login"]
    assert login["url"] == "/api/auth/password/login"
    assert login["method"] == "POST"
    assert login["body"] == '{"identifier":"synthetic-id","password":"synthetic-pass"}'
    assert login["passwordCleared"] is True
    assert login["dialogClosed"] >= 1
    assert login["statusRefreshed"] == 1
    assert login["submitReenabled"] is True
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
    assert replay["loginAttempts"] == 1
    assert replay["loginError"] == "auth-server-unreachable"
    # A 2xx without a route answer is not success and is never replayed.
    assert replay["twoHundredWithoutAnswer"] == {
        "attempts": 1, "error": "auth-server-unreachable",
    }


def test_the_dialog_opens_the_enabled_methods_only(observed: dict) -> None:
    assert observed["openDialog"] == {
        "shown": 1, "view": "login", "focused": 1,
        "googleHidden": True, "dividerHidden": True,
        "loginFormHidden": False, "resetPanelHidden": True,
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


@pytest.fixture(scope="module")
def observed() -> dict:
    return observations()
