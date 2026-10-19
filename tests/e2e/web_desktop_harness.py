"""#3098 LOCAL3 — the model-free Web ↔ Control Plane ↔ Desktop E2E composition.

One canonical broker authority is shared by every leg, so nothing here mints a
second execution, pairing or result authority:

    PAIRING_AUTHORITY      = packages/padiem-control-plane InMemoryBrokerPairingAuthority
    APPROVAL_AUTHORITY     = canonical P01 ApprovalPause/VerifiedApprovalDecision objects
    PERMISSION_AUTHORITY   = existing kagent Local Agent permission contracts
    PHYSICAL_EXECUTION     = existing kagent Windows runtimes (process + file)
    WEB_PRESENTATION       = existing padiem-chat Claw routes/app factory

Every transport is an in-process handler-backed port: no socket is opened, no
model/provider is constructed, and the fixture directory is the only filesystem
surface the desktop leg touches.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_access_composition import build_claw_local_access_source
from app.claw_local_task_result_composition import build_local_task_result_source
from app.config import Settings
from app.history import D1HistoryStore

from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_broker_pairing_client import LocalAgentBrokerPairingClient
from kagent.local_agent_command_material import build_command_material_wire_projection
from kagent.local_agent_control_plane_admission import (
    ControlPlanePhysicalAdmissionChannel,
    ControlPlanePhysicalAdmissionTransport,
)
from kagent.local_agent_durable_run_store import DurableRunStore
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_agent_pairing_handoff import LocalAgentPairingHandoffRunner
from kagent.local_agent_permissions import (
    LocalCapability,
    LocalPermissionRequest,
    default_device_permission_profile,
)
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_runtime_host import LocalAgentResidentRuntimeHost, ResidentHostState
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
    ProtectedFileDeviceCredentialStore,
)
from kagent.local_agent_server_projection import project_server_backed_online_binding
from kagent.windows_execution_authorization import (
    WINDOWS_EXECUTION_TOOL_ID,
    DeterministicWindowsExecutionAuthorityEvidencePort,
    P01LocalPermissionWindowsExecutionAuthorizationPort,
    WindowsExecutionAuthorityEvidence,
    windows_execution_tool_invocation,
)
from kagent.windows_local_executor import (
    WindowsExecutableProfile,
    WindowsExecutionReceipt,
    WindowsExecutionTermination,
    WindowsSubprocessLocalAgentRuntime,
    command_request_fingerprint,
)
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)
from padiem_control_plane.local_agent_broker_http import (
    LocalAgentBrokerHttpResponse,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_pairing import InMemoryBrokerPairingAuthority
from padiem_control_plane.local_agent_broker_pairing_http import (
    PairingAndAdmissionLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

# the durable broker runtime is a top-level control-plane module, not a package member
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime  # noqa: E402

AUTHORITY_REF = "control-plane.local-agent-broker.3098.e2e.v1"
PEPPER = b"3098-e2e-broker-pepper-16-bytes!!"
PAIRING_PEPPER = b"3098-e2e-pairing-pepper-16-bytes"
CREDENTIAL = b"3098-e2e-device-credential"
DEVICE_ID = "device.3098.e2e.1"
ROOT_REF = "root.fixture"
WORKSPACE = "workspace.3098.e2e"
OTHER_WORKSPACE = "workspace.3098.e2e.other"
OWNER_SUBJECT = "owner-3098-e2e"
OTHER_SUBJECT = "other-3098-e2e"
COMMAND_TTL_SECONDS = 300
SAMPLE_TEXT = "padiem-3098 non-model e2e fixture\n"
SAMPLE_SHA256 = hashlib.sha256(SAMPLE_TEXT.encode("utf-8")).hexdigest()
SECRET_MARKER_ENV = "PADIEM_3098_E2E_SECRET_MARKER"
SECRET_MARKER_VALUE = "do-not-project-3098"

# The Windows-only real-runtime script: a bounded read of the fixture sample.txt
# whose exit code is the whole proof. It exits non-zero unless the ticket really
# read the exact fixture bytes inside the selected root AND the injected secret
# never reached the bounded child environment. Nothing raw is ever returned: the
# parent sees only the bounded receipt (termination/exit_code), by contract.
SAMPLE_READ_SCRIPT = (
    "import hashlib, os, sys\n"
    "b = open(sys.argv[1], 'rb').read()\n"
    "assert hashlib.sha256(b).hexdigest() == sys.argv[2], 'fixture content mismatch'\n"
    "assert os.environ.get(sys.argv[3]) is None, 'secret leaked into the bounded environment'\n"
    "print('ok')\n"
)

SERVER_ROUTE_OFFSET = {
    "session": 5,
    "heartbeat": None,  # the heartbeat contract: the server clock follows the client's now
    "poll": 15,
    "material": 20,
    "admission": 25,
    "acknowledge": 30,
    "reconcile": 35,
    "v1/broker/pairings/challenge": 2,
    "v1/broker/pairings/redeem": 4,
}


def run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class HarnessClock:
    """One mutable wall clock shared by the server edge and the device client."""

    def __init__(self, start: datetime) -> None:
        self._start = start
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class DeterministicProtectedDataPort:
    """Reversible test adapter only, never live DPAPI."""

    prefix = b"FAKE-PROTECTED-v1:"

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        import hashlib

        mask = hashlib.sha256(entropy).digest()
        return self.prefix + bytes(
            value ^ mask[index % len(mask)] for index, value in enumerate(plaintext)
        )

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        import hashlib

        assert ciphertext.startswith(self.prefix)
        mask = hashlib.sha256(entropy).digest()
        body = ciphertext[len(self.prefix) :]
        return bytes(value ^ mask[index % len(mask)] for index, value in enumerate(body))


class DeviceCredentialStore:
    """The canonical protected-file store over the deterministic DPAPI double."""

    def __init__(self, *, base_dir: Path) -> None:
        self._store = ProtectedFileDeviceCredentialStore(
            base_dir=str(base_dir),
            protected_data=DeterministicProtectedDataPort(),
        )
        #: the exact binding object the desktop last persisted (pairing truth)
        self.last_saved_binding = None

    def save(self, *, binding, credential, now):
        self.last_saved_binding = binding
        return self._store.save(binding=binding, credential=credential, now=now)

    def load(self, *, binding, now):
        return self._store.load(binding=binding, now=now)

    def delete(self, binding_ref: str) -> None:
        self._store.delete(binding_ref)


class DurableSessionState:
    """Dict-backed durable session store satisfying the deployable-edge guard."""

    durable = True

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def save_session(self, record) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str):
        return self.records[session_id]

    def record_last_seen(self, session_id: str, *, seen_at: datetime):
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class MaterialResolver:
    """Serves material for exactly the registered bounded commands."""

    def __init__(self) -> None:
        self._wires: dict[tuple[str, str, str], dict] = {}

    def register(self, *, command_id: str, binding_ref: str, request_fingerprint: str, wire: dict) -> None:
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
        return deepcopy(wire)


class AdmissionReferences:
    """Server-owned, distinct admission/evidence reference pairs."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> tuple[str, str]:
        self.count += 1
        return f"admission.3098.{self.count}", f"evidence.3098.{self.count}"


class DeterministicNonces:
    def __init__(self) -> None:
        self._next = 0x3098_0000

    def __call__(self) -> str:
        self._next += 1
        return f"{self._next:032x}"


class _RequestPortBase:
    """Handler-backed transport port: every broker call stays in-process."""

    def __init__(self, *, handler, server_clock: HarnessClock, audit: list[str], freeze_clock: bool = False) -> None:
        self.handler = handler
        self.server_clock = server_clock
        self.audit = audit
        self.freeze_clock = freeze_clock
        self.calls: list[tuple[str, dict]] = []

    def _auth_for(self, route: str):  # pragma: no cover - overridden
        raise NotImplementedError

    def post(self, *, config, operation, payload, timeout_seconds):
        del config, timeout_seconds
        name = operation.value
        route = f"/{name}"  # pairing ops carry "v1/...", device ops carry bare names
        self.calls.append((name, deepcopy(payload)))
        self.audit.append(name)
        if not self.freeze_clock:
            offset = SERVER_ROUTE_OFFSET.get(name)
            if offset is None and isinstance(payload, dict) and "now" in payload:
                self.server_clock.now = datetime.fromisoformat(payload["now"].replace("Z", "+00:00"))
            elif offset is not None:
                self.server_clock.now = self.server_clock._start + timedelta(seconds=offset)
        response: LocalAgentBrokerHttpResponse = self.handler.handle(
            method="POST",
            route=route,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self._auth_for(route),
        )
        # The real pinned-HTTPS port maps non-200 to a bounded refusal; either
        # way the transport parses the {ok, error} envelope and raises the
        # exact canonical error code, so the body is what crosses this port.
        return deepcopy(response.body)


class DeviceRequestPort(_RequestPortBase):
    """The desktop's port: unauthenticated on redeem, authenticated afterwards."""

    def __init__(self, *, device_id: str, account_ref: str, workspace_ref: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._device_id = device_id
        self._account_ref = account_ref
        self._workspace_ref = workspace_ref

    def _auth_for(self, route: str) -> TrustedLocalAgentHttpAuthContext:
        authenticated = route != "/v1/broker/pairings/redeem"
        return TrustedLocalAgentHttpAuthContext(
            principal_ref=self._device_id,
            account_ref=self._account_ref,
            workspace_ref=self._workspace_ref,
            authenticated=authenticated,
            tls_verified=True,
        )


class WebRequestPort(_RequestPortBase):
    """The signed-in web user's port for minting a pairing challenge."""

    def __init__(self, *, principal_ref: str, account_ref: str, workspace_ref: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._principal_ref = principal_ref
        self._account_ref = account_ref
        self._workspace_ref = workspace_ref

    def _auth_for(self, route: str) -> TrustedLocalAgentHttpAuthContext:
        return TrustedLocalAgentHttpAuthContext(
            principal_ref=self._principal_ref,
            account_ref=self._account_ref,
            workspace_ref=self._workspace_ref,
            authenticated=True,
            tls_verified=True,
        )


class DeterministicReceiptRuntime:
    """The cross-platform desktop double: real receipts, no process spawn."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute_with_receipt(self, request: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.executed.append(request.request_id)
        return WindowsExecutionReceipt(
            result=LocalCommandResult(
                request_id=request.request_id,
                run_id=request.run_id,
                device_id=request.device_id,
                root_ref=request.root_ref,
                started_at=now,
                ended_at=now + timedelta(milliseconds=1),
                exit_code=0,
                stdout="padiem-3098-receipt-output",
                stderr="",
                cancelled=False,
                dirty_worktree_before=False,
                dirty_worktree_after=False,
            ),
            termination=WindowsExecutionTermination.EXITED,
            executable_profile_ref="receipt_profile_3098",
            authorization_ref="windows_p01_grant_3098_receipt",
        )

    def cancel(self, request_id: str) -> None:
        del request_id


class ReadOnlyBrokerBinding:
    """The private Service Binding surface: reads only, never mutates."""

    def __init__(self, runtime) -> None:
        self._runtime = runtime

    def device_truth(self, payload: dict) -> dict:
        return self._runtime.device_truth(payload)

    def terminal_command_result(self, payload: dict) -> dict:
        return self._runtime.terminal_command_result(payload)


# --- D1-shaped SQLite handles (the deployed chat/DO storage contracts) ------


class _Statement:
    def __init__(self, connection, sql):
        self._connection = connection
        self._sql = sql
        self._values: tuple = ()

    def bind(self, *values):
        self._values = values
        return self

    async def run(self):
        cursor = self._connection.execute(self._sql, self._values)
        columns = [item[0] for item in cursor.description] if cursor.description else []
        if columns:
            rows = cursor.fetchall()
            return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}
        return {"results": [], "meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}}

    async def first(self):
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return dict(zip(columns, rows[0])) if rows else None

    async def all(self):
        cursor = self._connection.execute(self._sql, self._values)
        rows = cursor.fetchall()
        columns = [item[0] for item in cursor.description] if cursor.description else []
        return {"results": [dict(zip(columns, row)) for row in rows], "meta": {"rows_written": 0}}


class SqliteD1:
    """A D1-shaped handle over a real SQLite file, with a real batch."""

    def __init__(self, path: Path):
        self._connection = sqlite3.connect(path, isolation_level=None)

    def prepare(self, sql):
        return _Statement(self._connection, sql)

    async def batch(self, statements):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self._connection.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if columns else []
                if columns:
                    results.append({"results": [dict(zip(columns, row)) for row in rows]})
                else:
                    results.append({"meta": {"rows_written": cursor.rowcount if cursor.rowcount >= 0 else 0}})
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")
        return results

    def close(self):
        self._connection.close()


class SqliteStorage:
    """D0-shaped storage for the durable broker runtime: a real transaction."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, isolation_level=None)

        class _Cursor:
            def __init__(self, inner):
                self._inner = inner

            @property
            def rowsWritten(self):
                return self._inner.rowcount if self._inner.rowcount >= 0 else 0

            def toArray(self):
                names = [c[0] for c in self._inner.description] if self._inner.description else []
                return [dict(zip(names, row)) for row in self._inner.fetchall()]

        class _Sql:
            def __init__(self, connection):
                self.connection = connection

            def exec(self, query, *bindings):
                return _Cursor(self.connection.execute(query, bindings))

        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return value

    def close(self):
        self.connection.close()


class WebDesktopE2E:
    """One composed Web ↔ Control Plane ↔ Desktop loop over shared authority."""

    def __init__(self, tmp_path: Path, *, runtime_mode: str = "receipt") -> None:
        assert runtime_mode in ("receipt", "windows")
        self.runtime_mode = runtime_mode
        self.tmp_path = tmp_path
        # Anchored slightly in the past: the server route offsets put broker
        # timestamps up to ~35s ahead of this base, and the chat's ONLINE
        # re-projection compares those facts against the real clock. Anchoring
        # keeps every server timestamp behind "now" while staying current.
        self.base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=120)
        self.server_clock = HarnessClock(self.base)
        self.client_clock = HarnessClock(self.base + timedelta(seconds=5))
        self.audit: list[str] = []
        self.receipts: list[WindowsExecutionReceipt] = []

        # --- the one canonical broker authority -----------------------------
        self.state_port = SerializedLocalAgentBrokerStatePort(
            backend=InMemorySerializedLocalAgentBrokerStateBackend()
        )
        self.authority = StateBackedLocalAgentBrokerAuthority(
            pepper=PEPPER,
            authority_ref=AUTHORITY_REF,
            state_port=self.state_port,
        )
        self.pairing = InMemoryBrokerPairingAuthority(
            pepper=PAIRING_PEPPER,
            authority=self.authority,
            code_nonce_factory=DeterministicNonces(),
            credential_factory=lambda: CREDENTIAL,
        )

        # --- the web side: chat storage + the read-only service binding -----
        chat_root = Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"
        self.db = SqliteD1(tmp_path / "chat.sqlite3")
        for migration in sorted((chat_root / "migrations").glob("*.sql")):
            self.db._connection.executescript(migration.read_text(encoding="utf-8"))
        self.history = D1HistoryStore(self.db)

        self._runtime_storage = SqliteStorage(tmp_path / "broker-do.sqlite3")
        runtime = LocalAgentBrokerDurableRuntime(
            storage=self._runtime_storage,
            env=_RuntimeEnv(),
        )
        # One Durable Object, exactly like the deployed composition: the web
        # binding and the device edge read the same canonical broker state.
        runtime.state_port = self.state_port
        if hasattr(runtime.material_store, "_state_port"):
            runtime.material_store._state_port = self.state_port
        self.runtime = runtime
        self.session_state = DurableSessionState()
        # device_truth reads heartbeat last-seen from the session store, so the
        # device edge and the web projection must share one session store.
        runtime.http_state = self.session_state
        self.binding = ReadOnlyBrokerBinding(runtime)

        env = {"LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": self.binding}
        self.result_source = build_local_task_result_source(env, self.history)
        self.access_source = build_claw_local_access_source(env)
        assert self.result_source is not None and self.result_source.configured is True
        assert self.access_source is not None and self.access_source.configured is True

        self.settings = Settings(session_secret="3098-e2e-session-secret", auth_mode="mock")
        self.app = create_app(
            self.settings,
            history_store=self.history,
            claw_local_access_source=self.access_source,
            local_task_result_source=self.result_source,
        )

        # --- the desktop side ------------------------------------------------
        self.fixture_dir = tmp_path / "fixture-root"
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        (self.fixture_dir / "sample.txt").write_bytes(SAMPLE_TEXT.encode("utf-8"))
        # The device profile speaks Windows paths by contract. On Windows the
        # root is the real fixture directory; elsewhere the receipt runtime
        # never touches the filesystem, so a synthetic absolute root stands in.
        fixture_windows_path = str(self.fixture_dir) if os.name == "nt" else r"C:\padiem98-e2e-fixture"
        self.device = LocalAgentDeviceProfile(
            device_id=DEVICE_ID,
            workspace_ref=WORKSPACE,
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref=ROOT_REF, windows_path=fixture_windows_path),),
        )
        self.credentials = DeviceCredentialStore(base_dir=tmp_path / "credentials")
        self.config = OutboundTransportConfig(
            endpoint=OutboundBrokerEndpoint(
                endpoint_ref="broker_endpoint_3098_e2e",
                url="https://broker.3098.e2e.padiem.test:443/broker",
                mode=OutboundTransportMode.HTTPS_LONG_POLL,
            ),
            heartbeat_seconds=30,
            poll_timeout_seconds=15,
            max_response_bytes=262_144,
            tls_required=True,
            public_inbound_port=False,
        )
        self.material_resolver = MaterialResolver()
        self.references = AdmissionReferences()
        self.handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=self.pairing,
            admission_reference_factory=self.references,
            rpc=LocalAgentBrokerRpcFacade(authority=self.authority),
            state=self.session_state,
            material_resolver=self.material_resolver,
            clock=self.server_clock,
        )
        self.durable_store = DurableRunStore(str(tmp_path / "durable-runs.sqlite3"))
        self.windows_runtime: WindowsSubprocessLocalAgentRuntime | None = None
        self.receipt_runtime = DeterministicReceiptRuntime()

    # --- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        try:
            self.durable_store.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass
        try:
            self.db.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass
        try:
            self._runtime_storage.close()
        except Exception:  # noqa: BLE001 - teardown only
            pass

    # --- web identity and run origin ----------------------------------------

    def accounts(self) -> dict[str, str]:
        resolved = {}
        for subject, email in ((OWNER_SUBJECT, "owner-3098@example.test"), (OTHER_SUBJECT, "other-3098@example.test")):
            profile = run(self.history.upsert_google_user(subject, email, f"user {subject}", ""))
            resolved[subject] = profile.id
        return resolved

    def create_conversation_with_run(self, *, owner: str, run_id: str, workspace_id: str = WORKSPACE) -> str:
        conversation_id = run(self.history.append_exchange(owner, None, "이 컴퓨터의 승인된 작업 폴더에서 sample.txt 상태를 확인", "바운디드 로컬 작업으로 실행하겠습니다."))
        run(
            self.history.record_claw_run(
                user_id=owner,
                run_id=run_id,
                channel="web",
                action="local_runner_task",
                title="bounded local task",
                status="running",
                conversation_id=conversation_id,
                workspace_id=workspace_id,
            )
        )
        return conversation_id

    def conversation_messages(self, conversation_id: str) -> list[dict]:
        return run(
            self.history._all(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY sequence_number ASC",
                conversation_id,
            )
        )

    # --- web HTTP legs --------------------------------------------------------

    def _async_client(self, owner_id: str):
        token = create_session_token(self.settings, owner_id)
        transport = httpx.ASGITransport(app=self.app)

        class _Client:
            def __init__(self, inner: httpx.AsyncClient) -> None:
                self._inner = inner
                self.cookies_set = False

            async def __aenter__(self):
                await self._inner.__aenter__()
                self._inner.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")
                return self

            async def __aexit__(self, *exc):
                return await self._inner.__aexit__(*exc)

            async def get(self, path: str, **kwargs):
                return await self._inner.get(path, **kwargs)

            async def post(self, path: str, **kwargs):
                return await self._inner.post(path, **kwargs)

        return _Client(httpx.AsyncClient(transport=transport, base_url="https://chat.example.test"))

    def web_get_local_access(self, *, owner_id: str, conversation_id: str) -> httpx.Response:
        async def drive():
            async with self._async_client(owner_id) as client:
                return await client.get(
                    "/api/claw/local-access",
                    params={"conversationId": conversation_id},
                )

        return run(drive())

    def web_post_local_result(self, *, owner_id: str, run_id: str, workspace_id: str | None = WORKSPACE) -> httpx.Response:
        async def drive():
            async with self._async_client(owner_id) as client:
                body = None if workspace_id is None else {"workspaceId": workspace_id}
                return await client.post(f"/api/claw/runs/{run_id}/local-result", json=body)

        return run(drive())

    # --- pairing --------------------------------------------------------------

    def web_issue_pairing_challenge(self, *, account_ref: str, workspace_ref: str, ttl_seconds: int = 300) -> dict:
        port = WebRequestPort(
            handler=self.handler,
            server_clock=self.server_clock,
            audit=self.audit,
            principal_ref=account_ref,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
        )
        response = port.post(
            config=None,
            operation=_Operation("v1/broker/pairings/challenge"),
            payload={
                "account_ref": account_ref,
                "workspace_ref": workspace_ref,
                "now": self.client_clock.now.isoformat().replace("+00:00", "Z"),
                "ttl_seconds": ttl_seconds,
            },
            timeout_seconds=10,
        )
        assert response["ok"] is True
        return response

    def pair_device(self, *, challenge_id: str, pairing_code: str, device_id: str = DEVICE_ID) -> DeviceBinding:
        port = DeviceRequestPort(
            handler=self.handler,
            server_clock=self.server_clock,
            audit=self.audit,
            device_id=device_id,
            account_ref="account.pending.pairing",
            workspace_ref=WORKSPACE,
        )
        runner = LocalAgentPairingHandoffRunner(
            config=self.config,
            credential_store=self.credentials,
            client=LocalAgentBrokerPairingClient(
                config=self.config,
                credential_store=self.credentials,
                request_port=port,
            ),
        )
        result = runner.redeem_handoff(
            pairing_code=pairing_code,
            challenge_id=challenge_id,
            device_id=device_id,
            correlation_ref="3098-e2e-pairing",
            now=self.client_clock.now,
        )
        assert result.binding_state == "paired_offline"
        assert result.local_online_claim is False
        # The desktop holds exactly the binding the canonical client persisted;
        # the canonical broker snapshot must agree with it.
        saved = self.credentials.last_saved_binding
        assert saved is not None, "the pairing client must persist the device binding"
        registered = None
        for candidate in self.state_port.load(authority_ref=AUTHORITY_REF).snapshot.bindings:
            if candidate.device_id == saved.device_id:
                registered = candidate
        assert registered is not None, "redeem must register the canonical broker binding"
        assert registered.binding_ref == saved.binding_ref
        assert registered.account_ref == saved.account_ref
        assert registered.workspace_ref == saved.workspace_ref == WORKSPACE
        return saved

    # --- device session --------------------------------------------------------

    def _channel(self, binding: DeviceBinding, *, freeze_clock: bool = False) -> ControlPlanePhysicalAdmissionChannel:
        port = DeviceRequestPort(
            handler=self.handler,
            server_clock=self.server_clock,
            audit=self.audit,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            freeze_clock=freeze_clock,
        )
        transport = ControlPlanePhysicalAdmissionTransport(
            credential_store=self.credentials,
            expected_admission_authority_ref=AUTHORITY_REF,
            request_port=port,
        )
        broker_binding = PinnedOutboundBrokerBinding.from_binding(binding=binding, config=self.config)
        return ControlPlanePhysicalAdmissionChannel(authority=broker_binding, transport=transport)

    def connect(self, binding: DeviceBinding, *, session_id: str, freeze_clock: bool = False):
        """The real bring-up: broker session, heartbeat, server-backed ONLINE."""

        channel = self._channel(binding, freeze_clock=freeze_clock)
        session = channel.open_session(
            binding=binding,
            session_id=session_id,
            now=self.client_clock.now,
            ttl_seconds=900,
        )
        heartbeat = channel.heartbeat(binding=binding, session=session, now=self.client_clock.now)
        online = project_server_backed_online_binding(
            binding=binding,
            session=session,
            heartbeat=heartbeat,
            now=self.client_clock.now,
        )
        return channel, session, online

    # --- work ticket -----------------------------------------------------------

    def build_sample_read_request(self, *, run_id: str, request_id: str = "request.3098.e2e.1") -> LocalCommandRequest:
        if self.runtime_mode == "windows":
            argv = (
                sys.executable,
                "-c",
                SAMPLE_READ_SCRIPT,
                "sample.txt",
                SAMPLE_SHA256,
                SECRET_MARKER_ENV,
            )
        else:
            argv = ("python", "-V")
        return LocalCommandRequest(
            request_id=request_id,
            run_id=run_id,
            device_id=DEVICE_ID,
            root_ref=ROOT_REF,
            argv=argv,
            cwd_relative=".",
            requested_at=self.server_clock.now,
            timeout_seconds=60,
        )

    def enqueue_ticket(self, *, command_id: str, request: LocalCommandRequest, binding_ref: str, ttl_seconds: int = COMMAND_TTL_SECONDS):
        fingerprint = command_request_fingerprint(request)
        queued = self.authority.enqueue_command(
            command_id=command_id,
            binding_ref=binding_ref,
            run_id=request.run_id,
            tool_request_ref=f"tool.{command_id}",
            request_fingerprint=fingerprint,
            now=self.server_clock.now,
            ttl_seconds=ttl_seconds,
        )
        self.material_resolver.register(
            command_id=queued.command_id,
            binding_ref=queued.binding_ref,
            request_fingerprint=fingerprint,
            wire=build_command_material_wire_projection(
                command=DeviceCommandEnvelope(
                    command_id=queued.command_id,
                    run_id=queued.run_id,
                    tool_request_ref=queued.tool_request_ref,
                    binding_ref=queued.binding_ref,
                    sequence=queued.sequence,
                    issued_at=queued.issued_at,
                    expires_at=queued.expires_at,
                    revision_ref=queued.revision_ref,
                ),
                request=request,
                request_fingerprint=fingerprint,
            ),
        )
        return queued

    # --- desktop execution ------------------------------------------------------

    def windows_profile(self) -> WindowsExecutableProfile:
        """The one allowlisted executable: the harness interpreter itself."""

        return WindowsExecutableProfile(
            profile_ref="profile.python.3098.e2e",
            executable_path=str(Path(sys.executable).resolve()),
            required_capabilities=(LocalCapability.PROCESS_EXECUTE.value,),
        )

    def windows_execution_evidence(
        self,
        request: LocalCommandRequest,
        *,
        profile: WindowsExecutableProfile | None = None,
    ) -> WindowsExecutionAuthorityEvidence:
        """Canonical P01 approval evidence bound to this exact command fingerprint."""

        profile = profile or self.windows_profile()
        fingerprint = command_request_fingerprint(request)
        invocation = windows_execution_tool_invocation(request, profile)
        now = self.server_clock.now
        return WindowsExecutionAuthorityEvidence(
            evidence_ref=f"authority_evidence_3098_{request.request_id}",
            request_fingerprint=fingerprint,
            permission_requests=(
                LocalPermissionRequest(
                    action_id=f"permission_{request.request_id}",
                    run_id=request.run_id,
                    device_id=request.device_id,
                    capability=LocalCapability.PROCESS_EXECUTE,
                    target_ref=fingerprint,
                    root_ref=request.root_ref,
                ),
            ),
            approval_pause=ApprovalPause(
                pause_id=f"pause_{request.request_id}",
                run_id=request.run_id,
                agent_runtime_id="agent_3098_e2e",
                tool_id=WINDOWS_EXECUTION_TOOL_ID,
                invocation_sha256=tool_invocation_digest(invocation),
                requirement=ApprovalRequirement.USER_CONFIRMATION,
                step_index=1,
                created_at=now - timedelta(seconds=30),
                expires_at=now + timedelta(minutes=10),
                approval_scope=(LocalCapability.PROCESS_EXECUTE.value,),
            ),
            approval_decision=VerifiedApprovalDecision(
                decision_id=f"decision_{request.request_id}",
                pause_id=f"pause_{request.request_id}",
                outcome=ApprovalOutcome.APPROVED,
                authority_ref="p01_authority_3098_e2e",
                evidence_ref="p01_evidence_3098_e2e",
                decided_at=now - timedelta(seconds=10),
            ),
            local_policy_ref="local_policy_v1",
            expires_at=now + timedelta(minutes=5),
        )

    def windows_authorization_port(self, *requests: LocalCommandRequest) -> P01LocalPermissionWindowsExecutionAuthorizationPort:
        profile = self.windows_profile()
        return P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=default_device_permission_profile(device=self.device),
            evidence_port=DeterministicWindowsExecutionAuthorityEvidencePort(
                tuple(self.windows_execution_evidence(request, profile=profile) for request in requests)
            ),
        )

    def prepare_windows_runtime(self, request: LocalCommandRequest) -> WindowsSubprocessLocalAgentRuntime:
        """The real Windows runtime with the canonical P01 grant for this ticket."""

        if os.name != "nt":
            raise RuntimeError("the real Windows runtime leg requires Windows")
        self.windows_runtime = WindowsSubprocessLocalAgentRuntime(
            device=self.device,
            executable_profiles=(self.windows_profile(),),
            authorization_port=self.windows_authorization_port(request),
        )
        return self.windows_runtime

    def host(self, channel: ControlPlanePhysicalAdmissionChannel, *, binding, session_id: str) -> LocalAgentResidentRuntimeHost:
        runtime = self.windows_runtime if self.runtime_mode == "windows" else self.receipt_runtime
        assembly = BoundLocalAgentRuntimeAssembly(
            device=self.device,
            binding=binding,
            permissions=default_device_permission_profile(device=self.device),
            broker_authority=channel.authority,
            runtime=runtime,
        )
        return LocalAgentResidentRuntimeHost(
            assembly=assembly,
            channel=channel,
            credential_store=self.credentials,
            durable_store=self.durable_store,
            clock=self.client_clock,
            instance_lock=_IsolatedInstanceLock(),
            session_id_factory=lambda: session_id,
            heartbeat_interval_seconds=30,
            session_ttl_seconds=900,
        )

    # --- observation helpers -----------------------------------------------------

    def device_truth(self, *, account_ref: str) -> dict:
        return self.binding.device_truth({"account_ref": account_ref})

    def terminal_result(self, *, run_id: str, account_ref: str, workspace_ref: str | None = None) -> dict:
        payload: dict[str, Any] = {"account_ref": account_ref, "run_id": run_id}
        if workspace_ref is not None:
            payload["workspace_ref"] = workspace_ref
        return self.binding.terminal_command_result(payload)

    def snapshot_commands(self) -> list:
        return list(self.state_port.load(authority_ref=AUTHORITY_REF).snapshot.commands)


class _RuntimeEnv:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
    LOCAL_AGENT_BROKER_PEPPER = PEPPER.decode("utf-8")


class _IsolatedInstanceLock:
    """Per-host single-instance lock so each harness host owns its own."""

    def __init__(self) -> None:
        self._held: str | None = None

    def acquire(self, lock_key: str) -> bool:
        if self._held is not None:
            return False
        self._held = lock_key
        return True

    def release(self, lock_key: str) -> None:
        if self._held == lock_key:
            self._held = None


class _Operation:
    """Minimal stand-in for the transport operation enums (value-only)."""

    def __init__(self, value: str) -> None:
        self.value = value
