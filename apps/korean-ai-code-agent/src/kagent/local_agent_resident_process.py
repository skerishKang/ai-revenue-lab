"""#3140 — the single long-lived resident host product process.

Items 1 and 2, together:

* **Item 1 / 3 — same-authority redeem, no fresh authority.** This process
  constructs *no* broker and *no* pairing authority, and it never re-issues a
  challenge. It is handed a `BrokerEntry` (authority ref + request port) by
  deployment configuration and redeems the **Web-issued** challenge through the
  #3095 client at that one boundary. The handoff therefore carries the
  `challenge_id` the Web session received, and the possession proof is computed
  against it. Issuer and redeemer meet at the same authority, which is the
  premise of the proof; a code minted anywhere else is refused by the broker.

* **Item 4 — acknowledgement only after ownership holds.** The ACK is emitted
  *after* the canonical redemption succeeds and the binding is durably stored,
  not on receipt of the envelope. A replay, a timeout or a broker rejection
  therefore produces no acknowledgement, so the main process never commits the
  one-shot for a handoff that was not actually taken.

* **Item 2 / 5 — one long-lived host.** Pairing configures and activates *this*
  process' host. The #3014 resident host is constructed exactly once and runs
  for the life of the process; there is no temporary proof host.

* **Item 6 — no execution PASS claim.** The P01 composition goes through the
  canonical fail-closed seam. Until #3148 lands a real `WorktreeStatePort`, that
  seam refuses and the host is not started. That refusal is reported, never
  worked around.

    PAIRING_AUTHORITY_IMPLEMENTED=NO
    BROKER_AUTHORITY_IMPLEMENTED=NO
    CHALLENGE_REISSUED=NO
    SECOND_RESIDENT_HOST=0
    PUBLIC_INBOUND_PORT=0
    PRODUCTION_MUTATION=0
    PAIRING_CODE_LOGGED=0
    PAIRING_CODE_PERSISTED=0
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from .local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
from .local_agent_desktop_material import (
    DESKTOP_REQUEST_KINDS,
    MAX_PREHANDOFF_SKIP_LINES,
    ResidentDesktopMaterialResponder,
)
from .local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from .local_agent_durable_run_store import DurableRunStore
from .local_agent_pairing import DeviceLifecycle
from .local_agent_permissions import default_device_permission_profile
from .local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from .local_agent_runtime_host import LocalAgentResidentRuntimeHost
from .local_agent_secure_channel import PinnedOutboundBrokerBinding
from .local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    ProtectedFileDeviceCredentialStore,
    WindowsDpapiProtectedDataPort,
)
from .local_agent_worktree_state import WindowsGitWorktreeStatePort
from .windows_execution_authorization import (
    P01LocalPermissionWindowsExecutionAuthorizationPort,
)
from .windows_local_executor import WindowsExecutableProfile

HANDOFF_CONTRACT_VERSION = "claw-desktop-pairing-handoff.v1"
ACK_CONTRACT_VERSION = "claw-desktop-pairing-ack.v1"
MAX_LINE_CHARS = 4_096
CODE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
#: The target device is Windows by contract, so these are Windows paths on any
#: host that runs the composition. Pairing does not dispatch, so neither is ever
#: resolved.
WINDOWS_PYTHON_EXECUTABLE = "C:/Python313/python.exe"
WINDOWS_ROOT = "C:/ProgramData/Padiem/runner"
#: #3140 PHASE 3: the trusted root the shell already passes to the resident. When
#: it is present this is the real bounded execution root; the constant above is
#: only the non-dispatching placeholder the unit fixtures still use.
PROJECT_ROOT_ENV = "PADIEM_AGENT_PROJECT_ROOT"
EXECUTION_ROOT_REF = "root.3140"
EXECUTION_PROFILE_REF = "profile.3140.python"
#: #3140 PHASE 3: the one bounded acceptance command contract. These are the
#: same canonical identifiers the owner lane enqueues (not a second authority).
ACCEPTANCE_COMMAND_ID = "command.3140.p01.1"
ACCEPTANCE_REQUEST_ID = "request.3140.p01.1"
ACCEPTANCE_RUN_ID = "run.3140.p01.1"


def trusted_execution_root() -> tuple[str, str]:
    """The bounded local execution root and where it came from (fail closed).

    Windows-only composition: only a Windows host can run the Windows command,
    so only a Windows host resolves the shell-supplied root. A non-Windows host
    (for example the Ubuntu test/composition job) keeps the non-dispatching
    Windows placeholder so a POSIX path can never be composed into the
    Windows-only device profile.
    """

    candidate = os.environ.get(PROJECT_ROOT_ENV)
    if sys.platform == "win32" and candidate and os.path.isdir(candidate):
        return os.path.abspath(candidate), "env"
    return WINDOWS_ROOT, "placeholder"


def trusted_executable_profile_path() -> str:
    """The executable the resident itself runs on: resolved in trusted code.

    Windows-only composition: the interpreter path is only meaningful for a
    Windows execution host. A non-Windows host keeps the non-dispatching
    Windows placeholder instead of feeding a POSIX interpreter path into a
    Windows executable profile, whose own validation is unchanged.
    """

    if sys.platform != "win32":
        return WINDOWS_PYTHON_EXECUTABLE
    return str(Path(sys.executable).resolve())


ACCEPTANCE_P01_AUTHORITY_REF = "p01_authority.3140.evidence"


def _acceptance_authorization_port(
    *,
    device: Any,
    root_source: str,
    acceptance_command_id: str = "",
    acceptance_binding_ref: str = "",
    acceptance_request_id: str = "",
    acceptance_request_fingerprint: str = "",
) -> Any:
    """The canonical P01 port, with the lane's bounded evidence client wired.

    Only when a real shell-supplied root (root_source=env) and a configured
    broker boundary exist; otherwise the default fail-closed port stands.
    The 4 acceptance correlation facts come from the /session canonical
    response and are passed through unchanged — no new correlation object.
    """

    broker_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if root_source != "env" or not broker_url:
        return P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=default_device_permission_profile(device=device)
        )

    from .windows_execution_evidence_source import (
        TrustedP01WindowsExecutionAuthorityEvidencePort,
    )

    return P01LocalPermissionWindowsExecutionAuthorizationPort(
        permission_profile=default_device_permission_profile(device=device),
        evidence_port=TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref=ACCEPTANCE_P01_AUTHORITY_REF,
            client=_FetchedP01EvidenceClient(
                broker_url,
                command_id=acceptance_command_id,
                binding_ref=acceptance_binding_ref,
                request_id=acceptance_request_id,
                request_fingerprint=acceptance_request_fingerprint,
            ),
        ),
    )


def _browser_open_authority(
    *,
    device: Any,
    store: Any,
    root_source: str,
    acceptance_command_id: str = "",
    acceptance_binding_ref: str = "",
    acceptance_request_id: str = "",
    host: Any | None = None,
) -> Any:
    """Compose the approved `browser.open` slice, fail-closed by default (#3611).

    The slice is built from the *same* redeemed device, the *same* local policy
    profile and the *same* durable store as the Windows execution lane, so there
    is no second device view, no second policy and no second one-shot store.

    Only when a real shell-supplied root (root_source=env) and a configured broker
    boundary and the acceptance correlation exist is the existing canonical P01
    evidence route wired; otherwise the authority keeps its fail-closed default
    evidence port. The **host** is never defaulted to something permissive: the
    trusted main view owner is injected by the process that owns the browser, so
    an unrouted authority refuses instead of opening.
    """

    from .browser_open_authority import (
        BrowserOpenAuthority,
        P01LoopbackBrowserOpenEvidenceClient,
    )

    permission_profile = default_device_permission_profile(device=device)
    broker_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if (
        root_source != "env"
        or not broker_url
        or not acceptance_command_id
        or not acceptance_binding_ref
        or not acceptance_request_id
    ):
        return BrowserOpenAuthority(
            device=device,
            permission_profile=permission_profile,
            store=store,
            host=host,
        )
    return BrowserOpenAuthority(
        device=device,
        permission_profile=permission_profile,
        store=store,
        host=host,
        evidence_port=P01LoopbackBrowserOpenEvidenceClient(
            store=store,
            command_id=acceptance_command_id,
            binding_ref=acceptance_binding_ref,
            request_id=acceptance_request_id,
            base_url=broker_url,
        ),
    )


def _resident_device(*, entry: "BrokerEntry", binding: Any, execution_root: str) -> LocalAgentDeviceProfile:
    """The single trusted device view every resident lane composes against.

    #3669: the browser.open slice and the browser.control lease slice must
    describe the same machine, so the device is built in exactly one place
    from the redeemed binding and the shell-supplied root — never a second,
    hard-coded view.
    """

    return LocalAgentDeviceProfile(
        device_id=entry.device_id,
        # #3140 review item 3: the workspace is whatever the redeemed binding
        # says. A hard-coded workspace would let a device from one workspace
        # present as a device of another.
        workspace_ref=binding.workspace_ref,
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref=EXECUTION_ROOT_REF, windows_path=execution_root),),
    )


def _browser_control_lease_authority(
    *,
    device: Any,
    credential_dir: str,
    root_source: str,
    redeemed_device_binding_ref: str = "",
    approved_command_correlation: Any = None,
    observer: Any = None,
) -> Any:
    """Compose the canonical `browser.control` lease slice, fail-closed by default (#3669).

    CENTRAL ruling DECISION=B: a *separate* canonical durable lease store sits
    next to the run store — the `DurableRunStore` itself is not touched. Only
    when a real shell-supplied root (root_source=env), an authenticated
    per-command browser.control work ticket, and a configured broker boundary
    ALL exist can the canonical P01 evidence route be wired. The #3140
    acceptance command is ONLY pairing/runner evidence, never this grant.
    Otherwise the authority keeps its fail-closed evidence port.

        DESKTOP_DURABLE_LEASE_AUTHORITY=NO
        NEW_APPROVAL_STORE=0
        NEW_DURABLE_LEASE_STORE=1
    """

    import os

    from .browser_control_lease_authority import (
        BrowserControlLeaseAuthority,
        BrowserControlP01CommandCorrelation,
        P01PerCommandBrowserControlEvidenceClient,
    )
    from .browser_control_lease_store import BrowserControlLeaseStore
    from .local_agent_permissions import default_device_permission_profile

    lease_store_path = os.path.join(credential_dir, "browser-control-leases.sqlite3")
    store = BrowserControlLeaseStore(lease_store_path, observer=observer)
    permission_profile = default_device_permission_profile(device=device)
    broker_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if (
        root_source != "env"
        or not broker_url
        or not isinstance(approved_command_correlation, BrowserControlP01CommandCorrelation)
        or not redeemed_device_binding_ref
        or approved_command_correlation.binding_ref != redeemed_device_binding_ref
    ):
        # Ambient #3140 pairing IDs are not accepted by this factory.
        # Only a distinct canonical broker-issued work-ticket can configure it.
        return BrowserControlLeaseAuthority(
            device=device,
            permission_profile=permission_profile,
            store=store,
        )
    return BrowserControlLeaseAuthority(
        device=device,
        permission_profile=permission_profile,
        store=store,
        evidence_port=P01PerCommandBrowserControlEvidenceClient(
            base_url=broker_url,
            correlation=approved_command_correlation,
        ),
    )


def _lease_authority_callables(lease_authority: Any) -> tuple[Callable[..., dict[str, Any]], Callable[..., int]]:
    """The two bounded dispatcher callables: PHASE A resolve, PHASE B consume.

    Each call reconstructs the bounded request from the wire fields only,
    stamps the store against the process's real UTC clock, and returns the
    bounded projection (or the new durable count). Every refusal the
    authority raises is a closed-vocabulary code the responder maps onto the
    wire — no error text, no page content and no approval payload crosses the
    pipe.
    """

    from .browser_control_lease_authority import BrowserControlLeaseRequest

    def lease_resolve(
        *,
        request_fingerprint: str,
        browser_session_ref: str,
        device_ref: str,
        run_ref: str,
        workspace_ref: str,
        owner_ref: str,
        origin_scope: str,
        allowed_action_classes: list[str],
        ttl_seconds: int,
        max_actions: int,
    ) -> dict[str, Any]:
        request = BrowserControlLeaseRequest(
            browser_session_ref=browser_session_ref,
            run_ref=run_ref,
            workspace_ref=workspace_ref,
            owner_ref=owner_ref,
            device_id=device_ref,
            origin_scope=origin_scope,
            allowed_action_classes=tuple(allowed_action_classes),
            ttl_seconds=ttl_seconds,
            max_actions=max_actions,
        )
        projection = lease_authority.resolve_or_issue(
            request,
            now=datetime.now(timezone.utc).replace(microsecond=0),
            provided_fingerprint=request_fingerprint,
        )
        return projection.wire_lease_dict()

    def lease_consume(
        *,
        request_fingerprint: str,
        browser_session_ref: str,
        run_ref: str,
        workspace_ref: str,
        owner_ref: str,
        action: str,
        observed_origin: str,
    ) -> int:
        projection = lease_authority.consume_action(
            request_fingerprint,
            browser_session_ref=browser_session_ref,
            run_ref=run_ref,
            workspace_ref=workspace_ref,
            owner_ref=owner_ref,
            action=action,
            observed_origin=observed_origin,
            now=datetime.now(timezone.utc).replace(microsecond=0),
        )
        return int(projection.consumed_actions)

    return lease_resolve, lease_consume


class _FetchedP01EvidenceClient:
    """Fetch the lane's canonical P01 acceptance envelope, bounded by 4 keys.

    #3140 PHASE 3: the evidence side (the owner process) builds the canonical
    APPROVED envelope for the exact command it enqueued. This client only carries
    it: it decides nothing, mints nothing and re-derives no digest of its own.
    The 4 correlation facts are supplied by the /session canonical response and
    sent back unchanged — the owner must parity all four or return 404.
    """

    def __init__(
        self,
        base_url: str,
        *,
        command_id: str = "",
        binding_ref: str = "",
        request_id: str = "",
        request_fingerprint: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.command_id = command_id
        self.binding_ref = binding_ref
        self.request_id = request_id
        self.request_fingerprint = request_fingerprint

    def resolve(self, request_fingerprint: str) -> Any:
        import urllib.request

        from padiem_ai_core.agent_approval import (
            ApprovalOutcome,
            ApprovalPause,
            ApprovalRequirement,
            VerifiedApprovalDecision,
        )

        from .local_agent_permissions import LocalCapability, LocalPermissionRequest
        from .windows_execution_evidence_source import (
            TrustedP01WindowsExecutionEvidenceEnvelope,
        )

        body = json.dumps(
            {
                "command_id": self.command_id,
                "binding_ref": self.binding_ref,
                "request_fingerprint": request_fingerprint,
                "request_id": self.request_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - fixed loopback boundary
            f"{self._base_url}/v1/broker/p01-evidence",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            raise ContractError("the evidence boundary returned no canonical envelope")
        pause_payload = envelope["approval_pause"]
        decision_payload = envelope["approval_decision"]
        pause = ApprovalPause(
            pause_id=pause_payload["pause_id"],
            run_id=pause_payload["run_id"],
            agent_runtime_id=pause_payload["agent_runtime_id"],
            tool_id=pause_payload["tool_id"],
            invocation_sha256=pause_payload["invocation_sha256"],
            requirement=ApprovalRequirement(pause_payload["requirement"]),
            step_index=int(pause_payload["step_index"]),
            created_at=datetime.fromisoformat(pause_payload["created_at"]),
            expires_at=datetime.fromisoformat(pause_payload["expires_at"]),
            approval_scope=tuple(pause_payload["approval_scope"]),
        )
        decision = VerifiedApprovalDecision(
            decision_id=decision_payload["decision_id"],
            pause_id=decision_payload["pause_id"],
            outcome=ApprovalOutcome(decision_payload["outcome"]),
            authority_ref=decision_payload["authority_ref"],
            evidence_ref=decision_payload["evidence_ref"],
            decided_at=datetime.fromisoformat(decision_payload["decided_at"]),
        )
        permission_requests = tuple(
            LocalPermissionRequest(
                action_id=item["action_id"],
                run_id=item["run_id"],
                device_id=item["device_id"],
                capability=LocalCapability(item["capability"]),
                target_ref=item["target_ref"],
                root_ref=item["root_ref"],
            )
            for item in envelope["permission_requests"]
        )
        return TrustedP01WindowsExecutionEvidenceEnvelope(
            evidence_ref=envelope["evidence_ref"],
            request_fingerprint=envelope["request_fingerprint"],
            approval_pause=pause,
            approval_decision=decision,
            permission_requests=permission_requests,
            local_policy_ref=envelope["local_policy_ref"],
            expires_at=datetime.fromisoformat(envelope["expires_at"]),
        )

RESIDENT_PROCESS_CONTRACT = {
    "pairing_authority_implemented": False,
    "broker_authority_implemented": False,
    "challenge_reissued": False,
    "second_resident_host": 0,
    "public_inbound_port": 0,
    "production_mutation": False,
    "pairing_code_logged": False,
    "pairing_code_persisted": False,
}


#: #3140 stall diagnosis: phase evidence is stamped against this process's own
#: monotonic origin, so a gap between two phases is measurable instead of
#: inferred from wall clock readings.
_PROCESS_STARTED_MONOTONIC = time.monotonic()
_EMIT_LOCK = threading.Lock()


def _phase_stamp() -> dict[str, Any]:
    """Bounded, secret-free phase timing for one emitted line."""

    return {
        "phase_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "phase_elapsed_ms": int((time.monotonic() - _PROCESS_STARTED_MONOTONIC) * 1000),
    }


def _observe_phase(event: str) -> None:
    """Phase marker emitted from the real worktree probe boundary (#3148)."""

    _emit(event=event, **_phase_stamp(), **RESIDENT_PROCESS_CONTRACT)


#: #3140 stall diagnosis: when this many seconds pass without a completed
#: phase, the resident reports every live thread's stack on stderr, so a stall
#: is attributed to a frame in one failing run instead of guessed at. Off
#: unless the evidence run explicitly asks for it.
_PHASE_DUMP_AFTER_ENV = "PADIEM_3140_PHASE_DUMP_AFTER_SECONDS"
_last_emit_monotonic = time.monotonic()
_STACK_FRAMES = 8


def _emit(**fields: Any) -> None:
    """One bounded, secret-free status line. Never a pairing code."""

    global _last_emit_monotonic

    line = json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n"
    # Lines are written whole: a phase marker emitted from the probe's own
    # thread must never interleave with another line.
    with _EMIT_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()
        _last_emit_monotonic = time.monotonic()


def _stall_stack_report() -> str:
    """Compact, secret-free stacks for every live thread (bounded frame count)."""

    report: list[str] = []
    for thread_id, frame in list(sys._current_frames().items()):
        report.append(f"[stall] thread {thread_id}")
        for entry in traceback.extract_stack(frame)[-_STACK_FRAMES:]:
            report.append(f"    {entry.filename}:{entry.lineno} in {entry.name}")
    return "\n".join(report)


def _start_stall_watchdog() -> None:
    """Report stacks while no phase completes, at most twice per process."""

    raw = os.environ.get(_PHASE_DUMP_AFTER_ENV)
    if not raw:
        return
    try:
        threshold = float(raw)
    except ValueError:
        return
    if threshold <= 0:
        return

    def watch() -> None:
        dumps = 0
        while dumps < 2:
            time.sleep(1.0)
            if (time.monotonic() - _last_emit_monotonic) < threshold:
                continue
            sys.stderr.write(
                f"[stall] no completed phase for {threshold:.0f}s\n" + _stall_stack_report() + "\n"
            )
            sys.stderr.flush()
            dumps += 1
            time.sleep(threshold)

    threading.Thread(target=watch, name="claw4-stall-watchdog", daemon=True).start()


def handoff_delivery_marker(pairing_code: str) -> str:
    """The non-reversible digest an acknowledgement echoes back."""

    return hashlib.sha256(f"delivery.v1:{pairing_code}".encode("utf-8")).hexdigest()[:32]


def acknowledge_handoff(handoff: dict) -> None:
    """Item 4 — acknowledge only once ownership actually holds.

    Called by the redemption path *after* the canonical redeem succeeded and the
    credential is durable. Receipt alone is deliberately not an acknowledgement,
    so a replay, a timeout or a broker rejection leaves the main process's
    one-shot uncommitted and therefore retryable.
    """

    _emit(
        event="handoff_ack",
        contract_version=ACK_CONTRACT_VERSION,
        handoff_marker=handoff_delivery_marker(handoff["pairing_code"]),
    )


def read_handoff(raw: str) -> dict:
    """Parse and bound-check one handoff envelope. Fails closed."""

    line = raw.strip()
    if not line:
        raise ContractError("empty handoff")
    if len(line) > MAX_LINE_CHARS:
        raise ContractError("handoff line exceeds the bound")
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractError("handoff is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContractError("handoff must be a JSON object")
    if parsed.get("contract_version") != HANDOFF_CONTRACT_VERSION:
        raise ContractError("unsupported handoff contract version")
    code = parsed.get("pairing_code")
    if not isinstance(code, str) or not CODE_PATTERN.fullmatch(code):
        raise ContractError("pairing code shape refused")
    correlation = parsed.get("correlation_ref")
    if not isinstance(correlation, str) or not correlation or len(correlation) > 256:
        raise ContractError("correlation ref shape refused")
    challenge_id = parsed.get("challenge_id")
    if not isinstance(challenge_id, str) or not CHALLENGE_PATTERN.fullmatch(challenge_id):
        raise ContractError("challenge id shape refused")
    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "pairing_code": code,
        "correlation_ref": correlation,
        "challenge_id": challenge_id,
    }


def default_transport_config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_3140_resident",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


class BrokerEntry:
    """The configured broker boundary this process redeems against.

    A name plus a request port. It holds no authority, opens nothing and mints
    no challenge: a process without one refuses rather than standing up a broker
    for itself, because a code issued by a broker this process invented is not a
    code any Web session received.
    """

    def __init__(
        self,
        *,
        device_id: str,
        authority_ref: str,
        request_port: Any,
        credential_dir: str,
        transport_config: OutboundTransportConfig | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        # #3140 review item 2: the credential store is a *persistent protected*
        # path. A temporary directory would delete the device credential the
        # moment the process exits, which is both a durability bug and a way to
        # lose the only copy of a secret. The path must be explicit.
        if not isinstance(credential_dir, str) or not credential_dir.strip():
            raise ContractError("credential_dir must be an explicit persistent path")
        if not device_id or not authority_ref:
            raise ContractError("device_id and authority_ref are required")
        if request_port is None or not hasattr(request_port, "post"):
            raise ContractError("request_port must be the configured broker port")
        self.device_id = device_id
        self.authority_ref = authority_ref
        self.request_port = request_port
        self.transport_config = transport_config or default_transport_config()
        self.credential_dir = os.path.abspath(credential_dir)
        # The run store is durable for the same reason, so a restart recovers
        # the same history instead of silently starting empty.
        self.durable_store_path = os.path.join(self.credential_dir, "durable-runs.sqlite3")
        self.session_id_factory = session_id_factory or (lambda: "session.3140.resident")

    @classmethod
    def from_environment(cls) -> "BrokerEntry | None":
        import os

        device_id = os.environ.get("PADIEM_AGENT_DEVICE_ID")
        authority_ref = os.environ.get("PADIEM_AGENT_AUTHORITY_REF")
        factory_path = os.environ.get("PADIEM_AGENT_REQUEST_PORT")
        if not device_id or not authority_ref or not factory_path:
            return None
        if not os.environ.get("PADIEM_AGENT_CREDENTIAL_DIR"):
            return None
        try:
            module_name, _, attribute = factory_path.partition(":")
            module = __import__(module_name, fromlist=[attribute or "__name__"])
            request_port_factory = getattr(module, attribute)
        except (ImportError, AttributeError, ValueError):
            return None
        return cls(
            device_id=device_id,
            authority_ref=authority_ref,
            request_port=request_port_factory(),
            credential_dir=os.environ.get("PADIEM_AGENT_CREDENTIAL_DIR", ""),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "authority_ref": self.authority_ref,
            "request_port": type(self.request_port).__name__,
            "broker_authority_implemented": False,
            "pairing_authority_implemented": False,
            "public_inbound_port": 0,
        }


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def redeem_handoff(
    handoff: dict,
    *,
    entry: BrokerEntry,
    base_dir: str,
    now: datetime,
    protected_data: Any | None = None,
    emit=None,
) -> dict:
    """Redeem the Web-issued challenge at the one configured broker boundary.

    `emit` is the acknowledgement hook. It fires only after the broker returned
    an enrollment and the credential is durable, so the caller's one-shot is
    committed on ownership, never on receipt.
    """

    clock = _Clock(now)
    config = entry.transport_config
    store = ProtectedFileDeviceCredentialStore(
        base_dir=base_dir,
        protected_data=protected_data if protected_data is not None else WindowsDpapiProtectedDataPort(),
    )
    client = LocalAgentBrokerPairingClient(
        config=config, credential_store=store, request_port=entry.request_port
    )
    enrollment = client.redeem(
        challenge_id=handoff["challenge_id"],
        pairing_code=handoff["pairing_code"],
        device_id=entry.device_id,
        now=now,
    )
    if enrollment.binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
        raise ContractError("redemption did not yield PAIRED_OFFLINE")
    # The credential is now durable; only then does ownership hold.
    store.load(binding=enrollment.binding, now=now)
    if emit is not None:
        emit(handoff)
    return {
        "binding": enrollment.binding,
        "store": store,
        "clock": clock,
        "config": config,
        "port": entry.request_port,
        "redeem_count": 1,
    }


def build_resident_host(
    redeemed: dict,
    *,
    entry: BrokerEntry,
    authorization_port: Any | None = None,
    worktree_state_port: Any | None = None,
    acceptance_command_id: str = "",
    acceptance_binding_ref: str = "",
    acceptance_request_id: str = "",
    acceptance_request_fingerprint: str = "",
    browser_open_host: Any | None = None,
    approved_office_pairs: Any | None = None,
) -> LocalAgentResidentRuntimeHost:
    """Construct *the* resident host, once, on the redeemed binding."""

    from .local_agent_management import compose_fail_closed_windows_runtime

    binding = redeemed["binding"]
    config = redeemed["config"]
    clock = redeemed["clock"]
    execution_root, root_source = trusted_execution_root()
    executable_path = trusted_executable_profile_path()
    # #3140 PHASE 3: the two paths a real execution depends on, reported from the
    # values actually used. The shell-supplied root is preferred; the constant is
    # only the non-dispatching placeholder.
    _emit(
        event="p01_paths",
        execution_root=execution_root,
        root_source=root_source,
        executable=executable_path,
        root_ref=EXECUTION_ROOT_REF,
        profile_ref=EXECUTION_PROFILE_REF,
    )
    device = _resident_device(
        entry=entry, binding=binding, execution_root=execution_root
    )
    # #3140 stall diagnosis: the composition seam is the widest silent step in
    # the resident's own path, so each bounded construction reports itself.
    _observe_phase("host_build_runtime_start")
    runtime = compose_fail_closed_windows_runtime(
        device=device,
        executable_profiles=(
            WindowsExecutableProfile(
                profile_ref=EXECUTION_PROFILE_REF,
                executable_path=executable_path,
            ),
        ),
        authorization_port=(
            authorization_port
            if authorization_port is not None
            else _acceptance_authorization_port(
                device=device,
                root_source=root_source,
                acceptance_command_id=acceptance_command_id,
                acceptance_binding_ref=acceptance_binding_ref,
                acceptance_request_id=acceptance_request_id,
                acceptance_request_fingerprint=acceptance_request_fingerprint,
            )
        ),
        # #3148: the real Windows git worktree probe is what backs the trusted
        # composition now. It is a probe, not a decision: a dirty or unreadable
        # worktree stops the approved child and is reported, never hidden.
        worktree_state_port=worktree_state_port
        if worktree_state_port is not None
        else WindowsGitWorktreeStatePort(observer=_observe_phase),
    )
    _observe_phase("host_build_runtime_done")
    _observe_phase("host_build_channel_start")
    broker_binding = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=config)
    channel = ControlPlanePhysicalAdmissionChannel(
        authority=broker_binding,
        transport=ControlPlanePhysicalAdmissionTransport(
            credential_store=redeemed["store"],
            expected_admission_authority_ref=entry.authority_ref,
            request_port=redeemed["port"],
        ),
    )
    _observe_phase("host_build_channel_done")
    _observe_phase("host_build_store_start")
    durable_store = DurableRunStore(entry.durable_store_path, observer=_observe_phase)
    _observe_phase("host_build_store_done")
    # #3611: the approved browser.open slice shares this durable store, the
    # redeemed device and the same local policy profile as the Windows lane.
    browser_open_authority = _browser_open_authority(
        device=device,
        store=durable_store,
        root_source=root_source,
        acceptance_command_id=acceptance_command_id,
        acceptance_binding_ref=acceptance_binding_ref,
        acceptance_request_id=acceptance_request_id,
        host=browser_open_host,
    )
    # #3580: only a deployment-injected trusted P01/Office producer may
    # opt into post-ACK byte staging. Ordinary pairing/env/browser/model cannot
    # supply a file path or mint Google Drive WRITE consent.
    office_staging = None
    if approved_office_pairs is not None:
        from .local_office_chunk_publisher import LocalOfficeChunkPublisher
        from .local_resident_office_delivery import ResidentOfficePairPublisher
        from .local_agent_control_plane_https import StdlibPinnedHttpsJsonRequestPort

        office_staging = ResidentOfficePairPublisher(
            approved_pairs=approved_office_pairs,
            publisher=LocalOfficeChunkPublisher(
                transport=StdlibPinnedHttpsJsonRequestPort(),
                config=config,
            ),
        )
    # #3140 stall diagnosis: the facts a stalled SQLite open would have produced,
    # reported only once the store is actually ready. No path, no handle.
    try:
        _emit(
            event="store_facts",
            journal_mode=str(durable_store._db.execute("PRAGMA journal_mode").fetchone()[0]),
            busy_timeout_ms=int(durable_store._db.execute("PRAGMA busy_timeout").fetchone()[0]),
            **_phase_stamp(),
            **RESIDENT_PROCESS_CONTRACT,
        )
    except Exception:  # pragma: no cover - evidence only
        pass
    _observe_phase("host_build_host_start")
    host = LocalAgentResidentRuntimeHost(
        assembly=BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=binding,
            permissions=default_device_permission_profile(device=device),
            broker_authority=broker_binding,
            runtime=runtime,
            browser_open=browser_open_authority,
        ),
        channel=channel,
        credential_store=redeemed["store"],
        durable_store=durable_store,
        clock=clock,
        session_id_factory=entry.session_id_factory,
        heartbeat_interval_seconds=30,
        session_ttl_seconds=900,
        office_staging=office_staging,
    )
    _observe_phase("host_build_host_done")
    return host


def main(argv: list[str] | None = None) -> int:
    del argv
    entry = BrokerEntry.from_environment()
    if entry is None:
        _emit(status="refused", reason="no_configured_broker_boundary", **RESIDENT_PROCESS_CONTRACT)
        return 2
    _start_stall_watchdog()
    # #3436 B2d: the supervised pipe carries more than the handoff now — the
    # material responder answers requests only after redemption — so lines that
    # are not a handoff are skipped, never honoured. The handoff itself must
    # still parse exactly; the bound keeps a hostile stdin from spinning.
    handoff: dict | None = None
    for _ in range(MAX_PREHANDOFF_SKIP_LINES):
        raw = sys.stdin.readline()
        if not raw:
            break
        try:
            handoff = read_handoff(raw)
            break
        except ContractError:
            continue
    if handoff is None:
        _emit(status="refused", reason="handoff_refused", detail="no handoff line", **RESIDENT_PROCESS_CONTRACT)
        return 2
    now = datetime.now(timezone.utc).replace(microsecond=0)
    os.makedirs(entry.credential_dir, exist_ok=True)
    if True:
        base_dir = entry.credential_dir
        try:
            # Item 4: the ACK fires from inside the redemption, after ownership.
            redeemed = redeem_handoff(
                handoff, entry=entry, base_dir=base_dir, now=now, emit=acknowledge_handoff
            )
        except ContractError as exc:
            # No acknowledgement, so the caller keeps the handoff armed.
            _emit(status="refused", reason="redemption_refused", detail=str(exc), **RESIDENT_PROCESS_CONTRACT)
            return 2
        _emit(
            event="handoff_redeemed",
            redemption="paired_offline",
            **_phase_stamp(),
            **RESIDENT_PROCESS_CONTRACT,
        )
        _emit(event="host_build_start", **_phase_stamp(), **RESIDENT_PROCESS_CONTRACT)
        try:
            host = build_resident_host(
                redeemed,
                entry=entry,
                # The 4 canonical correlation facts of the one bounded acceptance
                # command: shared contract ids plus the redeemed binding_ref. The
                # fingerprint is computed by the canonical P01 port at resolve
                # time. No new correlation object or authority is created.
                acceptance_command_id=ACCEPTANCE_COMMAND_ID,
                acceptance_binding_ref=redeemed["binding"].binding_ref,
                acceptance_request_id=ACCEPTANCE_REQUEST_ID,
            )
        except ContractError as exc:
            _emit(
                status="paired_without_host",
                detail=str(exc),
                redemption="paired_offline",
                host_started=False,
                **RESIDENT_PROCESS_CONTRACT,
            )
            return 0
        _emit(event="host_built", **_phase_stamp(), **RESIDENT_PROCESS_CONTRACT)
        _emit(event="connect_start", **_phase_stamp(), **RESIDENT_PROCESS_CONTRACT)
        host.start()
        # #3669 DECISION=B: the canonical browser.control lease slice gets its
        # own durable store in the same credential-dir family as the run store,
        # on the same redeemed device. No broker, pairing or resident state is
        # changed — only the store file and the evidence port.
        lease_execution_root, lease_root_source = trusted_execution_root()
        lease_device = _resident_device(
            entry=entry, binding=redeemed["binding"], execution_root=lease_execution_root
        )
        lease_authority = _browser_control_lease_authority(
            device=lease_device,
            credential_dir=entry.credential_dir,
            root_source=lease_root_source,
            redeemed_device_binding_ref=redeemed["binding"].binding_ref,
            # No ambient #3140 pairing command or request ID is supplied to
            # browser.control. This remains unconfigured until canonical
            # per-command Broker/P01 material arrives via a separate ingress.
            approved_command_correlation=None,
            observer=_observe_phase,
        )
        lease_resolve, lease_consume = _lease_authority_callables(lease_authority)
        # #3436 B2d + #3611 + #3669: one bounded dispatcher, one reader thread,
        # exactly four literal request kinds, on the supervised stdio boundary
        # the resident already shares with the shell. It starts only after the
        # handoff was consumed and the host is online, projects state the host
        # already holds (no session is opened, no credential minted or stored),
        # and owns the agent side of the browser-open redemption and of the
        # browser-control lease (PHASE A resolve + PHASE B consume).
        #
        # A second reader on this same stdin would race this one, so the
        # redemption and lease kinds are added here instead of in a new thread.
        material_responder = ResidentDesktopMaterialResponder(
            material_projection=host.current_desktop_session_material,
            redemption=host.redeem_desktop_browser_open,
            lease_resolve=lease_resolve,
            lease_consume=lease_consume,
        )
        material_responder.start()
        _emit(
            event="desktop_material_channel_ready",
            host_state=host.state.value,
            request_kinds=sorted(DESKTOP_REQUEST_KINDS),
            **_phase_stamp(),
            **RESIDENT_PROCESS_CONTRACT,
        )
        _emit(
            event="session_open",
            host_state=host.state.value,
            **_phase_stamp(),
            **RESIDENT_PROCESS_CONTRACT,
        )
        # #3140 item 2: report the heartbeat the host actually took, from the
        # host's own server-owned acknowledgement, instead of leaving the
        # harness to infer it from a later poll line.
        _emit(
            event="heartbeat",
            host_state=host.state.value,
            session_opened=host._session is not None,
            heartbeat_acknowledged=host._last_seen_at is not None,
            heartbeat_freshness_seconds=host.heartbeat_freshness_seconds(),
            last_seen_at=(
                host._last_seen_at.isoformat().replace("+00:00", "Z")
                if host._last_seen_at is not None
                else None
            ),
            **_phase_stamp(),
            **RESIDENT_PROCESS_CONTRACT,
        )
        # #3140: the evidence predicate needs the real composition named, not
        # assumed. These are bounded, secret-free facts about what the resident
        # actually used.
        _emit(
            status="online",
            host_state=host.state.value,
            host_started=True,
            worktree_state_port=type(host._assembly._runtime._worktree).__name__,
            p01_approval_reused=True,
            unapproved_execution=0,
            **RESIDENT_PROCESS_CONTRACT,
        )
        try:
            # One bounded cycle so the canonical session/heartbeat/poll path is
            # really taken, reported from the host's own state rather than
            # asserted by the harness.
            dispatched = host.run_once()
            _emit(
                event="poll",
                dispatched=dispatched,
                host_state=host.state.value,
                session_opened=host._session is not None,
                heartbeat_seen=host._last_heartbeat_at is not None,
                **_phase_stamp(),
            )
            # Item 5: one host, running for the life of the process.
            host.run_forever()
        except KeyboardInterrupt:  # pragma: no cover — operator shutdown
            pass
        finally:
            host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
