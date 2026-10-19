"""#5080 — owner-confirmed Android SAF TXT read trigger.

This is the Android lane's intake. It reuses the exact authority order of the
Windows TXT trigger, with one Android-specific substitution: the folder comes
from the SAF set the phone declared through the canonical Broker, never from
the browser.

```text
verified B54 session + CSRF
 -> memory workspace (Claw tenant realm)
 -> Identity enrollment consent for this device
 -> Identity connector workspace (must equal the consent's workspace)
 -> canonical Broker device binding (revoked/expired refused)
 -> stored conversation run (owner + memory workspace)
 -> Android SAF profile (server-verified, active credential generation)
 -> requested root_ref must be one of the phone's declared folders
 -> mint closed Android approval receipt
 -> atomic enqueue_command_with_material
 -> pre-write the return-leg correlation
```

The browser may name a device, a declared folder reference and a relative
``.txt`` path inside it. It cannot supply an account, workspace, binding,
credential, conversation, command, approval or folder outside the declared
set. The result returns to the conversation on the stored run row through the
existing projection; no new destination authority exists.

A phone that is offline is still a legitimate queue target: the command stays
in the canonical Broker until it is admitted or expires. That is exactly the
existing exactly-once contract, and the terminal projection reports an expired
command truthfully instead of inventing a failure.
"""
from __future__ import annotations

import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .connector_android_saf_approval_material import (
    ANDROID_TXT_PROFILE_REF,
    AndroidOwnerTxtApprovalProof,
    AndroidTxtApprovalMaterialError,
    mint_android_txt_read_receipt,
)
from .control_plane_identity import IdentityBridgeError
from .history import HistoryError, HistoryForbidden

CONNECTOR_ANDROID_READ_REQUEST_PATH = "/api/claw/connector/android-text-reads/request"
CONNECTOR_ANDROID_FOLDERS_PATH = "/api/claw/connector/android-text-reads/folders"
_MAX_BODY_BYTES = 4096
_BODY_KEYS = frozenset({"device_id", "root_ref", "path_relative", "run_id", "confirmed"})
_DEVICE_ID_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$"

_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_CAPABILITIES = ["local.filesystem.read"]


def _response(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(dict(payload), status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _response({"ok": False, "error": {"code": code}}, status)


def _read_body(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if type(value) is not dict or set(value) != _BODY_KEYS:
        return None
    for key in ("device_id", "root_ref", "path_relative", "run_id"):
        item = value.get(key)
        if not isinstance(item, str) or not item or len(item) > 1024:
            return None
    if value.get("confirmed") is not True:
        return None
    return value


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _valid_profile(profile: Any) -> dict[str, Any] | None:
    """Closed projection of the Broker's Android profile answer."""
    if not isinstance(profile, dict):
        return None
    folders = profile.get("folders")
    if (
        profile.get("profile_ref") != ANDROID_TXT_PROFILE_REF
        or profile.get("platform") != "android"
        or profile.get("capabilities") != _CAPABILITIES
        or profile.get("read_suffix") != ".txt"
        or not isinstance(folders, list)
        or len(folders) > 8
    ):
        return None
    seen: set[str] = set()
    safe_folders: list[dict[str, str]] = []
    for item in folders:
        if not isinstance(item, dict) or set(item) != {"root_ref", "display_name"}:
            return None
        root_ref, display_name = item["root_ref"], item["display_name"]
        if (
            not isinstance(root_ref, str) or not root_ref or len(root_ref) > 256
            or root_ref in seen
            or not isinstance(display_name, str) or not 1 <= len(display_name) <= 80
            or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
        ):
            return None
        seen.add(root_ref)
        safe_folders.append({"root_ref": root_ref, "display_name": display_name})
    return {"folders": safe_folders}


async def _resolve_android_scope(
    request: Request, *, device_id: str,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Every server authority the Android lane needs before any write."""
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "android_read_auth_required")
    uid = current_user_id(request)
    if not uid:
        return None, _error(401, "android_read_auth_required")
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return None, _error(503, "android_read_workspace_unavailable")
    if not workspace_id:
        return None, _error(503, "android_read_workspace_unavailable")

    source = getattr(request.app.state, "connector_txt_read_source", None)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if (
        getattr(source, "configured", False) is not True
        or not callable(getattr(source, "resolve_device_binding", None))
        or not callable(getattr(source, "resolve_android_saf_profile", None))
        or not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None))
        or not callable(getattr(identity, "resolve_connector_workspace", None))
    ):
        return None, _error(503, "android_read_unconfigured")

    try:
        consent = await _await(identity.resolve_connector_enrollment_consent_for_device(
            session_id=session.session_id, device_id=device_id,
        ))
    except Exception:
        return None, _error(403, "android_read_consent_required")
    if (
        not isinstance(consent, dict)
        or consent.get("device_id") != device_id
        or not isinstance(consent.get("account_ref"), str)
        or not consent["account_ref"]
        or not isinstance(consent.get("workspace_ref"), str)
        or not consent["workspace_ref"]
        or consent.get("withdrawn_at") is not None
    ):
        return None, _error(403, "android_read_consent_required")
    try:
        connector_workspace = await _await(identity.resolve_connector_workspace(
            session_id=session.session_id,
        ))
    except Exception:
        return None, _error(503, "android_read_unconfigured")
    if connector_workspace != consent["workspace_ref"]:
        return None, _error(403, "android_read_consent_required")

    try:
        device = await _await(source.resolve_device_binding(
            account_ref=consent["account_ref"],
            workspace_ref=consent["workspace_ref"],
            device_id=device_id,
        ))
    except IdentityBridgeError as exc:
        status = exc.status_code if isinstance(exc.status_code, int) else 503
        if status == 404:
            return None, _error(404, "android_read_device_unbound")
        if status == 403:
            return None, _error(403, "android_read_device_not_usable")
        return None, _error(503, "android_read_broker_unavailable")
    except Exception:
        return None, _error(503, "android_read_broker_unavailable")
    if (
        not isinstance(device, dict)
        or not isinstance(device.get("binding_ref"), str)
        or not device["binding_ref"]
        or not isinstance(device.get("credential_generation"), int)
    ):
        return None, _error(503, "android_read_broker_unavailable")

    try:
        profile = await _await(source.resolve_android_saf_profile(
            account_ref=consent["account_ref"],
            workspace_ref=consent["workspace_ref"],
            device_id=device_id,
            binding_ref=device["binding_ref"],
        ))
    except IdentityBridgeError:
        return None, _error(409, "android_read_profile_required")
    except Exception:
        return None, _error(503, "android_read_broker_unavailable")
    safe_profile = _valid_profile(profile)
    if safe_profile is None:
        return None, _error(503, "android_read_broker_unavailable")

    return {
        "uid": uid,
        "workspace_id": workspace_id,
        "source": source,
        "account_ref": consent["account_ref"],
        "connector_workspace_ref": consent["workspace_ref"],
        "consent_id": consent["consent_id"],
        "device": device,
        "profile": safe_profile,
    }, None


async def connector_android_folders(request: Request) -> JSONResponse:
    """List the folders this phone declared; never a SAF URI or local path."""
    if set(request.query_params) != {"device_id"}:
        return _error(400, "android_read_device_query_invalid")
    device_id = request.query_params.get("device_id")
    if not isinstance(device_id, str) or not device_id or len(device_id) > 128:
        return _error(400, "android_read_device_query_invalid")
    if re.fullmatch(_DEVICE_ID_PATTERN, device_id) is None:
        return _error(400, "android_read_device_query_invalid")
    scope, denial = await _resolve_android_scope(request, device_id=device_id)
    if denial is not None:
        return denial
    assert scope is not None
    return _response({
        "ok": True,
        "available": True,
        "device": {
            "device_id": device_id,
            "platform": "android",
            "profile_ref": ANDROID_TXT_PROFILE_REF,
            "capabilities": list(_CAPABILITIES),
            "read_suffix": ".txt",
            "folders": scope["profile"]["folders"],
        },
    })


async def connector_android_read_request(request: Request) -> JSONResponse:
    """Approve, mint and enqueue one SAF TXT read; return its correlation."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "android_read_unsupported_media_type")
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
            return _error(413, "android_read_request_too_large")
        raw = await request.body()
        if len(raw) > _MAX_BODY_BYTES:
            return _error(413, "android_read_request_too_large")
    except Exception:
        return _error(400, "android_read_invalid_body")
    wire = _read_body(raw)
    if wire is None:
        return _error(400, "android_read_invalid_body")

    scope, denial = await _resolve_android_scope(request, device_id=wire["device_id"])
    if denial is not None:
        return denial
    assert scope is not None

    declared_roots = {
        folder["root_ref"] for folder in scope["profile"]["folders"]
    }
    if wire["root_ref"] not in declared_roots:
        # A phone without any declared folder has effectively withdrawn SAF
        # access; the UI is told to re-select rather than silently failing.
        return _error(
            409 if not declared_roots else 403,
            "android_read_folder_selection_required"
            if not declared_roots else "android_read_folder_not_allowed",
        )

    history_store = getattr(request.app.state, "history_store", None)
    if (
        not callable(getattr(history_store, "get_claw_run", None))
        or not callable(getattr(history_store, "record_local_task_correlation", None))
    ):
        return _error(503, "android_read_unconfigured")
    try:
        run_row = await _await(history_store.get_claw_run(scope["uid"], wire["run_id"]))
    except Exception:
        return _error(503, "android_read_run_unavailable")
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != wire["run_id"]
        or run_row.get("workspace_id") != scope["workspace_id"]
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "android_read_run_unavailable")

    try:
        proof = AndroidOwnerTxtApprovalProof(
            owner_id=scope["uid"],
            workspace_id=scope["connector_workspace_ref"],
            device_id=wire["device_id"],
            binding_ref=scope["device"]["binding_ref"],
            credential_generation=scope["device"]["credential_generation"],
            consent_id=scope["consent_id"],
            run_id=wire["run_id"],
            profile_ref=ANDROID_TXT_PROFILE_REF,
            root_ref=wire["root_ref"],
            allowed_root_refs=tuple(sorted(declared_roots)),
        )
        issued = mint_android_txt_read_receipt(
            approval=proof, path_relative=wire["path_relative"],
        )
    except AndroidTxtApprovalMaterialError:
        return _error(400, "android_read_refused")

    try:
        receipt = await _await(scope["source"].enqueue_txt_read_command(
            command=issued["enqueue"], material=issued["material"],
        ))
    except IdentityBridgeError:
        return _error(409, "android_read_enqueue_refused")
    except Exception:
        return _error(503, "android_read_broker_unavailable")
    if (
        not isinstance(receipt, dict)
        or receipt.get("command_id") != issued["enqueue"]["command_id"]
        or not isinstance(receipt.get("revision_ref"), str)
        or not receipt["revision_ref"]
    ):
        return _error(503, "android_read_broker_unavailable")

    try:
        await _await(history_store.record_local_task_correlation(
            user_id=scope["uid"],
            run_id=wire["run_id"],
            command_id=issued["enqueue"]["command_id"],
            tool_request_ref=issued["tool_request_ref"],
            request_id=issued["material"]["request_id"],
            revision_ref=receipt["revision_ref"],
            evidence_ref=None,
            request_fingerprint=issued["enqueue"]["request_fingerprint"],
        ))
    except HistoryError as exc:
        if isinstance(exc, HistoryForbidden):
            return _error(503, "android_read_correlation_unavailable")
        return _error(409, "android_read_run_already_bound")
    except Exception:
        return _error(503, "android_read_correlation_unavailable")

    return _response({
        "ok": True,
        "command": {
            "command_id": issued["enqueue"]["command_id"],
            "run_id": wire["run_id"],
            "tool_request_ref": issued["tool_request_ref"],
        },
        "conversation_id": run_row["conversation_id"],
    })


ANDROID_TXT_LANE_REUSES_PC_APPROVAL = True
SECOND_DEVICE_AUTHORITY = False
SECOND_IDENTITY_AUTHORITY = False
SECOND_HISTORY_AUTHORITY = False
BROWSER_SUPPLIED_FOLDER = False
SAF_URI_EXPOSED = False
RAW_PATH_ECHOED = False
