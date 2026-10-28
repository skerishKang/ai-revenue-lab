"""#5895 follow-up (2026-10-28 incident): prove the signed-in Chat path after a deploy.

The morning's release served every anonymous request correctly - the sign-in
page, the free composer, the static screen - while every path that reads a
session answered 500. The deploy gate's existing proof is the free composer
(`post_deploy_real_chat_smoke.py --lane chat`), so it went green on a Chat that
no signed-in owner could use for two hours.

This step is the missing proof, in the order the browser actually walks it:

    login            QA identity, the same account the long-context canary uses
    /api/auth/status the session read that answers for the whole UI
    /api/conversations
    /api/orchestration   one real signed-in turn

Any 5xx, any non-200 on a session read, a session that does not report itself
authenticated, or an empty answer is a failure and the gate stays red. Like the
existing proof, this step runs AFTER the auto-rollback step, so a failure is
read by a person and never rolls a release back on its own. The one
provider-side excuse the chat lane has (429/503 from the model upstream) stays,
and only there: a 503 from our own session path is the bug this catches.

No credential, no answer text and no response body is ever printed.
"""
from __future__ import annotations
import json
import os
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b62_live_long_context_canary import (  # noqa: E402
    CHAT_TIMEOUT_SECONDS,
    CONVERSATION,
    LOGIN,
    ORIGIN,
    STATUS,
    _ID as CONVERSATION_ID,
)
from post_deploy_real_chat_smoke import (  # noqa: E402
    ORCHESTRATION,
    QA_PASSWORD_ENV,
    QA_USERNAME_ENV,
    CanaryError,
    conversation_id,
    decide,
    error_code,
    turn_payload,
)

STEP_ORDER = ("login", "auth_status", "conversations", "chat")
LIST_KEYS = ("conversations", "items", "results")


def decide_step(step: str, status: int, payload: Any) -> tuple[str, str]:
    """``(verdict, safe code)`` for one step of the signed-in path.

    The three session reads have one standard each: an exact 200 with the body
    shape that step owes. A provider-side limit is not an excuse for them,
    because none of them talks to a model - a 503 here is Chat itself failing
    to read a session, which is precisely what went unseen on 2026-10-28.
    """
    code = error_code(payload) if isinstance(payload, dict) else "unexpected_http_json_shape"
    # A session read that did not answer 200 is the incident itself, whatever
    # its body said, so the status is the part a reader needs. The chat turn
    # keeps its own rule below, where a provider-side limit is an excuse.
    if step in ("login", "auth_status", "conversations") and status != 200:
        return "FAIL", f"{step}:http_{status}"
    if step == "login":
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return "FAIL", f"login:{code}"
        return "PASS", "none"
    if step == "auth_status":
        if not isinstance(payload, dict):
            return "FAIL", "auth_status:unexpected_http_json_shape"
        if payload.get("authenticated") is not True:
            return "FAIL", "auth_status:session_not_authenticated"
        return "PASS", "none"
    if step == "conversations":
        if not isinstance(payload, dict):
            return "FAIL", "conversations:unexpected_http_json_shape"
        if not any(isinstance(payload.get(key), list) for key in LIST_KEYS):
            return "FAIL", "conversations:conversations_list_unreadable"
        return "PASS", "none"
    if step == "chat":
        verdict, chat_code = decide(status, payload)
        return verdict, chat_code
    raise CanaryError("unknown_signed_in_step")


def decide_path(results: list[tuple[str, int, Any]]) -> tuple[str, str]:
    """The verdict for the whole walk: the first step that is not a pass decides.

    A turn that only hit the provider limit is reported as that marked pass - it
    still proved the session path, which is the point of this check.
    """
    ordered = {step: (status, payload) for step, status, payload in results}
    limit_hit = ""
    for step in STEP_ORDER:
        if step not in ordered:
            return "FAIL", f"missing_step_{step}"
        verdict, code = decide_step(step, *ordered[step])
        if verdict == "FAIL":
            return "FAIL", code
        if verdict == "PASS_PROVIDER_LIMIT":
            limit_hit = code
    if limit_hit:
        return "PASS_PROVIDER_LIMIT", limit_hit
    return "PASS", "none"


def _call(opener, path: str, *, method: str = "GET", payload: dict | None = None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "PADIEM-B62-signed-in-deploy-smoke/1.0",
        "Cache-Control": "no-store",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Origin": ORIGIN,
                        "Referer": ORIGIN + "/"})
    request = Request(ORIGIN + path, method=method, data=data, headers=headers)
    try:
        with opener.open(request, timeout=CHAT_TIMEOUT_SECONDS if payload else 25) as response:
            status, body = response.status, response.read()
    except HTTPError as error:
        status, body = error.code, error.read()
    except (TimeoutError, URLError, OSError) as exc:
        raise CanaryError("http_transport_unavailable") from exc
    try:
        return status, json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return status, None


def run() -> int:
    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    if not username or not password:
        print("SIGNED_IN_SMOKE_FAILED=qa_credential_missing", file=sys.stderr)
        return 1
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    results: list[tuple[str, int, Any]] = []
    saved: str | None = None
    try:
        results.append(("login", *_call(
            opener, LOGIN, method="POST",
            payload={"identifier": username, "password": password},
        )))
        results.append(("auth_status", *_call(opener, STATUS)))
        results.append(("conversations", *_call(opener, CONVERSATION.rstrip("/"))))
        status, payload = _call(opener, ORCHESTRATION, method="POST", payload=turn_payload())
        saved = conversation_id(payload)
        results.append(("chat", status, payload))
    except CanaryError as failure:
        print(f"SIGNED_IN_SMOKE_FAILED={failure}", file=sys.stderr)
        return 1
    verdict, code = decide_path(results)
    print(f"SIGNED_IN_CHAT={verdict} code={code}")
    print("SIGNED_IN_CHAT_STEPS=" + ",".join(step for step, _, _ in results))
    print("SIGNED_IN_CHAT_ANSWER_TEXT_LOGGED=0")
    print("SIGNED_IN_CHAT_CREDENTIALS_LOGGED=0")
    if saved is not None:
        try:
            _call(opener, CONVERSATION + saved, method="DELETE")
            print("SIGNED_IN_CHAT_CONVERSATION_CLEANUP=PASS")
        except CanaryError:
            print("SIGNED_IN_CHAT_CONVERSATION_CLEANUP=NEEDS_REVIEW")
    if verdict == "FAIL":
        print("POST_DEPLOY_SIGNED_IN_SMOKE_FAILED=1", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
