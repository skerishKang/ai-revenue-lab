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
import inspect
import json
import logging
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_local_access_source import MESH_PRESENCE_MAX_AGE_SECONDS
from .pc_device_pairing_store import (
    INSTALL_TOKEN_HEX_CHARS,
    INSTALL_TOKEN_PREFIX,
    PcPairingError,
    drive_root,
    normalize_root_label,
    normalize_root_path,
)
from .pc_pairing_agent_install import (
    render_agent_install_block,
    render_user_helper_install_block,
)
from .pc_pairing_connect_exe_asset import connect_exe_bytes
from .pc_scope_cache import invalidate_owner_scope

#: The collection is the issue endpoint: POST creates a code, GET lists this
#: account's links and pending codes. A code that was issued and never redeemed
#: is abandoned on its own path, because the browser must be able to cancel
#: exactly the one it is showing.
PC_PAIRING_PATH = "/api/pc/pairings"
PC_PAIRING_CLAIM_PATH = "/api/pc/pairings/claim"
#: What the code entitles its holder to download. One path, one Windows link,
#: and the URL is never assembled from anything the request says.
PC_PAIRING_HANDOFF_PATH = "/api/pc/pairings/handoff"
#: The one-click install file: the signed-in account's own tag, already inside
#: the file, so nothing on the PC has to be typed.
PC_PAIRING_INSTALL_FILE_PATH = "/api/pc/pairings/install-file"
PC_PAIRING_INSTALL_FILENAME = "padiem-pc-connect.ps1"
#: The same connect as a program: one double-click, no PowerShell, no right-click
#: menu, nothing typed. The account's tag travels after the program's own bytes.
PC_PAIRING_INSTALL_EXE_PATH = "/api/pc/pairings/install-exe"
PC_PAIRING_INSTALL_EXE_FILENAME = "padiem-pc-connect.exe"
#: The line the program looks for at the end of its own file. Written here, read
#: there, and nothing else on the PC holds the pairing information.
PC_PAIRING_CONNECT_EXE_MARKER = "PADIEMTRAILER:PADIEM-PC-CONNECT-1"
#: Administrator adoption: the Owner links a device this deployment already
#: knows about to their own account, without waiting for somebody else's PC to
#: run an installer.
PC_PAIRING_ADOPT_PATH = "/api/pc/pairings/adopt"
#: 2026-11-08: administrator-only managed(contract) PC mark/unmark. SYSTEM
#: execution needs this mark together with the administrator verdict.
PC_PAIRING_MANAGED_PATH = "/api/pc/devices/{link_id}/managed"
PC_PAIRING_LINK_PATH = "/api/pc/pairings/{link_id}"
PC_PAIRING_ROOTS_PATH = "/api/pc/pairings/{link_id}/roots"
PC_PAIRING_ROOT_PATH = "/api/pc/pairings/{link_id}/roots/{root_ref}"
#: The owner's own name for one linked PC. A chat request chooses a machine with
#: this name when the account has more than one.
PC_PAIRING_LABEL_PATH = "/api/pc/pairings/{link_id}/label"
#: Pause and resume are two states of the same link, not two kinds of unlink:
#: revoke stays the only path that drops the folder approvals.
PC_PAIRING_PAUSE_PATH = "/api/pc/pairings/{link_id}/pause"
PC_PAIRING_RESUME_PATH = "/api/pc/pairings/{link_id}/resume"
#: #6695 PR-4: the owner's two answers to an install they handed out - cancel it,
#: or replace it with a fresh code and token.
PC_PAIRING_TOKEN_REVOKE_PATH = "/api/pc/pairings/{code_id}/token/revoke"
PC_PAIRING_TOKEN_REISSUE_PATH = "/api/pc/pairings/{code_id}/token/reissue"

#: What one adoption call may carry. `device_id` names the PC; `target` names the
#: account it belongs to (omitted: the caller's own); `drives` reports the PC's
#: fixed drives when nobody has reported them yet.
_ADOPT_BODY_KEYS = frozenset({
    frozenset({"device_id"}),
    frozenset({"device_id", "drives"}),
    frozenset({"device_id", "target"}),
    frozenset({"device_id", "drives", "target"}),
})

_MAX_BODY_BYTES = 2048
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
from .journal_host import ensure_journal_visible
from .auth_validation_cache import drop_cached_owner_scope_of

_LOGGER = logging.getLogger("padiem_chat.request")

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
    #: The deployment has not handed Chat the agent download link yet, so there
    #: is no file to give this account's PC. Same 준비 중 shape as an unapplied
    #: migration: nothing is refused about the account, and nothing is guessed.
    "pc_pairing_install_url_missing": "PC 설치 파일은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
    #: The reviewed program is not in this build, or its bytes are not the bytes the
    #: build recorded. Handing out something else would be worse than waiting.
    "pc_pairing_connect_exe_unavailable": "PC 연결 프로그램은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",
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
    "pc_pairing_managed_not_admin": "관리(계약) PC를 표시할 권한이 없습니다.",
    #: Adoption names an account and a device. Both answers are 404s with
    #: different work behind them: no such account, a machine the Mesh lane has
    #: never reported, or a reported machine whose drive scope nobody has stated.
    "pc_pairing_target_unknown": "지정된 계정을 찾을 수 없습니다.",
    "pc_pairing_device_unseen": "MeshCentral에 연결된 기록이 없는 PC입니다.",
    "pc_pairing_device_unscoped": "이 PC의 드라이브를 아직 알 수 없습니다. PC를 먼저 연결해 주세요.",
    "pc_pairing_link_not_active": "이 PC 연결은 아직 사용 대기 중이거나 해제되었습니다.",
    #: The link row exists under another account. This is a permission answer,
    # not a missing row, and it names no value either way.
    "pc_pairing_link_forbidden": "이 PC 연결을 바꿀 권한이 없습니다.",
    #: #6695 PR-4: the install itself, not the code, is the thing that failed.
    #: Each sentence says which half of the proof was refused without showing it.
    "pc_pairing_token_invalid": "이 설치 파일의 계정 정보를 확인할 수 없습니다. 새 설치 파일을 받아 주세요.",
    "pc_pairing_token_revoked": "취소된 설치입니다. 새 설치 파일을 받아 주세요.",
    "pc_pairing_token_expired": "설치 유효 시간이 지났습니다. 새 설치 파일을 받아 주세요.",
}

#: Store reason -> route code. The store deliberately never names a value.
_REASONS = {
    "pairing code unknown": "pc_pairing_code_unknown",
    "pairing code used": "pc_pairing_code_used",
    "pairing code expired": "pc_pairing_code_expired",
    "pairing code invalid": "pc_pairing_code_unknown",
    "pairing code id invalid": "pc_pairing_code_unknown",
    "pairing code not stored": "pc_pairing_unavailable",
    "pairing code not yours": "pc_pairing_link_forbidden",
    "install token invalid": "pc_pairing_token_invalid",
    "install token revoked": "pc_pairing_token_revoked",
    "install token expired": "pc_pairing_token_expired",
    "install token not stored": "pc_pairing_unavailable",
    "mesh node identity invalid": "pc_pairing_node_invalid",
    "root path invalid": "pc_pairing_root_invalid",
    "root reference invalid": "pc_pairing_root_invalid",
    "root label invalid": "pc_pairing_root_invalid",
    "root label exists": "pc_pairing_root_label_taken",
    "link roots too large": "pc_pairing_root_limit",
    "link roots unreadable": "pc_pairing_unavailable",
    "link id invalid": "pc_pairing_link_not_found",
    "adopt target invalid": "pc_pairing_body_invalid",
    "link not found": "pc_pairing_link_not_found",
    "link not active": "pc_pairing_link_not_active",
    "link not yours": "pc_pairing_link_forbidden",
    "link label invalid": "pc_pairing_body_invalid",
    "link label too long": "pc_pairing_body_invalid",
    "managed flag invalid": "pc_pairing_body_invalid",
    #: Migration 103 not applied: the mark cannot be written yet, but every
    #: existing link read still works. Same 준비 중 shape as an absent table.
    "managed column missing": "pc_pairing_not_ready",
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
    elif code.startswith("pc_pairing_token"):
        # A failed possession proof, exactly like a bad code: 403, never 404.
        status = 403
    elif code == "unauthorized":
        status = 401
    elif code == "pc_pairing_link_forbidden":
        status = 403
    elif code in {"pc_pairing_link_not_found", "pc_pairing_root_not_found"}:
        status = 404
    elif code in {"pc_pairing_link_not_active", "pc_pairing_root_label_taken"}:
        status = 409
    elif code in {"pc_pairing_unavailable", "pc_pairing_not_ready"}:
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


def _log_managed(*, actor: str, link_id: Any, managed: bool, result: str) -> None:
    """One admin mark/unmark line: actor, link and result; no command or path."""
    event = {"event": "pc_link_managed", "managed": bool(managed), "result": result}
    for key, value in (("actor", actor), ("link_id", link_id)):
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value):
            event[key] = value
    ensure_journal_visible(_LOGGER)
    _LOGGER.info(json.dumps(event, separators=(",", ":")))


def presence_pairing_verifier(presence_store: Any) -> Any:
    """The claim route's node-existence proof, built from the PR-2 directory.

    #7293 follow-up: the claim route reads ``app.state.pc_pairing_verifier``
    and no runtime ever injected one, so every typed-code claim landed in
    ``pending_verification`` forever and no self-service pairing could ever
    become an executable target. The verifier is exactly what the claim route's
    own comment says it should be: the same server-recorded Mesh presence
    receipt the owner's PC list reads — a node the directory currently sees as
    online. A runtime with no presence store stays fail-closed (never verified).
    """

    async def verify(*, mesh_node_id: Any, code: Any) -> bool:
        del code  # the code's possession proof already happened in the route
        if presence_store is None:
            return False
        view = await _presence_view(
            presence_store, device_id=mesh_node_id, now=_now())
        return view.get("online") is True

    return verify


def _issued_pairing(request: Request, issued: dict[str, Any]) -> dict[str, Any]:
    """One issued (or reissued) install, as the browser may see it.

    #6695 PR-4: the account-specific install URL carries this code's token as
    its own argument, beside whatever MeshCentral parameters the deployment
    configured. A deployment that has not configured the link still issues a
    code (the typed-code path needs one) and answers `null` here.
    """
    return {
        "code_id": issued["code_id"],
        "code": issued["code"],
        "install_tag": issued["install_tag"],
        "install_url": personalized_install_url(
            agent_url=getattr(request.app.state, "pc_pairing_install_url", None),
            install_token=issued.get("install_token"),
        ),
        "expires_at": issued["expires_at"],
    }


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
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "pairing": _issued_pairing(request, issued)}, 201)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


async def _presence_view(store: Any, *, device_id: str, now: datetime) -> dict[str, Any]:
    """MeshCentral's own node connectivity for the owner's PC list (#6694 A).

    A link's `state:'active'` is a pairing record, not a connection: the agent
    it named can be uninstalled while the row stays active forever. The
    liveness answer lives in the same server-recorded Mesh presence receipt
    the local-access lane already reads (`mesh_device_presence`, written from
    the executor's poll): `connected` is MeshCentral's node connection fact
    and the receipt is trusted only inside the staleness bound that lane
    already uses. This is display evidence for the owner's list - it creates
    no execution grant, and dispatch keeps asking its own questions.

    A missing or unreadable receipt is reported as not online, the same
    fail-closed answer the device directory gives a linked PC nothing has
    observed: never shown as connected without evidence.
    """
    row = None
    if store is not None and callable(getattr(store, "load", None)):
        try:
            row = store.load(device_id=device_id)
            if inspect.isawaitable(row):
                row = await row
        except Exception:
            row = None
    if not isinstance(row, dict) or row.get("device_id") != device_id:
        return {"online": False, "last_seen_at": None}
    connected = row.get("connected") is True
    observed = _parse_iso(row.get("received_at"))
    online = False
    if connected and observed is not None:
        age = (now - observed).total_seconds()
        online = 0 <= age <= MESH_PRESENCE_MAX_AGE_SECONDS
    last_seen = row.get("last_connected_at")
    return {
        "online": online,
        "last_seen_at": last_seen if isinstance(last_seen, str) and last_seen else None,
    }


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
    presence = getattr(request.app.state, "mesh_device_presence_store", None)
    now = _now()
    for link in links:
        node = link.get("mesh_node_id") if isinstance(link, dict) else None
        if not isinstance(node, str) or not node:
            continue
        view = await _presence_view(presence, device_id=node, now=now)
        link["online"] = view["online"]
        link["last_seen_at"] = view["last_seen_at"]
    # One boolean for the settings screen: the 관리 PC toggle renders only for
    # the platform administrator (the same verdict the mark route enforces).
    from .platform_admin_authority import platform_authority_for
    try:
        admin = await platform_authority_for(request).is_global_model_admin(user_id=user_id)
    except Exception:
        admin = False
    return _json({"ok": True, "links": links, "codes": codes, "admin": admin is True}, 200)


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
    # #6460: a removed PC changes what this account's connector scope can reach,
    # so the short window is dropped here rather than waited out.
    drop_cached_owner_scope_of(request, user_id)
    invalidate_owner_scope(user_id)
    return _json({"ok": True, "revoked": True}, 200)


async def pc_pairing_pause(request: Request) -> JSONResponse:
    """Stop this account's PC from taking work, keeping every folder approval.

    POST with no body and no confirmation token: pausing is the owner saying
    "not right now" about a link they already own, and the card is the whole
    intent. A link already paused returns the same answer it gave the first time.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    link, refused = await _await_store(
        store.pause_link, user_id=user_id,
        link_id=request.path_params.get("link_id"), now=_now(),
    )
    if refused is not None:
        return refused
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "link": link}, 200)


async def pc_pairing_resume(request: Request) -> JSONResponse:
    """Put a paused PC link back in front of dispatch."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    link, refused = await _await_store(
        store.resume_link, user_id=user_id,
        link_id=request.path_params.get("link_id"), now=_now(),
    )
    if refused is not None:
        return refused
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "link": link}, 200)


async def pc_pairing_token_revoke(request: Request) -> JSONResponse:
    """Cancel one install this account handed out (#6695 PR-4).

    The token is stamped and its still-pending code is cancelled, so neither
    the file in the owner's Downloads folder nor the code inside it pairs a PC
    afterwards. Revoking an install that already built a link only retires the
    token: the link is the owner's PC, and unlinking it is the DELETE below.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    cancelled, refused = await _await_store(
        store.revoke_install_token, user_id=user_id,
        code_id=request.path_params.get("code_id"), now=_now(),
    )
    if refused is not None:
        return refused
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "install": cancelled}, 200)


async def pc_pairing_token_reissue(request: Request) -> JSONResponse:
    """Replace an install with a fresh code and token (#6695 PR-4).

    Same response shape as issuing a new code, because it *is* a new code: the
    browser downloads the file for it through the install endpoints naming this
    code, so exactly one pending install exists at a time.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    issued, refused = await _await_store(
        store.reissue_install_token, user_id=user_id,
        code_id=request.path_params.get("code_id"), now=_now(),
    )
    if refused is not None:
        return refused
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "pairing": _issued_pairing(request, issued)}, 201)


async def pc_pairing_managed(request: Request) -> JSONResponse:
    """Administrator-only managed(contract) PC mark/unmark (2026-11-08)."""
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) != {"managed"} or not isinstance(body["managed"], bool):
        return _error(400, "pc_pairing_body_invalid")
    link_id = request.path_params.get("link_id")
    from .platform_admin_authority import platform_authority_for
    try:
        admin = await platform_authority_for(request).is_global_model_admin(user_id=user_id)
    except Exception:
        admin = False
    if admin is not True:
        _log_managed(actor=user_id, link_id=link_id, managed=body["managed"], result="denied")
        return _error(403, "pc_pairing_managed_not_admin")
    link, refused = await _await_store(
        store.set_managed, link_id=link_id, by_user_id=user_id,
        managed=body["managed"], now=_now(),
    )
    if refused is not None:
        _log_managed(actor=user_id, link_id=link_id, managed=body["managed"], result="refused")
        return refused
    _log_managed(actor=user_id, link_id=link_id, managed=body["managed"], result="ok")
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "link": link}, 200)


async def pc_pairing_managed_state(request: Request) -> JSONResponse:
    """Administrator-only read of one link's managed(contract) mark (2026-11-08).

    A separate query on purpose (#7147 principle): the base link reads never
    depend on the migration 103 column, so the toggle state travels on its own
    endpoint and degrades to 503 pc_pairing_not_ready while the column is away.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    from .platform_admin_authority import platform_authority_for
    try:
        admin = await platform_authority_for(request).is_global_model_admin(user_id=user_id)
    except Exception:
        admin = False
    if admin is not True:
        return _error(403, "pc_pairing_managed_not_admin")
    state, refused = await _await_store(
        store.managed_state, link_id=request.path_params.get("link_id"),
    )
    if refused is not None:
        return refused
    return _json({"ok": True, "link_id": state["link_id"], "managed": state["managed"]}, 200)


async def pc_pairing_label(request: Request) -> JSONResponse:
    """Name one linked PC, in the words this account will use for it.

    With a second linked PC the question "which machine?" has to be answerable
    in a chat request, and the answer is the name the owner gave the machine.
    This changes no identity and no authority: the row stays keyed by
    `(account, node)`, dispatch keeps re-deciding from it, and a name is only
    ever a way to ask.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or set(body) != {"label"}:
        return _error(400, "pc_pairing_body_invalid")
    link, refused = await _await_store(
        store.set_link_label, user_id=user_id,
        link_id=request.path_params.get("link_id"),
        label=body.get("label"), now=_now(),
    )
    if refused is not None:
        return refused
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "link": link}, 200)


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


#: The install token the store mints: `pt_` and 32 lowercase hex characters.
#: The route re-checks the shape before it writes one into a file it hands out.
_INSTALL_TOKEN_RE = re.compile(
    r"^" + re.escape(INSTALL_TOKEN_PREFIX) + r"[0-9a-f]{%d}$" % INSTALL_TOKEN_HEX_CHARS
)


def user_helper_config(url_value: Any, sha_value: Any) -> tuple[str, str] | None:
    """The deployment's reviewed helper EXE and digest, or ``None``.

    Both halves are required and both are deployment values, never request
    values: the URL is the versioned download the build published, and the
    digest is the one that build printed. A half-configured deployment is
    treated exactly like no configuration - the agent install still runs and
    the helper step is simply absent.
    """
    url = install_url_from_config(url_value)
    if url is None or not isinstance(sha_value, str):
        return None
    sha = sha_value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        return None
    return url, sha


def personalized_install_url(*, agent_url: Any, install_token: Any) -> str | None:
    """The deployment's install link with this account's token beside its own args.

    #6695 PR-4: the URL an account is given has to name the account, and the
    MeshCentral parameters already in the configured link (the mesh id, the
    install flags) are not ours to reuse for that. So the token travels as its
    own parameter, appended after whatever the deployment configured, and the
    existing query - if any - is left exactly as it was. A token that is not the
    shape this deployment mints is refused rather than pasted in.
    """
    url = install_url_from_config(agent_url)
    if url is None:
        return None
    if not isinstance(install_token, str) or _INSTALL_TOKEN_RE.fullmatch(install_token) is None:
        return None
    separator = "&" if "?" in url else "?"
    return url + separator + "padiem_install_token=" + install_token


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
    helper = user_helper_config(
        getattr(request.app.state, "pc_pairing_user_helper_url", None),
        getattr(request.app.state, "pc_pairing_user_helper_sha256", None),
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
            "user_helper_url": helper[0] if helper is not None else None,
            "user_helper_sha256": helper[1] if helper is not None else None,
            "expires_at": handoff["expires_at"],
        },
    }, 200)


_INSTALL_TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SCRIPT_VALUE_MAX_CHARS = 2048


def _script_quote(value: str) -> str:
    """One PowerShell single-quoted literal, or ``None`` for anything unsafe.

    The two interpolated values are a derived tag and a reviewed deployment URL,
    so this is a wall rather than an escape routine: a single quote is doubled
    the way PowerShell says, and a value carrying a control character or a line
    break is refused outright. A downloaded installer runs whatever this file
    says next, so the shape of what may be written is fixed here.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= _SCRIPT_VALUE_MAX_CHARS:
        return None
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
        return None
    return "'" + value.replace("'", "''") + "'"


def render_install_script(
    *, install_tag: Any, agent_url: Any, install_token: Any = None,
    user_helper_url: Any = None, user_helper_sha256: Any = None,
) -> str | None:
    """The Windows install file one click hands out, or ``None`` when it cannot.

    What makes it one click: the account's pairing tag is already inside the
    file, so the PC is never asked to type anything, and the agent it downloads
    is the deployment's own - the file carries no server address the browser
    chose. The PC reports its fixed drives next to the tag in the name the agent
    gives the server, which is how the link arrives with whole drives granted
    instead of empty.

    #6695 PR-4: when the issue response also gave this install a token, the
    file carries it the same way - inside the agent name, right after the tag -
    so the server can check that the token presented is the one minted for this
    code and this account. A file for a code minted before tokens existed
    carries none, and pairs exactly as it did.

    Refused rather than improvised when either value is unusable: an installer
    with a guessed host, or with no tag, is a file that connects a PC to the
    wrong place or to nowhere.
    """
    if not isinstance(install_tag, str) or _INSTALL_TAG_RE.fullmatch(install_tag) is None:
        return None
    url = install_url_from_config(agent_url)
    if url is None:
        return None
    quoted_tag = _script_quote(install_tag)
    quoted_url = _script_quote(url)
    if quoted_tag is None or quoted_url is None:
        return None
    if install_token is None:
        quoted_token = "''"
    else:
        if (
            not isinstance(install_token, str)
            or _INSTALL_TOKEN_RE.fullmatch(install_token) is None
        ):
            return None
        quoted_token = _script_quote(install_token)
        if quoted_token is None:
            return None
    # #7108 PR-2: the helper is optional. An unconfigured or malformed helper
    # value omits its step; it never refuses the agent install that is the
    # file's actual job.
    helper_vars = ""
    helper_call = ""
    helper = user_helper_config(user_helper_url, user_helper_sha256)
    if helper is not None:
        quoted_helper_url = _script_quote(helper[0])
        if quoted_helper_url is not None:
            helper_vars = (
                f"$PadiemUserHelperUrl = {quoted_helper_url}\n"
                f"$PadiemUserHelperSha256 = '{helper[1]}'\n"
            )
            helper_call = (
                "  # Optional: the MeshCentral connection above is the install's\n"
                "  # success criterion. A helper that cannot be provisioned here is\n"
                "  # recorded in helper-status.json and never undoes that connection.\n"
                "  try {\n"
                "    if (Install-PadiemUserHelper -Url $PadiemUserHelperUrl -Sha256 $PadiemUserHelperSha256 -DeviceId (Get-PadiemHelperDeviceId -Tag $PairingTag)) {\n"
                "      Write-Host \"사용자 세션 도우미를 설치했습니다.\"\n"
                "    } else {\n"
                "      Write-Host \"사용자 세션 도우미는 설치하지 못했습니다. PC 연결은 계속 진행됩니다.\"\n"
                "    }\n"
                "  } catch {\n"
                "    Write-Host \"사용자 세션 도우미는 설치하지 못했습니다. PC 연결은 계속 진행됩니다.\"\n"
                "  }\n"
            )
    return _INSTALL_SCRIPT_TEMPLATE % {
        "tag": quoted_tag, "url": quoted_url, "token": quoted_token,
        "helper_vars": helper_vars, "helper_call": helper_call,
    }


def connect_exe_trailer(
    *, install_tag: Any, agent_url: Any,
    user_helper_url: Any = None, user_helper_sha256: Any = None,
) -> bytes | None:
    """The lines a downloaded program reads out of its own file, or ``None``.

    The account's tag, the deployment's own installer link, and - when this
    deployment configured it - the versioned user-helper EXE and its digest.
    No chat origin travels here on purpose - the program needs neither to
    install, and a file that carried an address the browser had chosen would be
    a file that could be pointed somewhere else. The origin belongs to the
    typed-code path, which is a switch on the command line, not a value in a
    download.

    The helper pair is optional and travels before the agent link, so the last
    line of the trailer is always the same one older programs already read.
    """
    if not isinstance(install_tag, str) or _INSTALL_TAG_RE.fullmatch(install_tag) is None:
        return None
    url = install_url_from_config(agent_url)
    if url is None:
        return None
    lines = [
        f"{PC_PAIRING_CONNECT_EXE_MARKER}\r\n",
        f"PADIEMTAG:{install_tag}\r\n",
    ]
    helper = user_helper_config(user_helper_url, user_helper_sha256)
    if helper is not None:
        lines.append(f"PADIEMHELPERURL:{helper[0]}\r\n")
        lines.append(f"PADIEMHELPERSHA:{helper[1]}\r\n")
    lines.append(f"PADIEMURL:{url}\r\n")
    return "".join(lines).encode("ascii")


def render_install_exe(
    *, install_tag: Any, agent_url: Any,
    user_helper_url: Any = None, user_helper_sha256: Any = None,
) -> bytes | None:
    """The double-click connect program with this account's tag behind its bytes.

    Windows runs an executable without regard for what follows it, so the tag rides
    at the end of the file instead of in a second download, a registry value, or a
    prompt. Everything before the trailer is the reviewed artifact byte for byte -
    this function adds nothing to the front and changes nothing inside, which is
    what lets the same SHA-256 the build printed describe what a PC receives.
    """
    trailer = connect_exe_trailer(
        install_tag=install_tag, agent_url=agent_url,
        user_helper_url=user_helper_url, user_helper_sha256=user_helper_sha256,
    )
    if trailer is None:
        return None
    try:
        program = connect_exe_bytes()
    except ValueError:
        return None
    return program + trailer


#: UTF-8 with a byte-order mark: Windows PowerShell 5.1 reads a file without one
#: in the machine's own code page, which turns Korean prose into unreadable
#: bytes and, in this deployment's experience, is exactly what breaks a reply.
_INSTALL_SCRIPT_TEMPLATE = (
    "\ufeff"
    "# PADIEM PC 자동 연결 (#5573)\n"
    "#\n"
    "# 로그인한 계정의 연결 표식이 이미 이 파일 안에 있습니다. 코드를 입력하지 않습니다.\n"
    "# 실행: 파일에서 우클릭 -> PowerShell로 실행. 관리자 권한을 물으면 예라고 답하세요.\n"
    "$ErrorActionPreference = \"Stop\"\n"
    "$PairingTag = %(tag)s\n"
    # Empty for an install without a token (a code minted before 093), which
    # leaves the reported name exactly as it was.
    "$PadiemInstallToken = %(token)s\n"
    "$AgentInstallerUrl = %(url)s\n"
    "%(helper_vars)s"
    "\n"
    "function Get-PadiemDriveLetters {\n"
    "  # The PC names the fixed drives it actually has. Network drives carry a\n"
    "  # DisplayRoot and stay out; a failed query reports nothing at all.\n"
    "  try {\n"
    "    return @(Get-PSDrive -PSProvider FileSystem -ErrorAction Stop |\n"
    "      Where-Object { $null -eq $_.DisplayRoot } |\n"
    "      ForEach-Object { $_.Name.ToUpperInvariant() } | Sort-Object -Unique)\n"
    "  } catch {\n"
    "    return @()\n"
    "  }\n"
    "}\n"
    "\n"
    # The install sequence itself is the one definition both .ps1 lanes read:
    # the same constants and the same stop - copy - install - start - check walk
    # the double-click program runs. A lane that drifts is a test failure, not
    # a smaller version of the same answer.
    + render_agent_install_block()
    + "\n"
    + render_user_helper_install_block()
    + "\n"
    "# One approval covers the whole sequence: the service work below needs the\n"
    "# administrator token, the same single prompt the double-click program asks\n"
    "# for before it connects. A refused approval still exits with its own code.\n"
    "$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()\n"
    "if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {\n"
    "  Write-Host \"관리자 권한 승인 창이 나타나면 [예]를 눌러 주세요. 설치에는 관리자 권한이 필요합니다.\"\n"
    "  try {\n"
    "    Start-Process -FilePath \"powershell.exe\" -ArgumentList @(\"-NoProfile\", \"-ExecutionPolicy\", \"Bypass\", \"-File\", ('\"' + $PSCommandPath + '\"')) -Verb RunAs\n"
    "  } catch [System.ComponentModel.Win32Exception] {\n"
    "    Write-Host \"설치 권한이 거부되었습니다. 이 파일을 관리자 권한으로 다시 실행해 주세요.\"\n"
    "    exit 5\n"
    "  } catch {\n"
    "    Write-Host \"PC 연결 프로그램을 실행하지 못했습니다. 잠시 후 다시 시도해 주세요.\"\n"
    "    exit 6\n"
    "  }\n"
    "  exit 0\n"
    "}\n"
    "\n"
    "$work = Join-Path $env:TEMP (\"padiem-pc-\" + [guid]::NewGuid().ToString(\"N\"))\n"
    "New-Item -ItemType Directory -Path $work | Out-Null\n"
    "try {\n"
    "  $agent = Join-Path $work \"padiem-agent.exe\"\n"
    "  Invoke-WebRequest -Uri $AgentInstallerUrl -OutFile $agent -UseBasicParsing -TimeoutSec 180\n"
    "  # The name the agent reports is what the server reads the pairing from:\n"
    "  # the tag decides the account, the bracketed letters are this PC's own\n"
    "  # drives, and the trailing word is the name Windows gave the machine -\n"
    "  # which becomes the link's first name unless the owner renames it.\n"
    "  # Dns.GetHostName() is the whole DNS name; $env:COMPUTERNAME is the\n"
    "  # 15-character NetBIOS form and would store a truncated name.\n"
    "  $machine = try { [System.Net.Dns]::GetHostName() } catch { $env:COMPUTERNAME }\n"
    "  if (-not $machine) { $machine = $env:COMPUTERNAME }\n"
    "  $reported = $PairingTag\n"
    "  # The token, when this install has one, rides between the tag and the\n"
    "  # drives: the server reads the same three parts in the same order.\n"
    "  if ($PadiemInstallToken) { $reported = $reported + \" \" + $PadiemInstallToken }\n"
    "  $letters = @(Get-PadiemDriveLetters)\n"
    "  if ($letters.Count -gt 0) {\n"
    "    $reported = $reported + \" [\" + ($letters -join \" \") + \"]\"\n"
    "  }\n"
    "  $reported = $reported + \" \" + $machine\n"
    "  if (-not (Install-PadiemAgentService -SourceExe $agent -AgentName $reported)) {\n"
    "    Write-Host \"에이전트 설치를 마치지 못했습니다. 잠시 후 다시 시도해 주세요.\"\n"
    "    exit 6\n"
    "  }\n"
    "  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue\n"
    "  if ($service) {\n"
    "    Write-Host (\"에이전트 서비스 상태: \" + $service.Status + \" - \" + $PadiemAgentDurableExe)\n"
    "  }\n"
    "%(helper_call)s"
    "  Write-Host \"연결 진행 중 - 서버가 이 PC를 확인하면 PADIEM PC 목록에 자동으로 나타납니다.\"\n"
    "} finally {\n"
    "  Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue\n"
    "}\n"
)


#: The shapes a download may carry. Empty is "mint a fresh install"; naming a
#: code is "hand me the file for this install I already have" - the reissue lane
#: (#6695 PR-4), which must not leave a second pending code behind.
_INSTALL_BODY_KEYS = (frozenset(), frozenset({"code"}), frozenset({"code", "install_token"}))


async def _install_artifact(
    request: Request, *, store: Any, user_id: str,
) -> tuple[dict[str, Any], JSONResponse] | None:
    """The code, tag and token one download should embed, or the refusal.

    Returns ``None`` and writes nothing when the body is not one of the accepted
    shapes; otherwise the tuple carries either the freshly minted install or the
    peeked facts of an existing pending code. The body's `install_token` is only
    ever the value the browser just received from issue/reissue - the store
    validates it again at claim time, so a wrong value here costs the owner a
    refused claim, never a link.
    """
    body = await _body(request)
    if body is None or frozenset(body) not in _INSTALL_BODY_KEYS:
        return None
    if not body:
        issued, refused = await _await_store(
            store.issue_code, user_id=user_id, issued_at=_now(),
        )
        if refused is not None:
            return issued, refused
        return {
            "code_id": issued["code_id"],
            "install_tag": issued["install_tag"],
            "install_token": issued["install_token"],
        }, None
    code = body.get("code")
    if not isinstance(code, str) or not code:
        return None
    peeked, refused = await _await_store(store.peek_pairing_code, code=code, now=_now())
    if refused is not None:
        return peeked, refused
    token = body.get("install_token")
    if token is not None and (
        not isinstance(token, str) or _INSTALL_TOKEN_RE.fullmatch(token) is None
    ):
        return None
    return {
        "code_id": peeked["code_id"],
        "install_tag": peeked["install_tag"],
        "install_token": token,
    }, None


def _install_headers(filename: str, code_id: str) -> dict[str, str]:
    # The browser needs to know which install it just downloaded so the owner
    # can cancel or replace exactly that one. A code id is not a possession
    # proof; the code and token themselves never ride in a header.
    return {
        **_NO_STORE,
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-PC-Pairing-Code-Id": code_id,
    }


async def pc_pairing_install_file(request: Request) -> Response:
    """One click: the install file that binds this PC to the signed-in account.

    Session-authenticated and owner-scoped like the rest of this surface: the
    account is the verified session's user id, a fresh 10-minute code is issued
    for it, and what comes back is the file the PC runs. The code itself never
    leaves the server - only the tag derived from it, which is what the agent
    name carries back for the claim to complete. Nothing here consumes the code,
    so a download that dies halfway can be clicked again.

    #6695 PR-4: the same endpoint renders the file for an install the owner
    already has, when the body names its code. That is the reissue lane's
    second half, and it keeps one install - one code, one token - per download.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    # Read the deployment's link before minting anything: a click on a
    # deployment that cannot name a download must not leave a code behind that
    # nothing can ever hand out.
    agent_url = install_url_from_config(
        getattr(request.app.state, "pc_pairing_install_url", None),
    )
    if agent_url is None:
        return _error(503, "pc_pairing_install_url_missing")
    facts = await _install_artifact(request, store=store, user_id=user_id)
    if facts is None:
        return _error(400, "pc_pairing_body_invalid")
    issued, refused = facts
    if refused is not None:
        return refused
    token = issued.get("install_token")
    rendered_url = (
        personalized_install_url(agent_url=agent_url, install_token=token)
        if token is not None else agent_url
    )
    helper = user_helper_config(
        getattr(request.app.state, "pc_pairing_user_helper_url", None),
        getattr(request.app.state, "pc_pairing_user_helper_sha256", None),
    )
    script = render_install_script(
        install_tag=issued["install_tag"], agent_url=rendered_url, install_token=token,
        user_helper_url=helper[0] if helper is not None else None,
        user_helper_sha256=helper[1] if helper is not None else None,
    )
    if script is None:
        return _error(503, "pc_pairing_install_url_missing")
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers=_install_headers(PC_PAIRING_INSTALL_FILENAME, issued["code_id"]),
    )


async def pc_pairing_install_exe(request: Request) -> Response:
    """One double-click: this PC joins the signed-in account, no shell involved.

    The same lane as the install file above, in the shape a person who does not
    know what PowerShell is can use: the browser downloads one file, they run it,
    and it asks Windows for administrator approval itself. Session-authenticated and
    owner-scoped exactly the same way, and it mints a fresh code the same way, so a
    file that dies halfway can be clicked again - the code is never consumed here.

    Refused rather than improvised when the reviewed program is not in this build:
    the bytes a PC runs as a service have to be the bytes the build verified, and a
    substitute is not a smaller version of the same answer.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    agent_url = install_url_from_config(
        getattr(request.app.state, "pc_pairing_install_url", None),
    )
    if agent_url is None:
        return _error(503, "pc_pairing_install_url_missing")
    # Read the artifact before minting anything: a click on a build that cannot
    # hand out the program must not leave a code behind that nothing can redeem.
    try:
        connect_exe_bytes()
    except ValueError:
        return _error(503, "pc_pairing_connect_exe_unavailable")
    facts = await _install_artifact(request, store=store, user_id=user_id)
    if facts is None:
        return _error(400, "pc_pairing_body_invalid")
    issued, refused = facts
    if refused is not None:
        return refused
    # The reviewed program stamps only the tag into the agent name, so the
    # token rides in the URL it downloads from: same account-specific link the
    # issue response hands out, with the MeshCentral arguments left intact.
    token = issued.get("install_token")
    rendered_url = (
        personalized_install_url(agent_url=agent_url, install_token=token)
        if token is not None else agent_url
    )
    helper = user_helper_config(
        getattr(request.app.state, "pc_pairing_user_helper_url", None),
        getattr(request.app.state, "pc_pairing_user_helper_sha256", None),
    )
    program = render_install_exe(
        install_tag=issued["install_tag"], agent_url=rendered_url,
        user_helper_url=helper[0] if helper is not None else None,
        user_helper_sha256=helper[1] if helper is not None else None,
    )
    if program is None:
        return _error(503, "pc_pairing_connect_exe_unavailable")
    return Response(
        content=program,
        media_type="application/octet-stream",
        headers=_install_headers(PC_PAIRING_INSTALL_EXE_FILENAME, issued["code_id"]),
    )


async def pc_pairing_claim(request: Request) -> JSONResponse:
    """One PC redeems the code it was given (R2, R3).

    No session, no device credential, nothing to log in with on the PC: the code
    is the whole proof, and it is consumed exactly once. `mesh_node_id` is the
    composed MeshCentral identity the installing agent already knows for itself,
    validated against the same grammar every other PC boundary uses.

    `drives` is the installing PC's own list of fixed local drives. The Owner's
    default scope is a whole drive, so a fresh link starts granted. Only drive
    roots are accepted from this call - a PC may say which drives it has, it may
    not name folders through the channel that has no owner approval behind it.
    """
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    # #6695 PR-4 adds one optional member to the same claim: `install_token`,
    # the value the install URL carried. It is checked against the code's own
    # binding in the store; a claim without it keeps working for an install
    # whose token still stands, including codes minted before tokens existed.
    required = {"code", "mesh_node_id"}
    allowed = required | {"label", "drives", "install_token"}
    if body is None or not required <= set(body) or not set(body) <= allowed:
        return _error(400, "pc_pairing_body_invalid")
    code = body.get("code")
    mesh_node_id = body.get("mesh_node_id")
    label = body.get("label")
    if not isinstance(code, str) or not code or not isinstance(mesh_node_id, str):
        return _error(400, "pc_pairing_body_invalid")
    if label is not None and not isinstance(label, str):
        return _error(400, "pc_pairing_body_invalid")
    install_token = body.get("install_token")
    if install_token is not None and not isinstance(install_token, str):
        return _error(400, "pc_pairing_body_invalid")
    reported = body.get("drives")
    drives: list[str] = []
    if reported is not None:
        if not isinstance(reported, list) or len(reported) > 26:
            return _error(400, "pc_pairing_body_invalid")
        for entry in reported:
            single = drive_root(entry)
            if single is None:
                return _error(400, "pc_pairing_body_invalid")
            if single not in drives:
                drives.append(single)
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
        now=_now(), verified=verified, drives=drives, install_token=install_token,
    )
    if refused is not None:
        return refused
    # #6460: the account just gained a PC; its cached connector scope is stale.
    if link.get("_superseded_mesh_node_ids"):
        from .claw_pc_device_selection_store import sync_superseded_device_selections

        selection_store = getattr(
            request.app.state, "claw_pc_device_selection_store", None,
        )
        try:
            selection_synced = await sync_superseded_device_selections(
                selection_store, link=link, now=_now(),
            )
        except Exception as selection_exc:
            selection_synced = False
            logging.getLogger(__name__).warning(
                "pc_pairing_selection=failed reason=%s",
                type(selection_exc).__name__,
            )
        if not selection_synced:
            logging.getLogger(__name__).warning(
                "pc_pairing_selection=replacement_not_confirmed",
            )
    drop_cached_owner_scope_of(request, link.get("user_id"))
    invalidate_owner_scope(link.get("user_id"))
    granted = [root for root in link["roots"] if root["state"] == "active"]
    return _json({
        "ok": True,
        "link": {
            "link_id": link["link_id"],
            "mesh_node_id": link["mesh_node_id"],
            "state": link["state"],
            "roots": [{"label": root["label"]} for root in granted],
        },
        # A link whose drive query failed is said out loud. Silently empty would
        # read as "this PC has no drives", which is the wrong thing to tell an
        # owner who then finds nothing to click.
        "drives_status": "seeded" if granted else (
            "lookup_failed" if not drives else "not_applied"
        ),
    }, 201 if link["state"] == "active" else 202)


async def pc_pairing_adopt(request: Request) -> JSONResponse:
    """Adopt a real PC onto the account the administrator names (PR-4e).

    The Owner installs the agent on a customer's machine and then attaches that
    machine to the customer's own account, so the account is a parameter rather
    than always the caller: `target` names it by the id this deployment already
    uses or by the address that account signs in with, and no `target` means the
    caller's account exactly as before. Only a platform administrator may call
    this, and that guard still runs before anything is read, so a refused call
    learns nothing about which devices exist.

    The device is verified against what the Mesh lane actually reported —
    `mesh_device_presence`, written by the executor's own receipts — instead of a
    deployment ownership map an operator had to edit first. A PC whose executor
    has been seen can be adopted; a device that never reported one cannot be
    adopted into existence.

    The scope is #5981's default: the whole fixed drives the PC itself reported,
    read back from any link that already names this node, plus any the caller
    names on this call. Adoption stays idempotent — the same target account and
    the same device return the same link — and one machine may serve several
    accounts, because the table is keyed by the pair.
    """
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "unauthorized")
    store = _store(request)
    if store is None:
        return _error(503, "pc_pairing_unavailable")
    body = await _body(request)
    if body is None or frozenset(body) not in _ADOPT_BODY_KEYS:
        return _error(400, "pc_pairing_body_invalid")
    device_id = body.get("device_id")
    if not isinstance(device_id, str) or not device_id:
        return _error(400, "pc_pairing_body_invalid")
    target = body.get("target")
    if target is not None and (not isinstance(target, str) or not target.strip()):
        return _error(400, "pc_pairing_body_invalid")
    reported = body.get("drives")
    drives: list[str] = []
    if reported is not None:
        if not isinstance(reported, list) or len(reported) > 26:
            return _error(400, "pc_pairing_body_invalid")
        for entry in reported:
            single = drive_root(entry)
            if single is None:
                return _error(400, "pc_pairing_body_invalid")
            if single not in drives:
                drives.append(single)
    from .platform_admin_authority import platform_authority_for
    authority = platform_authority_for(request)
    try:
        admin = await authority.is_global_model_admin(user_id=user_id)
    except Exception:
        admin = False
    if admin is not True:
        return _error(403, "pc_pairing_not_admin")
    account_id = user_id
    if target is not None:
        resolved, refused = await _await_store(store.resolve_account_ref, target=target)
        if refused is not None:
            return refused
        if not resolved:
            return _error(404, "pc_pairing_target_unknown")
        account_id = resolved
    presence = getattr(request.app.state, "mesh_device_presence_store", None)
    if presence is None or not callable(getattr(presence, "load", None)):
        # No receipt port is a deployment that cannot answer the question, not a
        # device that failed it.
        return _error(503, "pc_pairing_unavailable")
    try:
        record = presence.load(device_id=device_id)
        if inspect.isawaitable(record):
            record = await record
    except Exception:
        return _error(503, "pc_pairing_unavailable")
    if not isinstance(record, dict) or not record.get("device_id"):
        return _error(404, "pc_pairing_device_unseen")
    known, refused = await _await_store(store.drive_roots_for_node, mesh_node_id=device_id)
    if refused is not None:
        return refused
    for single in known or []:
        if single not in drives:
            drives.append(single)
    if not drives:
        # Nothing is grantable: the PC exists but has never reported the drives
        # #5981 made the default scope, and this call named none. Adopting it
        # would create a link the account cannot use.
        return _error(404, "pc_pairing_device_unscoped")
    adopted, refused = await _await_store(
        store.adopt_link, user_id=account_id, mesh_node_id=device_id,
        root_paths=[], now=_now(), drives=drives,
    )
    if refused is not None:
        return refused
    # #6460: adoption attaches a PC to the target account, so that account's
    # cached connector scope is dropped too (the caller's stays valid).
    drop_cached_owner_scope_of(request, account_id)
    invalidate_owner_scope(account_id)
    granted = [root for root in adopted["roots"] if root["state"] == "active"]
    return _json({
        "ok": True,
        "link": {
            "link_id": adopted["link_id"],
            "mesh_node_id": adopted["mesh_node_id"],
            "user_id": adopted["user_id"],
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
                for root in granted
            ],
            "created_at": adopted["created_at"],
            "updated_at": adopted["updated_at"],
        },
        # Same vocabulary as the claim: an adopted link that carries no drive was
        # not given the Owner's default scope, and that has to be visible rather
        # than looking like a PC with no drives. Adoption cannot report
        # `lookup_failed`: it refuses before it gets here when no drive is known.
        "drives_status": (
            "seeded" if any(drive_root(root["path"]) is not None for root in granted)
            else "not_applied"
        ),
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
    drop_cached_owner_scope_of(request, user_id)
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
    drop_cached_owner_scope_of(request, user_id)
    return _json({"ok": True, "revoked": True}, 200)


__all__ = [
    "PC_PAIRING_CLAIM_PATH",
    "PC_PAIRING_ADOPT_PATH",
    "PC_PAIRING_HANDOFF_PATH",
    "PC_PAIRING_INSTALL_FILE_PATH",
    "PC_PAIRING_INSTALL_FILENAME",
    "PC_PAIRING_INSTALL_EXE_FILENAME",
    "PC_PAIRING_INSTALL_EXE_PATH",
    "PC_PAIRING_LABEL_PATH",
    "PC_PAIRING_LINK_PATH",
    "PC_PAIRING_PATH",
    "PC_PAIRING_ROOTS_PATH",
    "PC_PAIRING_ROOT_PATH",
    "pc_pairing_approve_root",
    "pc_pairing_claim",
    "pc_pairing_handoff",
    "pc_pairing_adopt",
    "pc_pairing_install_file",
    "pc_pairing_install_exe",
    "connect_exe_trailer",
    "render_install_exe",
    "install_url_from_config",
    "render_install_script",
    "pc_pairing_issue",
    "pc_pairing_label",
    "pc_pairing_list",
    "pc_pairing_revoke",
    "pc_pairing_revoke_root",
]
