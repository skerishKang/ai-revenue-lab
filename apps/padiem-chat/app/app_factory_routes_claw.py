from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .claw_general_routes import claw_general_execute, claw_general_capabilities

from .chat_pc_session import API_PATH as PC_SESSION_PATH, session_card_request

from .claw_office_preview_routes import (
    OFFICE_PDF_PREVIEW_PATH, claw_office_pdf_preview,
    OFFICE_XLSX_DOWNLOAD_PATH, claw_office_xlsx_download,
    OFFICE_OUTPUTS_QUERY_PATH, claw_office_outputs_query,
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

from .claw_durable_drive_artifact_routes import (
    claw_drive_artifact_download, claw_drive_artifact_preview,
)

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

from .claw_memory_routes import (
    claw_memory_approve,
    claw_memory_detail,
    claw_memory_list,
    claw_memory_reject,
)

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

from .claw_automation_rules_routes import claw_automation_rules

from .claw_automation_rule_create_routes import claw_automation_rule_create

from .claw_automation_rule_edit_routes import claw_automation_rule_edit

from .claw_automation_rule_enabled_routes import claw_automation_rule_set_enabled

from .util_quote_routes import UTIL_QUOTE_PREVIEW_PATH, util_quote_preview

from .util_excel_routes import UTIL_EXCEL_REVIEW_PATH, util_excel_review

def register_claw_routes(routes: list) -> None:
    routes.extend([
        Route("/api/claw/manual-intake/preview", claw_manual_intake_preview, methods=["POST"]),
        Route(UTIL_QUOTE_PREVIEW_PATH, util_quote_preview, methods=["POST"]),
        Route(UTIL_EXCEL_REVIEW_PATH, util_excel_review, methods=["POST"]),
        Route("/api/claw/manual-intake/execute", claw_manual_intake_execute, methods=["POST"]),
        # #3539: the generic Claw composer runs through the canonical #3382 P01
        # Engine lane. It is a distinct B54 product boundary from manual-intake
        # and has no direct-B14 (/api/chat/stream) fallback.
        Route("/api/claw/general/capabilities", claw_general_capabilities, methods=["GET"]),
        Route("/api/claw/general", claw_general_execute, methods=["POST"]),
        Route(PC_SESSION_PATH, session_card_request, methods=["POST"]),
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
        Route(OFFICE_XLSX_DOWNLOAD_PATH, claw_office_xlsx_download, methods=["GET"]),
        Route(OFFICE_OUTPUTS_QUERY_PATH, claw_office_outputs_query, methods=["GET"]),
        Route("/api/claw/runs/{run_id}/local-result", local_runner_result, methods=["POST"]),
        # #5034 Web Push opt-in for automation notifications. This adds a
        # device subscription, never a second notification authority.
        Route("/api/claw/inbox/push/capability", claw_push_capability, methods=["GET"]),
        Route("/api/claw/inbox/push/subscription", claw_push_subscription_register, methods=["POST"]),
        Route("/api/claw/inbox/push/subscription", claw_push_subscription_unregister, methods=["DELETE"]),
    ])
