"""#5895 ④: one ordinary chat through the operational path after a deploy.

Both production gates already proved the promoted version is served and that
``/health`` answers. What they never proved is that a chat actually completes,
which is the check a person used to do by hand right after the deploy. This is
that check: one free-grade chat turn on the route the product itself serves.

    --lane chat    POST /api/chat - the composer route the product serves.
                   Owner decision 2026-11-05 made the AI answers signed-in
                   only ("free without a login" is gone), so this lane now
                   signs in as the production QA account first, exactly like
                   the engine lane
    --lane engine  POST /api/orchestration behind the existing production QA
                   session - the lane the browser composer tries first (#4469)
                   and the one that is answered by the Engine

No model is named, read or checked. The transport, its bounds and the
error-code sanitising come from the existing long-context canary, so this step
adds no new second, byte or count limit and no new credential. The answer text
is never printed: a verdict line and a bounded error code only.

Verdict contract (#5895 ④, CTO 2026-10-27):
  200, a non-empty answer and no error -> REAL_CHAT=PASS
  provider-side 429 or 503             -> REAL_CHAT=PASS_PROVIDER_LIMIT (a pass)
  anything else                        -> REAL_CHAT=FAIL and exit 1
A FAIL reddens the gate. No rollback is wired to this step in either gate, so a
failed proof is seen instead of silently undone.
"""

from __future__ import annotations

import argparse
import os
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b62_live_long_context_canary import (  # noqa: E402  (sibling script import)
    CHAT,
    CHAT_TIMEOUT_SECONDS,
    CONVERSATION,
    LOGIN,
    STATUS,
    CanaryError,
    bounded_call,
    error_code,
)
from b62_live_long_context_canary import _ID as CONVERSATION_ID  # noqa: E402
from shared_login_client import (  # noqa: E402  (sibling script import)
    SESSION_COOKIE,
    SharedLoginError,
    login_session_cookie,
)

ORCHESTRATION = "/api/orchestration"
# 2026-11-11 CTO decision: the QA accounts are split by purpose so no single
# Free account burns its daily 100 on every check. This smoke is the deploy
# smoke and signs in with the dedicated QA_SMOKE_* pair; the daily usage check
# keeps the original account and the deploy AI check overrides these names to
# QA_DEPLOY_* (see post_deploy_ai_answer_check.py).
QA_USERNAME_ENV = "QA_SMOKE_USERNAME"
QA_PASSWORD_ENV = "QA_SMOKE_PASSWORD"
PROMPT = "정상 작동 확인입니다. 한 문장으로 답해 주세요."
PROVIDER_LIMIT_STATUSES = frozenset({429, 503})
GRADE = "free"


def turn_payload() -> dict:
    """One free-grade ordinary turn: the same shape the composer posts."""
    return {"tier": GRADE, "messages": [{"role": "user", "content": PROMPT}]}


def decide(status: int, payload: Any) -> tuple[str, str]:
    """Return ``(verdict, safe code)``. Only a non-empty answer without an
    error field passes; a provider-side limit passes as marked."""
    code = error_code(payload) if isinstance(payload, dict) else "unexpected_http_json_shape"
    if status in PROVIDER_LIMIT_STATUSES:
        return "PASS_PROVIDER_LIMIT", code
    if status != 200:
        return "FAIL", code
    if not isinstance(payload, dict) or "error" in payload:
        return "FAIL", code
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return "FAIL", "empty_answer"
    return "PASS", "none"


def conversation_id(payload: Any) -> str | None:
    """The canonical id of the turn that was just saved, when the body names one."""
    value = payload.get("conversation_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and CONVERSATION_ID.fullmatch(value) else None


def _engine_call(opener, path: str, *, stage: str, **kwargs):
    """Report only the fixed stage when the bounded transport cannot parse a reply."""
    try:
        return bounded_call(opener, path, **kwargs)
    except CanaryError:
        print(f"REAL_CHAT_FAILURE_STAGE={stage}")
        raise


def _attach_session_cookie(opener, cookie: str) -> None:
    """Carry the shared-login cookie on the gate's existing opener."""
    opener.addheaders = [
        (name, value) for name, value in opener.addheaders
        if name.lower() != "cookie"
    ]
    opener.addheaders.append(("Cookie", f"{SESSION_COOKIE}={cookie}"))


def _sign_in_shared(opener, origin: str, username: str, password: str) -> None:
    """The common login form is the only email entrance since the migration."""
    try:
        cookie = login_session_cookie(origin, username, password)
    except SharedLoginError:
        raise CanaryError("qa_login_refused") from None
    if not cookie:
        raise CanaryError("qa_login_refused")
    _attach_session_cookie(opener, cookie)


def sign_in(opener, *, base_url=None) -> None:
    """Sign the QA account in; Owner decision 2026-11-05 made every AI answer
    lane signed-in only, so both lanes share this one entrance."""
    target = {"origin": base_url} if base_url else {}
    origin = base_url or "https://chat.padiem.net"
    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    if not username or not password:
        # A gate that cannot sign in has not proved the chat lane. That is a
        # failure to read, never a silent skip.
        raise CanaryError("qa_credential_missing")
    status, body = _engine_call(
        opener, LOGIN, stage="login", method="POST",
        payload={"identifier": username, "password": password}, **target,
    )
    if status != 200 or body.get("ok") is not True:
        # The direct email entrance answers 409 after the common-login move.
        # Fall back to that one form instead of calling a working account bad.
        server_code = error_code(body) if isinstance(body, dict) else "no_json_body"
        if status == 409 and server_code == "email_login_moved":
            _sign_in_shared(opener, origin, username, password)
            status, state = _engine_call(opener, STATUS, stage="session", **target)
            if status != 200 or state.get("authenticated") is not True:
                state_code = error_code(state) if isinstance(state, dict) else "no_json_body"
                print(f"QA_SESSION_DIAGNOSTIC status_http_status={status} server_error_code={state_code}")
                raise CanaryError("qa_session_unverified")
            return
        # Diagnosis without discretion: the same 401 is a wrong password, a
        # missing identifier and an active lock by design (#3501/#3508), and the
        # client cannot tell them apart. Print the HTTP status and the server's
        # error code NAME only — never the body, never a credential — and keep
        # the verdict exactly as before.
        print(f"QA_LOGIN_DIAGNOSTIC login_http_status={status} server_error_code={server_code}")
        raise CanaryError("qa_login_refused")
    status, state = _engine_call(opener, STATUS, stage="session", **target)
    if status != 200 or state.get("authenticated") is not True:
        state_code = error_code(state) if isinstance(state, dict) else "no_json_body"
        print(f"QA_SESSION_DIAGNOSTIC status_http_status={status} server_error_code={state_code}")
        raise CanaryError("qa_session_unverified")


def chat_lane(opener, *, base_url=None) -> tuple[int, Any]:
    sign_in(opener, base_url=base_url)
    target = {"origin": base_url} if base_url else {}
    return _engine_call(
        opener, CHAT, stage="chat", method="POST", timeout=CHAT_TIMEOUT_SECONDS,
        payload=turn_payload(), **target,
    )


def engine_lane(opener, *, base_url=None) -> tuple[int, Any]:
    sign_in(opener, base_url=base_url)
    target = {"origin": base_url} if base_url else {}
    return _engine_call(
        opener, ORCHESTRATION, stage="orchestration", method="POST", timeout=CHAT_TIMEOUT_SECONDS,
        payload=turn_payload(), **target,
    )


def run(lane: str) -> int:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    saved_id: str | None = None
    try:
        status, payload = chat_lane(opener) if lane == "chat" else engine_lane(opener)
        saved_id = conversation_id(payload)
        verdict, code = decide(status, payload)
    except CanaryError as exc:
        verdict, code = "FAIL", exc.public_code
    print(f"REAL_CHAT={verdict} lane={lane} code={code}")
    print("REAL_CHAT_MODEL_NAME_CHECKED=NO")
    print("REAL_CHAT_ANSWER_TEXT_LOGGED=0")
    # Both lanes sign in now (Owner decision 2026-11-05), so both can leave a
    # conversation behind; the QA turn is cleaned up either way.
    try:
        if saved_id is not None:
            bounded_call(opener, CONVERSATION + saved_id, method="DELETE")
            print("REAL_CHAT_QA_CONVERSATION_CLEANUP=PASS")
    except Exception:
        print("REAL_CHAT_QA_CONVERSATION_CLEANUP=NEEDS_REVIEW")
    if verdict == "FAIL":
        print("POST_DEPLOY_REAL_CHAT_FAILED=1", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True, choices=("chat", "engine"))
    return run(parser.parse_args(argv).lane)


if __name__ == "__main__":
    raise SystemExit(main())
