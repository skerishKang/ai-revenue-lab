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
from .b66_ai_chat_routes import b66_ai_chat
from .b66_company_profile import CompanyProfileStore, D1CompanyProfileStore
from .b66_company_profile_routes import b66_company_profile_get, b66_company_profile_put
from .b66_quote_asset_routes import b66_quote_asset_detail
from .b66_member_admin import D1B66MemberAdminStore
from .b66_member_inquiries import (
    D1B66InquiryStore, b66_inquiries, b66_admin_inquiries,
    b66_admin_inquiry_status, b66_admin_inquiry_dispatch,
)
from .central_model_admin_identity import D1CentralModelAdminAuthorizer
from .central_model_policy_d1 import D1CentralModelPolicyStore
from .central_model_control_routes import (
    central_model_admin_me, central_model_admin_snapshot,
    central_model_admin_preview,
)
from .central_model_policy_write_routes import (
    central_model_change_preview, central_model_change_apply,
    central_model_rollback_preview, central_model_change_audit,
)
from .b66_admin_routes import b66_admin_me, b66_admin_members, b66_admin_member_access, b66_admin_member_detail, b66_admin_model_policy, b66_admin_dispatch_alerts
from .b66_quote_history_routes import (
    b66_quote_history_delete,
    b66_quote_history_detail,
    b66_quote_history_list,
    b66_quote_history_save,
)
from .b66_quote_history_store import D1QuoteHistoryStore
from .b66_guided_draft import D1GuidedDraftStore, guided_draft_route
from .b66_quote_assets import B66QuoteAssetStore, D1B66QuoteAssetMetadataStore
from .b66_certified_quote_bundle import B66CertifiedQuoteBundleStore
from .b66_certified_preview import B66CertifiedPreviewStore
from .b66_certified_pdf_routes import b66_certified_pdf, b66_certified_preview_base
from .b66_native_sol_routes import b66_native_sol_pdf, b66_native_sol_scope
from .b66_pc_directory_routes import B66_PC_DIRECTORY_PATH, b66_pc_directory
from padiem_control_plane.local_agent_pc_access import ProductPcAccessPolicy
from .b66_quote_routes import (
    b66_quote_interpret,
    b66_quote_models,
    b66_runtime_config,
    b66_saved_skill_detail,
    b66_saved_skills,
)
from .b66_saved_quote_skill_store import (
    D1SavedQuoteSkillStore,
    SavedQuoteSkillStore,
)
from .b66_saved_skill_candidate_routes import (
    b66_saved_skill_candidate_detail,
    b66_saved_skill_candidate_list,
    b66_saved_skill_candidate_submit,
)
from .b66_saved_skill_candidate_store import (
    D1SavedQuoteSkillCandidateStore,
    SavedQuoteSkillCandidateStore,
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
from .claw_general_routes import claw_general_execute, claw_general_capabilities
from .claw_office_preview_routes import (
    OFFICE_PDF_PREVIEW_PATH, claw_office_pdf_preview,
)
from .claw_web_xlsx_source_routes import (
    WEB_SOURCES_PATH, WEB_SOURCE_DOWNLOAD_PATH,
    web_xlsx_sources, web_xlsx_download,
)
from .claw_web_xlsx_selection_routes import (
    WEB_SELECTIONS_PATH, WEB_SELECTION_PATH,
    web_xlsx_selections, web_xlsx_selection_detail,
)
from .claw_web_xlsx_selection_store import D1WebXlsxSelectionStore
from .claw_web_xlsx_p01_request import D1WebXlsxP01RequestStore
from .claw_web_xlsx_p01_owner_decision import D1WebXlsxP01OwnerDecisionStore
from .claw_web_xlsx_p01_owner_decision_routes import (
    WEB_XLSX_P01_OWNER_DECISION_PATH, web_xlsx_p01_owner_decision,
    WEB_XLSX_P01_OWNER_STATUS_PATH, web_xlsx_p01_owner_status,
    WEB_XLSX_P01_WORKCOPY_DOWNLOAD_PATH, web_xlsx_p01_workcopy_download,
)
from .claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore
from .claw_web_xlsx_quote_write_owner_decision import D1WebQuoteWriteOwnerDecisionStore
from .claw_web_xlsx_quote_pdf import (
    PATH as WRITE_PDF_DOWNLOAD_PATH, web_xlsx_quote_pdf_download,
)
from .claw_web_xlsx_quote_write_pause_store import D1WebQuoteWritePauseStore
from .claw_web_xlsx_quote_approval_routes import (
    REQUEST as WRITE_REQUEST_PATH, DECISION as WRITE_DECISION_PATH,
    DECISION_STATUS as WRITE_APPROVAL_STATUS_PATH,
    request_quote_write, decide_quote_write, quote_write_approval_status,
)
from .claw_web_xlsx_quote_write_routes import (
    WRITE_PATH, WRITE_STATUS_PATH, WRITE_DOWNLOAD_PATH,
    web_xlsx_quote_edit_commit, web_xlsx_quote_edit_status,
    web_xlsx_quote_edit_download,
)
from .claw_web_xlsx_quote_preview_routes import (
    WEB_XLSX_QUOTE_PREVIEW_PATH, web_xlsx_quote_edit_preview,
)
from .claw_web_xlsx_p01_request_routes import (
    WEB_XLSX_REQUEST_P01_PATH, web_xlsx_request_p01,
)
from .claw_web_xlsx_p01_start_routes import (
    WEB_XLSX_START_P01_PATH, web_xlsx_start_p01,
)
from .claw_office_chooser_routes import (
    LIST_PATH as CLAW_OFFICE_CANDIDATES_PATH,
    SELECT_PATH as CLAW_OFFICE_SELECT_PATH,
    candidates as claw_office_candidates,
    select_candidate as claw_office_select_candidate,
)
from .claw_artifact_preview_routes import claw_artifact_inline_preview
from .claw_conversation_artifact_adopt_routes import (
    claw_conversation_artifact_adopt,
)
from .claw_conversation_artifact_routes import claw_conversation_artifact_followup
from .claw_durable_drive_output_pipeline import ClawDurableDriveOutputPipeline
from .claw_office_drive_completion import ClawOfficeDriveCompletion
from .claw_durable_drive_artifact_routes import (
    claw_drive_artifact_download, claw_drive_artifact_preview,
)
# NOTE: aliased because ``create_app`` has a parameter of the same name (the
# injected adapter); the route list is built inside that function.
from .claw_telegram_delivery_routes import (
    TELEGRAM_DELIVERY_PATH, claw_telegram_artifact_delivery as _claw_telegram_delivery_route,
)
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
from .claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH, UnconfiguredDeviceDirectorySource, claw_device_directory,
)
from .claw_local_access_routes import (
    CLAW_LOCAL_ACCESS_PATH,
    UnconfiguredClawLocalAccessTruthSource,
    claw_local_access,
)
from .claw_local_connect_routes import (
    CLAW_LOCAL_CONNECT_PATH,
    UnconfiguredClawLocalPairingConnectPort,
    claw_local_connect,
    claw_local_connect_status,
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
from .conversation_routes import api_conversation_detail, api_conversation_search, api_conversations
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
from .owner_model_preview_routes import claw_verified_model_choices, owner_model_name_preview
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
    # Config validation already requires keys for live web providers. This is
    # configuration readiness, not proof of upstream provider availability.
    web_ready = settings.web_provider in {"mock", "firecrawl", "daum", "tinyfish", "tinyfish_daum"}
    research_ready = settings.runtime_mode == "b14" and settings.web_provider in {"mock", "firecrawl"}
    abuse_ready = usage_gate.ready
    return JSONResponse({
        "status": "ok", "app": "padiem-chat", "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": web_ready,
        "deep_research_ready": research_ready,
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
    claw_drive_artifact_uploader=None,
    claw_drive_artifact_reader=None,
    claw_telegram_authority=None,
    claw_telegram_artifact_delivery=None,
    claw_artifact_delivery_receipt_store=None,
    claw_telegram_delivery_request_builder=None,
    approved_memory_store: ApprovedMemoryStore | None = None,
    b66_saved_quote_skill_store: SavedQuoteSkillStore | None = None,
    b66_saved_skill_candidate_store: SavedQuoteSkillCandidateStore | None = None,
    b66_company_profile_store: CompanyProfileStore | None = None,
    b66_quote_history_store=None,
    b66_guided_draft_store=None,
    b66_quote_asset_store=None,
    b66_certified_quote_bundle_store=None,
    b66_certified_preview_store=None,
    b66_pdf_renderer_client=None,
    b66_native_sol_pdf_client=None,
    b66_native_sol_releases=None,
    b66_quote_interpreter=None,
    b66_member_admin_store=None,
    b66_admin_google_email: str = "",
    central_model_admin_authorizer=None,
    central_model_admin_google_email: str = "",
    central_model_policy_store=None,
    central_model_policy_signing_key: str = "",
    claw_task_alert_store=None,
    calendar_store: CalendarStore | None = None,
    claw_automation_store=None,
    telemetry_emitter=None,
    claw_p01_continuation_client=None,
    claw_local_access_source=None,
    claw_device_directory_source=None,
    b66_pc_access_policy: ProductPcAccessPolicy | None = None,
    claw_local_connect_port=None,
    claw_office_chooser_source=None,
    local_task_result_source=None,
    desktop_device_session_authority=None,
    auth_abuse_store: AuthAbuseStore | None = None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/admin/models/me", central_model_admin_me, methods=["GET"]),
        Route("/api/admin/models/snapshot", central_model_admin_snapshot, methods=["GET"]),
        Route("/api/admin/models/preview", central_model_admin_preview, methods=["POST"]),
        Route("/api/admin/models/change-preview", central_model_change_preview, methods=["POST"]),
        Route("/api/admin/models/change-apply", central_model_change_apply, methods=["POST"]),
        Route("/api/admin/models/rollback-preview", central_model_rollback_preview, methods=["POST"]),
        Route("/api/admin/models/audit", central_model_change_audit, methods=["GET"]),
        Route("/api/models/owner-name-preview", owner_model_name_preview, methods=["GET"]),
        Route("/api/claw/verified-model-choices", claw_verified_model_choices, methods=["GET"]),
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
        Route("/api/conversations/search", api_conversation_search, methods=["GET"]),
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
        Route(B66_PC_DIRECTORY_PATH, b66_pc_directory, methods=["GET"]),
        Route("/api/b66/company-profile", b66_company_profile_get, methods=["GET"]),
        Route("/api/b66/company-profile", b66_company_profile_put, methods=["PUT"]),
        Route("/api/b66/saved-skills", b66_saved_skills, methods=["GET"]),
        Route(
            "/api/b66/saved-skills/{saved_skill_id}",
            b66_saved_skill_detail,
            methods=["GET"],
        ),
        # #3186: a customer may only *request* approval. Approve/reject has no
        # browser route; it is a trusted operator command
        # (b66_saved_skill_candidate_review) over the same durable store.
        Route(
            "/api/b66/saved-skill-candidates",
            b66_saved_skill_candidate_submit,
            methods=["POST"],
        ),
        Route(
            "/api/b66/saved-skill-candidates",
            b66_saved_skill_candidate_list,
            methods=["GET"],
        ),
        Route(
            "/api/b66/saved-skill-candidates/{candidate_id}",
            b66_saved_skill_candidate_detail,
            methods=["GET"],
        ),
        Route(
            "/api/b66/assets/{asset_id}",
            b66_quote_asset_detail,
            methods=["GET"],
        ),
        Route("/api/b66/quote/interpret", b66_quote_interpret, methods=["POST"]),
        Route("/api/b66/ai/chat", b66_ai_chat, methods=["POST"]),
        Route("/api/b66/quote/models", b66_quote_models, methods=["GET"]),
        Route("/api/b66/inquiries", b66_inquiries, methods=["GET", "POST"]),
        Route("/api/b66/admin/inquiries", b66_admin_inquiries, methods=["GET"]),
        Route("/api/b66/admin/inquiries/dispatch", b66_admin_inquiry_dispatch, methods=["POST"]),
        Route("/api/b66/admin/inquiries/{inquiry_id}", b66_admin_inquiry_status, methods=["PATCH"]),
        Route("/api/b66/admin/me", b66_admin_me, methods=["GET"]),
        Route("/api/b66/admin/members", b66_admin_members, methods=["GET"]),
        Route("/api/b66/admin/model-policy", b66_admin_model_policy, methods=["GET", "PUT"]),
        Route("/api/b66/admin/alerts/dispatch", b66_admin_dispatch_alerts, methods=["POST"]),
        Route("/api/b66/admin/members/{user_id}", b66_admin_member_access, methods=["PATCH"]),
        Route("/api/b66/admin/members/{user_id}/detail", b66_admin_member_detail, methods=["GET"]),
        Route("/api/b66/quote/preview-base", b66_certified_preview_base, methods=["GET"]),
        Route("/api/b66/quote/pdf", b66_certified_pdf, methods=["POST"]),
        Route("/api/b66/quote/native-sol-pdf", b66_native_sol_pdf, methods=["POST"]),
        Route("/api/b66/quote/native-sol-scope", b66_native_sol_scope, methods=["GET"]),
        Route("/api/b66/quotes", b66_quote_history_list, methods=["GET"]),
        Route("/api/b66/quotes", b66_quote_history_save, methods=["POST"]),
        Route("/api/b66/guided-draft", guided_draft_route, methods=["GET", "PUT", "DELETE"]),
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
        Route(WEB_SOURCES_PATH, web_xlsx_sources, methods=["GET", "POST"]),
        Route(WEB_SOURCE_DOWNLOAD_PATH, web_xlsx_download, methods=["GET"]),
        Route(WEB_SELECTIONS_PATH, web_xlsx_selections, methods=["GET", "POST"]),
        Route(WEB_SELECTION_PATH, web_xlsx_selection_detail, methods=["GET"]),
        Route(WEB_XLSX_REQUEST_P01_PATH, web_xlsx_request_p01, methods=["POST"]),
        Route(WEB_XLSX_START_P01_PATH, web_xlsx_start_p01, methods=["POST"]),
        Route(WEB_XLSX_P01_OWNER_DECISION_PATH, web_xlsx_p01_owner_decision, methods=["POST"]),
        Route(WEB_XLSX_P01_OWNER_STATUS_PATH, web_xlsx_p01_owner_status, methods=["GET"]),
        Route(WEB_XLSX_P01_WORKCOPY_DOWNLOAD_PATH, web_xlsx_p01_workcopy_download, methods=["GET"]),
        Route(WEB_XLSX_QUOTE_PREVIEW_PATH, web_xlsx_quote_edit_preview, methods=["POST"]),
        Route(WRITE_PATH, web_xlsx_quote_edit_commit, methods=["POST"]),
        Route(WRITE_REQUEST_PATH, request_quote_write, methods=["POST"]),
        Route(WRITE_DECISION_PATH, decide_quote_write, methods=["POST"]),
        Route(WRITE_APPROVAL_STATUS_PATH, quote_write_approval_status, methods=["GET"]),
        Route(WRITE_STATUS_PATH, web_xlsx_quote_edit_status, methods=["GET"]),
        Route(WRITE_DOWNLOAD_PATH, web_xlsx_quote_edit_download, methods=["GET"]),
        Route(WRITE_PDF_DOWNLOAD_PATH, web_xlsx_quote_pdf_download, methods=["GET"]),
        Route("/api/claw/manual-intake/preview", claw_manual_intake_preview, methods=["POST"]),
        Route("/api/claw/manual-intake/execute", claw_manual_intake_execute, methods=["POST"]),
        # #3539: the generic Claw composer runs through the canonical #3382 P01
        # Engine lane. It is a distinct B54 product boundary from manual-intake
        # and has no direct-B14 (/api/chat/stream) fallback.
        Route("/api/claw/general/capabilities", claw_general_capabilities, methods=["GET"]),
        Route("/api/claw/general", claw_general_execute, methods=["POST"]),
        Route(
            "/api/claw/manual-intake/quote-compare",
            claw_manual_intake_quote_compare,
            methods=["POST"],
        ),
        Route("/api/claw/manual-intake/artifact/{document_id}", claw_manual_intake_artifact, methods=["GET"]),
        # #3932 preview is a separate GET; existing download remains attachment-only.
        Route("/api/claw/manual-intake/artifact/{document_id}/preview", claw_artifact_inline_preview, methods=["GET"]),
        Route("/api/claw/telegram/ingest/{binding_ref}", claw_telegram_ingest, methods=["POST"]),
        Route("/api/claw/conversations/{conversation_id}/artifact-followup", claw_conversation_artifact_followup, methods=["GET"]),
        # #3933: making an already-completed result the input of a NEW task is
        # a separate POST. It re-reads only the exact owner-indexed revision
        # bytes and mints a NEW document identity, so no previous selection,
        # P01 READ decision, workcopy or WRITE receipt can apply and a NEW
        # owner READ approval is required before any processing.
        Route("/api/claw/conversations/{conversation_id}/artifact-followup/adopt", claw_conversation_artifact_adopt, methods=["POST"]),
        Route("/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/download", claw_drive_artifact_download, methods=["GET"]),
        Route("/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/preview", claw_drive_artifact_preview, methods=["GET"]),
        # #3580: the one consumer of the trusted Telegram delivery adapter. It
        # creates no WRITE/SEND authority; with no injected adapter, receipt
        # store and host request builder it answers 403 and no provider path
        # exists at all.
        Route(TELEGRAM_DELIVERY_PATH, _claw_telegram_delivery_route, methods=["POST"]),
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
        # #4139: read-only multi-PC list; owner + workspace derived from session.
        Route(CLAW_DEVICE_DIRECTORY_PATH, claw_device_directory, methods=["GET"]),
        # #3650: the local/nonprod initiating leg. Fail-closed unless the run
        # composition explicitly installs a connect port; the central #3476
        # same-origin guard covers it like every cookie-authenticated POST.
        Route(CLAW_LOCAL_CONNECT_PATH, claw_local_connect, methods=["POST"]),
        Route(CLAW_LOCAL_CONNECT_PATH, claw_local_connect_status, methods=["GET"]),
        Route(CLAW_OFFICE_CANDIDATES_PATH, claw_office_candidates, methods=["GET"]),
        Route(CLAW_OFFICE_SELECT_PATH, claw_office_select_candidate, methods=["POST"]),
        Route(OFFICE_PDF_PREVIEW_PATH, claw_office_pdf_preview, methods=["GET"]),
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
    # B66 admin authority shares signed user sessions and the existing D1.
    # Missing D1 or migrations fails closed rather than serving a demo roster.
    app.state.b66_member_admin_store = (b66_member_admin_store if b66_member_admin_store is not None
        else D1B66MemberAdminStore(d1_binding, admin_email=b66_admin_google_email) if d1_binding is not None else None)
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    # Separate deployment gate: migrate and audit the D1 schema before enabling.
    # A B66-scoped Google administrator is NOT a global model administrator.
    # Only a separately verified host-supplied central RBAC authority may
    # activate the cross-product model snapshot/preview APIs.
    global_model_admin = central_model_admin_authorizer
    if global_model_admin is None and central_model_admin_google_email and d1_binding is not None:
        try:
            global_model_admin = D1CentralModelAdminAuthorizer(
                d1_binding, verified_owner_email=central_model_admin_google_email,
            )
        except ValueError:
            global_model_admin = None
    app.state.central_model_admin_authorizer = global_model_admin
    # S2 read-only D1 policy inventory. Migration 039 and verified global
    # administrator remain separately gated. DO NOT wire apply or dispatch.
    app.state.central_model_policy_store = (
        central_model_policy_store if central_model_policy_store is not None
        else D1CentralModelPolicyStore(d1_binding)
        if d1_binding is not None and callable(getattr(d1_binding, "batch", None))
        and callable(getattr(d1_binding, "prepare", None)) else None
    )
    # Independent, server-only signer. Missing or malformed => all central writes OFF.
    import re as _model_re
    app.state.central_model_policy_write_key = (
        bytes.fromhex(central_model_policy_signing_key)
        if isinstance(central_model_policy_signing_key, str)
        and _model_re.fullmatch(r"[a-fA-F0-9]{64}", central_model_policy_signing_key)
        else None
    )
    app.state.b66_membership_enforced = False
    # Production host enables this independently of the membership rollout.
    # Pure ASGI fixtures without a D1 adapter keep their pre-existing behavior.
    app.state.b66_global_model_switch_enforced = False
    app.state.b66_signup_notifier = None
    # Inquiry tables are introduced by migration 038; without D1 the route
    # fails closed, and without the migration it cannot accept submissions.
    app.state.b66_inquiry_store = D1B66InquiryStore(d1_binding) if d1_binding is not None else None
    # Canonical identity remains Control Plane authority. Product D1 stores only
    # a non-authoritative shadow pointer used to reach the current canonical session.
    app.state.control_plane_identity_authority = control_plane_identity_authority
    app.state.identity_shadow_store = identity_shadow_store
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
    # Explicit trusted product policy only. No public API, environment bool,
    # email or feature flag may activate PC directory visibility.
    app.state.b66_pc_access_policy = (
        b66_pc_access_policy
        if isinstance(b66_pc_access_policy, ProductPcAccessPolicy)
        else ProductPcAccessPolicy.default_off()
    )
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
    # #3580: D1-persisted owner-scoped selection only; cannot mint an Engine
    # approval, access R2 bytes, or process a workbook. Separate migration 029.
    app.state.claw_web_xlsx_selection_store = (
        D1WebXlsxSelectionStore(d1_binding)
        if _workspace_store is not None and d1_binding is not None else None
    )
    # Engine adapter requires separately authenticated, private composition.
    # No default service calls, fake approval or in-memory fallback.
    app.state.web_xlsx_p01_request_store = (
        D1WebXlsxP01RequestStore(d1_binding)
        if _workspace_store is not None and d1_binding is not None else None
    )
    app.state.web_xlsx_p01_pause_client = None
    app.state.web_xlsx_p01_owner_decision_store = (
        D1WebXlsxP01OwnerDecisionStore(d1_binding)
        if _workspace_store is not None and d1_binding is not None else None
    )
    app.state.web_xlsx_p01_owner_decision_client = None
    # Explicit operator-only feature gate. The browser can never turn on
    # Engine-granted processing by posting its own approval status.
    app.state.web_xlsx_p01_workcopy_after_grant_enabled = False
    app.state.web_xlsx_quote_write_store = (
        D1WebQuoteWriteReceiptStore(d1_binding) if d1_binding is not None else None
    )
    app.state.web_xlsx_quote_write_pause_store = (
        D1WebQuoteWritePauseStore(d1_binding)
        if _workspace_store is not None and d1_binding is not None else None
    )
    # Separate explicit owner WRITE consent ledger. This does not enable the
    # public edit route or mint any Engine ToolRuntime grant by itself.
    app.state.web_xlsx_quote_write_owner_decision_store = (
        D1WebQuoteWriteOwnerDecisionStore(d1_binding)
        if _workspace_store is not None and d1_binding is not None else None
    )
    # Separate Core/Engine EDIT/WRITE P01 is deliberately NOT active. A READ
    # approval, preview hash or browser decision cannot enable actual writes.
    app.state.web_xlsx_quote_write_enabled = False
    app.state.web_xlsx_quote_write_client = None
    app.state.web_xlsx_quote_pdf_renderer = None
    app.state.web_xlsx_quote_pdf_enabled = False
    # Worker-native Claw P01/Engine adapter (#2229). Injected by the Worker
    # composition root from trusted bindings; None means unconfigured and the
    # execute route fails closed before any transport.
    app.state.claw_p01_adapter = claw_p01_adapter
    # #3929/#3580: no default Google/Drive WRITE. The CP-authorized host
    # must explicitly inject an existing approved Drive uploader; mere D1
    # binding / auth-cookie / model answer can never activate an upload.
    app.state.claw_durable_drive_output_pipeline = (
        ClawDurableDriveOutputPipeline(
            history=history_store, uploader=claw_drive_artifact_uploader
        )
        if history_store is not None and claw_drive_artifact_uploader is not None
        else None
    )
    # A verified local Office producer can hand over its two canonical outputs
    # only when the host has separately injected the approved Drive uploader.
    # No P01/Office producer or Drive grant is activated by this composition.
    app.state.claw_office_drive_completion = (
        ClawOfficeDriveCompletion(
            pipeline=app.state.claw_durable_drive_output_pipeline
        )
        if app.state.claw_durable_drive_output_pipeline is not None
        else None
    )
    # READ is a separate current-grant host capability. WRITE approval never
    # authorizes browser download; no implicit Worker transport is installed.
    app.state.claw_drive_artifact_reader = claw_drive_artifact_reader
    # Explicit trusted server opt-in; no browser-provided activation authority.
    app.state.claw_live_sse_enabled = False
    # #2961 owner approval decision lane: the same composed Engine client, used
    # only to submit a server-derived decision to the canonical resume route.
    # None keeps the decision route fail-closed before any Engine transport.
    app.state.claw_p01_continuation_client = claw_p01_continuation_client
    # #3094 read-only device projection for the "Connect this computer" panel.
    # The canonical pairing/broker authority (#3080) composes the real source in
    # from trusted bindings. The default is the fail-closed source: the panel is
    # told no projection exists rather than being shown a guessed device state.
    app.state.claw_device_directory_source = (
        claw_device_directory_source
        if claw_device_directory_source is not None
        else UnconfiguredDeviceDirectorySource()
    )
    app.state.claw_local_access_source = (
        claw_local_access_source
        if claw_local_access_source is not None
        else UnconfiguredClawLocalAccessTruthSource()
    )
    # #3650 local/nonprod connect initiating leg. None keeps the route at its
    # bounded fail-closed refusal: production never composes one, so no
    # challenge can be minted there and no pairing store appears.
    app.state.claw_local_connect = (
        claw_local_connect_port
        if claw_local_connect_port is not None
        else UnconfiguredClawLocalPairingConnectPort()
    )
    # #3139 return leg: the server-owned consumer of a Local Runner terminal
    # result. None keeps the route fail-closed until the Worker root composes
    # the concrete source from the trusted broker binding.
    app.state.local_task_result_source = local_task_result_source
    # Office chooser is fail-closed until the real trusted Engine/Resident
    # operator supplies an owner-bound, pre-approved candidate/approval source.
    app.state.claw_office_chooser_source = claw_office_chooser_source
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
    # #3580: outbound artifact delivery seam, separate from the inbound ingest
    # authority above. None keeps it fail-closed; the CP-authorized host must
    # inject the existing delivery adapter through
    # app.claw_telegram_delivery_host_composition, and no token, chat id or
    # destination is ever a request value.
    app.state.claw_telegram_artifact_delivery = claw_telegram_artifact_delivery
    # #3580: the delivery consumer's two remaining trusted seams. The receipt
    # store is the one-attempt-per-artifact record; the request builder is the
    # host's server-derived channel + approval binding. None keeps the route at
    # its 403 refusal with no provider path.
    app.state.claw_artifact_delivery_receipt_store = (
        claw_artifact_delivery_receipt_store
    )
    app.state.claw_telegram_delivery_request_builder = (
        claw_telegram_delivery_request_builder
    )
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

    # B66 #3186: customer approval *requests* for a new Saved Quote Skill. Reuses
    # the same PADIEM_CHAT_DB D1 and the same signed auth. Submission is
    # owner-scoped and idempotent; approval remains a trusted operator action and
    # is never reachable from the browser.
    _b66_saved_skill_candidate_store = b66_saved_skill_candidate_store
    if _b66_saved_skill_candidate_store is None and d1_binding is not None:
        try:
            _b66_saved_skill_candidate_store = D1SavedQuoteSkillCandidateStore(d1_binding)
        except Exception:
            _b66_saved_skill_candidate_store = None
    app.state.b66_saved_skill_candidate_store = _b66_saved_skill_candidate_store

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

    # #3396: one authenticated in-progress guided task per owner/workspace.
    _b66_guided_draft_store = b66_guided_draft_store
    if _b66_guided_draft_store is None and d1_binding is not None:
        _b66_guided_draft_store = D1GuidedDraftStore(d1_binding)
    app.state.b66_guided_draft_store = _b66_guided_draft_store

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
    # #4117: deliberately not wired from the legacy PDF Worker binding.
    # Only a separately certified native Sol runtime may populate these.
    app.state.b66_native_sol_pdf_client = b66_native_sol_pdf_client
    app.state.b66_native_sol_releases = b66_native_sol_releases

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
