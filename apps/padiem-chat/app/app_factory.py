from __future__ import annotations

import httpx
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .android_auth_routes import (
    android_handoff_claim,
    android_handoff_confirm,
    android_handoff_create,
    android_handoff_status,
)
from .account_model_selection_routes import (
    MODEL_SELECTION_PATH,
    account_model_selection_get,
    account_model_selection_put,
)
from .account_model_selection_store import D1AccountModelSelectionStore
from .android_auth_store import D1AndroidAuthHandoffStore
from .auth import GoogleOAuthClient
from .auth_abuse import AuthAbuseGate, AuthAbuseStore, D1AuthAbuseStore
from .b66_quote_conversation import B66QuoteConversationInterpreter
from .b66_ai_chat_routes import b66_ai_chat
from .b66_ai_conversation_routes import conversation_state, conversation_turn
from .b66_ai_conversation_store import D1ConversationStore
from .b66_conversation_store import B66ConversationStore
from .b66_durable_turn_attempt import D1B66TurnAttemptStore
from .b66_dialogue_routes import b66_dialogue_detail, b66_dialogue_list
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
from .central_model_route_d1 import D1CentralModelRouteStore
from .platform_admin_authority import PlatformAdminAuthority
from .platform_admin_routes import (
    platform_admin_role_assign,
    platform_admin_role_revoke,
    platform_admin_session,
)
from .central_model_route_routes import (
    central_model_route_apply, central_model_route_preview,
    central_model_route_rollback_preview, central_model_routes_get,
)
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
from .b66_guided_draft import D1GuidedDraftStore, guided_draft_route, guided_transcript_route
from .final_dispatch_guard_wiring import SimpleB14CatalogSource
from .b66_quote_assets import B66QuoteAssetStore, D1B66QuoteAssetMetadataStore
from .b66_template_source import (
    B66TemplateSourceStore,
    D1B66TemplateSourceMetadataStore,
)
from .b66_template_source_routes import (
    b66_template_source_detail,
    b66_template_source_list,
    b66_template_source_upload,
)
from .b66_certified_quote_bundle import B66CertifiedQuoteBundleStore
from .b66_certified_preview import B66CertifiedPreviewStore
from .b66_certified_pdf_routes import b66_certified_pdf, b66_certified_preview_base
from .b66_native_sol_routes import b66_native_sol_pdf, b66_native_sol_scope
from .b66_pc_directory_routes import B66_PC_DIRECTORY_PATH, b66_pc_directory
from .b66_pc_txt_read_routes import (
    B66_PC_RESULT_PATH,
    B66_PC_TXT_READ_PATH,
    b66_pc_run_result,
    b66_pc_txt_read_request,
)
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
    b66_saved_skill_candidate_operator_decision,
    b66_saved_skill_candidate_operator_detail,
    b66_saved_skill_candidate_operator_list,
    b66_saved_skill_candidate_submit,
)
from .b66_saved_skill_candidate_store import (
    D1SavedQuoteSkillCandidateStore,
    SavedQuoteSkillCandidateStore,
)
from .home_product_access_routes import ACCESS_PATH, home_product_access
from .auth_routes import (
    auth_status,
    google_callback,
    google_start,
    logout,
    password_change,
    password_login,
    password_register,
    password_reset_confirm,
    password_reset_request,
)
from .auto_grounding import AutoGroundingService
from .voice_stt_routes import IDENTITY_PATH as VOICE_IDENTITY_PATH
from .voice_stt_routes import TRANSCRIBE_PATH as VOICE_TRANSCRIBE_PATH
from .voice_stt_routes import LIVE_TOKEN_PATH as VOICE_LIVE_TOKEN_PATH
from .voice_stt_routes import CLAW_IDENTITY_PATH as CLAW_VOICE_IDENTITY_PATH
from .voice_stt_routes import CLAW_TRANSCRIBE_PATH as CLAW_VOICE_TRANSCRIBE_PATH
from .voice_stt_routes import CLAW_LIVE_TOKEN_PATH as CLAW_VOICE_LIVE_TOKEN_PATH
from .voice_stt_routes import voice_identity, voice_transcribe, voice_live_token
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
from .claw_meeting_store import D1ClawMeetingStore
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
from .claw_ticket_drive_output_host import ClawTicketDriveOutputHost
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
    claw_pending_result,
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
    calendar_appointment_manage,
    calendar_work_log_manage,
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
from .claw_push_subscriptions import (
    D1ClawPushSubscriptionStore,
    claw_push_capability,
    claw_push_subscription_register,
    claw_push_subscription_unregister,
)
from .claw_local_task_result_routes import CLAW_LOCAL_TASK_RESULT_PATH, local_runner_result
from .claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH, CLAW_PC_PAUSE_PATH, CLAW_PC_RESUME_PATH,
    CLAW_PC_SELECT_PATH,
    UnconfiguredDeviceDirectorySource, claw_device_directory, claw_pc_pause,
    claw_pc_resume, claw_pc_select,
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
from .connector_disconnect_routes import disconnect_google_drive
from .github_oauth_routes import (github_start, github_callback, github_status,
                                  github_repositories, github_disconnect, github_pause, github_resume,
                                  github_installation_settings)
from .byok_client import CustomProviderClient
from .byok_credentials import D1CustomProviderCredentialStore
from .byok_routes import (
    custom_credential_delete,
    custom_credential_save,
    custom_credential_status,
    custom_credential_test,
    custom_provider_models,
)
from .connector_ticket_routes import google_connector_ticket
from .meeting_drive_upload_routes import MEETING_DRIVE_SESSION_PATH, meeting_drive_upload_session
from .claw_meeting_routes import (
    MEETING_ACTION_PATH, MEETING_ACTIONS_PATH, MEETING_ARTIFACT_PATH, MEETING_END_PATH,
    MEETING_PATH, MEETINGS_PATH,
    claw_meeting_action, claw_meeting_action_create, claw_meeting_artifact,
    claw_meeting_detail, claw_meeting_end, claw_meetings,
)
from .b66_drive_routes import (
    b66_drive_connect,
    b66_drive_connect_callback_return,
    b66_drive_disconnect,
    b66_drive_status,
)
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
from .password_reset import PasswordResetService
from .password_reset_store import D1PasswordResetStore
from .project_file_routes import (
    owner_files_collection,
    project_file_detail,
    project_file_original,
    project_files_collection,
)
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
from .session_revocation_guard import SessionRevocationGuardMiddleware
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
        "voice_stt_available": getattr(request.app.state, "voice_stt_transport", None) is not None,
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
    meeting_drive_upload_session_port=None,
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
    b66_ai_conversation_store=None,
    b66_quote_asset_store=None,
    b66_template_source_store=None,
    b66_certified_quote_bundle_store=None,
    b66_certified_preview_store=None,
    b66_pdf_renderer_client=None,
    b66_native_sol_pdf_client=None,
    b66_native_sol_releases=None,
    b66_quote_interpreter=None,
    b66_member_admin_store=None,
    b66_admin_google_email: str = "",
    b66_review_grant_issuer=None,
    b66_canonical_candidate_target_resolver=None,
    central_model_admin_authorizer=None,
    central_model_admin_google_email: str = "",
    platform_admin_role_store=None,
    central_model_policy_store=None,
    central_model_policy_signing_key: str = "",
    claw_task_alert_store=None,
    claw_push_subscription_store=None,
    calendar_store: CalendarStore | None = None,
    claw_automation_store=None,
    telemetry_emitter=None,
    telemetry_exporter=None,
    claw_p01_continuation_client=None,
    claw_local_access_source=None,
    claw_device_directory_source=None,
    claw_pc_device_selection_store=None,
    b66_pc_access_policy: ProductPcAccessPolicy | None = None,
    claw_local_connect_port=None,
    claw_office_chooser_source=None,
    local_task_result_source=None,
    connector_txt_read_source=None,
    oracle_mesh_return_source=None,
    claw_engine_desktop_secret=None,
    desktop_device_session_authority=None,
    auth_abuse_store: AuthAbuseStore | None = None,
    password_reset_store=None,
    password_reset_delivery=None,
    android_handoff_store=None,
    connector_owner_enrollment=None,
    github_oauth_store=None,
    github_oauth_provider=None,
    central_model_route_store=None,
    custom_credential_store=None,
    custom_provider_client=None,
    account_model_selection_store=None,
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
        Route("/api/admin/models/routes", central_model_routes_get, methods=["GET"]),
        Route("/api/admin/models/route-preview", central_model_route_preview, methods=["POST"]),
        Route("/api/admin/models/route-apply", central_model_route_apply, methods=["POST"]),
        Route("/api/admin/models/route-rollback-preview", central_model_route_rollback_preview, methods=["POST"]),
        Route("/api/admin/session", platform_admin_session, methods=["GET"]),
        Route("/api/admin/roles", platform_admin_role_assign, methods=["POST"]),
        Route("/api/admin/roles/{user_id}", platform_admin_role_revoke, methods=["DELETE"]),
        Route("/api/models/owner-name-preview", owner_model_name_preview, methods=["GET"]),
        Route("/api/claw/verified-model-choices", claw_verified_model_choices, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route(VOICE_IDENTITY_PATH, voice_identity, methods=["GET"]),
        Route(VOICE_TRANSCRIBE_PATH, voice_transcribe, methods=["POST"]),
        Route(VOICE_LIVE_TOKEN_PATH, voice_live_token, methods=["POST"]),
        Route(CLAW_VOICE_IDENTITY_PATH, voice_identity, methods=["GET"]),
        Route(CLAW_VOICE_TRANSCRIBE_PATH, voice_transcribe, methods=["POST"]),
        Route(CLAW_VOICE_LIVE_TOKEN_PATH, voice_live_token, methods=["POST"]),
        Route(ACCESS_PATH, home_product_access, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        # Android 1.0.0 external-browser return contract. The callback above
        # serves both flows; these routes create, poll, confirm, and claim a
        # one-time handoff without adding a second account/session authority.
        Route("/auth/android/handoff", android_handoff_create, methods=["POST"]),
        Route("/auth/android/handoff/{handoff_id}", android_handoff_status, methods=["GET"]),
        Route("/auth/android/handoff/{handoff_id}/claim", android_handoff_claim, methods=["POST"]),
        Route("/auth/android/confirm", android_handoff_confirm, methods=["POST"]),
        Route("/api/auth/password/register", password_register, methods=["POST"]),
        Route("/api/auth/password/login", password_login, methods=["POST"]),
        Route("/api/auth/password/change", password_change, methods=["POST"]),
        # #5441 lost-password self-service reset. The request route issues one
        # short-lived, single-use link; the confirm route redeems it and sets
        # the new password.
        Route("/api/auth/password/reset/request", password_reset_request, methods=["POST"]),
        Route("/api/auth/password/reset/confirm", password_reset_confirm, methods=["POST"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/connectors/google/ticket", google_connector_ticket, methods=["POST"]),
        Route(MEETING_DRIVE_SESSION_PATH, meeting_drive_upload_session, methods=["POST"]),
        Route(MEETINGS_PATH, claw_meetings, methods=["GET", "POST"]),
        Route(MEETING_PATH, claw_meeting_detail, methods=["GET", "PATCH", "DELETE"]),
        Route(MEETING_END_PATH, claw_meeting_end, methods=["POST"]),
        Route(MEETING_ARTIFACT_PATH, claw_meeting_artifact, methods=["POST"]),
        Route(MEETING_ACTIONS_PATH, claw_meeting_action_create, methods=["POST"]),
        Route(MEETING_ACTION_PATH, claw_meeting_action, methods=["PATCH", "DELETE"]),
        Route("/api/connectors/google/calendar/activate-read", activate_google_calendar_read, methods=["POST"]),
        Route("/api/connectors/status", connectors_status, methods=["GET"]),
        Route("/api/connectors/google/drive/disconnect", disconnect_google_drive, methods=["POST"]),
        Route("/api/b66/drive/status", b66_drive_status, methods=["GET"]),
        Route("/api/b66/drive/connect", b66_drive_connect, methods=["POST"]),
        Route("/api/b66/drive/connect/callback", b66_drive_connect_callback_return, methods=["GET"]),
        Route("/api/b66/drive/disconnect", b66_drive_disconnect, methods=["POST"]),
        Route("/api/connectors/github/start", github_start, methods=["GET"]),
        Route("/api/connectors/github/callback", github_callback, methods=["GET"]),
        Route("/api/connectors/github/status", github_status, methods=["GET"]),
        Route("/api/connectors/github/installations", github_installation_settings, methods=["GET"]),
        Route("/api/connectors/github/repositories", github_repositories, methods=["GET"]),
        Route("/api/connectors/github/disconnect", github_disconnect, methods=["POST"]),
        Route("/api/connectors/github/pause", github_pause, methods=["POST"]),
        Route("/api/connectors/github/resume", github_resume, methods=["POST"]),
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        # #4489: one owner-scoped keyset-paginated read over every stored project file,
        # so the Library can walk a full history without per-project fan-out.
        Route("/api/project-files", owner_files_collection, methods=["GET"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}/files/{file_id}/original", project_file_original, methods=["GET"]),
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
        Route("/api/chat/custom/credential", custom_credential_status, methods=["GET"]),
        Route("/api/chat/custom/credential", custom_credential_save, methods=["PUT"]),
        Route("/api/chat/custom/credential", custom_credential_delete, methods=["DELETE"]),
        # #5121 PADIEM Custom (BYOK) multi-provider routes: the customer key
        # lane, separate from the B14 managed model routes.
        Route("/api/chat/custom/credential/test", custom_credential_test, methods=["GET"]),
        Route("/api/chat/custom/models", custom_provider_models, methods=["GET"]),
        # #5222 account-scoped last selected AI tier. One signed-in account owns
        # one stored preference; the browser never names the account.
        Route(MODEL_SELECTION_PATH, account_model_selection_get, methods=["GET"]),
        Route(MODEL_SELECTION_PATH, account_model_selection_put, methods=["PUT"]),
        Route("/api/b66/runtime-config", b66_runtime_config, methods=["GET"]),
        Route(B66_PC_DIRECTORY_PATH, b66_pc_directory, methods=["GET"]),
        Route(B66_PC_TXT_READ_PATH, b66_pc_txt_read_request, methods=["POST"]),
        Route(B66_PC_RESULT_PATH, b66_pc_run_result, methods=["POST"]),
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
            "/api/b66/admin/saved-skill-candidates",
            b66_saved_skill_candidate_operator_list,
            methods=["GET"],
        ),
        Route(
            "/api/b66/admin/saved-skill-candidates/{candidate_id}",
            b66_saved_skill_candidate_operator_detail,
            methods=["GET"],
        ),
        Route(
            "/api/b66/admin/saved-skill-candidates/{candidate_id}/decision",
            b66_saved_skill_candidate_operator_decision,
            methods=["POST"],
        ),
        Route(
            "/api/b66/assets/{asset_id}",
            b66_quote_asset_detail,
            methods=["GET"],
        ),
        # B66 #3884 Slice 1: private customer template source custody.
        # Upload/list/download only; no approve/compile route exists in this slice.
        Route(
            "/api/b66/template-sources",
            b66_template_source_upload,
            methods=["POST"],
        ),
        Route(
            "/api/b66/template-sources",
            b66_template_source_list,
            methods=["GET"],
        ),
        Route(
            "/api/b66/template-sources/{template_source_id}",
            b66_template_source_detail,
            methods=["GET"],
        ),
        Route("/api/b66/quote/interpret", b66_quote_interpret, methods=["POST"]),
        Route("/api/b66/ai/chat", b66_ai_chat, methods=["POST"]),
        Route("/api/b66/ai/conversation", conversation_turn, methods=["POST"]),
        Route("/api/b66/ai/conversation", conversation_state, methods=["GET"]),
        Route("/api/b66/ai/dialogues", b66_dialogue_list, methods=["GET"]),
        Route("/api/b66/ai/dialogues/{conversation_id}", b66_dialogue_detail, methods=["GET", "DELETE"]),
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
        Route("/api/b66/guided-conversations", guided_transcript_route, methods=["GET"]),
        Route("/api/b66/guided-conversations/{conversation_id}", guided_transcript_route, methods=["GET", "DELETE"]),
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
        Route("/api/claw/runs/{run_id}/pending-result", claw_pending_result, methods=["GET"]),
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
        Route(CLAW_PC_PAUSE_PATH, claw_pc_pause, methods=["POST"]),
        Route(CLAW_PC_RESUME_PATH, claw_pc_resume, methods=["POST"]),
        Route(CLAW_PC_SELECT_PATH, claw_pc_select, methods=["POST"]),
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
        # #5034 Web Push opt-in for the EXISTING user inbox. This adds a device
        # subscription, never a second inbox or a second notification authority.
        Route("/api/claw/inbox/push/capability", claw_push_capability, methods=["GET"]),
        Route("/api/claw/inbox/push/subscription", claw_push_subscription_register, methods=["POST"]),
        Route("/api/claw/inbox/push/subscription", claw_push_subscription_unregister, methods=["DELETE"]),
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
        Route("/api/calendar/appointments/{appointment_id}", calendar_appointment_manage, methods=["PUT","DELETE"]),
        Route("/api/calendar/work-logs/{log_id}", calendar_work_log_manage, methods=["PUT","DELETE"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    # #4139: append the owner-only consent/challenge routes before the catch-all
    # StaticFiles Mount, solely when the server provided canonical private
    # Identity+Broker ports. The default public app has no such route.
    if connector_owner_enrollment is not None:
        from .connector_owner_runtime_mount import reviewed_owner_enrollment_routes
        from .connector_txt_read_routes import (
            CONNECTOR_TXT_READ_REQUEST_PATH,
            connector_txt_read_request,
        )
        from .connector_android_read_routes import (
            CONNECTOR_ANDROID_FOLDERS_PATH,
            CONNECTOR_ANDROID_READ_REQUEST_PATH,
            connector_android_folders,
            connector_android_read_request,
        )
        from .android_device_enrollment_routes import (
            ANDROID_ENROLLMENT_CHALLENGE_PATH,
            android_enrollment_challenge,
        )
        routes[-1:-1] = list(reviewed_owner_enrollment_routes(connector_owner_enrollment))
        routes[-1:-1] = [
            Route(CONNECTOR_TXT_READ_REQUEST_PATH, connector_txt_read_request, methods=["POST"]),
            # #5080: the Android device enrollment challenge. Same canonical
            # enrollment, Identity consent and Broker challenge as the browser
            # issue route; the one-time pairing code is released to the DEVICE
            # so the device can redeem the credential on the broker pairing
            # surface. It never releases a credential or a browser reference.
            Route(
                ANDROID_ENROLLMENT_CHALLENGE_PATH,
                android_enrollment_challenge,
                methods=["POST"],
            ),
            # #5080: Android adapter over the same approval/enqueue/result
            # pipeline. Folders are the phone's declared SAF set; the browser
            # never supplies an account, workspace, credential or SAF URI.
            Route(CONNECTOR_ANDROID_FOLDERS_PATH, connector_android_folders, methods=["GET"]),
            Route(
                CONNECTOR_ANDROID_READ_REQUEST_PATH,
                connector_android_read_request,
                methods=["POST"],
            ),
        ]
        # #4139 Oracle management-host return legs: owner intent, executor
        # poll, executor submit. Verified server-side and appended through
        # the existing history authority. Mounted solely when the deployment
        # composes the ownership map plus channel secret; the default app has
        # no such routes.
        if oracle_mesh_return_source is not None:
            from .oracle_mesh_read_return_routes import (
                ORACLE_MESH_READ_ORIGINAL_PATH,
                ORACLE_MESH_READ_POLL_PATH,
                ORACLE_MESH_READ_REQUEST_PATH,
                ORACLE_MESH_READ_RESULT_PATH,
                oracle_chat_engine_pc_drive_call,
                oracle_mesh_engine_chat_files_call,
                oracle_mesh_engine_claw_files_call,
                oracle_mesh_read_original,
                oracle_mesh_read_poll,
                oracle_mesh_read_request,
                oracle_mesh_engine_desktop_call,
                oracle_mesh_read_result,
            )
            routes[-1:-1] = [
                Route(ORACLE_MESH_READ_REQUEST_PATH, oracle_mesh_read_request, methods=["POST"]),
                Route("/internal/claw/engine-desktop", oracle_mesh_engine_desktop_call, methods=["POST"]),
                Route("/internal/claw/engine-pc-drive", oracle_mesh_engine_desktop_call, methods=["POST"]),
                Route("/internal/claw/engine-pc-files", oracle_mesh_engine_claw_files_call, methods=["POST"]),
                Route("/internal/chat/engine-pc-drive", oracle_chat_engine_pc_drive_call, methods=["POST"]),
                Route("/internal/chat/engine-pc-files", oracle_mesh_engine_chat_files_call, methods=["POST"]),
                Route(ORACLE_MESH_READ_POLL_PATH, oracle_mesh_read_poll, methods=["POST"]),
                Route(ORACLE_MESH_READ_RESULT_PATH, oracle_mesh_read_result, methods=["POST"]),
                Route(ORACLE_MESH_READ_ORIGINAL_PATH, oracle_mesh_read_original, methods=["GET"]),
            ]
    app = Starlette(routes=routes)
    # #5225: the canonical session guard resolves the Control Plane session
    # behind the session cookie once per request. It is added first so it stays
    # the innermost of the three layers: the same-origin guard refuses a
    # cross-origin mutation before any canonical authority read happens, and
    # the telemetry layer stays outermost so it still records guard rejections.
    app.add_middleware(SessionRevocationGuardMiddleware)
    # #3476: added before telemetry deliberately — Starlette prepends each
    # middleware, so the later-added telemetry layer stays outermost and keeps
    # recording guard rejections.
    app.add_middleware(SameOriginGuardMiddleware)
    # #1975: raw ASGI middleware, installed outermost so every route (including
    # the static Mount and the later-installed orchestration routes) is covered.
    app.add_middleware(
        RequestTelemetryMiddleware,
        emitter=telemetry_emitter,
        exporter=telemetry_exporter,
    )
    app.state.request_telemetry_enabled = True
    app.state.settings = resolved
    app.state.github_oauth_store = github_oauth_store
    app.state.github_oauth_provider = github_oauth_provider
    # #5121: owner-scoped customer-provider keys live in the canonical Chat D1,
    # sealed with a dedicated encryption secret that is separate from the
    # session-cookie secret. The session secret is consulted only to read
    # pre-separation v1 rows, which are then re-sealed under the dedicated key.
    # A missing or unusable dedicated secret leaves the feature unavailable
    # (fail closed) instead of silently deriving from the session secret.
    resolved_custom_store = custom_credential_store
    if (
        resolved_custom_store is None
        and d1_binding is not None
        and isinstance(resolved.custom_key_secret, str)
        and resolved.custom_key_secret
    ):
        try:
            resolved_custom_store = D1CustomProviderCredentialStore(
                d1_binding,
                key_secret=resolved.custom_key_secret,
                session_secret=resolved.session_secret,
                previous_key_secrets=resolved.custom_key_previous_secrets,
                legacy_session_secrets=resolved.custom_key_legacy_session_secrets,
            )
        except Exception:
            resolved_custom_store = None
    app.state.custom_credential_store = resolved_custom_store
    app.state.custom_provider_client = custom_provider_client or CustomProviderClient(
        timeout_seconds=min(600.0, resolved.completed_timeout_seconds)
    )
    app.state.history_store = history_store
    # Android 1.0.0 launches Google sign-in in the external browser, whose
    # cookies never reach the WebView. The one-time handoff store bridges that
    # gap inside the canonical Chat D1; it does not mint another identity or a
    # second session authority. Without D1/session material both flows fail
    # closed with 503 instead of issuing an unverifiable session.
    resolved_handoff_store = android_handoff_store
    if (
        resolved_handoff_store is None
        and d1_binding is not None
        and isinstance(resolved.session_secret, str)
        and resolved.session_secret
    ):
        resolved_handoff_store = D1AndroidAuthHandoffStore(d1_binding)
    app.state.android_handoff_store = resolved_handoff_store
    # #4657: the B66 customer dialogue surface reuses the canonical history
    # store behind the owner+PRODUCT_SCOPE_B66 adapter. It is the same D1/R2 the
    # Chat/Claw surfaces read — no second database, table or migration. Without
    # a real store the B66 dialogue routes fail closed instead of exposing any
    # conversation.
    app.state.b66_conversation_store = (
        B66ConversationStore(history_store) if history_store is not None else None
    )
    # #4672: one durable owner/product/token claim BEFORE any charged B66 turn.
    # If a bound production D1 lacks the migration, the route refuses before
    # provider dispatch. Test-only no-D1 fixtures preserve their existing seam.
    app.state.b66_turn_attempt_store = (
        D1B66TurnAttemptStore(d1_binding) if d1_binding is not None else None
    )
    # B66 admin authority shares signed user sessions and the existing D1.
    # Missing D1 or migrations fails closed rather than serving a demo roster.
    app.state.b66_member_admin_store = (b66_member_admin_store if b66_member_admin_store is not None
        else D1B66MemberAdminStore(d1_binding, admin_email=b66_admin_google_email) if d1_binding is not None else None)
    # #5222 the account-scoped last selected AI tier reuses the same D1. Without
    # the table the route fails closed with 503 and the browser keeps its
    # server-verified default; it never invents a stored preference.
    app.state.account_model_selection_store = (
        account_model_selection_store if account_model_selection_store is not None
        else D1AccountModelSelectionStore(d1_binding) if d1_binding is not None else None
    )
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
    # #5118 integrated administrator roles reuse the signed product session and
    # the existing users/D1 authority; the host supplies the D1-backed store.
    app.state.platform_admin_role_store = platform_admin_role_store
    # One composed authority feeds the existing central model guard. The B66
    # customer-data store is deliberately NOT replaced: an integrated ADMIN
    # manages B66 platform policy but never inherits the customer roster.
    app.state.platform_admin_authority = (
        PlatformAdminAuthority(
            role_store=platform_admin_role_store,
            legacy_model_admin=global_model_admin,
            legacy_b66_admin=app.state.b66_member_admin_store,
        )
        if platform_admin_role_store is not None else None
    )
    app.state.central_model_admin_authorizer = (
        app.state.platform_admin_authority
        if app.state.platform_admin_authority is not None else global_model_admin
    )
    # S2 read-only D1 policy inventory. The allow/block ledger remains
    # stored-only; only the #4428 per-grade routes below are read at dispatch.
    app.state.central_model_policy_store = (
        central_model_policy_store if central_model_policy_store is not None
        else D1CentralModelPolicyStore(d1_binding)
        if d1_binding is not None and callable(getattr(d1_binding, "batch", None))
        and callable(getattr(d1_binding, "prepare", None)) else None
    )
    # Migration 050 route ledger. Without it, runtime selection keeps the
    # historical static product contract (never a wider model set).
    app.state.central_model_route_store = (
        central_model_route_store if central_model_route_store is not None
        else D1CentralModelRouteStore(d1_binding)
        if d1_binding is not None and callable(getattr(d1_binding, "batch", None))
        and callable(getattr(d1_binding, "prepare", None)) else None
    )
    # Independent, server-only signer. Missing or malformed => all central writes OFF.
    # Dashboard copy/paste artifacts (surrounding whitespace, 0x prefix) are
    # stripped before validation; the bar stays exactly 64 hex chars (256-bit
    # key), so already-valid values and the fail-closed default are unchanged.
    import re as _model_re
    _signing_key_text = (
        central_model_policy_signing_key.strip().removeprefix("0x").removeprefix("0X")
        if isinstance(central_model_policy_signing_key, str)
        else ""
    )
    app.state.central_model_policy_write_key = (
        bytes.fromhex(_signing_key_text)
        if _model_re.fullmatch(r"[a-fA-F0-9]{64}", _signing_key_text)
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
    app.state.control_plane_identity_authority = (
        connector_owner_enrollment.identity if connector_owner_enrollment is not None
        else control_plane_identity_authority
    )
    # B54 signed-session + exact-origin browser handlers use the SAME injected
    # canonical Identity and Broker issue host; device credential redemption
    # is absent from the HTTP route table (WSS owns that).
    app.state.connector_enrollment_async_host = (
        connector_owner_enrollment.host if connector_owner_enrollment is not None else None
    )
    app.state.connector_enrollment_browser_csrf = (
        connector_owner_enrollment.csrf if connector_owner_enrollment is not None else None
    )
    # Only a server-owned B54 acceptance composition can supply this per-
    # verified-owner factory. Unconfigured product app has no approval route.
    app.state.connector_one_click_approval_factory = (
        getattr(connector_owner_enrollment, "one_click_factory", None)
        if connector_owner_enrollment is not None else None
    )
    app.state.connector_owner_native_pc_completion = (
        getattr(connector_owner_enrollment, "native_pc_completion", None)
        if connector_owner_enrollment is not None else None
    )
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

    # #5441 lost-password reset. The store holds the one-time token digests
    # and the reset audit ledger; the delivery transport sends the one-time
    # link to the account's own address. Both are optional: without them the
    # reset routes fail closed with a retryable error instead of pretending a
    # mail was sent.
    _password_reset_store = password_reset_store
    if _password_reset_store is None and d1_binding is not None:
        try:
            _password_reset_store = D1PasswordResetStore(d1_binding)
        except Exception:
            _password_reset_store = None
    app.state.password_reset_store = _password_reset_store
    app.state.password_reset_delivery = password_reset_delivery
    app.state.password_reset_service = (
        PasswordResetService(
            _password_reset_store,
            pepper=resolved.session_secret or "",
            public_base_url=resolved.public_base_url or "",
        )
        if _password_reset_store is not None
        and resolved.session_secret
        and resolved.public_base_url
        else None
    )

    # AI usage quotas are disabled by default during development.
    # Explicitly injected quota stores retain opt-in policy coverage.
    # Development-stage AI usage is provider-governed, not locally quota-gated.
    # Explicitly injected quota stores keep the opt-in policy/test seam available.
    app.state.usage_gate_enforced = usage_store is not None
    # Fail closed until CP supplies verified user Drive WRITE grant and owner-scoped upload session.
    app.state.meeting_drive_upload_session_port = meeting_drive_upload_session_port
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = PadiemTierB14Client(resolved, transport=transport)
    # B14 catalog source for the final dispatch guard (#4483).  Built from the
    # same base URL as the B14 client; absent when no B14 base URL is configured
    # (guard then degrades to unguarded dispatch).
    if resolved.b14_base_url:
        _catalog_client = httpx.AsyncClient()

        async def _catalog_get_json(path: str):
            resp = await _catalog_client.get(resolved.b14_base_url + path)
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            return resp.status_code, body

        app.state.b14_catalog_source = SimpleB14CatalogSource(_catalog_get_json)
    else:
        app.state.b14_catalog_source = None
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
    # #4647: the meeting ledger reuses this same PADIEM_CHAT_DB D1 binding and the
    # existing signed owner + resolved workspace authority. Migrations 055-057 own
    # the schema; no second database, no media bytes and no Drive capability here.
    app.state.claw_meeting_store = (
        D1ClawMeetingStore(d1_binding) if d1_binding is not None else None
    )
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
    # #3330: host junction — verified Work Ticket → existing Drive output pipeline.
    # Active only when the trusted production Worker injects both pipeline and
    # history; no browser/model activation authority. The host exposes
    # complete_ticketed_output() which forwards to the existing verified
    # ticket composition and existing uploader/D1 pipeline.
    app.state.claw_ticket_drive_output_host = (
        ClawTicketDriveOutputHost(
            pipeline=app.state.claw_durable_drive_output_pipeline,
            history=history_store,
            drive_reader=claw_drive_artifact_reader,
        )
        if app.state.claw_durable_drive_output_pipeline is not None
        and history_store is not None
        else None
    )
    # READ is a separate current-grant host capability. WRITE approval never
    # authorizes browser download; no implicit Worker transport is installed.
    app.state.claw_drive_artifact_reader = claw_drive_artifact_reader
    # Explicit trusted server opt-in; no browser-provided activation authority.
    app.state.claw_live_sse_enabled = False
    # #4469: no implicit activation from an AI decision, browser or adapter;
    # the trusted production Worker composes the member/quota-bound flag.
    app.state.claw_web_search_enabled = False
    # #3933 S1: first-turn trusted coding-context gate. Fail-closed default:
    # the route helper is a no-op and no grant store is composed here, so
    # production keeps the exact historical first-turn path until CENTRAL
    # composes a store and enables the flag in a reviewed change.
    app.state.claw_first_turn_grant_enabled = False
    app.state.claw_first_turn_grant_store = None
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
    app.state.claw_pc_device_selection_store = claw_pc_device_selection_store
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
    # #4139 TXT read request leg: owner-confirmed read intake that mints real
    # approval material and enqueues through the same trusted broker binding.
    # None keeps the route fail-closed until the Worker root composes it.
    from .connector_txt_read_routes import UnconfiguredTxtReadSource
    app.state.connector_txt_read_source = (
        connector_txt_read_source
        if connector_txt_read_source is not None
        else UnconfiguredTxtReadSource()
    )
    # #4139 Oracle return leg: the deployment-owned (account, device, Mesh
    # node) map behind the management-host return route. None keeps the route
    # unmounted and every return fail-closed until the Worker root composes it.
    from .oracle_mesh_read_return_routes import UnconfiguredOracleMeshReturnSource
    app.state.claw_engine_desktop_secret = claw_engine_desktop_secret
    app.state.oracle_mesh_return_source = (
        oracle_mesh_return_source
        if oracle_mesh_return_source is not None
        else UnconfiguredOracleMeshReturnSource()
    )
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
    # #3186 STEP 3-B: staff status alone never issues review permission.
    # Both inputs are separate server-injected authorities. Without either,
    # the existing operator decision endpoint remains fail-closed (503).
    # #5094: compose B66-only defaults from authorities that already exist —
    # the verified Google admin store, the candidate's server-recorded owner
    # scope and the shared Control Plane canonical session. An explicitly
    # injected resolver still wins. No request value can mint a grant or a
    # target, and missing bindings leave the route at 503.
    _review_grant_issuer = b66_review_grant_issuer
    _review_target_resolver = b66_canonical_candidate_target_resolver
    if (isinstance(app.state.b66_member_admin_store, D1B66MemberAdminStore)
            and _b66_saved_skill_candidate_store is not None):
        from .b66_candidate_review_host_composition import (
            build_b66_candidate_review_host,
        )
        _composed = build_b66_candidate_review_host(
            member_admin_store=app.state.b66_member_admin_store,
            candidate_store=_b66_saved_skill_candidate_store,
        )
        if _composed is not None:
            if _review_grant_issuer is None:
                _review_grant_issuer = _composed[0]
            if _review_target_resolver is None:
                _review_target_resolver = _composed[1]

    _candidate_review_authority = None
    if (isinstance(app.state.b66_member_admin_store, D1B66MemberAdminStore)
            and _b66_saved_skill_candidate_store is not None
            and callable(_review_grant_issuer)
            and callable(_review_target_resolver)):
        from .b66_saved_skill_candidate_authority import (
            D1B66SavedQuoteSkillCandidateOperatorAuthority,
        )
        _candidate_review_authority = D1B66SavedQuoteSkillCandidateOperatorAuthority(
            member_admin_store=app.state.b66_member_admin_store,
            candidate_store=_b66_saved_skill_candidate_store,
            trusted_review_grant_issuer=_review_grant_issuer,
            canonical_target_resolver=_review_target_resolver,
        )
    app.state.b66_saved_skill_candidate_operator_authority = _candidate_review_authority
    app.state.b66_operator_grant_resolver = (
        _candidate_review_authority.issue_operator_grant
        if _candidate_review_authority is not None else None
    )
    app.state.b66_operator_target_resolver = (
        _candidate_review_authority.resolve_operator_target
        if _candidate_review_authority is not None else None
    )

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
    _b66_ai_conversation_store = b66_ai_conversation_store
    if _b66_ai_conversation_store is None and d1_binding is not None:
        _b66_ai_conversation_store = D1ConversationStore(d1_binding)
    app.state.b66_ai_conversation_store = _b66_ai_conversation_store

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

    # B66 #3884 Slice 1: private customer template source custody reuses the same
    # private R2 binding for immutable original bytes and D1 for owner-scoped
    # metadata. Upload alone stores status='uploaded' and never certifies; no
    # approve/compile route is composed here.
    _b66_template_source_store = b66_template_source_store
    if _b66_template_source_store is None and d1_binding is not None and r2_binding is not None:
        try:
            _b66_template_source_metadata = D1B66TemplateSourceMetadataStore(d1_binding)
            _b66_template_source_store = B66TemplateSourceStore(
                _b66_template_source_metadata, r2_binding
            )
        except Exception:
            _b66_template_source_store = None
    app.state.b66_template_source_store = _b66_template_source_store

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

    # #5034 Web Push subscriptions: the same PADIEM_CHAT_DB binding, a device
    # endpoint registry only. No notification record is stored here.
    _push_subscription_store = claw_push_subscription_store
    if _push_subscription_store is None and d1_binding is not None:
        try:
            _push_subscription_store = D1ClawPushSubscriptionStore(d1_binding)
        except Exception:
            _push_subscription_store = None
    app.state.claw_push_subscription_store = _push_subscription_store

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