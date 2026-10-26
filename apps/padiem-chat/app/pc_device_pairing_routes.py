"""#5573 PC pairing routes: issue a code, claim it from a PC, list and revoke.

Owner-scoped like every other Chat store: the account is always the verified
session's user id and is never a request value. The two exceptions are the
claim, which carries no session at all because the caller is a PC that has not
been introduced yet and is authorized solely by the one-time code it was given,
and nothing else.

What this route does not do: it mints no device credential, registers nothing
with MeshCentral, and authorizes no execution. A link answers "whose PC is
this"; dispatch keeps asking its own questions (PR-2 wires that read), and a
link that nothing has yet observed on the Mesh is created as
`pending_verification` rather than trusted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .pc_device_pairing_store import (
    PcPairingError,
    normalize_root_path,
)

#: The collection is the issue endpoint: POST creates a code, GET lists this
#: account's links and pending codes. A code that was issued and never redeemed
#: is abandoned on its own path, because the browser must be able to cancel
#: exactly the one it is showing.
PC_PAIRING_PATH = "/api/pc/pairings"
PC_PAIRING_CLAIM_PATH = "/api/pc/pairings/claim"
PC_PAIRING_LINK_PATH = "/api/pc/pairings/{link_id}"
PC_PAIRING_ROOTS_PATH = "/api/pc/pairings/{link_id}/roots"
PC_PAIRING_ROOT_PATH = "/api/pc/pairings/{link_id}/roots/{root_ref}"

_MAX_BODY_BYTES = 2048
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}

#: Refusal codes this surface can produce, and the browser-visible sentence for
#: each. Anything else is the generic failure: a pairing refusal must not
#: disclose whether a code exists, whose it was, or which node collided.
_MESSAGES = {
    "unauthorized": "로그인이 필요합니다.",
    "pc_pairing_unavailable": "PC 연결을 현재 처리할 수 없습니다.",
    "pc_pairing_body_invalid": "PC 연결 요청 형식이 올바르지 않습니다.",
    "pc_pairing_code_unknown": "연결 코드를 확인할 수 없습니다. 새 코드로 다시 시도해 주세요.",
    "pc_pairing_code_used": "이 연결 코드는 이미 사용되었습니다. 새 코드를 발급해 주세요.",
    "pc_pairing_code_expired": "연결 코드가 만료되었습니다. 새 코드로 다시 시도해 주세요.",
    "pc_pairing_node_invalid": "PC 식별 형식이 올바르지 않습니다.",
    "pc_pairing_root_invalid": "승인할 폴더 경로를 사용할 수 없습니다.",
    "pc_pairing_root_not_found": "승인된 폴더를 찾을 수 없습니다.",
    "pc_pairing_root_limit": "이 PC 연결에 승인할 수 있는 폴더 한계에 도달했습니다.",
    "pc_pairing_link_not_found": "연결을 찾을 수 없습니다.",
    "pc_pairing_link_not_active": "이 PC 연결은 아직 사용 대기 중이거나 해제되었습니다.",
}

#: Store reason -> route code. The store deliberately never names a value.
_REASONS = {
    "pairing code unknown": "pc_pairing_code_unknown",
    "pairing code used": "pc_pairing_code_used",
    "pairing code expired": "pc_pairing_code_expired",
    "pairing code invalid": "pc_pairing_code_unknown",
    "pairing code id invalid": "pc_pairing_code_unknown",
    "pairing code not stored": "pc_pairing_unavailable",
    "mesh node identity invalid": "pc_pairing_node_invalid",
    "root path invalid": "pc_pairing_root_invalid",
    "root reference invalid": "pc_pairing_root_invalid",
    "too many approved roots": "pc_pairing_root_limit",
    "link roots too large": "pc_pairing_root_limit",
    "link roots unreadable": "pc_pairing_unavailable",
    "link id invalid": "pc_pairing_link_not_found",
    "link not found": "pc_pairing_link_not_found",
    "link not active": "pc_pairing_link_not_active",
    "link label invalid": "pc_pairing_body_invalid",
    "link label too long": "pc_pairing_body_invalid",
    "link not stored": "pc_pairing_unavailable",
    "pairing link not stored": "pc_pairing_unavailable",
    "user id invalid": "unauthorized",
    "trusted aware receipt time required": "pc_pairing_unavailable",
}


def _json(body: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _json({"ok": False, "error": {"code": code, "message": _MESSAGES[code]}}, status)


def _refused(exc: PcPairingError) -> JSONResponse:
    code = _REASONS.get(str(exc), "pc_pairing_unavailable")
    # A failed possession proof is 403, an unknown or dead pair is 404, and the
    # rest are the request's own defect. Nothing here describes a value it
    # refused, so the status carries no extra disclosure.
    if code.startswith("pc_pairing_code"):
        status = 403
    elif code == "unauthorized":
        status = 401
    elif code in {"pc_pairing_link_not_found", "pc_pairing_root_not_found"}:
        status = 404
    elif code == "pc_pairing_link_not_active":
        status = 409
    elif code == "pc_pairing_unavailable":
        status = 503
    else:
        status = 400
    return _error(status, code)


def _store(request: Request) -> Any:
    return getattr(request.app.state, "pc_device_pairing_store", None)


async def _body(request: Request) -> dict[str, Any] | None:
    """One closed JSON object, or None when the body is not one."""
    try:
        raw = await read_bounded_request_body(request, max_bytes=_MAX_BODY_BYTES)
    except RequestBodyTooLarge:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def pc_pairing_issue(request: Request) -> JSONResponse:
    """Issue a 10-minute one-time code for this account's next PC link (R2)."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) not in (set(), {"label"}):
        return _error(400, "pc_pairing_body_invalid")
    try:
        issued = await store.issue_code(user_id=user_id, issued_at=_now())
    except PcPairingError as exc:
        return _refused(exc)
    return _json({
        "ok": True,
        "pairing": {
            "code_id": issued["code_id"],
            "code": issued["code"],
            "install_tag": issued["install_tag"],
            "expires_at": issued["expires_at"],
        },
    }, 201)


async def pc_pairing_list(request: Request) -> JSONResponse:
    """This account's PC links and its still-pending codes."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    try:
        links = await store.list_links(user_id=user_id)
        codes = await store.list_codes(user_id=user_id, now=_now())
    except PcPairingError as exc:
        return _refused(exc)
    return _json({"ok": True, "links": links, "codes": codes}, 200)


async def pc_pairing_revoke(request: Request) -> JSONResponse:
    """R5: delete one link and exactly that pair's folder approvals."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    try:
        revoked = await store.revoke_link(
            user_id=user_id, link_id=request.path_params.get("link_id"), now=_now(),
        )
    except PcPairingError as exc:
        return _refused(exc)
    if not revoked:
        return _error(404, "pc_pairing_link_not_found")
    return _json({"ok": True, "revoked": True}, 200)


async def pc_pairing_claim(request: Request) -> JSONResponse:
    """One PC redeems the code it was given (R2, R3).

    No session, no device credential, nothing to log in with on the PC: the code
    is the whole proof, and it is consumed exactly once. `mesh_node_id` is the
    composed MeshCentral identity the installing agent already knows for itself,
    validated against the same grammar every other PC boundary uses.
    """
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) not in ({"code", "mesh_node_id"}, {"code", "mesh_node_id", "label"}):
        return _error(400, "pc_pairing_body_invalid")
    code = body.get("code")
    mesh_node_id = body.get("mesh_node_id")
    label = body.get("label")
    if not isinstance(code, str) or not code or not isinstance(mesh_node_id, str):
        return _error(400, "pc_pairing_body_invalid")
    if label is not None and not isinstance(label, str):
        return _error(400, "pc_pairing_body_invalid")
    # The Mesh observation that proves a node exists is PR-2's directory. Without
    # it a link is recorded and stays `pending_verification`: a claimed code must
    # never become an executable target on the strength of the claim alone.
    verifier = getattr(request.app.state, "pc_pairing_verifier", None)
    verified = False
    if callable(verifier):
        try:
            verified = bool(await verifier(mesh_node_id=mesh_node_id, code=code))
        except Exception:
            verified = False
    try:
        link = await store.redeem_code(
            code=code, mesh_node_id=mesh_node_id, label=label, now=_now(), verified=verified,
        )
    except PcPairingError as exc:
        return _refused(exc)
    return _json({
        "ok": True,
        "link": {
            "link_id": link["link_id"],
            "mesh_node_id": link["mesh_node_id"],
            "state": link["state"],
            "roots": [],
        },
    }, 201 if link["state"] == "active" else 202)


async def pc_pairing_approve_root(request: Request) -> JSONResponse:
    """Approve one folder on one link (R1)."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) != {"path"}:
        return _error(400, "pc_pairing_body_invalid")
    path = normalize_root_path(body.get("path"))
    if path is None:
        return _error(400, "pc_pairing_root_invalid")
    try:
        root = await store.approve_root(
            user_id=user_id, link_id=request.path_params.get("link_id"), path=path, now=_now(),
        )
    except PcPairingError as exc:
        return _refused(exc)
    return _json({"ok": True, "root": root}, 201)


async def pc_pairing_revoke_root(request: Request) -> JSONResponse:
    """Withdraw one folder from one link, leaving the link itself usable."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    try:
        revoked = await store.revoke_root(
            user_id=user_id,
            link_id=request.path_params.get("link_id"),
            root_ref=request.path_params.get("root_ref"),
            now=_now(),
        )
    except PcPairingError as exc:
        return _refused(exc)
    if not revoked:
        return _error(404, "pc_pairing_root_not_found")
    return _json({"ok": True, "revoked": True}, 200)


__all__ = [
    "PC_PAIRING_CLAIM_PATH",
    "PC_PAIRING_LINK_PATH",
    "PC_PAIRING_PATH",
    "PC_PAIRING_ROOTS_PATH",
    "PC_PAIRING_ROOT_PATH",
    "pc_pairing_approve_root",
    "pc_pairing_claim",
    "pc_pairing_issue",
    "pc_pairing_list",
    "pc_pairing_revoke",
    "pc_pairing_revoke_root",
]
