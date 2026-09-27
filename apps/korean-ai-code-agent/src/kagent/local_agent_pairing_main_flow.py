"""#3140 — the runner-side main flow: pairing handoff in, canonical session out.

The Electron main process hands this process exactly one bounded pairing
handoff. Everything after that point is *existing* machinery, composed and
never re-implemented:

    #3095  LocalAgentPairingHandoffRunner / LocalAgentBrokerPairingClient
           the only redemption path, still the only one
    #3014  LocalAgentResidentRuntimeHost
           the only resident host, still the only one
    #3014  BoundLocalAgentRuntimeAssembly + WindowsSubprocessLocalAgentRuntime
           the P01-approved Windows executor, still the only one
    #3080  InMemoryLocalAgentBrokerAuthority + InMemoryBrokerPairingAuthority
           the only broker and pairing authority, still the only ones

This module adds no authority, no executor and no host. It is the composition
root the supervised runner executes, and it is deliberately non-Production: the
broker and the pairing authority are in-process.

    PAIRING_AUTHORITY_IMPLEMENTED=NO
    RESIDENT_HOST_IMPLEMENTED=NO
    EXECUTION_AUTHORITY_IMPLEMENTED=NO
    SECOND_PAIRING_AUTHORITY=0
    SECOND_RESIDENT_HOST=0
    PUBLIC_INBOUND_PORT=0
    PRODUCTION_MUTATION=0
    PAIRING_CODE_LOGGED=0
    PAIRING_CODE_PERSISTED=0

stdin  : one bounded JSON handoff envelope.
stdout : bounded, secret-free status lines. The pairing code is never printed.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

from .contracts import ContractError
from .local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalRoot,
)
from .local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
from .local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from .local_agent_durable_run_store import DurableRunStore
from .local_agent_pairing import DeviceLifecycle
from .local_agent_pairing_handoff import LocalAgentPairingHandoffRunner
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
from .windows_local_executor import WindowsExecutableProfile, WindowsSubprocessLocalAgentRuntime

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import TrustedLocalAgentHttpAuthContext
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PairingAndAdmissionLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

HANDOFF_CONTRACT_VERSION = "claw-desktop-pairing-handoff.v1"
BROKER_PEPPER = b"control-plane-broker-pepper-16bytes!!"
PAIRING_PEPPER = b"control-plane-pairing-pepper16byte!!"
AUTHORITY_REF = "control-plane.local-agent-broker.3140.runner.v1"
CODE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MAX_LINE_CHARS = 4_096
ACCOUNT_REF = "account.1"
WORKSPACE_REF = "workspace.1"


def _emit(**fields: Any) -> None:
    """One bounded, secret-free status line. Never a pairing code."""

    sys.stdout.write(json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(reason: str, **extra: Any) -> int:
    _emit(status="refused", reason=reason, **extra)
    return 2


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

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


class _MaterialResolver:
    def resolve(self, request: Any) -> dict:
        raise AssertionError("the pairing main flow must not resolve command material")


class _References:
    def __call__(self) -> tuple[str, str]:
        return "admission_3140_runner_1", "evidence_3140_runner_1"


class _Nonces:
    def __init__(self) -> None:
        self._next = 0xC0000

    def __call__(self) -> str:
        self._next += 1
        return f"{self._next:032x}"


class _InProcessPort:
    """Loopback adapter into the real deployable handler. Opens no socket."""

    def __init__(self, *, handler: Any, auth: Any, clock: _Clock, audit: list[str]) -> None:
        self._handler = handler
        self._auth = auth
        self._clock = clock
        self.audit = audit

    def post(self, *, config: Any, operation: Any, payload: dict, timeout_seconds: int) -> dict:
        del config, timeout_seconds
        name = operation.value
        self.audit.append(name)
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            self._clock.now = datetime.fromisoformat(str(payload["now"]).replace("Z", "+00:00"))
        response = self._handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self._auth,
        )
        return json.loads(json.dumps(response.body))


class _RecordingClient:
    """The #3095 client, wrapped so the enrollment the runner obtained is visible.

    The redemption happens exactly once, inside the handoff runner. This wrapper
    adds no behaviour: it delegates to the canonical client and remembers the
    enrollment the runner already produced, so the resident host is composed
    from the same redemption rather than a second one.
    """

    def __init__(self, inner: LocalAgentBrokerPairingClient) -> None:
        self._inner = inner
        self.enrollment: Any | None = None
        self.redeem_count = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def redeem(self, **kwargs: Any) -> Any:
        self.redeem_count += 1
        enrollment = self._inner.redeem(**kwargs)
        self.enrollment = enrollment
        return enrollment


def _transport_config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_3140_runner",
            url="https://local-agent.padiem.net:443/broker",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


def read_handoff(raw: str) -> dict:
    """Parse and bound-check the one handoff envelope. Fails closed."""

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
    return {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "pairing_code": code,
        "correlation_ref": correlation,
    }


def run(
    handoff: dict,
    *,
    base_dir: str,
    device_id: str,
    now: datetime,
    protected_data: Any | None = None,
) -> dict:
    """Redeem once through the #3095 runner, then drive the #3014 host.

    `protected_data` is the credential-store's protection port. It defaults to
    the real Windows DPAPI adapter — the deployed shape — and is injectable so
    the composition itself can be exercised on a non-Windows CI host without
    pretending DPAPI exists there. The Windows evidence run always uses the
    real adapter.
    """

    clock = _Clock(now)
    authority = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF)
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=authority,
        code_nonce_factory=_Nonces(),
        credential_factory=lambda: b"3140-runner-device-credential",
    )
    handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
        pairing_authority=pairing,
        admission_reference_factory=_References(),
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=_MaterialResolver(),
        clock=clock,
    )
    browser = TrustedLocalAgentHttpAuthContext(
        principal_ref="principal.browser.3140",
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        authenticated=True,
        tls_verified=True,
    )
    issued = handler.handle(
        method="POST",
        route=PAIRING_CHALLENGE_ROUTE,
        content_type="application/json",
        body=json.dumps(
            {
                "account_ref": ACCOUNT_REF,
                "workspace_ref": WORKSPACE_REF,
                "now": now.isoformat(),
                "ttl_seconds": 300,
            }
        ).encode("utf-8"),
        auth=browser,
    ).body
    challenge_id = issued["challenge"]["challenge_id"]
    issued_code = issued["pairing_code"]

    # #3080 owns issuance, so the runner may only redeem a code the broker
    # actually issued. In the deployed product the same broker issued this code
    # to the signed-in web session, which put it in the `padiem://` deep link;
    # in this in-process composition the issuance happens here, and the handoff
    # must be the one that issuance produced. Anything else is refused rather
    # than redeemed — a code nobody issued is exactly what a possession proof
    # exists to stop.
    if handoff["pairing_code"] != issued_code:
        raise ContractError("handoff code is not the code this broker issued")

    config = _transport_config()
    store = ProtectedFileDeviceCredentialStore(
        base_dir=base_dir,
        # The real protected store on Windows. The credential never reaches a
        # log, the renderer, or this process's own output.
        protected_data=protected_data if protected_data is not None else WindowsDpapiProtectedDataPort(),
    )
    device_auth = TrustedLocalAgentHttpAuthContext(
        principal_ref=device_id,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        authenticated=True,
        tls_verified=True,
    )
    port = _InProcessPort(handler=handler, auth=device_auth, clock=clock, audit=[])
    client = _RecordingClient(
        LocalAgentBrokerPairingClient(config=config, credential_store=store, request_port=port)
    )
    runner = LocalAgentPairingHandoffRunner(config=config, credential_store=store, client=client)
    redemption = runner.redeem_handoff(
        pairing_code=issued_code,
        challenge_id=challenge_id,
        device_id=device_id,
        correlation_ref=handoff["correlation_ref"],
        now=now,
    )
    if redemption.binding_state != DeviceLifecycle.PAIRED_OFFLINE.value:
        raise ContractError("redemption did not yield PAIRED_OFFLINE")
    if redemption.pairing_code_logged or redemption.pairing_code_persisted:
        raise ContractError("redemption reported a logged or persisted pairing code")
    if client.redeem_count != 1 or client.enrollment is None:
        raise ContractError("redemption did not happen exactly once")

    paired_offline = client.enrollment.binding
    broker_binding = PinnedOutboundBrokerBinding.from_binding(binding=paired_offline, config=config)
    channel = ControlPlanePhysicalAdmissionChannel(
        authority=broker_binding,
        transport=ControlPlanePhysicalAdmissionTransport(
            credential_store=store,
            expected_admission_authority_ref=AUTHORITY_REF,
            request_port=port,
        ),
    )
    device = LocalAgentDeviceProfile(
        device_id=device_id,
        workspace_ref=WORKSPACE_REF,
        platform=LocalAgentPlatform.WINDOWS,
        # The device profile describes the *target* device, which is Windows by
        # contract; the credential store keeps its own OS-native temp directory.
        roots=(LocalRoot(root_ref="root.3140", windows_path=r"C:\ProgramData\Padiem\runner"),),
    )
    runtime = WindowsSubprocessLocalAgentRuntime(
        device=device,
        executable_profiles=(
            WindowsExecutableProfile(
                profile_ref="profile.3140.python",
                executable_path=sys.executable,
            ),
        ),
    )
    assembly = BoundLocalAgentRuntimeAssembly(
        device=device,
        binding=paired_offline,
        permissions=default_device_permission_profile(device=device),
        broker_authority=broker_binding,
        runtime=runtime,
    )
    host = LocalAgentResidentRuntimeHost(
        assembly=assembly,
        channel=channel,
        credential_store=store,
        durable_store=DurableRunStore(":memory:"),
        clock=clock,
        session_id_factory=lambda: "session.3140.runner",
        heartbeat_interval_seconds=30,
        session_ttl_seconds=900,
    )
    host.start()
    host_state = host.state.value
    dispatched = host.run_once()
    host.stop()
    return {
        "status": "ok",
        "redemption": redemption.binding_state,
        "credential_generation": redemption.credential_generation,
        "redeem_count": client.redeem_count,
        "host_state": host_state,
        "host_final_state": host.state.value,
        "dispatched": dispatched,
        "wire_routes": port.audit,
        "public_inbound_port": False,
        "production_mutation": False,
        "pairing_code_logged": False,
        "pairing_code_persisted": False,
        "second_pairing_authority": 0,
        "second_resident_host": 0,
        "second_execution_authority": 0,
    }


def issue_code(*, now: datetime) -> str:
    """The web leg: issue a challenge and return the one-time code.

    Exposed so the Windows evidence run can put the *real* issued code into the
    `padiem://` deep link, exactly as the signed-in web session does. The
    evidence harness is the only caller; the main flow never issues for itself.
    """

    authority = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF)
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=authority,
        code_nonce_factory=_Nonces(),
        credential_factory=lambda: b"3140-runner-device-credential",
    )
    handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
        pairing_authority=pairing,
        admission_reference_factory=_References(),
        rpc=LocalAgentBrokerRpcFacade(authority=authority),
        state=_DurableState(),
        material_resolver=_MaterialResolver(),
        clock=_Clock(now),
    )
    issued = handler.handle(
        method="POST",
        route=PAIRING_CHALLENGE_ROUTE,
        content_type="application/json",
        body=json.dumps(
            {
                "account_ref": ACCOUNT_REF,
                "workspace_ref": WORKSPACE_REF,
                "now": now.isoformat(),
                "ttl_seconds": 300,
            }
        ).encode("utf-8"),
        auth=TrustedLocalAgentHttpAuthContext(
            principal_ref="principal.browser.3140",
            account_ref=ACCOUNT_REF,
            workspace_ref=WORKSPACE_REF,
            authenticated=True,
            tls_verified=True,
        ),
    ).body
    return str(issued["pairing_code"])


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--issue-handoff-code"]:
        # The web leg, for evidence only: prints the one-time code so the
        # harness can put it in the deep link. Never part of the main flow.
        _emit(status="issued", pairing_code=issue_code(now=datetime.now(timezone.utc).replace(microsecond=0)))
        return 0
    raw = sys.stdin.readline()
    try:
        handoff = read_handoff(raw)
    except ContractError as exc:
        return _fail("handoff_refused", detail=str(exc))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with tempfile.TemporaryDirectory(prefix="claw4-3140-runner-") as base_dir:
        try:
            outcome = run(handoff, base_dir=base_dir, device_id="device.3140.runner", now=now)
        except ContractError as exc:
            return _fail("main_flow_contract_refused", detail=str(exc))
        except Exception as exc:  # noqa: BLE001 — a refusal must be truthful, not a crash
            return _fail("main_flow_failed", detail=type(exc).__name__)
    _emit(**outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
