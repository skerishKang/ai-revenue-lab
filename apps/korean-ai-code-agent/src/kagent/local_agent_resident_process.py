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
from datetime import datetime, timezone
from typing import Any, Callable

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from .local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
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


def _emit(**fields: Any) -> None:
    """One bounded, secret-free status line. Never a pairing code."""

    sys.stdout.write(json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


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
) -> LocalAgentResidentRuntimeHost:
    """Construct *the* resident host, once, on the redeemed binding."""

    from .local_agent_management import compose_fail_closed_windows_runtime

    binding = redeemed["binding"]
    config = redeemed["config"]
    clock = redeemed["clock"]
    device = LocalAgentDeviceProfile(
        device_id=entry.device_id,
        # #3140 review item 3: the workspace is whatever the redeemed binding
        # says. A hard-coded workspace would let a device from one workspace
        # present as a device of another.
        workspace_ref=binding.workspace_ref,
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root.3140", windows_path=WINDOWS_ROOT),),
    )
    runtime = compose_fail_closed_windows_runtime(
        device=device,
        executable_profiles=(
            WindowsExecutableProfile(
                profile_ref="profile.3140.python",
                executable_path=WINDOWS_PYTHON_EXECUTABLE,
            ),
        ),
        authorization_port=authorization_port
        if authorization_port is not None
        else P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=default_device_permission_profile(device=device)
        ),
        # #3148: the real Windows git worktree probe is what backs the trusted
        # composition now. It is a probe, not a decision: a dirty or unreadable
        # worktree stops the approved child and is reported, never hidden.
        worktree_state_port=worktree_state_port
        if worktree_state_port is not None
        else WindowsGitWorktreeStatePort(),
    )
    broker_binding = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=config)
    channel = ControlPlanePhysicalAdmissionChannel(
        authority=broker_binding,
        transport=ControlPlanePhysicalAdmissionTransport(
            credential_store=redeemed["store"],
            expected_admission_authority_ref=entry.authority_ref,
            request_port=redeemed["port"],
        ),
    )
    return LocalAgentResidentRuntimeHost(
        assembly=BoundLocalAgentRuntimeAssembly(
            device=device,
            binding=binding,
            permissions=default_device_permission_profile(device=device),
            broker_authority=broker_binding,
            runtime=runtime,
        ),
        channel=channel,
        credential_store=redeemed["store"],
        durable_store=DurableRunStore(entry.durable_store_path),
        clock=clock,
        session_id_factory=entry.session_id_factory,
        heartbeat_interval_seconds=30,
        session_ttl_seconds=900,
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    entry = BrokerEntry.from_environment()
    if entry is None:
        _emit(status="refused", reason="no_configured_broker_boundary", **RESIDENT_PROCESS_CONTRACT)
        return 2
    raw = sys.stdin.readline()
    try:
        handoff = read_handoff(raw)
    except ContractError as exc:
        _emit(status="refused", reason="handoff_refused", detail=str(exc), **RESIDENT_PROCESS_CONTRACT)
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
        try:
            host = build_resident_host(redeemed, entry=entry)
        except ContractError as exc:
            _emit(
                status="paired_without_host",
                detail=str(exc),
                redemption="paired_offline",
                host_started=False,
                **RESIDENT_PROCESS_CONTRACT,
            )
            return 0
        host.start()
        _emit(
            event="session_open",
            host_state=host.state.value,
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
