"""Padiem Chat compatibility entrypoint.

Server responsibilities live in focused modules; legacy imports from ``app.main``
remain available while the module-level ASGI app stays unchanged.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .attachments import AttachmentValidationError, ImageAttachment, parse_attachments
from .app_factory import STATIC_DIR, create_app, health
from .auth import GoogleOAuthClient
from .auth_routes import auth_ready, auth_status, current_user_id, google_callback, google_start, logout
from .auto_grounding import AutoGroundingService
from .b14_client import B14Client, ChatRuntimeError
from .chat_routes import (
    _close_stream,
    _conversation_not_found,
    _empty_stream_json_error,
    _project_files_unavailable,
    _project_not_found,
    _public_evidence,
    _public_sse,
    _stream_json_error,
    _too_large_response,
    _usage_denied_response,
    api_chat,
    api_chat_stream,
)
from .config import ConfigError, Settings
from .conversation_routes import _history_unavailable, api_conversation_detail, api_conversations
from .documents import (
    DocumentAttachment,
    build_document_context,
    build_project_files_context,
    combine_reference_context,
)
from .grounding import GroundedChatService, GroundingError
from .history import (
    HistoryForbidden,
    HistoryStore,
    build_project_context,
    validate_conversation_id,
    validate_project_id,
)
from .model_policy import ModelPolicyError, model_supports, resolve_model_policy
from .project_file_routes import project_file_detail, project_files_collection
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .public_chat import public_chat_result
from .request_contract import (
    MAX_BROWSER_BODY_BYTES,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    MAX_TOTAL_MESSAGE_CHARS,
    _ALLOWED_ROLES,
    BrowserRequestError,
    BrowserToolRequest,
    _apply_b62_model_policy,
    _validate_payload,
    _validate_tool_request,
)
from .saved_output_routes import output_detail, outputs_collection
from .saved_outputs import SavedOutputStore
from .task_modes import TaskMode, get_task_mode
from .tool_presentations import ToolPresentationDescriptor, get_tool_presentation
from .usage_gate import UsageCounterStore, UsageGate
from .web_tools import MAX_QUERY_CHARS, WebToolError, create_web_provider, normalize_public_url


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc
