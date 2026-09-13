from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .auth import GoogleOAuthClient
from .auth_routes import auth_status, google_callback, google_start, logout
from .auto_grounding import AutoGroundingService
from .chat_routes import api_chat, api_chat_stream
from .claw_routes import (
    claw_manual_intake_artifact,
    claw_manual_intake_preview,
    claw_manual_intake_execute,
    claw_runs_history,
)
from .claw_telegram_routes import claw_telegram_ingest
from .approved_memory import ApprovedMemoryStore, D1ApprovedMemoryStore
from .claw_memory_routes import (
    claw_memory_approve,
    claw_memory_detail,
    claw_memory_list,
    claw_memory_reject,
)
from .claw_inbox_routes import claw_inbox_list, claw_inbox_status
from .claw_task_alert_store import D1ClawTaskAlertStore
from .config import Settings
from .connector_ticket_routes import google_connector_ticket
from .conversation_routes import api_conversation_detail, api_conversations
from .grounding import GroundedChatService
from .history import HistoryStore
from .project_file_routes import project_file_detail, project_files_collection
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .request_telemetry import RequestTelemetryMiddleware
from .saved_output_routes import output_detail, outputs_collection
from .saved_outputs import SavedOutputStore
from .tier_identity_client import PadiemTierB14Client
from .usage_gate import UsageCounterStore, UsageGate
from .web_tools import create_web_provider
from .workspace_storage import (
    D1ClawDocumentMetadataStore,
    WorkspaceDocumentStore,
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


async def health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    usage_gate: UsageGate = request.app.state.usage_gate
    web_ready = settings.web_provider in {"mock", "firecrawl"}
    abuse_ready = usage_gate.ready
    return JSONResponse({
        "status": "ok", "app": "padiem-chat", "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": web_ready,
        "deep_research_ready": settings.runtime_mode == "b14" and web_ready,
        "image_attachment_ready": True,
        "text_document_attachment_ready": True,
        "auth_configured": settings.auth_mode == "google",
        "history_store_bound": request.app.state.history_store is not None,
        "projects_code_ready": True,
        "project_files_code_ready": True,
        "project_file_store_bound": request.app.state.project_file_store is not None,
        "saved_outputs_code_ready": True,
        "saved_output_store_bound": request.app.state.saved_output_store is not None,
        "quota_store_bound": usage_gate.quota_store_bound,
        "live_abuse_gate_ready": abuse_ready,
        "live_enabled": settings.runtime_mode == "b14" and abuse_ready,
        "canonical_identity_bound": request.app.state.control_plane_identity_authority is not None,
        "identity_shadow_bound": request.app.state.identity_shadow_store is not None,
        # #1975: per-request telemetry is wired at composition time, so this
        # reports whether the deployed build actually carries the channel. It is
        # a boolean only — no counters, no per-isolate numbers.
        "request_telemetry_enabled": getattr(
            request.app.state, "request_telemetry_enabled", False
        ),
    })


def create_app(
    settings: Settings | None = None,
    transport=None,
    web_transport=None,
    auth_transport=None,
    history_store: HistoryStore | None = None,
    project_file_store: ProjectFileStore | None = None,
    saved_output_store: SavedOutputStore | None = None,
    usage_store: UsageCounterStore | None = None,
    control_plane_identity_authority=None,
    identity_shadow_store=None,
    d1_binding=None,
    r2_binding=None,
    claw_p01_adapter=None,
    claw_telegram_authority=None,
    approved_memory_store: ApprovedMemoryStore | None = None,
    claw_task_alert_store=None,
    telemetry_emitter=None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/connectors/google/ticket", google_connector_ticket, methods=["POST"]),
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}/files/{file_id}", project_file_detail, methods=["GET", "DELETE"]),
        Route("/api/outputs", outputs_collection, methods=["GET", "POST"]),
        Route("/api/outputs/{output_id}", output_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/conversations", api_conversations, methods=["GET"]),
        Route("/api/conversations/{conversation_id}", api_conversation_detail, methods=["GET", "DELETE"]),
        Route("/api/chat/stream", api_chat_stream, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/claw/manual-intake/preview", claw_manual_intake_preview, methods=["POST"]),
        Route("/api/claw/manual-intake/execute", claw_manual_intake_execute, methods=["POST"]),
        Route("/api/claw/manual-intake/artifact/{document_id}", claw_manual_intake_artifact, methods=["GET"]),
        Route("/api/claw/telegram/ingest/{binding_ref}", claw_telegram_ingest, methods=["POST"]),
        Route("/api/claw/runs", claw_runs_history, methods=["GET"]),
        Route("/api/claw/memory/approve", claw_memory_approve, methods=["POST"]),
        Route("/api/claw/memory/reject", claw_memory_reject, methods=["POST"]),
        Route("/api/claw/memory", claw_memory_list, methods=["GET"]),
        Route("/api/claw/memory/{memory_id}", claw_memory_detail, methods=["GET"]),
        Route("/api/claw/inbox/{kind}", claw_inbox_list, methods=["GET"]),
        Route("/api/claw/inbox/{kind}/{item_id}", claw_inbox_status, methods=["PATCH"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    # #1975: raw ASGI middleware, installed outermost so every route (including
    # the static Mount and the later-installed orchestration routes) is covered.
    app.add_middleware(RequestTelemetryMiddleware, emitter=telemetry_emitter)
    app.state.request_telemetry_enabled = True
    app.state.settings = resolved
    app.state.history_store = history_store
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    # Canonical identity remains Control Plane authority. Product D1 stores only
    # a non-authoritative shadow pointer used to reach the current canonical session.
    app.state.control_plane_identity_authority = control_plane_identity_authority
    app.state.identity_shadow_store = identity_shadow_store
    app.state.usage_gate = UsageGate(resolved, usage_store)
    # An explicitly injected B14 transport is the existing network-free regression seam.
    # It cannot occur through browser input or Worker bindings. Production/ordinary runtime
    # (transport=None) always enforces the gate; quota-specific integration tests also
    # enforce it by supplying a usage store.
    app.state.usage_gate_enforced = not (transport is not None and usage_store is None)
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = PadiemTierB14Client(resolved, transport=transport)
    app.state.web_provider = create_web_provider(resolved, transport=web_transport)
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, app.state.web_provider)
    app.state.auto_grounding = AutoGroundingService(app.state.web_provider)
    # Workspace document store: D1 metadata + private R2 bytes.
    # Both bindings must be present; no memory fallback.
    _metadata_store: D1ClawDocumentMetadataStore | None = None
    _workspace_store: WorkspaceDocumentStore | None = None
    if d1_binding is not None and r2_binding is not None:
        try:
            _metadata_store = D1ClawDocumentMetadataStore(d1_binding)
            _workspace_store = WorkspaceDocumentStore(_metadata_store, r2_binding)
        except Exception:
            _metadata_store = None
            _workspace_store = None
    app.state.workspace_document_store = _workspace_store
    app.state._workspace_metadata_store = _metadata_store
    # Worker-native Claw P01/Engine adapter (#2229). Injected by the Worker
    # composition root from trusted bindings; None means unconfigured and the
    # execute route fails closed before any transport.
    app.state.claw_p01_adapter = claw_p01_adapter
    # Bounded non-secret composition diagnostic (#2413). Set by the Worker
    # composition root alongside a None adapter; always None on the success
    # path and validated against the closed allowlist before public projection.
    app.state.claw_p01_composition_diagnostic = None
    # Thin Telegram inbound consumer seam (#2315): the trusted binding
    # authority is injected server-side only; None keeps the route fail-closed.
    app.state.claw_telegram_authority = claw_telegram_authority
    # Durable explicitly user-approved memory (#2331): reuse the existing
    # PADIEM_CHAT_DB D1 binding with no new database authority. An explicitly
    # injected store wins (network-free tests); otherwise derive from the
    # D1 binding when present. None keeps the routes fail-closed.
    _approved_memory_store = approved_memory_store
    if _approved_memory_store is None and d1_binding is not None:
        try:
            _approved_memory_store = D1ApprovedMemoryStore(d1_binding)
        except Exception:
            _approved_memory_store = None
    app.state.approved_memory_store = _approved_memory_store

    # #2341 Task/Alert inbox: consume the existing migration-010 D1 authority.
    # No schema creation or alternate DB authority is introduced here.
    _task_alert_store = claw_task_alert_store
    if _task_alert_store is None and d1_binding is not None:
        try:
            _task_alert_store = D1ClawTaskAlertStore(d1_binding)
        except Exception:
            _task_alert_store = None
    app.state.claw_task_alert_store = _task_alert_store
    return app
