"""#3140 — the non-Production broker boundary, shared by both legs.

The Web leg and the resident must meet at ONE canonical broker authority: the
Web session issues the challenge there, and the resident redeems the same
challenge at the same boundary. This module publishes such a broker in-process
for a non-Production run, and hands out a request-port factory the resident
process can be configured with.

It is evidence scaffolding, not product authority:

    LOOPBACK_NON_PRODUCTION=YES
    SHARED_AUTHORITY_INSTANCE=YES   (issuer and redeemer get the same one)
    CHALLENGE_REISSUED_BY_RESIDENT=NO
    PUBLIC_INBOUND_PORT=0           (the boundary is reached in-process)

The same factory is what the resident's `PADIEM_AGENT_REQUEST_PORT` points at,
so both legs genuinely cross one authority. If the two sides ever constructed
different instances, the possession proof would fail — which is the property
the evidence run depends on.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .contracts import ContractError

#: #3140 stall diagnosis: the owner process reports its own bounded, secret-free
#: request boundaries, so a client-side stall can be attributed to a leg.
_OWNER_EMIT_LOCK = threading.Lock()
_OWNER_STARTED_MONOTONIC = time.monotonic()


def _owner_emit(**fields: Any) -> None:
    """One bounded owner-process line: route names and timing only."""

    fields.setdefault("owner_elapsed_ms", int((time.monotonic() - _OWNER_STARTED_MONOTONIC) * 1000))
    line = json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n"
    with _OWNER_EMIT_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()

BROKER_PEPPER = b"control-plane-broker-pepper-16bytes!!"
PAIRING_PEPPER = b"control-plane-pairing-pepper16byte!!"
AUTHORITY_REF = "control-plane.local-agent-broker.3140.loopback.v1"
CREDENTIAL = b"3140-loopback-nonproduction-credential"


class _Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def save_session(self, record: Any) -> Any:
        self.records[record.session_id] = record
        return record

    def load_session(self, session_id: str) -> Any:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> Any:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


#: #3140 PHASE 3 — the one bounded acceptance command this evidence lane may
#: resolve material for. Harmless, deterministic, no shell, no network, no admin.
ACCEPTANCE_COMMAND_ID = "command.3140.p01.1"
ACCEPTANCE_RUN_ID = "run.3140.p01.1"
ACCEPTANCE_REQUEST_ID = "request.3140.p01.1"
ACCEPTANCE_TOOL_REQUEST_REF = "tool_request.3140.p01.1"
ACCEPTANCE_REVISION_REF = "revision.3140.p01.1"
ACCEPTANCE_MARKER = "padiem-3140-p01-ok"
ACCEPTANCE_EXECUTABLE_ENV = "PADIEM_3140_ACCEPTANCE_EXECUTABLE"
#: #3140 PHASE 3 — the canonical P01 acceptance evidence this lane supplies.
ACCEPTANCE_EVIDENCE_REF = "evidence.3140.p01.1"
ACCEPTANCE_PAUSE_ID = "pause.3140.p01.1"
ACCEPTANCE_DECISION_ID = "decision.3140.p01.1"
ACCEPTANCE_ACTION_ID = "action.3140.p01.1"
ACCEPTANCE_LOCAL_POLICY_REF = "local_policy.3140.p01"
ACCEPTANCE_PROFILE_REF = "profile.3140.python"
P01_AUTHORITY_REF = "p01_authority.3140.evidence"
P01_EVIDENCE_ROUTE = "/v1/broker/p01-evidence"
# #3217 — loopback-only emulation of the broker Worker Service Binding read.
TERMINAL_RESULT_SERVICE_ROUTE = "/__private/terminal-command-result"
MAX_PRIVATE_RESULT_REQUEST_BYTES = 4 * 1024
MAX_PRIVATE_RESULT_RESPONSE_BYTES = 16 * 1024
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ACCEPTANCE_AGENT_RUNTIME_ID = "agent_runtime.3140"


def _acceptance_envelope_payload(envelope: Any) -> dict:
    """Bounded, secret-free projection of one canonical P01 envelope.

    Ids, digests, capabilities and timestamps only. No argv, no credential, no
    approval UI payload: the resident rebuilds the canonical objects from these
    fields and never invents an approval of its own.
    """

    return {
        "contract_version": "claw-3140-p01-acceptance-evidence.v1",
        "evidence_ref": envelope.evidence_ref,
        "request_fingerprint": envelope.request_fingerprint,
        "local_policy_ref": envelope.local_policy_ref,
        "expires_at": envelope.expires_at.isoformat(),
        "approval_pause": {
            "pause_id": envelope.approval_pause.pause_id,
            "run_id": envelope.approval_pause.run_id,
            "agent_runtime_id": envelope.approval_pause.agent_runtime_id,
            "tool_id": envelope.approval_pause.tool_id,
            "invocation_sha256": envelope.approval_pause.invocation_sha256,
            "requirement": envelope.approval_pause.requirement.value,
            "step_index": envelope.approval_pause.step_index,
            "created_at": envelope.approval_pause.created_at.isoformat(),
            "expires_at": envelope.approval_pause.expires_at.isoformat(),
            "approval_scope": list(envelope.approval_pause.approval_scope),
        },
        "approval_decision": {
            "decision_id": envelope.approval_decision.decision_id,
            "pause_id": envelope.approval_decision.pause_id,
            "outcome": envelope.approval_decision.outcome.value,
            "authority_ref": envelope.approval_decision.authority_ref,
            "evidence_ref": envelope.approval_decision.evidence_ref,
            "decided_at": envelope.approval_decision.decided_at.isoformat(),
        },
        "permission_requests": [
            {
                "action_id": item.action_id,
                "run_id": item.run_id,
                "device_id": item.device_id,
                "capability": item.capability.value,
                "target_ref": item.target_ref,
                "root_ref": item.root_ref,
            }
            for item in envelope.permission_requests
        ],
    }


class _MaterialResolver:
    """Resolves material for exactly one registered bounded command.

    Pairing, redeem, session and heartbeat must never reach material: the
    registry starts empty and only an exact (command_id, binding_ref,
    request_fingerprint) match resolves. Everything else fails closed, which is
    what the previous pairing-only denial protected.
    """

    def __init__(self) -> None:
        self._wires: dict[tuple[str, str, str], dict] = {}

    def register(
        self,
        *,
        command_id: str,
        binding_ref: str,
        request_fingerprint: str,
        wire: dict,
    ) -> None:
        self._wires[(command_id, binding_ref, request_fingerprint)] = wire

    def resolve(self, request: Any) -> dict:
        key = (
            getattr(request, "command_id", None),
            getattr(request, "binding_ref", None),
            getattr(request, "request_fingerprint", None),
        )
        wire = self._wires.get(key)
        if wire is None:
            raise AssertionError("material may only be resolved for the exact registered command")
        return wire


class _References:
    def __call__(self) -> tuple[str, str]:
        return "admission_3140_loopback_1", "evidence_3140_loopback_1"


class _Nonces:
    def __init__(self) -> None:
        self._next = 0xB0000

    def __call__(self) -> str:
        self._next += 1
        return f"{self._next:032x}"


class LoopbackPairingBroker:
    """One broker + pairing authority, plus the request port both legs use."""

    def __init__(self) -> None:
        from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
        from padiem_control_plane.local_agent_broker_pairing import (
            InMemoryBrokerPairingAuthority,
        )
        from padiem_control_plane.local_agent_broker_pairing_http import (
            PairingAndAdmissionLocalAgentBrokerHttpHandler,
        )
        from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )

        self.clock = _Clock()
        self.authority = InMemoryLocalAgentBrokerAuthority(
            pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF
        )
        self.pairing = InMemoryBrokerPairingAuthority(
            pepper=PAIRING_PEPPER,
            authority=self.authority,
            code_nonce_factory=_Nonces(),
            credential_factory=lambda: CREDENTIAL,
        )
        # #3140 PHASE 3: one gated material registry, reachable only for the
        # exact bounded acceptance command enqueued on a real session, plus the
        # durable session state that carries the canonical binding correlation.
        self.material = _MaterialResolver()
        self.state = _DurableState()
        self.handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=self.pairing,
            admission_reference_factory=_References(),
            rpc=LocalAgentBrokerRpcFacade(authority=self.authority),
            state=self.state,
            material_resolver=self.material,
            clock=self.clock,
        )
        self.acceptance_active = False
        self._acceptance_envelope: Any | None = None
        self._acceptance_command_id: str | None = None
        self._acceptance_binding_ref: str | None = None
        self._acceptance_request_id: str | None = None
        self._acceptance_run_id: str | None = None
        self._acceptance_enqueued: bool = False
        self._acceptance_session_id: str | None = None
        self.audit: list[str] = []
        # #3140 handoff boundary fix: the per-route principals.
        # `_device_auth` is the *unauthenticated* device principal the redeem
        # route presents (it carries the possession proof), and
        # `_authenticated_device_auth` is the post-pairing device principal for
        # session/heartbeat/poll/material/admission/acknowledgement. These were
        # previously assigned as unreachable code *after* a `return`, so the
        # redeem route raised AttributeError and the owner closed the connection
        # without a response: the observed handoff_ack failure in run2/run3.
        self._device_auth = TrustedLocalAgentHttpAuthContext(
            principal_ref="device.3140.resident",
            account_ref="account.1",
            workspace_ref="workspace.1",
            authenticated=False,
            tls_verified=True,
        )
        self._authenticated_device_auth = TrustedLocalAgentHttpAuthContext(
            principal_ref="device.3140.resident",
            account_ref="account.1",
            workspace_ref="workspace.1",
            authenticated=True,
            tls_verified=True,
        )

    def _build_acceptance_envelope(self, *, request: Any, fingerprint: str) -> Any:
        """Canonical P01 acceptance envelope for the one bounded command."""

        from datetime import timedelta

        from padiem_ai_core.agent_approval import (
            ApprovalOutcome,
            ApprovalPause,
            ApprovalRequirement,
            VerifiedApprovalDecision,
            tool_invocation_digest,
        )

        from .local_agent_permissions import LocalCapability, LocalPermissionRequest
        from .windows_execution_authorization import (
            WINDOWS_EXECUTION_TOOL_ID,
            windows_execution_tool_invocation,
        )
        from .windows_execution_evidence_source import (
            TrustedP01WindowsExecutionEvidenceEnvelope,
        )
        from .windows_local_executor import WindowsExecutableProfile

        now = self.clock.now
        profile = WindowsExecutableProfile(
            profile_ref=ACCEPTANCE_PROFILE_REF,
            executable_path=str(Path(sys.executable).resolve()),
            required_capabilities=(LocalCapability.PROCESS_EXECUTE.value,),
        )
        pause = ApprovalPause(
            pause_id=ACCEPTANCE_PAUSE_ID,
            run_id=request.run_id,
            agent_runtime_id=ACCEPTANCE_AGENT_RUNTIME_ID,
            tool_id=WINDOWS_EXECUTION_TOOL_ID,
            invocation_sha256=tool_invocation_digest(
                windows_execution_tool_invocation(request, profile)
            ),
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            approval_scope=(LocalCapability.PROCESS_EXECUTE.value,),
        )
        # #3140 evidence-harness only: the negative lane asks this evidence
        # owner for a DENIED decision so the canonical P01 port can refuse it
        # before any process starts. This switch lives only in this evidence
        # owner process; the product runtime never reads it.
        decision_outcome = (
            ApprovalOutcome.DENIED
            if os.environ.get("PADIEM_3140_P01_DENY") == "1"
            else ApprovalOutcome.APPROVED
        )
        decision = VerifiedApprovalDecision(
            decision_id=ACCEPTANCE_DECISION_ID,
            pause_id=pause.pause_id,
            outcome=decision_outcome,
            authority_ref=P01_AUTHORITY_REF,
            evidence_ref=ACCEPTANCE_EVIDENCE_REF,
            decided_at=now + timedelta(seconds=1),
        )
        permission_request = LocalPermissionRequest(
            action_id=ACCEPTANCE_ACTION_ID,
            run_id=request.run_id,
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref=fingerprint,
            root_ref=request.root_ref,
        )
        return TrustedP01WindowsExecutionEvidenceEnvelope(
            evidence_ref=ACCEPTANCE_EVIDENCE_REF,
            request_fingerprint=fingerprint,
            approval_pause=pause,
            approval_decision=decision,
            permission_requests=(permission_request,),
            local_policy_ref=ACCEPTANCE_LOCAL_POLICY_REF,
            expires_at=now + timedelta(minutes=5),
        )

    def p01_evidence_payload(
        self,
        *,
        command_id: str,
        binding_ref: str,
        request_fingerprint: str,
        request_id: str,
    ) -> dict:
        """The canonical acceptance envelope, or fail unless all four keys match.

        #3140: a fingerprint alone can be reused across lanes. The evidence
        boundary must bind to the exact command, binding, request id and
        fingerprint — any mismatch is a 404/refused, never a partial hit.
        """

        envelope = self._acceptance_envelope
        if (
            envelope is None
            or envelope.request_fingerprint != request_fingerprint
            or self._acceptance_command_id != command_id
            or self._acceptance_binding_ref != binding_ref
            or self._acceptance_request_id != request_id
        ):
            raise ContractError(
                "no canonical P01 acceptance evidence for this command/binding/request"
            )
        return _acceptance_envelope_payload(envelope)

    def enqueue_acceptance_command_for_latest_session(
        self,
        *,
        root_ref: str = "root.3140",
    ) -> dict | None:
        """Enqueue the bounded acceptance command against the newest session.

        The session record is the canonical binding/session correlation this
        lane already established, so the command is bound to it rather than to
        anything the enqueue path invents.
        """

        records = list(self.state.records.values())
        if not records:
            return None
        record = records[-1]
        return self.enqueue_acceptance_command(
            binding_ref=record.binding_ref,
            device_id=record.device_id,
            # The one-shot scope is the canonical session this command is bound
            # to. The command record itself carries no session id, so it is
            # passed from the session record rather than read off the command.
            session_id=record.session_id,
            root_ref=root_ref,
        )

    def enqueue_acceptance_command(
        self,
        *,
        binding_ref: str,
        device_id: str,
        session_id: str,
        root_ref: str,
    ) -> dict:
        """Enqueue the one bounded acceptance command for the redeemed binding.

        It reuses the canonical enqueue + material encoder. No new authority is
        created: the command is an ordinary queued broker command whose material
        is only resolvable for its exact correlation.
        """

        from .local_agent import LocalCommandRequest
        from .local_agent_command_material import (
            build_command_material_wire_projection,
            command_request_fingerprint,
        )
        from .local_agent_pairing import DeviceCommandEnvelope

        if self.acceptance_active:
            raise ContractError("the bounded acceptance command was already enqueued")
        if not binding_ref or not device_id:
            raise ContractError("the acceptance command requires a canonical binding and device")
        # #3140 PHASE 3: the executable is chosen by trusted resident code
        # (`Path(sys.executable).resolve()`); the owner process runs the same
        # interpreter, so it names the identical path without any env input.
        executable = str(Path(sys.executable).resolve())
        now = self.clock.now
        request = LocalCommandRequest(
            request_id=ACCEPTANCE_REQUEST_ID,
            run_id=ACCEPTANCE_RUN_ID,
            device_id=device_id,
            root_ref=root_ref,
            argv=(executable, "-c", f"print('{ACCEPTANCE_MARKER}')"),
            cwd_relative=".",
            requested_at=now,
            timeout_seconds=30,
        )
        fingerprint = command_request_fingerprint(request)
        record = self.authority.enqueue_command(
            command_id=ACCEPTANCE_COMMAND_ID,
            binding_ref=binding_ref,
            run_id=ACCEPTANCE_RUN_ID,
            tool_request_ref=ACCEPTANCE_TOOL_REQUEST_REF,
            request_fingerprint=fingerprint,
            now=now,
        )
        envelope = DeviceCommandEnvelope(
            command_id=record.command_id,
            run_id=record.run_id,
            tool_request_ref=record.tool_request_ref,
            binding_ref=record.binding_ref,
            sequence=record.sequence,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            revision_ref=record.revision_ref,
        )
        wire = build_command_material_wire_projection(
            command=envelope,
            request=request,
            request_fingerprint=fingerprint,
        )
        self.material.register(
            command_id=record.command_id,
            binding_ref=record.binding_ref,
            request_fingerprint=fingerprint,
            wire=wire,
        )
        # One-shot, scoped to one canonical session+binding:
        # same session + same binding → cached facts, enqueue count stays 1.
        # different session or different binding → fail closed, never reuse.
        if self._acceptance_enqueued:
            if (
                self._acceptance_session_id == session_id
                and self._acceptance_binding_ref == record.binding_ref
            ):
                return {
                    "command_id": self._acceptance_command_id,
                    "binding_ref": self._acceptance_binding_ref,
                    "request_id": self._acceptance_request_id,
                    "run_id": self._acceptance_run_id,
                    "request_fingerprint": fingerprint,
                }
            raise ContractError("acceptance already enqueued for a different session or binding")
        self._acceptance_session_id = session_id
        self._acceptance_enqueued = True

        # #3140 PHASE 3: the evidence side builds the canonical APPROVED envelope
        # from the exact request it just enqueued. The resident only fetches it by
        # command_id + binding_ref + request_id + fingerprint and consumes it.
        self._acceptance_command_id = record.command_id
        self._acceptance_binding_ref = record.binding_ref
        self._acceptance_request_id = request.request_id
        self._acceptance_envelope = self._build_acceptance_envelope(
            request=request,
            fingerprint=fingerprint,
        )
        self.acceptance_active = True
        self._acceptance_run_id = record.run_id
        return {
            "command_id": record.command_id,
            "binding_ref": record.binding_ref,
            "run_id": record.run_id,
            "request_id": request.request_id,
            "revision_ref": record.revision_ref,
            "sequence": record.sequence,
            "request_fingerprint": fingerprint,
        }

    def terminal_command_result(self, payload: dict) -> dict:
        """Read #3139 facts from this exact canonical broker authority."""

        from padiem_control_plane.local_agent_broker_state import (
            LocalAgentBrokerStateSnapshot,
            terminal_command_result_from_snapshot,
        )

        snapshot = LocalAgentBrokerStateSnapshot.capture(self.authority)
        return terminal_command_result_from_snapshot(snapshot, payload)

    def request_port(self) -> "LoopbackRequestPort":
        return LoopbackRequestPort(self)

    def web_issue_challenge(self, *, now: datetime) -> dict:
        """The Web leg: an authenticated browser session issues the challenge."""

        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )
        from padiem_control_plane.local_agent_broker_pairing_http import (
            PAIRING_CHALLENGE_ROUTE,
        )

        body = json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": now.isoformat(),
                "ttl_seconds": 300,
            }
        ).encode("utf-8")
        response = self.handler.handle(
            method="POST",
            route=PAIRING_CHALLENGE_ROUTE,
            content_type="application/json",
            body=body,
            auth=TrustedLocalAgentHttpAuthContext(
                principal_ref="principal.browser.3140",
                account_ref="account.1",
                workspace_ref="workspace.1",
                authenticated=True,
                tls_verified=True,
            ),
        )
        if response.status != 200:
            raise ContractError("the web leg could not issue a pairing challenge")
        return response.body


class LoopbackRequestPort:
    """The request port the resident is configured with."""

    def __init__(self, broker: LoopbackPairingBroker) -> None:
        self._broker = broker

    def post(self, *, config: Any, operation: Any, payload: dict, timeout_seconds: int) -> dict:
        del config, timeout_seconds
        name = operation.value
        self._broker.audit.append(name)
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            self._broker.clock.now = datetime.fromisoformat(
                str(payload["now"]).replace("Z", "+00:00")
            )
        response = self._broker.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self._broker._device_auth,
        )
        return json.loads(json.dumps(response.body))


class BrokerClientPort:
    """A client port that *connects* to the one shared broker.

    #3140: the resident must never stand up an authority of its own. This port
    reaches the broker owned by the separate broker process over the loopback
    service, so the Web leg and the resident redeem leg cross the same canonical
    authority rather than two deterministic reconstructions of one.

    #3206: it honors the bounded request-port contract the canonical Production
    adapter already keeps. A 4xx carrying a valid bounded broker JSON error
    body (``{"ok": false, "error": {"code", "message"}}``) is returned to the
    caller, so the canonical pairing client raises its own ``ContractError``
    and the resident emits ``redemption_refused``. Malformed, oversized or
    unreadable transports are bounded ``ContractError`` here. A raw
    ``urllib.error.HTTPError`` must never escape into the resident, whose
    refusal path is written against ``ContractError``.
    """

    #: A refusal is a small canonical JSON error, never a stream: the owner's
    #: bodies are byte-sized, so anything larger cannot be one.
    MAX_RESPONSE_BODY_BYTES = 16 * 1024

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def _bounded_json(self, raw: bytes) -> Any:
        """Decode one bounded broker body, or fail closed with ContractError."""

        if len(raw) > self.MAX_RESPONSE_BODY_BYTES:
            raise ContractError("shared broker response exceeds the bounded size")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("shared broker response is not bounded JSON") from exc

    def post(self, *, config: Any, operation: Any, payload: dict, timeout_seconds: int) -> dict:
        import http.client
        import urllib.error
        import urllib.request

        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/{operation.value}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds or 10) as response:
                raw = response.read(self.MAX_RESPONSE_BODY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # The owner answers a refusal with a bounded canonical JSON error.
            # Handing that body to the canonical pairing client turns the
            # refusal into its own ContractError instead of a raw urllib
            # traceback escaping the resident's `except ContractError` path.
            try:
                raw = exc.read(self.MAX_RESPONSE_BODY_BYTES + 1)
            except OSError as read_exc:
                raise ContractError("shared broker refusal body is unreadable") from read_exc
            finally:
                exc.close()
            if 400 <= exc.code < 500:
                decoded = self._bounded_json(raw)
                if type(decoded) is dict:
                    return decoded
            raise ContractError(f"shared broker returned HTTP status {exc.code}") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise ContractError("Local Agent outbound broker is unavailable") from exc
        decoded = self._bounded_json(raw)
        if type(decoded) is not dict:
            raise ContractError("shared broker response must be a JSON object")
        return decoded


class LoopbackBrokerAuthorityServiceBinding:
    """Read-only #3217 Service Binding shape over the shared loopback owner."""

    def __init__(self, base_url: str) -> None:
        import urllib.parse

        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS or not parsed.port:
            raise ContractError("terminal-result binding requires a loopback broker URL")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
            raise ContractError("terminal-result binding broker URL must be an origin")
        self._base_url = base_url.rstrip("/")

    @staticmethod
    def _unavailable() -> dict:
        return {
            "ok": False,
            "error": {
                "code": "local_runner_result_binding_unavailable",
                "message": "the private broker result binding is unavailable",
            },
        }

    def terminal_command_result(self, payload: dict) -> dict:
        import http.client
        import urllib.error
        import urllib.request

        if type(payload) is not dict:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_terminal_result_request",
                    "message": "terminal result request was rejected",
                },
            }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_PRIVATE_RESULT_REQUEST_BYTES:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_terminal_result_request",
                    "message": "terminal result request was rejected",
                },
            }
        request = urllib.request.Request(
            f"{self._base_url}{TERMINAL_RESULT_SERVICE_ROUTE}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read(MAX_PRIVATE_RESULT_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(MAX_PRIVATE_RESULT_RESPONSE_BYTES + 1)
            except OSError:
                raw = b""
            finally:
                exc.close()
            if len(raw) > MAX_PRIVATE_RESULT_RESPONSE_BYTES:
                return self._unavailable()
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._unavailable()
            return decoded if type(decoded) is dict else self._unavailable()
        except (OSError, http.client.HTTPException):
            return self._unavailable()
        if len(raw) > MAX_PRIVATE_RESULT_RESPONSE_BYTES:
            return self._unavailable()
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._unavailable()
        return decoded if type(decoded) is dict else self._unavailable()

def make_request_port() -> BrokerClientPort:
    """Client factory for the resident's configured broker entry.

    It connects to the broker owner process. It does not create an authority:
    a process that minted its own broker could redeem a code that no Web
    session ever received.
    """

    import os

    base_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if not base_url:
        raise ContractError("PADIEM_AGENT_BROKER_URL must name the shared broker service")
    return BrokerClientPort(base_url)


def main(argv: list[str] | None = None) -> int:
    """The Web leg for the evidence run: issue a challenge, print it, exit.

    It prints the one-time code and the server-owned challenge id. Neither is
    persisted; the caller carries them into the `padiem://` deep link.
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] not in (["--issue-handoff"], ["--web-issue"]):
        sys.stderr.write("usage: python -m kagent.local_agent_broker_pairing_handoff_entry --issue-handoff\n")
        return 2
    # #3140: the web leg issues through the running owner when one is
    # configured, so the challenge belongs to the authority the resident will
    # redeem at. A private instance is only the single-process fallback.
    import os
    import urllib.request

    from padiem_control_plane.local_agent_broker_pairing_http import (
        PAIRING_CHALLENGE_ROUTE,
    )

    broker_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if broker_url:
        body = json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "ttl_seconds": 300,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{broker_url}{PAIRING_CHALLENGE_ROUTE}", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            issued = json.loads(response.read().decode("utf-8"))
    else:
        broker = LoopbackPairingBroker()
        issued = broker.web_issue_challenge(
            now=datetime.now(timezone.utc).replace(microsecond=0)
        )
    sys.stdout.write(
        json.dumps(
            {
                "pairing_code": issued["pairing_code"],
                "challenge_id": issued["challenge"]["challenge_id"],
                "authority_ref": AUTHORITY_REF,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


def serve(host: str = "127.0.0.1", port: int = 0) -> int:
    """Own the one non-Production broker authority and serve it.

    This process is the owner: it holds the single broker and pairing authority
    both legs reach. It binds loopback only and is never a public ingress.
    """

    import http.server
    import threading
    import urllib.parse

    if host not in _LOOPBACK_HOSTS:
        raise ValueError("non-Production broker owner must bind to loopback")

    broker = LoopbackPairingBroker()
    holder = {"url": ""}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler surface
            length = int(self.headers.get("Content-Length", "0"))
            path_only = urllib.parse.urlparse(self.path).path
            if path_only.startswith("/v1/"):
                route = path_only
            else:
                route = f"/{path_only.lstrip('/')}"
            if route == TERMINAL_RESULT_SERVICE_ROUTE and length > MAX_PRIVATE_RESULT_REQUEST_BYTES:
                out_body = {
                    "ok": False,
                    "error": {
                        "code": "invalid_terminal_result_request",
                        "message": "terminal result request was rejected",
                    },
                }
                raw = json.dumps(out_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(413)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            # #3140 stall diagnosis: request accepted, handler entered, response
            # written. Route names only -- never a body, a code or a credential.
            _owner_emit(event="broker_request_accepted", route=route)
            if route == TERMINAL_RESULT_SERVICE_ROUTE:
                out_body = broker.terminal_command_result(payload)
                raw = json.dumps(out_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if len(raw) > MAX_PRIVATE_RESULT_RESPONSE_BYTES:
                    out_body = LoopbackBrokerAuthorityServiceBinding._unavailable()
                    raw = json.dumps(out_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                _owner_emit(event="broker_response_written", route=route, status=200)
                return
            if route == P01_EVIDENCE_ROUTE:
                # The bounded evidence fetch the resident performs; served before
                # the product routes, and only for the exact fingerprint.
                requested = payload
                try:
                    evidence = broker.p01_evidence_payload(
                        command_id=str(requested.get("command_id", "")),
                        binding_ref=str(requested.get("binding_ref", "")),
                        request_fingerprint=str(requested.get("request_fingerprint", "")),
                        request_id=str(requested.get("request_id", "")),
                    )
                except Exception as exc:  # noqa: BLE001 - bounded report
                    _owner_emit(event="p01_evidence_refused", detail=type(exc).__name__)
                    out_body = {"ok": False}
                    out_status = 404
                else:
                    _owner_emit(
                        event="p01_evidence_served",
                        decision=str(
                            evidence.get("approval_decision", {}).get("outcome", "")
                        ),
                    )
                    out_body = {"ok": True, "envelope": evidence}
                    out_status = 200
                raw = json.dumps(out_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(out_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                _owner_emit(event="broker_response_written", route=route, status=out_status)
                return
            auth = _auth_for_route(route)
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            _owner_emit(event="broker_handler_enter", route=route)
            response = broker.handler.handle(
                method="POST",
                route=route,
                content_type="application/json",
                body=body,
                auth=auth,
            )
            # #3140 PHASE 3: once a canonical session exists, the control-plane
            # side of this lane enqueues exactly one bounded acceptance command
            # against that session's binding. It runs BEFORE the response is
            # written so the resident receives the canonical acceptance facts
            # (command_id/binding_ref/request_id/request_fingerprint) in the very
            # /session reply it then uses for the bounded P01 evidence fetch.
            if route == "/session" and response.status == 200 and not broker.acceptance_active:
                try:
                    facts = broker.enqueue_acceptance_command_for_latest_session()
                except Exception as exc:  # noqa: BLE001 - bounded, secret-free report
                    # Bounded diagnostic: the type AND a short message so a refused
                    # enqueue names its cause instead of one opaque token.
                    _owner_emit(
                        event="acceptance_command_refused",
                        detail=f"{type(exc).__name__}: {str(exc)[:180]}",
                    )
                else:
                    if facts is not None:
                        _owner_emit(
                            event="acceptance_command_enqueued",
                            command_id=facts["command_id"],
                            binding_ref=facts["binding_ref"],
                            run_id=facts["run_id"],
                            request_id=facts["request_id"],
                            sequence=facts["sequence"],
                            request_fingerprint=facts["request_fingerprint"],
                        )
            # The /session payload is a *closed* mapping on the resident side, so
            # the acceptance facts must NOT be injected here. The resident derives
            # the same four keys from the canonical command it polls and from the
            # canonical material projection it resolves — identical source data.
            out = json.dumps(response.body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            _owner_emit(event="broker_response_written", route=route, status=response.status)
            # #3140 PHASE 3: the canonical acknowledgement the broker accepted,
            # projected as bounded facts so the harness can compare the resident's
            # command_result correlation against the server-observed one.
            if route == "/acknowledge" and response.status == 200:
                _owner_emit(
                    event="acknowledged",
                    command_id=str(payload.get("command_id", "")),
                    request_id=str(payload.get("request_id", "")),
                    admission_ref=str(payload.get("admission_ref", "")),
                    evidence_ref=str(payload.get("evidence_ref", "")),
                    revision_ref=str(payload.get("revision_ref", "")),
                    exit_code=payload.get("exit_code"),
                    termination=str(payload.get("termination", "")),
                )

        def log_message(self, *args: Any) -> None:
            return

    def _auth_for_route(route: str):
        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )

        # The same per-route principal rule the real broker enforces: the Web
        # session issues as an authenticated browser, the pairing redeem presents
        # an *unauthenticated* device principal with a possession proof, and
        # every post-pairing route is the authenticated device.
        if "pairings/challenge" in route:
            return TrustedLocalAgentHttpAuthContext(
                principal_ref="principal.browser.3140",
                account_ref="account.1", workspace_ref="workspace.1",
                authenticated=True, tls_verified=True,
            )
        if "pairings/redeem" in route:
            return broker._device_auth
        return broker._authenticated_device_auth

    server = http.server.HTTPServer((host, port), Handler)
    holder["url"] = f"http://{host}:{server.server_address[1]}"
    sys.stdout.write(
        json.dumps(
            {"broker_url": holder["url"], "owner_process": True,
             "public_inbound_port": 0},
            sort_keys=True, separators=(",", ":"),
        )
    )
    sys.stdout.flush()
    try:
        # The owner holds the one authority for the life of this process.
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover — operator shutdown
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    if "--serve" in sys.argv[1:]:
        raise SystemExit(serve())
    raise SystemExit(main())
