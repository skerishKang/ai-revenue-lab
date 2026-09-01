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
from .b14_client import B14Client
from .chat_routes import api_chat, api_chat_stream
from .config import Settings
from .conversation_routes import api_conversation_detail, api_conversations
from .grounding import GroundedChatService
from .history import HistoryStore
from .project_file_routes import project_file_detail, project_files_collection
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .saved_output_routes import output_detail, outputs_collection
from .saved_outputs import SavedOutputStore
from .usage_gate import UsageCounterStore, UsageGate
from .web_tools import create_web_provider

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
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
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
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.settings = resolved
    app.state.history_store = history_store
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    app.state.usage_gate = UsageGate(resolved, usage_store)
    # An explicitly injected B14 transport is the existing network-free regression seam.
    # It cannot occur through browser input or Worker bindings. Production/ordinary runtime
    # (transport=None) always enforces the gate; quota-specific integration tests also
    # enforce it by supplying a usage store.
    app.state.usage_gate_enforced = not (transport is not None and usage_store is None)
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = B14Client(resolved, transport=transport)
    app.state.web_provider = create_web_provider(resolved, transport=web_transport)
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, app.state.web_provider)
    app.state.auto_grounding = AutoGroundingService(app.state.web_provider)
    return app
