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

import asyncio

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from padiem_control_plane import AuthSessionSnapshot, SubjectType
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .app_factory import STATIC_DIR, create_app
from .b66_b14_free_first_resolver import B66ExplicitQuoteModelResolver
from .b66_quote_conversation import B66QuoteConversationInterpreter
from .b66_registered_model_boundary import (
    B14QuoteExactModelExecutor,
    B66RegisteredModelCompletion,
)
from .config import ConfigError, Settings
from .cpython_aes_gcm import CPythonAesGcmPort
from .control_plane_identity import IdentityBridgeError, PADIEM_CHAT_PRODUCT_ID
from .control_plane_identity_shadow import D1IdentityShadowStore
from .control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from . import sqlite_settings as sqlite_policy
from .d1_sqlite import SqliteD1
from .dispatch_quota import DispatchAwareB14Client, _refund_active_reservation
from .push_http_transport import build_host_push_transport
from .grounding import GroundedChatService
from .history import D1HistoryStore
from .local_r2 import ThreadedLocalDiskR2
from .loop_stall_watchdog import install as install_loop_stall_watchdog
from .local_service_bridge import (
    HttpRpcBinding,
    LocalB66PdfRendererClient,
    compose_local_b14_transports,
)
from .local_voice_stt_transport import HostVoiceSttRpcTransport
from .claw_search_decision import trusted_claw_search_activation
from .local_p01_engine import (
    build_local_calendar_read_activation_client,
    build_local_calendar_read_state_client,
    build_local_connector_tool_client,
    build_local_engine_client,
    build_local_p01_lanes,
)
from .worker_config import binding_value
from .maintenance_mode import apply_write_freeze
from .model_first import model_first_enabled
from .orchestration_composition import compose_orchestration_bridge
from .orchestration_routes import install_orchestration_routes
from .orchestration_stream import orchestration_stream_enabled, orchestration_stream_users
from .project_files import D1ProjectFileStore
from .queue_store_proxy import (
    QueueBackedDriveStore,
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
#: production ledger shape. Available filenames define order; numeric gaps are allowed.
LOCAL_LEDGER_TABLE = "padiem_local_migration_ledger"


def local_data_dir() -> Path:
    raw = os.getenv("PADIEM_CHAT_LOCAL_DATA_DIR")
    base = Path(raw) if raw else Path(__file__).resolve().parents[1] / "local_dev_data"
    return base


def apply_migrations(connection: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Apply every pending migration in filename order; return how many ran."""
    from .local_bootstrap import migration_lock
    with migration_lock(connection):
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


async def run_wal_checkpoint_loop(db, owner, *, period: float = sqlite_policy.IDLE_QUIET_SECONDS,
                                  **checkpoint_options) -> None:
    """Keep the WAL file small from exactly one of the worker processes.

    Every worker process runs this loop on the same database file. An idle
    worker cannot see that another one is busy, so only the process holding
    ``owner`` (the checkpoint lock in the data folder) checkpoints. The others
    ask for the lock again each period and take over once its holder is gone.
    """
    while True:
        await asyncio.sleep(period)
        try:
            if not owner.held and not await asyncio.to_thread(owner.acquire, wait=False):
                continue
            report = await db.checkpoint_if_idle(**checkpoint_options)
        except Exception as exc:  # a checkpoint must never take the app down
            print(f"[local] wal_checkpoint=failed reason={type(exc).__name__}")
            continue
        if not report.get("skipped"):
            print("[local] wal_checkpoint busy=%s log=%s checkpointed=%s" % (
                report.get("busy"), report.get("log"), report.get("checkpointed")))


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


class CurrentCanonicalSubjectResolver:
    """Read the same current canonical session as the admission authority.

    Shared-login sessions need no product-local shadow row. The existing
    identity RPC resolves the authenticated product user to its active session;
    neither this adapter nor a browser supplies or creates a canonical subject.
    """

    def __init__(self, authority: Any) -> None:
        self._authority = authority

    async def resolve_subject_id(self, *, product_user_id: str) -> str:
        session = await self._authority.resolve_current_auth_session(
            product_id=PADIEM_CHAT_PRODUCT_ID, product_user_id=product_user_id,
        )
        if not isinstance(session, AuthSessionSnapshot):
            raise IdentityBridgeError(
                503, "control_plane_session_invalid", "Canonical auth session is invalid."
            )
        if (
            session.product_id != PADIEM_CHAT_PRODUCT_ID
            or session.subject.subject_type is not SubjectType.USER
        ):
            raise IdentityBridgeError(
                403, "control_plane_session_mismatch", "Canonical auth session does not match Chat."
            )
        if not session.is_active(now=datetime.now(timezone.utc)):
            raise IdentityBridgeError(
                401, "control_plane_session_inactive", "Canonical auth session is inactive."
            )
        return session.subject.subject_id


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

    authority = getattr(app.state, "control_plane_identity_authority", None)
    canonical_subject_resolver = (
        CurrentCanonicalSubjectResolver(authority) if authority is not None else None
    )
    bridge = compose_orchestration_bridge(
        env=env,
        settings=settings,
        db_binding=db_binding,
        build_client=lambda: build_local_engine_client(env, client=client)[0],
        canonical_subject_resolver=canonical_subject_resolver,
    )
    if bridge is None:
        return None
    install_orchestration_routes(
        app,
        bridge,
        stream_enabled=orchestration_stream_enabled(os.environ),
        stream_users=orchestration_stream_users(os.environ),
        model_first_enabled=model_first_enabled(os.environ),
    )
    return bridge


def _mesh_command_output_limit() -> int | None:
    # Unset means no product ceiling on the local host. An operator may set a
    # positive byte limit; Cloudflare retains the existing default.
    name = "PADIEM_CHAT_PC_COMMAND_OUTPUT_MAX_BYTES"
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        raise ConfigError(name + " must be a positive integer")
    return int(raw)


def build_app(*, outbound_http_client: httpx.AsyncClient | None = None):
    """Compose the Chat ASGI app over the local SQLite + disk-R2 bindings.

    ``outbound_http_client`` is an injection seam for tests only: the host
    otherwise owns one client per composed binding and closes it at shutdown.
    """

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

    # This process is the one that serves, and it is the one with no logging config:
    # bind the stage-time line to stderr here so the COM2 journal actually gets it.
    from .orchestration_timing import ensure_host_visible

    ensure_host_visible()
    from .chat_stream_timing import ensure_host_visible as ensure_stream_timing_visible

    ensure_stream_timing_visible()

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
    # One policy for every SQLite connection on this host (WAL, NORMAL,
    # busy_timeout, cache, autocheckpoint): app/sqlite_settings.py.
    sqlite_policy.configure_writer(connection)

    applied = apply_migrations(connection)
    if applied:
        print(f"[local] migrations applied: {applied}")

    db = SqliteD1(connection, threaded=True,
                  read_workers=_nonnegative_env('PADIEM_CHAT_SQLITE_READERS', 2))
    r2 = ThreadedLocalDiskR2(data_dir / "objects")

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
    identity_binding = (
        HttpRpcBinding(
            identity_origin, identity_secret,
            keepwarm_seconds=_identity_keepwarm_seconds(),
        ) if identity_origin else None
    )
    # The connector status projection reads connector truth from the same two
    # private authorities the Worker composes: the identity lane above resolves
    # *which* workspace, and this Google OAuth lane answers *whether the
    # connector is usable*. Without both, /api/connectors/status keeps its
    # reviewed unverified projection and the connect button stays hidden.
    google_oauth_origin, google_oauth_secret = _optional_pair(
        "PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN",
        "PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET",
    )
    google_oauth_binding = (
        HttpRpcBinding(
            google_oauth_origin, google_oauth_secret,
            client=outbound_http_client,
        ) if google_oauth_origin else None
    )
    # #7228 recovery: the live STT lane rides the Chat Worker's authenticated
    # voice RPC (the Worker owns the VOICE_STT_SERVICE binding; the STT Worker
    # gains no new HTTPS ingress). Same optional-pair rule as above: a
    # half-configured pair is a boot error, an absent pair keeps the host's
    # voice_stt_transport unbound and every voice lane fail-closed 503.
    voice_rpc_origin, voice_rpc_secret = _optional_pair(
        "PADIEM_CHAT_VOICE_RPC_ORIGIN", "PADIEM_CHAT_VOICE_RPC_SECRET"
    )
    voice_stt_transport = (
        HostVoiceSttRpcTransport(
            HttpRpcBinding(voice_rpc_origin, voice_rpc_secret, client=outbound_http_client)
        )
        if voice_rpc_origin else None
    )
    # The GitHub App connector ports compose through the same shared helper
    # the Worker uses (app/github_oauth_composition.py): one class pair and
    # one reviewed fail-closed gate. Absent or insufficient material keeps
    # the reviewed 503 on /api/connectors/github/* and never refuses the
    # host at boot; no secret or length ever enters the log.
    from .github_oauth_composition import compose_github_oauth_ports
    github_client_secret = os.getenv("PADIEM_GITHUB_APP_CLIENT_SECRET", "").strip()
    github_oauth_store, github_oauth_provider, github_unbound_reason = (
        compose_github_oauth_ports(
            db=db,
            session_secret=settings.session_secret,
            client_secret=github_client_secret,
        )
    )
    print("[local] github_oauth=" + (
        "bound" if github_oauth_store is not None
        else "unbound reason=" + str(github_unbound_reason)
    ))
    identity_authority = (
        CloudflareControlPlaneIdentityAuthority(identity_binding)
        if identity_binding is not None else None
    )
    # The identity keepwarm cycle (#6975) now arms at host boot: the ASGI
    # startup below arms the binding on the running loop, so the first warm
    # ping goes out a full period after boot instead of after the first turn.
    # The pre-wrap binding is armed directly — the cache wrapper is unrelated
    # to the warm cycle and the loopback binding stays off (keepwarm 0).
    # 261104: the two per-turn identity reads (chat owner + PC owner scope)
    # are pure functions of a verified credential and cost 0.6-1.0 s of
    # trans-Pacific Worker RTT from this host. Successful answers are cached
    # for at most 60 s, keyed by a hash of the credential or session id;
    # rejections are never cached, and logout, deletion, permission changes
    # and session revocation invalidate through invalidate_auth_cache.
    if identity_authority is not None:
        from .identity_call_cache import CachedIdentityAuthority
        identity_authority = CachedIdentityAuthority(identity_authority)
    identity_shadow_store = D1IdentityShadowStore(db)
    pdf_renderer = (
        LocalB66PdfRendererClient(pdf_origin, pdf_secret) if pdf_origin else None
    )

    shared_login_flow = None
    if os.getenv("PADIEM_CHAT_SHARED_LOGIN_ENABLED", "").strip().lower() == "true":
        from .cpython_shared_login import create_host_shared_login_flow
        # #7161: the shared flow issues cookies only — it never established the
        # canonical B62/B54 session the Claw/MCP consumers resolve. The adapter
        # now re-establishes those sessions behind a verified request when the
        # authority reports them missing, with this deployment's own lifetime.
        shared_login_flow = create_host_shared_login_flow(
            os.environ, identity_authority, settings.public_base_url,
            canonical_session_lifetime_seconds=settings.session_max_age_seconds)
        # Stage 1 shadow (#7078): warm the JWKS cache once at startup (off
        # the request path) so the first verified request does not pay the
        # ~400 ms JWKS fetch. No-op unless the shadow switch is ON. Wrapped so
        # a JWKS outage can never fail server startup (Argon (a)-2).
        try:
            from .auth_shadow_verify import prewarm_shadow_verifier
            prewarm_shadow_verifier()
        except Exception as exc:
            print("shadow_prewarm outcome=fail code=%s" % type(exc).__name__, flush=True)

    # #4139 Oracle management-host return leg, composed from the SAME env
    # bindings the Worker root composes (worker.py build_oracle_mesh_return_source_from_env).
    # On this host the bindings are plain environment variables, and a secret
    # lives only in the operator's EnvironmentFile. Uvicorn loads this factory
    # inside its own event loop, so the async builder runs from the app's
    # startup instead of asyncio.run() at factory time (which raised
    # "asyncio.run() cannot be called from a running event loop"). Absent or
    # invalid material keeps the fail-closed unconfigured source, the builder's
    # fixed reason line (oracle_mesh_source_unconfigured=<reason>), and one
    # explicit host marker line.
    from .oracle_mesh_read_return_routes import (
        build_oracle_mesh_return_source_from_env,
        host_engine_lane_mount_marker,
        legacy_map_lane_enabled,
        valid_claw_engine_desktop_secret,
    )

    # The Engine signs its desktop/PC-query calls with this shared secret. A
    # missing or too-short value keeps the existing fail-closed 503 answer; the
    # marker names the state only, never the value or its length.
    claw_engine_desktop_secret = valid_claw_engine_desktop_secret(
        os.getenv("CLAW_ENGINE_DESKTOP_SECRET", "").strip()
    )
    print(
        "[local] claw_engine_desktop_secret="
        + ("configured" if claw_engine_desktop_secret else "unconfigured")
    )
    # create_app gates the internal Engine lanes on the return source, and the
    # host cannot await the async builder inside uvicorn's factory loop: the
    # marker says "this deployment names the mesh lane", and the startup hook
    # below swaps in the composed source before the first request is served.
    oracle_mesh_return_source = host_engine_lane_mount_marker(os.environ)
    print(
        "[local] engine_lanes="
        + ("mounted_pending_source" if oracle_mesh_return_source is not None else "unmounted")
    )

    app = create_app(
        shared_login_flow=shared_login_flow,
        settings=settings,
        history_store=D1HistoryStore(
            db, full_context_bucket=r2,
            mesh_command_output_max_bytes=_mesh_command_output_limit(),
        ),
        d1_binding=db,
        custom_credential_cipher=CPythonAesGcmPort(),
        r2_binding=r2,
        project_file_store=D1ProjectFileStore(db),
        saved_output_store=D1SavedOutputStore(db),
        usage_store=D1UsageCounterStore(db),
        control_plane_identity_authority=identity_authority,
        identity_shadow_store=identity_shadow_store,
        b66_pdf_renderer_client=pdf_renderer,
        github_oauth_store=github_oauth_store,
        github_oauth_provider=github_oauth_provider,
        central_model_admin_google_email=os.getenv(
            "PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL", ""
        ).strip(),
        # The central route dashboard signs its confirmation receipts with this
        # server-only key. The Worker reads it from a secret binding; the host
        # reads the same name from its EnvironmentFile. Absent or malformed
        # leaves every central write fail-closed, exactly as before.
        central_model_policy_signing_key=os.getenv(
            "PADIEM_CENTRAL_MODEL_POLICY_SIGNING_KEY", ""
        ).strip(),
        oracle_mesh_return_source=oracle_mesh_return_source,
        oracle_mesh_legacy_map_lane=legacy_map_lane_enabled(os.environ),
        claw_engine_desktop_secret=claw_engine_desktop_secret,
        # #5034 Web Push: the same adapter the Worker composes, over this
        # runtime's own HTTPX transport. Without VAPID material the factory
        # leaves the sender unset and the capability route keeps answering
        # not_configured — an idle transport never becomes a delivery claim.
        claw_push_vapid_private_key=os.getenv("PADIEM_PUSH_VAPID_PRIVATE_KEY"),
        claw_push_vapid_public_key=os.getenv("PADIEM_PUSH_VAPID_PUBLIC_KEY"),
        claw_push_vapid_subject=os.getenv("PADIEM_PUSH_VAPID_SUBJECT"),
        claw_push_transport=build_host_push_transport(),
        voice_stt_transport=voice_stt_transport,
    )

    from .connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth

    app.state.google_oauth_workspace_truth = (
        CloudflareGoogleOAuthWorkspaceTruth(google_oauth_binding)
        if google_oauth_binding is not None
        else None
    )
    print(
        "[local] google_oauth_workspace_truth="
        + ("bound" if google_oauth_binding is not None else "unbound")
    )
    # #2952: Calendar READ activation reuses the same P01 Engine caller surface
    # the Worker validates, over this host's loopback binding.
    calendar_read_activation_client, calendar_diagnostic = (
        build_local_calendar_read_activation_client(
            os.environ, client=outbound_http_client
        )
    )
    app.state.calendar_read_activation_client = calendar_read_activation_client
    print(
        "[local] calendar_read_activation="
        + ("bound" if calendar_read_activation_client is not None else "unbound")
        + (" reason=" + calendar_diagnostic if calendar_diagnostic else "")
    )
    # #7228 recovery marker: names the lane state only, never a value.
    print(
        "[local] voice_stt_transport="
        + ("bound" if voice_stt_transport is not None else "unbound")
    )
    # #2952 follow-up: the persisted Calendar READ grant state (the read-only
    # half) reuses the same P01 Engine caller surface the Worker binds over its
    # Service Binding. Without this the COM2 host never projected
    # ``calendar_read_grant_state`` and the status surface silently dropped the
    # third axis while the Worker path answered it.
    calendar_read_state_client, calendar_state_diagnostic = (
        build_local_calendar_read_state_client(
            os.environ, client=outbound_http_client
        )
    )
    app.state.calendar_read_state_engine_client = calendar_read_state_client
    print(
        "[local] calendar_read_state="
        + ("bound" if calendar_read_state_client is not None else "unbound")
        + (" reason=" + calendar_state_diagnostic if calendar_state_diagnostic else "")
    )
    # The connector READ tool lane reuses the same P01 Engine caller surface
    # over the same loopback binding, restricted to the private tool-execute
    # path. Authority stays Engine-side; an unbound client only means the lane
    # fails closed while the turn itself proceeds.
    connector_tool_client, connector_tool_diagnostic = (
        build_local_connector_tool_client(os.environ, client=outbound_http_client)
    )
    app.state.connector_tool_engine_client = connector_tool_client
    print(
        "[local] connector_tool_execute="
        + ("bound" if connector_tool_client is not None else "unbound")
        + (" reason=" + connector_tool_diagnostic if connector_tool_diagnostic else "")
    )

    # apply_write_freeze below rebinds ``app`` to the ASGI wrapper; bind the
    # Starlette app in the handler default so startup still updates the state
    # object requests read (the wrapper itself has no .state).
    async def _compose_oracle_mesh_return_source_on_startup(app=app):
        source = await build_oracle_mesh_return_source_from_env(os.environ)
        if source is None:
            # The builder logs the fixed reason through
            # app.oracle_mesh_read_return_routes; this extra single-line host
            # marker keeps one explicit startup line even if that logging path
            # changes later.
            print("[local] oracle_mesh_source_unconfigured=env_binding_unavailable")
            return
        app.state.oracle_mesh_return_source = source
        print("[local] oracle_mesh_return_source=mesh_env_configured")

    app.router.on_startup.append(_compose_oracle_mesh_return_source_on_startup)

    async def _arm_identity_keepwarm_on_startup() -> None:
        """Arm the identity keepwarm cycle on the running loop (host boot)."""

        if identity_binding is not None:
            from .identity_cache_metrics import arm
            arm()
            identity_binding.arm_warmer()
            print("[local] identity_keepwarm=armed")

    app.router.on_startup.append(_arm_identity_keepwarm_on_startup)

    wal_checkpoint_tasks = {}
    from .local_bootstrap import checkpoint_owner_lock
    wal_checkpoint_owner = checkpoint_owner_lock(connection)

    async def _bound_wal_on_startup(app=app):
        """Keep the WAL file small: truncate it only while the database is idle."""
        loop = asyncio.get_running_loop()
        current = wal_checkpoint_tasks.get(loop)
        if current is not None and not current.done():
            app.state.wal_checkpoint_task = current
            return

        task = loop.create_task(run_wal_checkpoint_loop(db, wal_checkpoint_owner))
        wal_checkpoint_tasks[loop] = task
        app.state.wal_checkpoint_task = task

    async def _stop_bound_wal(app=app):
        task = wal_checkpoint_tasks.pop(asyncio.get_running_loop(), None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if getattr(app.state, "wal_checkpoint_task", None) is task:
            app.state.wal_checkpoint_task = None
        if not wal_checkpoint_tasks:
            # Hand the checkpoint role to another worker process right away.
            wal_checkpoint_owner.release()

    app.router.on_startup.append(_bound_wal_on_startup)
    app.router.on_shutdown.append(_stop_bound_wal)
    app.router.on_shutdown.append(db.close_readers)
    # #6923: journal event-loop stalls and dump every thread's stack while
    # one lasts (app/loop_stall_watchdog.py; PADIEM_CHAT_LOOP_STALL_WATCHDOG=off
    # turns it off on a host).
    install_loop_stall_watchdog(app, env=os.environ)
    if identity_binding is not None:
        from .identity_cache_metrics import stop as stop_identity_cache_metrics
        app.router.on_shutdown.append(stop_identity_cache_metrics)
        # #6613: the identity RPC client is pooled for the life of the host, so
        # the same shutdown hook that stops the SQLite readers closes it.
        app.router.on_shutdown.append(identity_binding.aclose)
    if google_oauth_binding is not None and outbound_http_client is None:
        app.router.on_shutdown.append(google_oauth_binding.aclose)
    if shared_login_flow is not None:
        exchange_close = getattr(getattr(shared_login_flow, 'exchange', None), 'aclose', None)
        if callable(exchange_close):
            app.router.on_shutdown.append(exchange_close)
    # Optional short-lived validation results; roles/entitlements stay live.
    from .auth_validation_cache import SqliteAuthValidationCache
    cache_seconds = _nonnegative_env('PADIEM_CHAT_AUTH_CACHE_SECONDS', 30)
    link_seconds = _nonnegative_env('PADIEM_CHAT_SHARED_LINK_CACHE_SECONDS', 600)
    # #7084: the revocation guard's successful session check is reused for a
    # longer window than the shared account mapping, because the 30 s window kept
    # expiring between request bursts and every miss paid the ~1.2 s authority
    # call (COM2 journal: 7,736 checks, 420 upstream calls). Logout, password
    # change, account deletion and admin membership/role changes delete the row
    # before they answer, so only a revocation made in another product waits for
    # this window to end. 0 keeps the mapping window instead of refusing a boot.
    session_seconds = _nonnegative_env('PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS', 300)
    # #7084: the revocation guard reloads this entry on a background task just
    # before it expires, so the request that would have waited ~1.2 s for the
    # authority answers from the still-valid entry instead.
    refresh_ahead = _nonnegative_env('PADIEM_CHAT_AUTH_REFRESH_AHEAD_SECONDS', 5)
    app.state.auth_validation_cache = (
        SqliteAuthValidationCache(db, ttl_seconds=cache_seconds,
                                  session_ttl_seconds=session_seconds or cache_seconds,
                                  refresh_ahead_seconds=refresh_ahead,
                                  link_ttl_seconds=link_seconds) if cache_seconds else None
    )
    from .config import session_local_verify_enabled
    if session_local_verify_enabled(settings):
        try:
            from .auth_shadow_verify import _short_fetch
            from .session_revocation_guard import (
                LOCAL_VERIFY_LEEWAY_SECONDS,
                load_padiem_auth_verify_module,
                prewarm_local_token_verifier,
            )

            verify_mod = load_padiem_auth_verify_module()
            client_id = str(os.getenv("PADIEM_CHAT_SHARED_AUTH_CLIENT_ID") or "b62").strip() or "b62"
            local_verifier = verify_mod.Verifier(
                audience=client_id,
                fetcher=_short_fetch,
                leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
            )
            app.state.local_token_verifier = local_verifier
            prewarm_local_token_verifier(local_verifier)
        except Exception as exc:
            print("local_verify_setup outcome=fail code=%s" % type(exc).__name__, flush=True)

    # #5441 / B66 alerts: the transactional-mail channel on the CPython host.
    # The Worker resolves these names from trusted bindings; here they come from
    # systemd's EnvironmentFile (app/mail_channel_env.py keeps the same
    # reuse-first order). An absent credential stays absent: the reset route
    # answers 503 and signup alerts stay queued, exactly as before this wiring.
    from .mail_channel_env import resolve_b66_channel, resolve_mail_channel
    from .password_reset_delivery import build_email_delivery

    mail_api_key, mail_from = resolve_mail_channel(os.environ)
    app.state.password_reset_delivery = build_email_delivery(
        resend_api_key=mail_api_key,
        email_from=mail_from,
    )
    b66_member_store = getattr(app.state, "b66_member_admin_store", None)
    if b66_member_store is not None:
        from .b66_signup_notifications import B66SignupNotifier

        b66_notifier = B66SignupNotifier(
            b66_member_store,
            resend_api_key=mail_api_key,
            email_from=mail_from,
            **resolve_b66_channel(os.environ),
        )
        app.state.b66_signup_notifier = b66_notifier if b66_notifier.channels else None

    # Match the Worker's staged entry layout while keeping the council app as
    # the sole source. The installer checks the checkout contains these assets.
    # Caching (2026-11-01, Owner-approved): the entry answers no-cache so the
    # next load always revalidates, and its assets are addressed with
    # content-hashed URLs by the council app itself (app/asset_versions.py), so
    # a year of immutable caching is safe — a deploy changes the URL, not the
    # file, and no edge cache can mask a new deploy (the 2026-11-01 incident).
    council_static = Path(__file__).resolve().parents[2] / "padiem-council-apps" / "static"

    async def council_entry(request):
        return FileResponse(council_static / "index.html",
                            headers={"Cache-Control": "no-cache"})

    class CouncilLongCacheStaticFiles(StaticFiles):
        """/apps/council/static/* files are content-hashed, so a long, immutable
        cache is safe; 404s keep Starlette's own (header-free) answer."""

        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    static_index = next(i for i, route in enumerate(app.router.routes)
                        if isinstance(route, Mount) and route.name == "static")
    app.router.routes[static_index:static_index] = [
        Route("/apps/council/", council_entry, methods=["GET"]),
        Mount("/apps/council/static",
              app=CouncilLongCacheStaticFiles(directory=str(council_static)),
              name="council-assets"),
    ]

    # The explicit COM2 queue below replaces them when that backend is selected.
    from .mesh_device_presence_store import D1MeshDevicePresenceStore
    from .mesh_device_drive_store import D1MeshDeviceDriveStore
    from .pc_device_pairing_store import D1PcPairingStore
    from .claw_pc_device_selection_store import D1PcDeviceSelectionStore
    app.state.mesh_device_presence_store = D1MeshDevicePresenceStore(db)
    app.state.mesh_device_drive_store = D1MeshDeviceDriveStore(db)
    app.state.pc_device_pairing_store = D1PcPairingStore(db)
    app.state.claw_pc_device_selection_store = D1PcDeviceSelectionStore(db)
    app.state.pc_pairing_install_url = (os.getenv("PC_AGENT_INSTALL_URL") or "").strip()
    app.state.pc_pairing_user_helper_url = (
        os.getenv("PC_USER_HELPER_INSTALL_URL") or ""
    ).strip()
    app.state.pc_pairing_user_helper_sha256 = (
        os.getenv("PC_USER_HELPER_SHA256") or ""
    ).strip()
    # #7108: while chat.padiem.net is served by padiem-chat-front, this COM2
    # host is the operating pairing authority; these values feed the handoff
    # and one-click install responses. The Worker reads the same names only
    # for the fallback/rollback path.

    # The upload UI and write routes open only on the COM2 host when the
    # reviewed PDF conversion dependency is actually installed.
    import importlib.util
    app.state.pdfmd_com2_ready = host_flag and importlib.util.find_spec("pypdf") is not None

    queue_client = build_queue_client(_queue_env())
    # #6460 step 2: the desktop lane deposits a one-shot typed value through
    # this same declared store door, so the value never enters the row.
    app.state.queue_client = queue_client
    if queue_client is not None:
        # #6617: the queue client is pooled for the life of the host.
        app.router.on_shutdown.append(queue_client.aclose)
        # The same three replacements worker.py performs when its env selects
        # the queue. Production still defaults to D1; only a deployment that
        # explicitly sets PC_QUEUE_BACKEND=com2 takes this path.
        app.state.pc_device_pairing_store = QueueBackedPairingStore(queue_client)
        app.state.mesh_device_presence_store = QueueBackedPresenceStore(queue_client)
        app.state.mesh_device_drive_store = QueueBackedDriveStore(queue_client)
        app.state.history_store = QueueForwardingHistoryStore(
            app.state.history_store, queue_client
        )
    # #7293 follow-up: the claim route's node-existence proof — the PR-2 Mesh
    # presence directory — was never injected, so every typed-code claim landed
    # in pending_verification forever. Wire it from whichever presence store
    # this runtime selected above; no store stays fail-closed (never verified).
    from .pc_device_pairing_routes import presence_pairing_verifier
    app.state.pc_pairing_verifier = presence_pairing_verifier(
        app.state.mesh_device_presence_store
    )

    # The same server-owned v2 loopback authority as the connector gateway.
    # Missing configuration leaves the existing unconfigured source in place.
    broker_secret_file = os.getenv("PADIEM_COM2_BROKER_RPC_SECRET_FILE", "").strip()
    if host_flag and broker_secret_file:
        from .claw_device_directory_routes import BrokerDeviceDirectorySource
        from .com2_connector_websocket import LoopbackRpcBinding
        try:
            broker_secret = Path(broker_secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError("PADIEM_COM2_BROKER_RPC_SECRET_FILE is unreadable") from exc
        directory_binding = LoopbackRpcBinding(
            port=8799, secret=broker_secret, sign_request_id=True,
            methods=frozenset({"device_directory", "set_owner_usage", "android_saf_profiles"}),
        )
        app.state.claw_device_directory_source = BrokerDeviceDirectorySource(
            directory_binding, presence_store=app.state.mesh_device_presence_store,
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
        # Anything the app factory built FROM the previous client has to be
        # rebuilt here, exactly as worker.py does: GroundedChatService captured
        # the stub client, so a Chat web-search turn on this host executed
        # without the dispatch proof and without the reservation-refund rule
        # the dispatch-aware client carries.
        app.state.grounded_chat = GroundedChatService(
            app.state.b14_client,
            app.state.web_provider,
        )
        # #4469: worker.py was the only entry point that composed the Claw
        # public web search switch, so after the 10-31 COM2 move the host read
        # the deployment value nowhere and the lane stayed off. The host now
        # composes the SAME wiring (compose_p01_lanes over one loopback Engine
        # client) and the SAME trusted activation worker.py calls. Nothing is
        # composed unless the deployment asks for it, so an absent or false
        # switch leaves this host exactly as it is today
        # (503 engine_not_configured on the Claw lane).
        if binding_value(
            os.environ, "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"
        ) == "true":
            (
                app.state.claw_p01_adapter,
                app.state.claw_p01_continuation_client,
                app.state.claw_p01_composition_diagnostic,
            ) = build_local_p01_lanes(
                os.environ,
                # The host's analogue of the Worker's identity-authority
                # binding: the canonical USER lane turns on only when a
                # Control Plane identity authority is actually composed.
                allow_subject_identity=identity_authority is not None,
            )
            app.state.claw_web_search_enabled = trusted_claw_search_activation(
                flag=binding_value(
                    os.environ, "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"
                ),
                runtime_mode=settings.runtime_mode,
                adapter=app.state.claw_p01_adapter,
                usage_gate=app.state.usage_gate,
            )
        # #7306: worker.py composes the Claw live SSE switch from the deployment
        # flag PADIEM_CLAW_P01_LIVE_SSE_ENABLED; the CPython host hardcoded
        # False, so the lane stayed off here even when the deployment armed it.
        # Compose the SAME flag with the SAME judgment worker.py applies: the
        # runtime is B14, the flag is exactly "true", and the composed P01
        # adapter has a verified canonical subject lane.
        app.state.claw_live_sse_enabled = (
            settings.runtime_mode == "b14"
            and binding_value(
                os.environ, "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"
            ) == "true"
            and getattr(
                getattr(app.state, "claw_p01_adapter", None),
                "subject_identity_lane",
                False,
            ) is True
        )
        quote_model_resolver = B66ExplicitQuoteModelResolver(completion_transport)
        app.state.b66_quote_model_resolver = quote_model_resolver
        app.state.b14_model_choice_resolver = quote_model_resolver
        # B66 quote execution needs the exact-model facade worker.py composes.
        # The client captured while the app was built cannot carry an exact
        # model selection, so every grade-resolved interpret died as an opaque
        # 502 on this host before a single B14 request left the process.
        b66_quote_executor = B14QuoteExactModelExecutor(app.state.b14_client)
        app.state.b66_reasoning_transport_supported = bool(
            b66_quote_executor.supports_native_parameters
        )
        app.state.b66_quote_interpreter = B66QuoteConversationInterpreter(
            B66RegisteredModelCompletion(
                resolver=quote_model_resolver,
                executor=b66_quote_executor,
                refund_pre_dispatch=_refund_active_reservation,
            )
        )
        # The owner credential board uses the same B14 origin and proof secret
        # as the completion lane; an absent secret fails closed in the source.
        if settings.b14_base_url:
            from .b14_slot_status_source import HttpsSlotStatusSource

            app.state.b14_slot_status_source = HttpsSlotStatusSource(
                settings.b14_base_url,
                os.getenv("PADIEM_B14_SERVICE_PROOF_SECRET"),
            )
            # Owner model console writes use the same origin and proof secret.
            from .b14_model_ops_source import HttpsModelOpsSource

            app.state.b14_model_ops_source = HttpsModelOpsSource(
                settings.b14_base_url,
                os.getenv("PADIEM_B14_SERVICE_PROOF_SECRET"),
            )

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
            port=int(os.getenv("PADIEM_COM2_BROKER_RPC_PORT", "8799")),
            secret=secret_file("PADIEM_COM2_BROKER_RPC_SECRET_FILE"),
            methods=_BROKER_METHODS,
            # The broker ingress consumes the signed id (#6424), so this lane
            # signs one exactly like the identity lane does.
            sign_request_id=True,
        )
        gateway = create_com2_gateway(verifier=verifier, identity_binding=identity, broker_binding=broker)

        async def connector_gateway(websocket):
            await gateway(websocket.scope, websocket.receive, websocket.send)

        app.router.routes.insert(0, WebSocketRoute(CONNECTOR_GATEWAY_WSS_PATH, connector_gateway))
    else:
        # A websocket scope must never reach the static catch-all: Starlette's
        # StaticFiles asserts an http scope, so the 2026-11-03 11:23:40 connector
        # attempt surfaced as a 500 AssertionError traceback. With the gateway
        # switched off, the connector's own path is refused explicitly instead —
        # closed before accept, no traceback, no half-open socket.
        from starlette.routing import WebSocketRoute
        from .canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH

        async def refuse_connector_gateway(websocket):
            await websocket.close(code=4403)

        app.router.routes.insert(0, WebSocketRoute(CONNECTOR_GATEWAY_WSS_PATH, refuse_connector_gateway))

    # The Worker's orchestration bridge, over this host's loopback Engine
    # transport (#5115 step ②). Off unless the same three server-owned switches
    # are present; without them every chat route keeps the direct B14 path.
    compose_host_orchestration(
        app, env=os.environ, settings=settings, db_binding=db,
    )

    # App HMAC ingress belongs only to the COM2 host; it uses the same P01
    # loopback client and never inherits a browser session.
    if host_flag:
        from .apps_ai import install_apps_ai_routes
        install_apps_ai_routes(app, env=os.environ)
        from .bookai_records import install_bookai_records_routes
        install_bookai_records_routes(app, env=os.environ, db_binding=db)

    # The write window (#5573, #5115 step ③): reads keep working, mutations
    # answer 503 while the sentinel file exists or the environment switch is on.
    # Wrapped outermost so the answer never depends on origin or cookie state,
    # and applied after every ``app.state`` assignment above so callers keep a
    # Starlette application to attach state to.
    if edge_required:
        from .com2_edge_middleware import EdgeProofMiddleware
        app.add_middleware(EdgeProofMiddleware, verifier=verifier)
        # Include ingress replay-store waits in the existing request event.
        from .request_telemetry import RequestTelemetryMiddleware
        timing = next(item for item in app.user_middleware
                      if item.cls is RequestTelemetryMiddleware)
        app.user_middleware.remove(timing)
        app.user_middleware.insert(0, timing)
    app = apply_write_freeze(app)
    return app


def _nonnegative_env(name: str, default: int) -> int:
    value = os.getenv(name, str(default)).strip()
    if not value.isascii() or not value.isdecimal():
        raise ConfigError(name + ' must be a non-negative integer')
    return int(value)


def _identity_keepwarm_seconds() -> float:
    # PADIEM_CHAT_IDENTITY_KEEPWARM_SECONDS — the identity warm cycle period
    # (#6956): unset or unreadable keeps the 45 s default, 0 switches the
    # cycle off. A typo must not silently drop the host back to a cold
    # identity handshake on every turn, and must not fail the boot: the cycle
    # only ever carries a read-only RPC whose answer is discarded.
    raw = os.getenv('PADIEM_CHAT_IDENTITY_KEEPWARM_SECONDS', '').strip()
    if not raw:
        return 45.0
    try:
        parsed = float(raw)
    except ValueError:
        return 45.0
    return parsed if parsed >= 0 else 45.0


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
