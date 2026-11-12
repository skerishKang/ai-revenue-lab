"""What a sign-out answers when a server-side session could not be ended (#7554).

A sign-out ends two things: the cookies on this device and the server-side
session(s) behind them. The cookies always go — this device is signed out
either way. The server-side revocation is different: when it cannot be
confirmed, a copy of the cookie made earlier could keep working, so the
sign-out must not report success. It answers a retryable refusal instead and
journals one closed line.

When the local verifier is on, the canonical session id behind the cookie is
also put on the shared local deny list for as long as that cookie can live,
so the copy is refused on this host even though the authority still holds the
session as active.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.responses import JSONResponse

LOGOUT_REVOCATION_FAILED = "session_revocation_failed"
LOGOUT_REVOCATION_MESSAGE = (
    "이 기기에서는 로그아웃했지만 서버의 로그인 상태를 끝내지 못했습니다. "
    "다시 로그인한 뒤 로그아웃을 다시 시도해 주세요."
)

_SAFE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def revocation_outcome_failed(request: Any, code: str | None) -> bool:
    """Whether a canonical revocation answer means a live session was left behind.

    A deployment with no canonical authority bound has no canonical session to
    end (the request-time guard checks none either), so its
    ``session_revocation_unavailable`` is not a failure of this sign-out.
    """

    if code is None:
        return False
    state = getattr(getattr(request, "app", None), "state", None)
    if code == "session_revocation_unavailable" and getattr(
        state, "control_plane_identity_authority", None
    ) is None:
        return False
    return True


def journal_logout_revocation_failure(stage: str, code: str) -> None:
    """One closed journal line: fixed stage and code words, never an identifier."""

    safe_stage = stage if _SAFE.fullmatch(stage or "") else "other"
    safe_code = code if _SAFE.fullmatch(code or "") else "other"
    print(
        "logout_revocation_failed stage=%s code=%s" % (safe_stage, safe_code),
        flush=True,
    )


def logout_revocation_failed_response(*, headers: dict[str, str] | None = None) -> JSONResponse:
    """The refusal body. The caller clears the cookies on it."""

    return JSONResponse(
        {
            "error": {
                "code": LOGOUT_REVOCATION_FAILED,
                "message": LOGOUT_REVOCATION_MESSAGE,
                "retryable": True,
            }
        },
        status_code=503,
        headers=headers or {"cache-control": "no-store"},
    )


async def hold_unrevoked_session_locally(request: Any, session_id: str | None) -> None:
    """Deny the unrevoked canonical session locally for the cookie's whole life.

    The ordinary deny marker lasts DENYLIST_TTL_SECONDS, which is enough when
    the authority has revoked the session too. Here it has not, so the marker
    must outlive every cookie that could still name the session. Best effort:
    the sign-out already answers a failure, so a marker that cannot be written
    changes nothing it reports.
    """

    if not isinstance(session_id, str) or not session_id:
        return
    try:
        from .auth_validation_cache import record_auth_revocation

        settings = getattr(getattr(getattr(request, "app", None), "state", None), "settings", None)
        max_age = int(getattr(settings, "session_max_age_seconds", 0) or 0)
        await record_auth_revocation(
            request,
            session_ids=(session_id,),
            ttl_seconds=float(max(max_age, 1)),
        )
    except Exception as exc:
        journal_logout_revocation_failure("local_hold", type(exc).__name__.lower())
