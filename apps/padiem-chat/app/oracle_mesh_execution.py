"""Owner-scoped selection of the ordinary TXT execution lane."""
from __future__ import annotations

from typing import Any
from starlette.requests import Request
from starlette.responses import JSONResponse

from .claw_connector_enrollment_routes import _verified_owner_request
from .connector_account_shadow import mode_connector_read
from .control_plane_identity import IdentityBridgeError
from .oracle_mesh_contract import EXECUTION_MODE_OFF, EXECUTION_MODE_NATIVE
from .oracle_mesh_http import _error
from .request_telemetry import emit_stage_event


async def resolve_oracle_mesh_execution(
    request: Request, *, path_relative: str, selected_device_id: str | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Decide whether one ordinary TXT request runs on the Mesh lane.

    Returns ``(target, None)`` when the request should execute on the
    management host, ``(None, None)`` when it must stay on the native lane, and
    ``(None, response)`` for a refusal that the caller must surface.

    Order matters: the ownership decision comes from the deployment map, so an
    unregistered PC is never filtered out by the native device directory first.
    Consent, consent withdrawal and the OFF switch are still enforced here —
    only the *native binding* requirement is dropped, never the checks.
    """

    if not getattr(request.app.state, "oracle_mesh_legacy_map_lane", True):
        # Retired on purpose: this request names a file for the deployment map, which
        # is no longer an authority. Tell the owner where the working path is instead
        # of a 403 that says "not yours" about a file that is theirs.
        return None, _error(
            409, "oracle_mesh_map_lane_retired",
            "이 방식은 더 이상 쓰지 않아요 — 내 컴퓨터 연결에서 폴더를 고르세요.",
        )
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if getattr(source, "configured", False) is not True:
        return None, None
    mode = source.execution_mode
    if mode == EXECUTION_MODE_OFF:
        return None, None
    if mode == EXECUTION_MODE_NATIVE:
        return None, None

    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "canonical_session_required")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
    except Exception as exc:
        # #4139: this is the only place the canonical owner-scope refusal is
        # observed. The public projection is one fixed code, so the Identity
        # code is retained on the existing bounded stage-telemetry channel
        # (code + stage + request-scoped id only; build_stage_event sanitizes
        # the value and never carries a message).
        emit_stage_event(
            stage="mesh.owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    if not isinstance(account_ref, str) or not account_ref:
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    disposition = source.classify(account_ref=account_ref, path_relative=path_relative)
    if disposition == "none":
        # The deployment maps no Mesh target for this file: the request keeps
        # the native lane rather than silently executing somewhere else.
        return None, None
    if disposition == "foreign":
        # The file IS mapped, but only to other accounts. That is a hard
        # ownership refusal, never a lane fallback.
        return None, _error(403, "oracle_mesh_ownership_unverified")
    # Consent withdrawal is enforced HERE, before a run is staged: an owner
    # who withdrew the connector consent must be refused up front. Absence of
    # a consent record is not a precondition on this lane (no native
    # enrollment is required); a backend failure still fails closed.
    if callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        try:
            consent = await mode_connector_read(
                identity, "consent",
                session_id=session.session_id,
                device_id=source.device_hint_for(
                    account_ref=account_ref, path_relative=path_relative,
                    selected_device_id=selected_device_id,
                ),
            )
        except IdentityBridgeError as exc:
            if getattr(exc, "code", None) != "enrollment_consent_required":
                return None, _error(503, "oracle_mesh_unconfigured")
        except Exception:
            return None, _error(503, "oracle_mesh_unconfigured")
        else:
            if isinstance(consent, dict) and consent.get("withdrawn_at") is not None:
                return None, _error(403, "oracle_mesh_consent_required")
    target = source.target_for(
        account_ref=account_ref, path_relative=path_relative,
        device_id=selected_device_id,
    )
    if target is None:
        return None, _error(403, "oracle_mesh_ownership_unverified")
    return {
        "device_id": target.get("device_id") or target["node_ref"],
        "root_ref": target["root_ref"],
        "path_relative": target["path_relative"],
        "account_ref": account_ref,
    }, None
