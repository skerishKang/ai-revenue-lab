"""#3650 — the local/nonprod "Connect this computer" initiating leg.

Why this module exists
----------------------
#3084/#3094 built the consumer of a web handoff and #3095/#3140 built the
desktop redeem, but no product path mints the pairing challenge a first-time
connection needs: the canonical broker never carries a ``handoff_value`` for an
unpaired device, and the #3094 projection drops any handoff below ONLINE by
design. This module adds the missing initiating leg for the **local/nonprod
evidence run only**: one authenticated POST that performs exactly ONE call to
the canonical pairing-challenge mint and returns the deep link in the existing
``#3095`` schema.

Authority boundary
------------------
* Non-Production only. The route exists in the route table but refuses with a
  bounded 503 unless a connect port was explicitly composed into
  ``app.state.claw_local_connect``. The production Worker composition never
  composes one, so the deployed surface is a bounded refusal — no minting, no
  store, no pairing activation.
* The request body is never the authority. The account/workspace principal the
  challenge is minted for is fixed when the nonprod composition is built (the
  real authenticated TEST account the host was started for); the browser only
  supplies the optional conversation id used for envelope correlation. A session
  owner outside the composition's allowlist is refused outright.
* ONE mint per call. The port performs a single challenge POST and never
  retries: a transport failure or a canonical refusal is reported as a bounded
  code, and a second mint can only happen through a second explicit user
  action. Single-use redemption stays with the canonical authority.
* The handoff value is canonical mint output formatted into the existing
  ``padiem://pair?code=<32hex>&challenge=<id>`` schema. Nothing here mints,
  signs, parses or extends a pairing token: a response whose code is not 32 hex
  or whose challenge id is not a bounded safe reference is dropped whole.
* Same-origin protection is the central #3476 middleware: this is a
  cookie-authenticated browser POST, so it is guarded like every other
  mutation. No exemption is added here.

Contract markers
----------------
``NONPROD_EVIDENCE_HOST_ONLY = True``
``PRODUCTION_PAIRING_STORE_ADDED = False``
``DURABLE_PAIRING_STORE_CONFIGURED = False``
``REQUEST_BODY_IS_AUTHORITY = False``
``PAIRING_MINTING_AUTHORITY = "canonical_broker_challenge_mint_via_nonprod_host"``
``DEEP_LINK_SCHEMA = "existing #3095/#3140 padiem://pair"``
``SCOPE_MISMATCH_BYPASS = False``
``HANDOFF_VALUE_MINTED_OR_PARSED = False``
``MUTATION = True`` (one canonical challenge mint; no pairing store, no
device session, no approval, no execution)
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id

__all__ = [
    "CLAW_LOCAL_CONNECT_PATH",
    "CLAW_LOCAL_CONNECT_PROJECTION_VERSION",
    "ClawLocalPairingConnectPort",
    "UnconfiguredClawLocalPairingConnectPort",
    "claw_local_connect",
    "claw_local_connect_status",
]

CLAW_LOCAL_CONNECT_PATH = "/api/claw/local-access/connect"

CLAW_LOCAL_CONNECT_PROJECTION_VERSION = "claw-local-connect/1"

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_MAX_CONVERSATION_ID_LENGTH = 128
_CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")

# The exact #3095 deep-link schema the desktop shell already parses
# (apps/padiem-desktop-shell/src/contract/pairing-deeplink.ts): a 32-hex code
# and a bounded safe challenge reference. A mint response outside this shape is
# not a handoff and is dropped, never repaired.
_PAIRING_CODE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CHALLENGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_MAX_HANDOFF_VALUE_LENGTH = 512

# Bounded reason vocabulary. Exception text and upstream response bodies never
# reach the browser.
_CODE_UNCONFIGURED = "local_connect_unconfigured"
_CODE_NO_OWNER = "owner_session_required"
_CODE_INVALID_BODY = "invalid_conversation_id"
_CODE_OWNER_UNAUTHORIZED = "local_connect_owner_unauthorized"
_CODE_REFUSED = "local_connect_refused"
_CODE_INVALID_MINT = "local_connect_invalid_mint"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _validate_conversation_id(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > _MAX_CONVERSATION_ID_LENGTH:
        return None
    if not _CONVERSATION_ID_PATTERN.match(candidate):
        return None
    return candidate


class ClawLocalPairingConnectPort(Protocol):
    """The one typed seam between this route and a canonical challenge mint.

    An implementation performs exactly one canonical pairing-challenge call for
    the principal it was composed with and returns the closed canonical mint
    fields (``pairing_code`` plus the ``challenge`` envelope) — or ``None`` when
    the mint refused. The route never reaches a broker, network or store
    itself.
    """

    def issue_pairing_challenge(
        self,
        *,
        owner_id: str,
        conversation_id: str | None,
        now: datetime,
    ) -> Mapping[str, Any] | None:  # pragma: no cover - protocol declaration
        ...


class UnconfiguredClawLocalPairingConnectPort:
    """Fail-closed default: no nonprod composition, no initiating leg.

    The production composition installs nothing, so the deployed route answers
    with the bounded unconfigured refusal — the honest "this surface does not
    exist in production" rather than a hidden minting path.
    """

    configured = False

    def issue_pairing_challenge(
        self,
        *,
        owner_id: str,
        conversation_id: str | None,
        now: datetime,
    ) -> Mapping[str, Any] | None:
        del owner_id, conversation_id, now
        return None


def _deep_link(mint: Mapping[str, Any]) -> str | None:
    """Format canonical mint output into the existing #3095 deep-link schema.

    Formatting only: any field outside the exact schema the desktop parser
    accepts means this mint cannot be carried, and ``None`` is returned rather
    than a repaired value. The challenge id is percent-encoded the way the
    desktop parser's ``URLSearchParams`` decodes it, so a reference containing
    ``+`` or ``:`` survives the trip byte-for-byte.
    """

    pairing_code = mint.get("pairing_code")
    challenge = mint.get("challenge")
    challenge_id = challenge.get("challenge_id") if isinstance(challenge, Mapping) else None
    if not isinstance(pairing_code, str) or not _PAIRING_CODE_PATTERN.fullmatch(pairing_code):
        return None
    if not isinstance(challenge_id, str) or not _CHALLENGE_ID_PATTERN.fullmatch(challenge_id):
        return None
    value = (
        "padiem://pair?"
        f"code={pairing_code}&challenge={urllib.parse.quote(challenge_id, safe='')}"
    )
    if len(value) > _MAX_HANDOFF_VALUE_LENGTH:
        return None
    return value


async def claw_local_connect_status(request: Request) -> JSONResponse:
    """Read-only availability probe for the nonprod initiating leg.

    GET is a read: it mints nothing, touches no port state and reveals no
    principal. Its only job is to keep the nonprod affordance invisible in
    every composition that did not explicitly install one — including
    production, where the answer is always ``available: false``.
    """

    port = getattr(request.app.state, "claw_local_connect", None)
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, _CODE_NO_OWNER, "인증이 필요합니다.")
    allowed_owners = getattr(port, "allowed_owner_ids", None)
    available = (
        port is not None
        and getattr(port, "configured", False) is True
        and isinstance(allowed_owners, (set, frozenset))
        and uid in allowed_owners
    )
    return JSONResponse(
        {
            "ok": True,
            "available": available,
            "projectionVersion": CLAW_LOCAL_CONNECT_PROJECTION_VERSION,
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_local_connect(request: Request) -> JSONResponse:
    """Mint one canonical pairing challenge for the authenticated TEST owner.

    Non-Production only; one canonical mint per call; the deep link is returned
    in the existing #3095 schema for the page to hand to the OS handler.
    """

    port = getattr(request.app.state, "claw_local_connect", None)
    if port is None or getattr(port, "configured", False) is not True:
        return _error(503, _CODE_UNCONFIGURED, "이 환경에서는 컴퓨터 연결을 시작할 수 없습니다.")

    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, _CODE_NO_OWNER, "인증이 필요합니다.")

    body: Any = None
    try:
        raw_body = await request.body()
        if raw_body:
            import json

            body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        # A malformed or undecodable request must never mint a challenge.
        # Silently treating it as an empty request bypasses input validation.
        return _error(400, _CODE_INVALID_BODY, "요청 본문이 올바르지 않습니다.")
    except Exception:
        return _error(400, _CODE_INVALID_BODY, "요청 본문을 읽을 수 없습니다.")
    if body is not None and not isinstance(body, Mapping):
        return _error(400, _CODE_INVALID_BODY, "요청 본문이 올바르지 않습니다.")
    conversation_id = _validate_conversation_id(body.get("conversationId") if body else None)
    if body and body.get("conversationId") is not None and conversation_id is None:
        return _error(400, _CODE_INVALID_BODY, "conversationId가 올바르지 않습니다.")

    allowed_owners = getattr(port, "allowed_owner_ids", None)
    if not isinstance(allowed_owners, (set, frozenset)) or uid not in allowed_owners:
        # Existence of other owners is never disclosed; the refusal is the
        # same bounded shape for any unauthorized session.
        return _error(403, _CODE_OWNER_UNAUTHORIZED, "이 세션은 컴퓨터 연결을 시작할 수 없습니다.")

    mint = None
    try:
        mint = port.issue_pairing_challenge(
            owner_id=uid,
            conversation_id=conversation_id,
            now=datetime.now(timezone.utc),
        )
        if hasattr(mint, "__await__"):
            mint = await mint
    except Exception:
        # The canonical mint refused or the transport failed: one bounded code,
        # never a retry, never upstream detail.
        return _error(502, _CODE_REFUSED, "연결 요청이 처리되지 못했습니다.")

    if not isinstance(mint, Mapping) or mint.get("ok") is not True:
        return _error(502, _CODE_REFUSED, "연결 요청이 처리되지 못했습니다.")

    value = _deep_link(mint)
    if value is None:
        return _error(502, _CODE_INVALID_MINT, "연결 요청 결과를 사용할 수 없습니다.")

    handoff: dict[str, Any] = {"kind": "deep_link", "value": value}
    if conversation_id is not None:
        handoff["conversationId"] = conversation_id
    return JSONResponse(
        {
            "ok": True,
            "projectionVersion": CLAW_LOCAL_CONNECT_PROJECTION_VERSION,
            "handoff": handoff,
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

NONPROD_EVIDENCE_HOST_ONLY = True
PRODUCTION_PAIRING_STORE_ADDED = False
DURABLE_PAIRING_STORE_CONFIGURED = False
REQUEST_BODY_IS_AUTHORITY = False
PAIRING_MINTING_AUTHORITY = "canonical_broker_challenge_mint_via_nonprod_host"
DEEP_LINK_SCHEMA = "existing #3095/#3140 padiem://pair"
SCOPE_MISMATCH_BYPASS = False
HANDOFF_VALUE_MINTED_OR_PARSED = False
PRODUCTION_MUTATION = False
