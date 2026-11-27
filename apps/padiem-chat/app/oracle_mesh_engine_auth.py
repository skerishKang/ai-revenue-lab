"""Engine proof, owner and target verification."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse
from padiem_ai_core.pc_device_identity import is_pc_device_id
from .connector_account_shadow import mode_connector_read
from .oracle_mesh_contract import EXECUTION_MODE_MESH
from .oracle_mesh_http import _error
from .oracle_mesh_pc_paths import _pc_files_roots_of_map_row
from .oracle_mesh_source import valid_claw_engine_desktop_secret
from .request_telemetry import emit_stage_event


async def _verify_engine_proof(
    request: Request, *, max_body_bytes: int | None = 8192,
) -> tuple[bytes | None, JSONResponse | None]:
    """Shared Engine proof check for the signed Mesh lanes (Claw and Chat).

    The deployment-owned Engine proof secret authenticates the Engine caller;
    browser cookies never act as proof. Returns the raw body or a ready-made
    error response. Both product lanes use this exact check.
    """
    import hmac
    import hashlib
    import time

    secret = valid_claw_engine_desktop_secret(
        getattr(request.app.state, "claw_engine_desktop_secret", None)
    )
    if secret is None:
        return None, _error(503, "claw_engine_desktop_unconfigured")
    raw = await request.body()
    if max_body_bytes is not None and len(raw) > max_body_bytes:
        return None, _error(413, "claw_engine_desktop_invalid_body")
    timestamp = request.headers.get("X-Claw-Engine-Time", "")
    signature = request.headers.get("X-Claw-Engine-Proof", "")
    try:
        seconds = int(timestamp)
    except (ValueError, TypeError):
        return None, _error(401, "claw_engine_proof_required")
    if abs(int(time.time()) - seconds) > 60 or not isinstance(signature, str) or len(signature) != 64:
        return None, _error(401, "claw_engine_proof_required")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None, _error(401, "claw_engine_proof_required")
    return raw, None


# ---------------------------------------------------------------------------
# #5015/#4976 — structured PC file tools (list/read) on the existing Mesh
# lane.
#
# The Engine's model-selected list_files/read_file tools send a structured op
# and a path relative to the approved folder; they never send a shell command.
# This server derives the approved root from the deployment ownership row's
# mapped file, rejects traversal/absolute paths, and then:
#
# * list stays on the existing kind="command" PowerShell lane, and
# * read reuses the existing kind="read" MeshCentral download lane
#   (``meshctrl.js download``), whose result bytes are already verified,
#   pinned, stored and retrievable through the command result modes.
#
# The read dispatch carries the server-computed per-call bound so the executor
# cannot be told to accept more than the PC file contract allows.
# ---------------------------------------------------------------------------

_ENGINE_PC_FILES_SCOPE_OPS = {
    # A name search is a listing that filters; a content search reads the same
    # files a `files` grant may already read, one match line at a time.
    "files_list": ["list", "search_name"],
    "files": ["list", "read", "search_name", "search_content"],
    "files_write": ["write", "edit", "move", "delete", "mkdir"],
    "query_drives": ["drives"], "none": [],
    "files_search": ["search_name"],
    "files_search_contents": ["search_content"],
    "files_chunk": [],
}


def _engine_pc_scope_claim(request: Request, raw: bytes, *, product: str):
    """Authenticate the optional ceiling without widening the legacy body."""
    import hmac
    encoded = request.headers.get("X-Claw-PC-Scope")
    proof = request.headers.get("X-Claw-PC-Scope-Proof")
    if encoded is None and proof is None:
        return None, None  # Old Engine compatibility; existing auth still runs.
    if not isinstance(encoded, str) or len(encoded) > 1024 or not isinstance(proof, str):
        return None, _error(401, "pc_scope_proof_invalid")
    secret = getattr(request.app.state, "claw_engine_desktop_secret", "")
    timestamp = request.headers.get("X-Claw-Engine-Time", "")
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw + b"." + encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(proof, expected):
        return None, _error(401, "pc_scope_proof_invalid")
    try:
        claim = json.loads(encoded)
    except (ValueError, TypeError):
        return None, _error(422, "pc_scope_claim_invalid")
    scopes = _ENGINE_PC_FILES_SCOPE_OPS
    if (
        not isinstance(claim, dict)
        or set(claim) != {"version", "requested", "admitted", "source", "ops", "app_id"}
        or type(claim["version"]) is not int or claim["version"] != 1
        or not isinstance(claim["requested"], str) or claim["requested"] not in scopes
        or not isinstance(claim["admitted"], str) or claim["admitted"] not in scopes
        # The ops list is a ceiling, not an inventory: a claim produced by an
        # Engine that predates a capability still names a real subset of the
        # admitted scope, and the dispatch below refuses any op it did not
        # name. Requiring the full list would fail every file call during a
        # rolling deploy whose Chat side shipped one capability earlier.
        or not set(claim["ops"]).issubset(scopes[claim["admitted"]])
        or not set(claim["ops"]).issubset(scopes[claim["requested"]])
        or len(set(claim["ops"])) != len(claim["ops"])
        or claim["source"] not in ("declared", "decision", "missing")
        or claim["source"] not in ("declared", "decision", "missing")
        or claim["app_id"] != ("padiem-chat" if product == "chat" else "b54-padiem-claw")
    ):
        return None, _error(422, "pc_scope_claim_invalid")
    return claim, None
async def _engine_pc_files_owner(
    request: Request, *, product: str, subject_id: str,
) -> tuple[str | None, Any, JSONResponse | None]:
    """Resolve the product's current canonical owner session from the proof.

    The Engine proof authenticates the caller; the canonical session is still
    re-resolved here exactly like the existing signed Mesh lanes. No browser
    cookie, subject value or device value is trusted as authority.
    """
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_product_user_for_subject", None)):
        return None, None, _error(503, "claw_engine_identity_unavailable")
    try:
        uid = await identity.resolve_product_user_for_subject(
            product_id="b62", canonical_subject_id=subject_id,
        )
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    if product == "claw":
        from padiem_control_plane.b54_identity_bridge import (
            resolve_current_b54_canonical_session as resolve_b54_session,
        )
        try:
            bridged = await resolve_b54_session(identity, uid)
        except Exception:
            return None, None, _error(401, "canonical_session_required")
        if (
            bridged is None
            or bridged.auth_session.subject.subject_id != subject_id
            or not bridged.auth_session.tenant_id
        ):
            return None, None, _error(401, "canonical_session_required")
        return uid, bridged.auth_session, None
    if not callable(getattr(identity, "resolve_current_auth_session", None)):
        return None, None, _error(503, "claw_engine_identity_unavailable")
    try:
        session = await identity.resolve_current_auth_session(
            product_id="b62", product_user_id=uid,
        )
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    if (
        session is None
        or session.subject.subject_id != subject_id
        or session.product_id != "b62"
        or not session.is_active(now=_dt.now(_tz.utc))
        or not session.tenant_id
    ):
        return None, None, _error(401, "canonical_session_required")
    # The product identity above is b62; the connector owner scope is the
    # shared B54 canonical session (#5088). Resolve the same bridge the Claw
    # signed lane uses instead of handing the b62 product session to the
    # owner-scope lookup.
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session as resolve_b54_session,
    )
    try:
        bridged = await resolve_b54_session(identity, uid)
    except Exception:
        return None, None, _error(401, "canonical_session_required")
    if (
        bridged is None
        or bridged.auth_session.subject.subject_id != subject_id
        or not bridged.auth_session.tenant_id
    ):
        return None, None, _error(401, "canonical_session_required")
    return uid, bridged.auth_session, None


#: The pairing directory could not be consulted at all, so the deployment map
#: decides. Distinct from the directory answering "this account has no PC",
#: which is a real answer and must never widen back to the map.
_DIRECTORY_UNUSABLE = "directory_unusable"


async def _pc_files_directory_target(
    request: Request, *, user_id: str, selected_device_id: str | None,
) -> tuple[str, dict[str, Any] | None]:
    """The owner's own linked PC, from migration 072's link table.

    R4's directory-first rule. A deployment with no pairing store, or one whose
    072 tables are not applied yet, falls through to the ownership map so it
    behaves exactly as before; an account the directory answered for is bounded
    by what it answered. Ambiguity stays a refusal, never a guess.
    """
    store = getattr(request.app.state, "pc_device_pairing_store", None)
    if not callable(getattr(store, "links_for_owner", None)):
        return _DIRECTORY_UNUSABLE, None
    try:
        links = await store.links_for_owner(user_id=user_id)
    except Exception:
        return _DIRECTORY_UNUSABLE, None
    if not isinstance(links, list):
        return _DIRECTORY_UNUSABLE, None
    if not links:
        return "empty", None
    matches = [
        link for link in links
        if isinstance(link, dict)
        and (
            selected_device_id is None
            or link.get("mesh_node_id") == selected_device_id
        )
    ]
    if len(matches) != 1:
        return "ambiguous", None
    link = matches[0]
    node_ref = link.get("mesh_node_id")
    roots = link.get("roots")
    if (
        not isinstance(node_ref, str) or not is_pc_device_id(node_ref)
        or not isinstance(roots, list) or not roots
    ):
        # A linked PC with no approved folder cannot answer a file call, and a
        # link that is not active never reaches here.
        return "unapproved", None
    return "link", {
        "node_ref": node_ref,
        # The link's composed node identity is the canonical device identity,
        # the same rule an unpinned ownership row already follows.
        "device_id": node_ref,
        "link_id": link.get("link_id"),
        "label": link.get("label"),
        "roots": roots,
    }


async def _engine_pc_files_target(
    request: Request, *, session: Any, selected_device_id: str | None, user_id: str,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Resolve the one owner target and the folders it may read.

    The context and the dispatch use this exact resolution, so the device the
    model is told about and the device that receives the command cannot drift
    apart. A selected device only narrows the choice; it never adds one. The
    account's own PC links decide first; the deployment ownership map is the
    fallback for a deployment that has no directory to ask.
    """
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if (
        source is None
        or getattr(source, "configured", False) is not True
        or getattr(source, "execution_mode", None) != EXECUTION_MODE_MESH
    ):
        return None, _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await mode_connector_read(
            identity, "owner_scope", session_id=session.session_id,
        )
    except Exception as exc:
        emit_stage_event(
            stage="mesh.files_owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    workspace_ref = scope.get("workspace_ref") if isinstance(scope, dict) else None
    if (
        not isinstance(account_ref, str) or not account_ref
        or not isinstance(workspace_ref, str) or not workspace_ref
    ):
        return None, _error(503, "oracle_mesh_device_directory_unavailable")

    kind, linked = await _pc_files_directory_target(
        request, user_id=user_id, selected_device_id=selected_device_id,
    )
    if kind == "link":
        node_ref = linked["node_ref"]
        # The link decides which PC and which folders. What the Mesh client is
        # run against stays the deployment's own answer: a row that names this
        # device supplies the reference it already used, so an adopted identity
        # can never become a command sent to a node nobody listens to. A PC the
        # map does not name at all keeps the node it reported for itself.
        address_of = getattr(source, "mesh_node_ref_for_device", None)
        addressed = address_of(device_id=node_ref) if callable(address_of) else None
        if addressed is not None and addressed != node_ref:
            linked = {**linked, "node_ref": addressed}
        return {
            "authorized": True,
            "target": linked,
            "roots": linked["roots"],
            "account_ref": account_ref,
            "workspace_ref": workspace_ref,
        }, None
    # No answer from the directory is NOT an error here. #5906 made "this
    # account has no linked PC" a 403, and an ordinary chat turn that only asked
    # what tools exist then read as a failure. Context answers 200 with no roots
    # and no PC tools; only a call that actually needs a PC refuses.
    # #6695 PR-3: this transitional fallback ends with the same operating
    # switch that retires the TXT map lane. ``ORACLE_MESH_LEGACY_MAP_LANE=off``
    # leaves the ownership link as the only authority here — a directory answer
    # of "no usable link" then refuses instead of falling to the map, and a
    # directory that could not answer at all fails closed. Default (unset)
    # keeps today's behaviour: the two production PCs still run link-less.
    if not getattr(request.app.state, "oracle_mesh_legacy_map_lane", True):
        if kind == _DIRECTORY_UNUSABLE:
            return None, _error(503, "oracle_mesh_device_directory_unavailable")
        return None, None
    try:
        target = source.command_target(
            account_ref=account_ref, device_id=selected_device_id,
        )
    except Exception:
        if kind == _DIRECTORY_UNUSABLE:
            return None, _error(503, "oracle_mesh_device_directory_unavailable")
        return None, None
    if target is None:
        return None, None
    roots = _pc_files_roots_of_map_row(target.get("file_path"))
    if not roots:
        return None, _error(503, "oracle_mesh_file_root_unavailable")
    # #5573: transitional fallback — the map answers only while the lane
    # switch above still allows it, and it retires with that switch once the
    # production devices carry their ownership links.
    return {
        "authorized": True,
        "target": target,
        "roots": roots,
        "account_ref": account_ref,
        "workspace_ref": workspace_ref,
    }, None
