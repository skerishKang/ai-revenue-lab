"""#4139 — owner-confirmed TXT read request trigger (no page, one POST route).

This is the entry point that turns an actual user TXT request into a Broker
command carrying real approval material. It creates no approval by itself:
every material fact comes from an existing server authority. The original
HTTP route retains its closed ``confirmed: true`` wire format; the general Claw
composer derives this field internally from the authenticated owner's actual
TXT READ request (no second confirmation UI).

Order per request (each step server-derived, fail closed):

1. verified owner session (B54 canonical session + CSRF),
2. memory workspace for the owner,
3. active enrollment consent for (session, device) via Identity,
4. owner-scoped device binding via the Broker directory (account/workspace
   from consent, never the browser; revoked/expired refused),
5. existing stored conversation run via history (owner + workspace match;
   the result returns to that row's conversation through the existing
   projection — the browser never chooses the destination),
6. issuance (pure constructor over the verified proof + owner-named intent),
7. atomic ``enqueue_command_with_material`` via the existing Broker binding.

Engine service calls: none. The Engine shared library
(``padiem_ai_core.agent_approval`` object model + digests) shapes the
material, but no Engine RPC, continuation, or deployment is involved; the
owner's explicit confirmation above is the approval act, formalized into
canonical objects. No new login and no duplicate approval procedure.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .connector_txt_approval_material import (
    OwnerTxtApprovalProof,
    TxtApprovalMaterialError,
    mint_txt_read_receipt,
)
from .history import HistoryError, HistoryForbidden
from .control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from .control_plane_identity import IdentityBridgeError

CONNECTOR_TXT_READ_REQUEST_PATH = "/api/claw/connector/text-reads/request"
_MAX_BODY_BYTES = 4096
_BODY_KEYS = frozenset({"device_id", "root_ref", "path_relative", "run_id", "confirmed"})


class UnconfiguredTxtReadSource:
    """Fail-closed until the Worker root composes the trusted source."""

    configured = False


class BrokerTxtReadSource:
    """Trusted broker control surface for TXT reads; no private record escapes.

    Holds the canonical pairing client built from the Worker-owned Service
    Binding. Device resolution and command enqueue go through it; account and
    workspace always originate from Identity consent or the verified session,
    never the browser or the PC.
    """

    configured = True

    def __init__(self, broker_client: Any) -> None:
        if not callable(getattr(broker_client, "owner_device_binding", None)):
            raise TypeError("canonical broker TXT device resolution unavailable")
        if not callable(getattr(broker_client, "enqueue_txt_read_command", None)):
            raise TypeError("canonical broker TXT command enqueue unavailable")
        if not callable(getattr(broker_client, "installed_txt_execution_profile", None)):
            raise TypeError("canonical broker TXT execution profile unavailable")
        self._broker_client = broker_client

    async def resolve_device_binding(
        self, *, account_ref: str, workspace_ref: str, device_id: str,
    ) -> dict[str, Any]:
        return await self._broker_client.owner_device_binding(
            account_ref=account_ref, workspace_ref=workspace_ref,
            device_id=device_id,
        )

    async def installed_txt_execution_profile(
        self, *, account_ref: str, workspace_ref: str, device_id: str,
        binding_ref: str,
    ) -> str:
        return await self._broker_client.installed_txt_execution_profile(
            account_ref=account_ref, workspace_ref=workspace_ref,
            device_id=device_id, binding_ref=binding_ref,
        )

    async def owner_device_directory(
        self, *, account_ref: str, workspace_ref: str,
    ) -> dict[str, Any]:
        return await self._broker_client.owner_device_directory(
            account_ref=account_ref, workspace_ref=workspace_ref,
        )

    async def enqueue_txt_read_command(
        self, *, command: dict[str, Any], material: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._broker_client.enqueue_txt_read_command(
            command=command, material=material,
        )


def build_connector_txt_read_source(env: Any) -> BrokerTxtReadSource | None:
    """Trusted Worker composition only; missing/invalid binding is unconfigured."""
    from .control_plane_broker_pairing_client import (
        CloudflareCanonicalBrokerPairingClient,
    )
    from .worker_config import (
        LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
        binding_value,
    )

    binding = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if binding is None:
        return None
    try:
        return BrokerTxtReadSource(CloudflareCanonicalBrokerPairingClient(binding))
    except Exception:
        return None
_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


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


async def connector_txt_read_request(request: Request) -> JSONResponse:
    """Owner-confirmed TXT read: approve, mint, enqueue, return correlation."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "txt_read_unsupported_media_type")
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
            return _error(413, "txt_read_request_too_large")
        raw = await request.body()
        if len(raw) > _MAX_BODY_BYTES:
            return _error(413, "txt_read_request_too_large")
    except Exception:
        return _error(400, "txt_read_invalid_body")
    wire = _read_body(raw)
    if wire is None:
        return _error(400, "txt_read_invalid_body")

    return await dispatch_verified_txt_read(request, wire)


async def choose_verified_txt_device(
    request: Request, *, selected_device_id: str | None = None,
) -> tuple[str | None, JSONResponse | None]:
    """Select a usable canonical owner device, never from an asserted account."""
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "canonical_session_required")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    broker = getattr(request.app.state, "connector_txt_read_source", None)
    if (not callable(getattr(identity, "resolve_connector_owner_scope", None))
            or not callable(getattr(broker, "owner_device_directory", None))):
        return None, _error(503, "txt_read_device_directory_unavailable")
    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session.session_id)
        directory = await broker.owner_device_directory(
            account_ref=scope["account_ref"], workspace_ref=scope["workspace_ref"],
        )
    except Exception:
        return None, _error(503, "txt_read_device_directory_unavailable")
    if (not isinstance(directory, dict) or directory.get("available") is not True
            or not isinstance(directory.get("devices"), list)
            or len(directory["devices"]) > 24):
        return None, _error(409, "txt_read_no_usable_device")
    usable = []
    for item in directory["devices"]:
        if not isinstance(item, dict) or not isinstance(item.get("binding"), dict):
            return None, _error(503, "txt_read_device_directory_unavailable")
        binding = item["binding"]
        if (binding.get("account_ref") != scope["account_ref"]
                or binding.get("workspace_ref") != scope["workspace_ref"]):
            return None, _error(503, "txt_read_device_directory_unavailable")
        # The Broker directory never claims ONLINE: paired_offline means an
        # unrevoked registered device eligible for outbound queueing, not an
        # assertion that the Resident is currently running.
        if item.get("canonical_state") == "paired_offline":
            if isinstance(binding.get("device_id"), str) and binding["device_id"]:
                usable.append(binding["device_id"])
    usable = sorted(set(usable))
    candidate = selected_device_id or (usable[0] if len(usable) == 1 else None)
    if candidate is not None:
        if candidate not in usable:
            return None, _error(403, "txt_read_device_not_usable")
        # A missing LOCAL2-installed path MUST fail before any pending history
        # row is written: only a true Resident profile permits this command.
        try:
            binding = await broker.resolve_device_binding(
                account_ref=scope["account_ref"], workspace_ref=scope["workspace_ref"],
                device_id=candidate,
            )
            await broker.installed_txt_execution_profile(
                account_ref=scope["account_ref"], workspace_ref=scope["workspace_ref"],
                device_id=candidate, binding_ref=binding["binding_ref"],
            )
        except Exception:
            return None, _error(503, "txt_read_execution_profile_unavailable")
        return candidate, None
    if not usable:
        return None, _error(409, "txt_read_no_usable_device")
    # Existing owner-scoped multi-PC selection can consume this device list.
    # It is not enrollment authority or an input requiring a device-ID text box.
    return None, _response({
        "ok": False, "error": {"code": "txt_read_device_selection_required"},
        "devices": [{"device_id": value} for value in usable],
    }, 409)


async def dispatch_verified_txt_read(request: Request, wire: dict[str, Any]) -> JSONResponse:
    """Trusted internal and existing POST dispatch share exactly one authority path."""
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return denial if denial is not None else _error(401, "canonical_session_required")
    uid = current_user_id(request)
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return _error(503, "txt_read_workspace_unavailable")
    if not workspace_id:
        return _error(503, "txt_read_workspace_unavailable")

    broker_source = getattr(request.app.state, "connector_txt_read_source", None)
    if getattr(broker_source, "configured", False) is not True:
        return _error(503, "txt_read_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        return _error(503, "txt_read_unconfigured")
    if not callable(getattr(identity, "resolve_connector_workspace", None)):
        return _error(503, "txt_read_unconfigured")
    history_store = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history_store, "get_claw_run", None)):
        return _error(503, "txt_read_unconfigured")
    if not callable(getattr(history_store, "record_local_task_correlation", None)):
        return _error(503, "txt_read_unconfigured")

    try:
        consent = await identity.resolve_connector_enrollment_consent_for_device(
            session_id=session.session_id, device_id=wire["device_id"],
        )
        if inspect.isawaitable(consent):
            consent = await consent
    except Exception:
        return _error(403, "txt_read_consent_required")
    if (
        not isinstance(consent, dict)
        or consent.get("device_id") != wire["device_id"]
        or not isinstance(consent.get("account_ref"), str)
        or not consent["account_ref"]
        or not isinstance(consent.get("workspace_ref"), str)
        or not consent["workspace_ref"]
        or consent.get("withdrawn_at") is not None
    ):
        return _error(403, "txt_read_consent_required")
    # The two realms are never compared as strings. The memory/tenant
    # workspace above stays inside Claw history checks; the connector
    # workspace below stays inside Broker calls. Their relationship is
    # confirmed by the Identity authority itself: the session's canonical
    # connector workspace must equal the consent's workspace.
    try:
        connector_workspace = await identity.resolve_connector_workspace(
            session_id=session.session_id,
        )
        if inspect.isawaitable(connector_workspace):
            connector_workspace = await connector_workspace
    except Exception:
        return _error(503, "txt_read_unconfigured")
    if connector_workspace != consent["workspace_ref"]:
        return _error(403, "txt_read_consent_required")
    account_ref = consent["account_ref"]
    connector_workspace_ref = consent["workspace_ref"]

    try:
        device = await broker_source.resolve_device_binding(
            account_ref=account_ref, workspace_ref=connector_workspace_ref,
            device_id=wire["device_id"],
        )
    except IdentityBridgeError as exc:
        status = exc.status_code if isinstance(exc.status_code, int) else 503
        if status == 404:
            return _error(404, "txt_read_device_unbound")
        if status == 403:
            return _error(403, "txt_read_device_not_usable")
        return _error(503, "txt_read_broker_unavailable")
    except Exception:
        return _error(503, "txt_read_broker_unavailable")

    try:
        run_row = await history_store.get_claw_run(uid, wire["run_id"])
        if inspect.isawaitable(run_row):
            run_row = await run_row
    except Exception:
        return _error(503, "txt_read_run_unavailable")
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != wire["run_id"]
        or run_row.get("workspace_id") != workspace_id
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "txt_read_run_unavailable")

    try:
        executable = await broker_source.installed_txt_execution_profile(
            account_ref=account_ref, workspace_ref=connector_workspace_ref,
            device_id=wire["device_id"], binding_ref=device["binding_ref"],
        )
    except Exception:
        return _error(503, "txt_read_execution_profile_unavailable")

    try:
        proof = OwnerTxtApprovalProof(
            owner_id=uid,
            workspace_id=connector_workspace_ref,
            device_id=wire["device_id"],
            binding_ref=device["binding_ref"],
            credential_generation=device["credential_generation"],
            consent_id=consent["consent_id"],
            run_id=wire["run_id"],
        )
        issued = mint_txt_read_receipt(
            approval=proof,
            root_ref=wire["root_ref"],
            path_relative=wire["path_relative"],
            executable_path=executable,
        )
    except TxtApprovalMaterialError:
        return _error(400, "txt_read_refused")

    try:
        receipt = await broker_source.enqueue_txt_read_command(
            command=issued["enqueue"], material=issued["material"],
        )
    except IdentityBridgeError:
        return _error(409, "txt_read_enqueue_refused")
    except Exception:
        return _error(503, "txt_read_broker_unavailable")
    if (
        not isinstance(receipt, dict)
        or receipt.get("command_id") != issued["enqueue"]["command_id"]
        or not isinstance(receipt.get("revision_ref"), str)
        or not receipt["revision_ref"]
    ):
        return _error(503, "txt_read_broker_unavailable")
    # Pre-write the return-leg correlation (evidence still unknown: it is
    # minted at Broker admission, and the projection fills it once). Without
    # this row the later sessionless result reads could not resolve the
    # canonical account scope; without the evidence fill below they could not
    # verify the body. A pre-write failure orphans the enqueued command, so
    # it is a 503, never a silent success: the command TTL-bounds the orphan.
    try:
        bound = await history_store.record_local_task_correlation(
            user_id=uid,
            run_id=wire["run_id"],
            command_id=issued["enqueue"]["command_id"],
            tool_request_ref=issued["tool_request_ref"],
            request_id=issued["material"]["request_id"],
            revision_ref=receipt["revision_ref"],
            evidence_ref=None,
            request_fingerprint=issued["enqueue"]["request_fingerprint"],
        )
        if inspect.isawaitable(bound):
            await bound
    except HistoryError as exc:
        if isinstance(exc, HistoryForbidden):
            return _error(503, "txt_read_correlation_unavailable")
        # The run is already bound to a different command: one run carries
        # one command, so a further read needs its own conversation turn.
        return _error(409, "txt_read_run_already_bound")
    except Exception:
        return _error(503, "txt_read_correlation_unavailable")
    return _response({
        "ok": True,
        "command": {
            "command_id": issued["enqueue"]["command_id"],
            "run_id": wire["run_id"],
            "tool_request_ref": issued["tool_request_ref"],
        },
        "conversation_id": run_row["conversation_id"],
    })
