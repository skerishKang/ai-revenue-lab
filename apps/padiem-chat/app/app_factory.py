from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .auth import GoogleOAuthClient
from .auth_abuse import AuthAbuseGate, AuthAbuseStore, D1AuthAbuseStore
from .b66_quote_conversation import B66QuoteConversationInterpreter
from .b66_company_profile import CompanyProfileStore, D1CompanyProfileStore
from .b66_company_profile_routes import b66_company_profile_get, b66_company_profile_put
from .b66_quote_asset_routes import b66_quote_asset_detail
from .b66_quote_history_routes import (
    b66_quote_history_delete,
    b66_quote_history_detail,
    b66_quote_history_list,
    b66_quote_history_save,
)
from .b66_quote_history_store import D1QuoteHistoryStore
from .b66_quote_assets import B66QuoteAssetStore, D1B66QuoteAssetMetadataStore
from .b66_certified_quote_bundle import B66CertifiedQuoteBundleStore
from .b66_certified_preview import B66CertifiedPreviewStore
from .b66_certified_pdf_routes import b66_certified_pdf, b66_certified_preview_base
from .b66_quote_routes import (
    b66_quote_interpret,
    b66_runtime_config,
    b66_saved_skill_detail,
    b66_saved_skills,
)
from .b66_saved_quote_skill_store import (
    D1SavedQuoteSkillStore,
    SavedQuoteSkillStore,
)
from .auth_routes import (
    auth_status,
    google_callback,
    google_start,
    logout,
    password_login,
    password_register,
)
from .auto_grounding import AutoGroundingService
from .chat_routes import api_chat, api_chat_stream
from .claw_general_routes import claw_general_execute
from .claw_routes import (
    claw_approval_decision,
    claw_manual_intake_artifact,
    claw_manual_intake_preview,
    claw_manual_intake_execute,
    claw_manual_intake_quote_compare,
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
from .calendar_routes import (
    calendar_appointments_create,
    calendar_appointments_list,
    calendar_item_detail,
    calendar_items,
    calendar_today,
    calendar_upcoming,
    calendar_work_logs_create,
    calendar_work_logs_list,
)
from .calendar_store import CalendarStore, D1CalendarStore, InMemoryCalendarStore
from .claw_inbox_routes import claw_inbox_list, claw_inbox_status
from .claw_local_task_result_routes import CLAW_LOCAL_TASK_RESULT_PATH, local_runner_result
from .claw_local_access_routes import (
    CLAW_LOCAL_ACCESS_PATH,
    UnconfiguredClawLocalAccessTruthSource,
    claw_local_access,
)
from .claw_task_alert_store import D1ClawTaskAlertStore
from .claw_automation_store import D1ClawAutomationStore
from .claw_automation_rules_routes import claw_automation_rules
from .claw_automation_rule_create_routes import claw_automation_rule_create
from .claw_automation_rule_edit_routes import claw_automation_rule_edit
from .claw_automation_rule_enabled_routes import claw_automation_rule_set_enabled
from .config import Settings
from .connector_status_projection import connectors_status
from .connector_ticket_routes import google_connector_ticket
from .calendar_read_activation_routes import activate_google_calendar_read
from .conversation_routes import api_conversation_detail, api_conversations
from .desktop_conversation_authority import UnconfiguredDesktopDeviceSessionAuthority
from .desktop_conversation_routes import (
    DESKTOP_CONVERSATION_DETAIL_PATH,
    DESKTOP_CONVERSATIONS_PATH,
    desktop_conversation_detail,
    desktop_conversations,
)
from .grounding import GroundedChatService
from .history import HistoryStore
from .project_file_routes import project_file_detail, project_files_collection
from .drive_case_folder_routes import (
    drive_case_folder_delete,
    drive_case_folder_put,
    drive_case_folder_status,
    drive_folders_collection,
)
from .drive_case_pdf_routes import (
    drive_case_pdf_detail,
    drive_case_pdf_extraction_review,
    drive_case_pdfs_collection,
)
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .request_telemetry import RequestTelemetryMiddleware
from .same_origin_guard import SameOriginGuardMiddleware
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
        "auth_configured": settings.auth_mode != "off",
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
    drive_case_folder_engine_client=None,
    d1_binding=None,
    r2_binding=None,
    claw_p01_adapter=None,
    claw_telegram_authority=None,
    approved_memory_store: ApprovedMemoryStore | None = None,
    b66_saved_quote_skill_store: SavedQuoteSkillStore | None = None,
    b66_company_profile_store: CompanyProfileStore | None = None,
    b66_quote_history_store=None,
    b66_quote_asset_store=None,
    b66_certified_quote_bundle_store=None,
    b66_certified_preview_store=None,
    b66_pdf_renderer_client=None,
    b66_quote_interpreter=None,
    claw_task_alert_store=None,
    calendar_store: CalendarStore | None = None,
    claw_automation_store=None,
    telemetry_emitter=None,
    claw_p01_continuation_client=None,
    claw_local_access_source=None,
    local_task_result_source=None,
    desktop_device_session_authority=None,
    auth_abuse_store: AuthAbuseStore | None = None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/api/auth/password/register", password_register, methods=["POST"]),
        Route("/api/auth/password/login", password_login, methods=["POST"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/connectors/google/ticket", google_connector_ticket, methods=["POST"]),
        Route("/api/connectors/google/calendar/activate-read", activate_google_calendar_read, methods=["POST"]),
        Route("/api/connectors/status", connectors_status, methods=["GET"]),
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}/files/{file_id}", project_file_detail, methods=["GET", "DELETE"]),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_status,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_put,
            methods=["PUT"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_delete,
            methods=["DELETE"],
        ),
        Route(
            "/api/projects/{project_id}/drive-folders",
            drive_folders_collection,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs",
            drive_case_pdfs_collection,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs/{file_id}",
            drive_case_pdf_detail,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs/{file_id}/browser-extraction",
            drive_case_pdf_extraction_review,
            methods=["POST"],
        ),
        Route("/api/outputs", outputs_collection, methods=["GET", "POST"]),
        Route("/api/outputs/{output_id}", output_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/conversations", api_conversations, methods=["GET"]),
        Route("/api/conversations/{conversation_id}", api_conversation_detail, methods=["GET", "DELETE"]),
        # #3436 B2c: the GET-only canonical conversation surface for the paired
        # Desktop. Identity is the canonical broker device session, derived
        # server-side; it creates, deletes and writes nothing, and no browser
        # cookie path reaches it.
        Route(DESKTOP_CONVERSATIONS_PATH, desktop_conversations, methods=["GET"]),
        Route(
            DESKTOP_CONVERSATION_DETAIL_PATH,
            desktop_conversation_detail,
            methods=["GET"],
        ),
        Route("/api/chat/stream", api_chat_stream, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/b66/runtime-config", b66_runtime_config, methods=["GET"]),
        Route("/api/b66/company-profile", b66_company_profile_get, methods=["GET"]),
        Route("/api/b66/company-profile", b66_company_profile_put, methods=["PUT"]),
        Route("/api/b66/saved-skills", b66_saved_skills, methods=["GET"]),
        Route(
            "/api/b66/saved-skills/{saved_skill_id}",
            b66_saved_skill_detail,
            methods=["GET"],
        ),
        Route(
            "/api/b66/assets/{asset_id}",
            b66_quote_asset_detail,
            methods=["GET"],
        ),
        Route("/api/b66/quote/interpret", b66_quote_interpret, methods=["POST"]),
        Route("/api/b66/quote/preview-base", b66_certified_preview_base, methods=["GET"]),
        Route("/api/b66/quote/pdf", b66_certified_pdf, methods=["POST"]),
        Route("/api/b66/quotes", b66_quote_history_list, methods=["GET"]),
        Route("/api/b66/quotes", b66_quote_history_save, methods=["POST"]),
        Route(
            "/api/b66/quotes/{quote_history_id}",
            b66_quote_history_detail,
            methods=["GET"],
        ),
        Route(
            "/api/b66/quotes/{quote_history_id}",
            b66_quote_history_delete,
            methods=["DELETE"],
        ),
        Route("/api/claw/manual-intake/preview", claw_manual_intake_preview, methods=["POST"]),
        Route("/api/claw/manual-intake/execute", claw_manual_intake_execute, methods=["POST"]),
        # #3539: the generic Claw composer runs through the canonical #3382 P01
        # Engine lane. It is a distinct B54 product boundary from manual-intake
        # and has no direct-B14 (/api/chat/stream) fallback.
        Route("/api/claw/general", claw_general_execute, methods=["POST"]),
        Route(
            "/api/claw/manual-intake/quote-compare",
            claw_manual_intake_quote_compare,
            methods=["POST"],
        ),
        Route("/api/claw/manual-intake/artifact/{document_id}", claw_manual_intake_artifact, methods=["GET"]),
        Route("/api/claw/telegram/ingest/{binding_ref}", claw_telegram_ingest, methods=["POST"]),
        Route("/api/claw/runs", claw_runs_history, methods=["GET"]),
        Route("/api/claw/approvals/decision", claw_approval_decision, methods=["POST"]),
        Route("/api/claw/memory/approve", claw_memory_approve, methods=["POST"]),
        Route("/api/claw/memory/reject", claw_memory_reject, methods=["POST"]),
        Route("/api/claw/memory", claw_memory_list, methods=["GET"]),
        Route("/api/claw/memory/{memory_id}", claw_memory_detail, methods=["GET"]),
        # #3237: read-only canonical automation rule catalogue. Owner-scoped and
        # tenant-resolved server-side; it creates, updates, deletes, enables,
        # runs nothing and activates no cron.
        Route("/api/claw/automation/rules", claw_automation_rules, methods=["GET"]),
        # #3257: the first Create surface on the same resource. OWNER-only,
        # server-minted identifiers, server-owned execution intent; read-only
        # semantics of the GET route above are unchanged.
        Route("/api/claw/automation/rules", claw_automation_rule_create, methods=["POST"]),
        # #3262: OWNER-gated enable/disable of one canonical rule — the stored
        # rule setting only. Legacy/quarantined rows stay immutable; no Edit,
        # Delete, Run-now, schedule edit or scheduler activation.
        Route(
            "/api/claw/automation/rules/{rule_id}/enabled",
            claw_automation_rule_set_enabled,
            methods=["PATCH"],
        ),
        # #3270: bounded Edit of name + schedule on a canonical, execution-ready
        # rule. The #2908 execution intent, owner provenance, target, output,
        # notifications and enabled state are carried over unchanged.
        Route("/api/claw/automation/rules/{rule_id}", claw_automation_rule_edit, methods=["PATCH"]),
        # #3094: the one real read-only source behind the "Connect this computer"
        # panel. Owner-scoped; it pairs nothing and approves nothing.
        Route(CLAW_LOCAL_ACCESS_PATH, claw_local_access, methods=["GET"]),
        Route("/api/claw/runs/{run_id}/local-result", local_runner_result, methods=["POST"]),
        Route("/api/claw/inbox/{kind}", claw_inbox_list, methods=["GET"]),
        Route("/api/claw/inbox/{kind}/{item_id}", claw_inbox_status, methods=["PATCH"]),
        Route("/api/calendar/today", calendar_today, methods=["GET"]),
        Route("/api/calendar/upcoming", calendar_upcoming, methods=["GET"]),
        Route("/api/calendar/items", calendar_items, methods=["GET"]),
        Route(
            "/api/calendar/items/{calendar_item_id}",
            calendar_item_detail,
            methods=["GET"],
        ),
        Route("/api/calendar/work-logs", calendar_work_logs_list, methods=["GET"]),
        Route("/api/calendar/work-logs", calendar_work_logs_create, methods=["POST"]),
        Route("/api/calendar/appointments", calendar_appointments_list, methods=["GET"]),
        Route("/api/calendar/appointments", calendar_appointments_create, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    # #3476: added before telemetry deliberately — Starlette prepends each
    # middleware, so the later-added telemetry layer stays outermost and keeps
    # recording guard rejections.
    app.add_middleware(SameOriginGuardMiddleware)
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
    # #3782: no browser owner ticket request route in the product app.
    # A trusted Worker may compose its Engine client after CP session binding;
    # this default is never an approval source or browser execution grant.
    app.state.browser_control_owner_ticket_engine_client = None
    # #3190: owner-gated Project Drive case-folder routes. A missing client fails
    # closed with 503; there is no global/network fallback.
    app.state.drive_case_folder_engine_client = drive_case_folder_engine_client
    app.state.usage_gate = UsageGate(resolved, usage_store)

    # #3508 dedicated password-login abuse authority. This deliberately does
    # not reuse the B14/AI UsageGate. Production derives a durable store from
    # the existing Chat D1 binding; tests may inject a network-free oracle.
    _auth_abuse_store = auth_abuse_store
    if _auth_abuse_store is None and d1_binding is not None:
        try:
            _auth_abuse_store = D1AuthAbuseStore(d1_binding)
        except Exception:
            _auth_abuse_store = None
    app.state.auth_abuse_gate = AuthAbuseGate(resolved, _auth_abuse_store)

    # An explicitly injected B14 transport is the existing network-free regression seam.
    # It cannot occur through browser input or Worker bindings. Production/ordinary runtime
    # (transport=None) always enforces the gate; quota-specific integration tests also
    # enforce it by supplying a usage store.
    app.state.usage_gate_enforced = not (transport is not None and usage_store is None)
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = PadiemTierB14Client(resolved, transport=transport)
    # Public, non-secret browser render origin. Unset means B66 account runtime
    # stays fully hidden/off; Production activation is a separate env/deploy gate.
    app.state.b66_quote_base_url = resolved.b66_quote_base_url
    app.state.b66_quote_interpreter = (
        b66_quote_interpreter
        if b66_quote_interpreter is not None
        else B66QuoteConversationInterpreter(app.state.b14_client)
    )
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
    # #2961 owner approval decision lane: the same composed Engine client, used
    # only to submit a server-derived decision to the canonical resume route.
    # None keeps the decision route fail-closed before any Engine transport.
    app.state.claw_p01_continuation_client = claw_p01_continuation_client
    # #3094 read-only device projection for the "Connect this computer" panel.
    # The canonical pairing/broker authority (#3080) composes the real source in
    # from trusted bindings. The default is the fail-closed source: the panel is
    # told no projection exists rather than being shown a guessed device state.
    app.state.claw_local_access_source = (
        claw_local_access_source
        if claw_local_access_source is not None
        else UnconfiguredClawLocalAccessTruthSource()
    )
    # #3139 return leg: the server-owned consumer of a Local Runner terminal
    # result. None keeps the route fail-closed until the Worker root composes
    # the concrete source from the trusted broker binding.
    app.state.local_task_result_source = local_task_result_source
    # #3436 B2c: the canonical broker device-session authority behind the
    # GET-only Desktop conversation surface. Composed from the trusted
    # LOCAL_AGENT_BROKER_AUTHORITY_SERVICE binding by the Worker root; the
    # default refuses every session, so the surface fails closed until the
    # trusted runtime actually exists.
    app.state.desktop_device_session_authority = (
        desktop_device_session_authority
        if desktop_device_session_authority is not None
        else UnconfiguredDesktopDeviceSessionAuthority()
    )
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

    # B66 #3301/#3303: account-bound approved Saved Quote Skills reuse the
    # existing PADIEM_CHAT_DB D1. Browser/local storage is not account authority.
    _b66_saved_quote_skill_store = b66_saved_quote_skill_store
    if _b66_saved_quote_skill_store is None and d1_binding is not None:
        try:
            _b66_saved_quote_skill_store = D1SavedQuoteSkillStore(d1_binding)
        except Exception:
            _b66_saved_quote_skill_store = None
    app.state.b66_saved_quote_skill_store = _b66_saved_quote_skill_store

    # B66 #3406: canonical account/workspace company identity/defaults. This is
    # separate from Saved Quote Skill layout behavior and browser-local presets.
    _b66_company_profile_store = b66_company_profile_store
    if _b66_company_profile_store is None and d1_binding is not None:
        try:
            _b66_company_profile_store = D1CompanyProfileStore(d1_binding)
        except Exception:
            _b66_company_profile_store = None
    app.state.b66_company_profile_store = _b66_company_profile_store

    # B66 #3405 (Slice A): durable account/workspace-scoped quotation history.
    # Server authority only — browser-local quoteBeta.history.v1 is untouched.
    # A stored record is a normalized QuoteDraft snapshot, never a total
    # authority; QuoteCore recalculates on load.
    _b66_quote_history_store = b66_quote_history_store
    if _b66_quote_history_store is None and d1_binding is not None:
        try:
            _b66_quote_history_store = D1QuoteHistoryStore(d1_binding)
        except Exception:
            _b66_quote_history_store = None
    app.state.b66_quote_history_store = _b66_quote_history_store

    # B66 #3402: private logo/stamp bytes reuse the existing private workspace
    # R2 binding, while D1 stores only owner/workspace-scoped metadata. No
    # browser upload surface is composed here.
    _b66_quote_asset_store = b66_quote_asset_store
    if _b66_quote_asset_store is None and d1_binding is not None and r2_binding is not None:
        try:
            _b66_asset_metadata = D1B66QuoteAssetMetadataStore(d1_binding)
            _b66_quote_asset_store = B66QuoteAssetStore(_b66_asset_metadata, r2_binding)
        except Exception:
            _b66_quote_asset_store = None
    app.state.b66_quote_asset_store = _b66_quote_asset_store

    # Certified private PDF bundles reuse the approved Saved Quote Skill and
    # existing private R2 binding. This composition reads only; no upload,
    # assignment, D1 migration or production activation occurs here.
    _b66_bundle_store = b66_certified_quote_bundle_store
    if _b66_bundle_store is None and r2_binding is not None:
        try:
            _b66_bundle_store = B66CertifiedQuoteBundleStore(r2_binding)
        except Exception:
            _b66_bundle_store = None
    app.state.b66_certified_quote_bundle_store = _b66_bundle_store

    _b66_preview_store = b66_certified_preview_store
    if _b66_preview_store is None and r2_binding is not None:
        try:
            _b66_preview_store = B66CertifiedPreviewStore(r2_binding)
        except Exception:
            _b66_preview_store = None
    app.state.b66_certified_preview_store = _b66_preview_store
    app.state.b66_pdf_renderer_client = b66_pdf_renderer_client

    # #2341 Task/Alert inbox: consume the existing migration-010 D1 authority.
    # No schema creation or alternate DB authority is introduced here.
    _task_alert_store = claw_task_alert_store
    if _task_alert_store is None and d1_binding is not None:
        try:
            _task_alert_store = D1ClawTaskAlertStore(d1_binding)
        except Exception:
            _task_alert_store = None
    app.state.claw_task_alert_store = _task_alert_store

    # #2834 Native Padiem Calendar Phase B-2: durable D1 store.
    # Fail-closed: if d1_binding is present but D1CalendarStore construction
    # fails, raise rather than silently falling back to InMemoryCalendarStore.
    # InMemory fallback is allowed only when d1_binding is absent.
    # An explicitly injected calendar_store always wins.
    if calendar_store is not None:
        _calendar_store = calendar_store
    elif d1_binding is not None:
        _calendar_store = D1CalendarStore(d1_binding)
    else:
        _calendar_store = InMemoryCalendarStore()
    app.state.calendar_store = _calendar_store
    # #2983 Native Claw automation durable store (B62 worker persistence seam).
    # Reuses the existing PADIEM_CHAT_DB D1 binding; migration 018 owns the schema
    # and this adapter creates no tables at runtime. An explicitly injected store
    # wins (network-free tests); otherwise derive from the D1 binding when present.
    # None keeps the routes fail-closed.
    _claw_automation_store = claw_automation_store
    if _claw_automation_store is None and d1_binding is not None:
        try:
            _claw_automation_store = D1ClawAutomationStore(d1_binding)
        except Exception:
            _claw_automation_store = None
    app.state.claw_automation_store = _claw_automation_store
    return app