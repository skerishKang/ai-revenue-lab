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
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .pc_device_pairing_store import (
    PcPairingError,
    normalize_root_label,
    normalize_root_path,
)

#: The collection is the issue endpoint: POST creates a code, GET lists this
#: account's links and pending codes. A code that was issued and never redeemed
#: is abandoned on its own path, because the browser must be able to cancel
#: exactly the one it is showing.
PC_PAIRING_PATH = "/api/pc/pairings"
PC_PAIRING_CLAIM_PATH = "/api/pc/pairings/claim"
#: What the code entitles its holder to download. One path, one Windows link,
#: and the URL is never assembled from anything the request says.
PC_PAIRING_HANDOFF_PATH = "/api/pc/pairings/handoff"
#: Administrator adoption: the Owner links a device this deployment already
#: knows about to their own account, without waiting for somebody else's PC to
#: run an installer.
PC_PAIRING_ADOPT_PATH = "/api/pc/pairings/adopt"
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
    #: Migration 072 not applied yet: the Worker composes the store against a
    #: live D1 binding that has no pairing tables. This is the sentence the
    #: browser sees until the Owner applies the migration.
    "pc_pairing_not_ready": "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
    "pc_pairing_body_invalid": "PC 연결 요청 형식이 올바르지 않습니다.",
    "pc_pairing_code_unknown": "연결 코드를 확인할 수 없습니다. 새 코드로 다시 시도해 주세요.",
    "pc_pairing_code_used": "이 연결 코드는 이미 사용되었습니다. 새 코드를 발급해 주세요.",
    "pc_pairing_code_expired": "연결 코드가 만료되었습니다. 새 코드로 다시 시도해 주세요.",
    "pc_pairing_node_invalid": "PC 식별 형식이 올바르지 않습니다.",
    "pc_pairing_root_invalid": "승인할 폴더 경로를 사용할 수 없습니다.",
    "pc_pairing_root_not_found": "승인된 폴더를 찾을 수 없습니다.",
    "pc_pairing_root_label_taken": "같은 PC 연결에 이미 같은 이름의 폴더가 있습니다. 다른 이름으로 지정해 주세요.",
    "pc_pairing_root_limit": "이 PC 연결에 승인할 수 있는 폴더 한계에 도달했습니다.",
    "pc_pairing_link_not_found": "연결을 찾을 수 없습니다.",
    "pc_pairing_not_admin": "이 PC를 채택할 수 있는 권한이 없습니다.",
    "pc_pairing_device_unmapped": "이 배포에서 확인할 수 없는 PC입니다.",
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
    "root label invalid": "pc_pairing_root_invalid",
    "root label exists": "pc_pairing_root_label_taken",
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
    elif code in {"pc_pairing_link_not_active", "pc_pairing_root_label_taken"}:
        status = 409
    elif code == "pc_pairing_unavailable":
        status = 503
    else:
        status = 400
    return _error(status, code)


def _store(request: Request) -> Any:
    return getattr(request.app.state, "pc_device_pairing_store", None)


#: What a D1 database says when the migration that creates a pairing table has
#: not been applied. Text matching is enough here because both branches refuse:
#: neither one authorizes anything, and neither echoes the driver's sentence.
_MISSING_SCHEMA_MARKERS = ("no such table", "no such column")


def _unavailable(exc: BaseException) -> JSONResponse:
    """A store fault is always a refusal, never a partial answer.

    The Worker composes this store against whatever D1 binding is configured, so
    before the Owner applies 072 every pairing query fails in the driver. The
    deployment must read as "not ready yet" rather than as an HTTP 500.
    """
    text = str(exc).lower()
    return _error(503, "pc_pairing_not_ready"
                  if any(marker in text for marker in _MISSING_SCHEMA_MARKERS)
                  else "pc_pairing_unavailable")


async def _await_store(action: Any, **values: Any) -> tuple[Any, JSONResponse | None]:
    """Run one store call, or return the refusal it deserves."""
    try:
        return await action(**values), None
    except PcPairingError as exc:
        return None, _refused(exc)
    except Exception as exc:
        return None, _unavailable(exc)


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
    issued, refused = await _await_store(store.issue_code, user_id=user_id, issued_at=_now())
    if refused is not None:
        return refused
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
    links, refused = await _await_store(store.list_links, user_id=user_id)
    if refused is not None:
        return refused
    codes, refused = await _await_store(store.list_codes, user_id=user_id, now=_now())
    if refused is not None:
        return refused
    return _json({"ok": True, "links": links, "codes": codes}, 200)


async def pc_pairing_revoke(request: Request) -> JSONResponse:
    """R5: delete one link and exactly that pair's folder approvals."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    revoked, refused = await _await_store(
        store.revoke_link, user_id=user_id,
        link_id=request.path_params.get("link_id"), now=_now(),
    )
    if refused is not None:
        return refused
    if not revoked:
        return _error(404, "pc_pairing_link_not_found")
    return _json({"ok": True, "revoked": True}, 200)


def install_url_from_config(value: Any) -> str | None:
    """The reviewed deployment value, or ``None`` when there is nothing to hand out.

    Only a plain https URL with a host and no credentials is accepted: this value
    is what a PC downloads an installer from, so an empty or http configuration
    is treated exactly like no configuration rather than as a weaker grant. The
    route never takes the URL from the request, so an unconfigured deployment
    answers "준비 중" instead of guessing a host or letting a caller point a PC at
    a machine of its own choosing.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 2048:
        return None
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in text):
        return None
    scheme, _, rest = text.partition("://")
    if scheme.lower() != "https" or not rest:
        return None
    host = rest.split("/", 1)[0]
    if not host or "@" in host:
        return None
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:[0-9]{1,5})?", host):
        return None
    return text


async def pc_pairing_handoff(request: Request) -> JSONResponse:
    """Turn a code the PC already holds into the tag and installer it needs.

    No session: whoever presents the code is the PC it was issued for, and the
    code is the whole proof (R2, R3). Nothing is consumed here — the claim
    completes when the tag reappears in an observed agent name, or when the PC
    posts the code itself, so a download that fails mid-way leaves a code that
    still works inside its ten minutes.
    """
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    # An unset installer link is not a refusal: a PC whose agent is already
    # installed needs only the tag, and the account with no agent yet is told to
    # wait for the link by the wrapper, not by an HTTP error on a code that is
    # still perfectly good. The code is validated either way, below.
    agent_url = install_url_from_config(
        getattr(request.app.state, "pc_pairing_install_url", None),
    )
    body = await _body(request)
    if body is None or set(body) != {"code"}:
        return _error(400, "pc_pairing_body_invalid")
    code = body.get("code")
    if not isinstance(code, str) or not code:
        return _error(400, "pc_pairing_body_invalid")
    handoff, refused = await _await_store(
        store.peek_pairing_code, code=code, now=_now(),
    )
    if refused is not None:
        return refused
    return _json({
        "ok": True,
        "handoff": {
            "install_tag": handoff["install_tag"],
            "agent_url": agent_url,
            "expires_at": handoff["expires_at"],
        },
    }, 200)


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
    link, refused = await _await_store(
        store.redeem_code, code=code, mesh_node_id=mesh_node_id, label=label,
        now=_now(), verified=verified,
    )
    if refused is not None:
        return refused
    return _json({
        "ok": True,
        "link": {
            "link_id": link["link_id"],
            "mesh_node_id": link["mesh_node_id"],
            "state": link["state"],
            "roots": [],
        },
    }, 201 if link["state"] == "active" else 202)


async def pc_pairing_adopt(request: Request) -> JSONResponse:
    """Adopt a mapped PC into the calling administrator's own account (PR-4e).

    Three rules carry the whole design. Only a platform administrator may call
    this — the guard is the existing central-admin one, and it runs before
    anything is read out of the deployment map, so a refused call learns nothing
    about which devices exist. A device the map does not name is a 404, because
    inventing a target from a request is exactly what this lane must never do.
    And adoption produces the same authority a normal claim does: an active link
    with that device's approved folders, usable by the file lane and idempotent,
    so a second click returns the same link instead of widening anything.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) != {"device_id"}:
        return _error(400, "pc_pairing_body_invalid")
    device_id = body.get("device_id")
    if not isinstance(device_id, str) or not device_id:
        return _error(400, "pc_pairing_body_invalid")
    from .platform_admin_authority import platform_authority_for
    authority = platform_authority_for(request)
    try:
        admin = await authority.is_global_model_admin(user_id=user_id)
    except Exception:
        admin = False
    if admin is not True:
        return _error(403, "pc_pairing_not_admin")
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if source is None or getattr(source, "configured", False) is not True:
        return _error(503, "pc_pairing_unavailable")
    try:
        mapped = source.names_device(device_id=device_id)
        roots = source.adopted_roots_for_device(device_id=device_id)
    except Exception:
        return _error(503, "pc_pairing_unavailable")
    if not mapped:
        return _error(404, "pc_pairing_device_unmapped")
    if not roots:
        # The map names the device but pins no usable folder: adopting it would
        # create a link that cannot be used, so it is refused instead.
        return _error(404, "pc_pairing_device_unmapped")
    adopted, refused = await _await_store(
        store.adopt_link, user_id=user_id, mesh_node_id=device_id,
        root_paths=roots, now=_now(),
    )
    if refused is not None:
        return refused
    return _json({
        "ok": True,
        "link": {
            "link_id": adopted["link_id"],
            "mesh_node_id": adopted["mesh_node_id"],
            "label": adopted.get("label"),
            "state": adopted["state"],
            "roots": [
                {
                    "root_ref": root["root_ref"],
                    "label": root["label"],
                    "path": root["path"],
                    "state": root["state"],
                    "approved_at": root["approved_at"],
                }
                for root in adopted["roots"]
                if root["state"] == "active"
            ],
            "created_at": adopted["created_at"],
            "updated_at": adopted["updated_at"],
        },
    }, 200)


async def pc_pairing_approve_root(request: Request) -> JSONResponse:
    """Approve one folder on one link (R1)."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or not set(body) <= {"path", "label"} or "path" not in body:
        return _error(400, "pc_pairing_body_invalid")
    path = normalize_root_path(body.get("path"))
    if path is None:
        return _error(400, "pc_pairing_root_invalid")
    label = body.get("label")
    if label is not None and normalize_root_label(label) is None:
        return _error(400, "pc_pairing_root_invalid")
    root, refused = await _await_store(
        store.approve_root, user_id=user_id,
        link_id=request.path_params.get("link_id"), path=path, now=_now(), label=label,
    )
    if refused is not None:
        return refused
    return _json({"ok": True, "root": root}, 201)


async def pc_pairing_revoke_root(request: Request) -> JSONResponse:
    """Withdraw one folder from one link, leaving the link itself usable."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    revoked, refused = await _await_store(
        store.revoke_root, user_id=user_id,
        link_id=request.path_params.get("link_id"),
        root_ref=request.path_params.get("root_ref"), now=_now(),
    )
    if refused is not None:
        return refused
    if not revoked:
        return _error(404, "pc_pairing_root_not_found")
    return _json({"ok": True, "revoked": True}, 200)


__all__ = [
    "PC_PAIRING_CLAIM_PATH",
    "PC_PAIRING_ADOPT_PATH",
    "PC_PAIRING_HANDOFF_PATH",
    "PC_PAIRING_LINK_PATH",
    "PC_PAIRING_PATH",
    "PC_PAIRING_ROOTS_PATH",
    "PC_PAIRING_ROOT_PATH",
    "pc_pairing_approve_root",
    "pc_pairing_claim",
    "pc_pairing_handoff",
    "pc_pairing_adopt",
    "install_url_from_config",
    "pc_pairing_issue",
    "pc_pairing_list",
    "pc_pairing_revoke",
    "pc_pairing_revoke_root",
]
