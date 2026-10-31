"""#5573 stage 2 — the Chat app on plain CPython, behind PADIEM_LOCAL_DEV=1.

`worker.py` (Cloudflare) and this module compose the SAME `create_app`; the
only difference is where the D1/R2 bindings come from. Here they are a local
SQLite file and a disk folder, wired through the shared `SqliteD1` facade —
no fourth store dialect, no second app factory, and the production path is
untouched: this module refuses to build unless the explicit local flag is
set, and the Worker binding path can never set it (app/worker_config.py
calls Settings.from_values without the flag).

Lanes that need workerd stay fail-closed exactly as in production when a
binding is absent: connector WSS, cron telemetry export, Drive/P01 service
bindings, Web Push. The password-auth → conversations → mock-chat lane is
what this entry point is for.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from .app_factory import create_app
from .b66_b14_free_first_resolver import B66ExplicitQuoteModelResolver
from .config import ConfigError, Settings
from .d1_sqlite import SqliteD1
from .dispatch_quota import DispatchAwareB14Client
from .history import D1HistoryStore
from .local_r2 import LocalDiskR2
from .local_service_bridge import (
    HttpRpcBinding,
    LocalB66PdfRendererClient,
    compose_local_b14_transports,
)
from .local_p01_engine import build_local_engine_client
from .maintenance_mode import apply_write_freeze
from .orchestration_composition import compose_orchestration_bridge
from .orchestration_routes import install_orchestration_routes
from .project_files import D1ProjectFileStore
from .queue_store_proxy import (
    QueueBackedPairingStore,
    QueueBackedPresenceStore,
    QueueForwardingHistoryStore,
    build_queue_client,
)
from .saved_outputs import D1SavedOutputStore
from .usage_gate import D1UsageCounterStore

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

#: Own ledger instead of wrangler's `d1_migrations`: the local file must never
#: look "already migrated" to a future wrangler run and must never rewrite the
#: production ledger shape. Same order guarantee — filenames sort 001…076.
LOCAL_LEDGER_TABLE = "padiem_local_migration_ledger"


def local_data_dir() -> Path:
    raw = os.getenv("PADIEM_CHAT_LOCAL_DATA_DIR")
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "local_dev_data"
    return base


def apply_migrations(connection: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Apply every pending migration in filename order; return how many ran."""

    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {LOCAL_LEDGER_TABLE} ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in connection.execute(f"SELECT name FROM {LOCAL_LEDGER_TABLE}")}
    count = 0
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            f"INSERT INTO {LOCAL_LEDGER_TABLE} (name, applied_at) VALUES (?, ?)",
            (path.name, datetime.now(timezone.utc).isoformat()),
        )
        count += 1
    return count


def _ensure_session_secret(data_dir: Path) -> None:
    """Persist one dev session key next to the local database.

    The value never leaves the file; nothing here prints it. A process
    restart keeps existing cookies valid, which a random per-boot secret
    would not.
    """
    configured = os.getenv("PADIEM_CHAT_SESSION_SECRET", "").strip()
    if len(configured) >= 32:
        return
    secret_file = data_dir / "session_secret"
    if secret_file.exists():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            os.environ["PADIEM_CHAT_SESSION_SECRET"] = existing
            return
    generated = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(generated, encoding="utf-8")
    os.environ["PADIEM_CHAT_SESSION_SECRET"] = generated


def compose_host_orchestration(
    app: Any,
    *,
    env: Any,
    settings: Settings,
    db_binding: Any,
    client: httpx.AsyncClient | None = None,
) -> Any | None:
    """Attach the Engine orchestration bridge to the CPython host.

    This is the Worker's own composition (``orchestration_composition``); the
    host's loopback transport is the only difference. It stays off unless all
    three server-owned prerequisites are present, and its routes are installed
    only together with a real bridge, so a host without them keeps today's
    direct-B14 behaviour and its existing 404s.
    """

    bridge = compose_orchestration_bridge(
        env=env,
        settings=settings,
        db_binding=db_binding,
        build_client=lambda: build_local_engine_client(env, client=client)[0],
    )
    if bridge is None:
        return None
    install_orchestration_routes(app, bridge)
    return bridge


def build_app():
    """Compose the Chat ASGI app over the local SQLite + disk-R2 bindings."""

    local_flag = os.getenv("PADIEM_LOCAL_DEV", "").strip().lower() in {"1", "true"}
    host_flag = os.getenv("PADIEM_CHAT_CPYTHON_HOST", "").strip().lower() in {"1", "true"}
    if not local_flag and not host_flag:
        raise ConfigError(
            "app.local_cpython is the explicit CPython entry point: "
            "PADIEM_LOCAL_DEV=1 for a loopback dev run, or "
            "PADIEM_CHAT_CPYTHON_HOST=1 for the COM2 parallel host "
            "(see tools/run_chat_local_cpython.py / deploy/host-com2/chat)"
        )
    data_dir = local_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _ensure_session_secret(data_dir)

    settings = Settings.from_env()
    if local_flag and not settings.local_dev:
        raise ConfigError("PADIEM_LOCAL_DEV did not reach Settings — from_env regression")
    if host_flag:
        # The host run is the parallel-operation host: its public origin is a
        # real https hostname, so the loopback allowance must stay off and the
        # https-only validation applies exactly as in Production.
        if settings.local_dev:
            raise ConfigError("host runs must not set PADIEM_LOCAL_DEV")
        if not str(settings.public_base_url or "").startswith("https://"):
            raise ConfigError("PADIEM_CHAT_PUBLIC_BASE_URL must be https on the CPython host")

    # Same autocommit stance as the shared facade's connect(), minus the
    # foreign_keys pragma: production D1 never enforces it and the migration
    # set was built under that assumption.
    connection = sqlite3.connect(
        str(data_dir / "chat.sqlite3"), isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")

    applied = apply_migrations(connection)
    if applied:
        print(f"[local] migrations applied: {applied}")

    db = SqliteD1(connection)
    r2 = LocalDiskR2(data_dir / "objects")

    # HTTPS stand-ins for the Worker Service bindings. Only an explicitly
    # configured origin+secret pair builds one; a half-configured pair is a
    # boot error, never a silent downgrade. Absent pairs keep the exact
    # fail-closed behavior the Worker has when a binding is missing.
    identity_origin, identity_secret = _optional_pair(
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN", "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET"
    )
    pdf_origin, pdf_secret = _optional_pair(
        "PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN", "PADIEM_CHAT_LOCAL_B66_PDF_SECRET"
    )
    identity_authority = (
        HttpRpcBinding(identity_origin, identity_secret) if identity_origin else None
    )
    pdf_renderer = (
        LocalB66PdfRendererClient(pdf_origin, pdf_secret) if pdf_origin else None
    )

    shared_login_flow = None
    if os.getenv("PADIEM_CHAT_SHARED_LOGIN_ENABLED", "").strip().lower() == "true":
        from .control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
        from .cpython_shared_login import create_host_shared_login_flow
        shared_authority = (CloudflareControlPlaneIdentityAuthority(identity_authority)
                            if identity_authority is not None else None)
        shared_login_flow = create_host_shared_login_flow(os.environ, shared_authority, settings.public_base_url)

    app = create_app(
        shared_login_flow=shared_login_flow,
        settings=settings,
        history_store=D1HistoryStore(db, full_context_bucket=r2),
        d1_binding=db,
        r2_binding=r2,
        project_file_store=D1ProjectFileStore(db),
        saved_output_store=D1SavedOutputStore(db),
        usage_store=D1UsageCounterStore(db),
        control_plane_identity_authority=identity_authority,
        b66_pdf_renderer_client=pdf_renderer,
    )

    queue_client = build_queue_client(_queue_env())
    if queue_client is not None:
        # The same three replacements worker.py performs when its env selects
        # the queue. Production still defaults to D1; only a deployment that
        # explicitly sets PC_QUEUE_BACKEND=com2 takes this path.
        app.state.pc_device_pairing_store = QueueBackedPairingStore(queue_client)
        app.state.mesh_device_presence_store = QueueBackedPresenceStore(queue_client)
        app.state.history_store = QueueForwardingHistoryStore(
            app.state.history_store, queue_client
        )

    if settings.runtime_mode == "b14":
        # The same replacement worker.py performs when it composes the B14
        # transports: the default client stays as a stub any other subsystem
        # already captured, and the dispatch-aware client carries the proof.
        completion_transport, stream_transport = compose_local_b14_transports(
            settings, os.getenv("PADIEM_B14_SERVICE_PROOF_SECRET")
        )
        app.state.b14_client = DispatchAwareB14Client(
            settings,
            service_transport=completion_transport,
            stream_transport=stream_transport,
            require_service_binding=True,
        )
        quote_model_resolver = B66ExplicitQuoteModelResolver(completion_transport)
        app.state.b66_quote_model_resolver = quote_model_resolver
        app.state.b14_model_choice_resolver = quote_model_resolver

    edge_required = os.getenv("PADIEM_COM2_EDGE_PROOF_REQUIRED", "").strip().lower() in {"1", "true"}
    connector_enabled = os.getenv("PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED", "").strip().lower() in {"1", "true"}
    verifier = None
    if edge_required or connector_enabled:
        if not host_flag:
            raise ConfigError("COM2 edge proof requires the CPython host")
        from com2_edge_proof import EdgeProofVerifier
        edge_file = os.getenv("PADIEM_COM2_EDGE_SECRET_FILE", "").strip()
        replay_db = os.getenv("PADIEM_COM2_EDGE_REPLAY_DB", "").strip()
        if not edge_file:
            raise ConfigError("PADIEM_COM2_EDGE_SECRET_FILE is required")
        try:
            edge_secret = Path(edge_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError("PADIEM_COM2_EDGE_SECRET_FILE is unreadable") from exc
        verifier = EdgeProofVerifier(edge_secret, replay_db, all_requests=edge_required)

    # This route is a separate, explicit COM2 staging activation. Cloudflare
    # composition does not import this host-only module.
    if connector_enabled:
        if not host_flag:
            raise ConfigError("COM2 connector gateway requires the CPython host")
        from starlette.routing import WebSocketRoute
        from .com2_connector_websocket import (
            LoopbackRpcBinding, _BROKER_METHODS, _IDENTITY_METHODS,
            create_com2_gateway,
        )
        from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH

        def secret_file(name):
            filename = os.getenv(name, "").strip()
            if not filename:
                raise ConfigError(f"{name} is required")
            try:
                return Path(filename).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigError(f"{name} is unreadable") from exc

        identity = LoopbackRpcBinding(
            port=8802, secret=secret_file("PADIEM_COM2_IDENTITY_RPC_SECRET_FILE"),
            methods=_IDENTITY_METHODS,
        )
        broker = LoopbackRpcBinding(
            port=8799, secret=secret_file("PADIEM_COM2_BROKER_RPC_SECRET_FILE"),
            methods=_BROKER_METHODS,
        )
        gateway = create_com2_gateway(verifier=verifier, identity_binding=identity, broker_binding=broker)

        async def connector_gateway(websocket):
            await gateway(websocket.scope, websocket.receive, websocket.send)

        app.router.routes.insert(0, WebSocketRoute(CONNECTOR_GATEWAY_WSS_PATH, connector_gateway))

    # The Worker's orchestration bridge, over this host's loopback Engine
    # transport (#5115 step ②). Off unless the same three server-owned switches
    # are present; without them every chat route keeps the direct B14 path.
    compose_host_orchestration(
        app, env=os.environ, settings=settings, db_binding=db,
    )

    # The write window (#5573, #5115 step ③): reads keep working, mutations
    # answer 503 while the sentinel file exists or the environment switch is on.
    # Wrapped outermost so the answer never depends on origin or cookie state,
    # and applied after every ``app.state`` assignment above so callers keep a
    # Starlette application to attach state to.
    if edge_required:
        from .com2_edge_middleware import EdgeProofMiddleware
        app.add_middleware(EdgeProofMiddleware, verifier=verifier)
    app = apply_write_freeze(app)
    return app


def _optional_pair(origin_env: str, secret_env: str) -> tuple[str | None, str | None]:
    origin = os.getenv(origin_env, "").strip()
    secret = os.getenv(secret_env, "").strip()
    if not origin and not secret:
        return None, None
    if not origin or not secret:
        raise ConfigError(f"{origin_env} and {secret_env} must be set together")
    return origin, secret


def _queue_service_secret() -> str:
    """The queue secret value, preferably read from the staging file path.

    The COM2 staging queue keeps its service secret in a root-owned file. The
    deployment names that path, not the value; this reads it only when the
    queue is switched on. The value is never logged or written back out.
    """

    direct = os.getenv("PC_QUEUE_SERVICE_SECRET", "").strip()
    if direct:
        return direct
    path = os.getenv("PC_QUEUE_SERVICE_SECRET_FILE", "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfigError("PC_QUEUE_SERVICE_SECRET_FILE is unreadable") from exc


def _queue_env() -> SimpleNamespace:
    backend = os.getenv("PC_QUEUE_BACKEND", "").strip().lower()
    return SimpleNamespace(
        PC_QUEUE_BACKEND=backend,
        PC_QUEUE_ORIGIN=os.getenv("PC_QUEUE_ORIGIN"),
        PC_QUEUE_SERVICE_SECRET=_queue_service_secret() if backend == "com2" else "",
        PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP=os.getenv(
            "PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP"
        ),
    )
