from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .b66_ai_chat_routes import b66_ai_chat

from .b66_ai_conversation_routes import conversation_state, conversation_turn

from .b66_dialogue_routes import b66_dialogue_detail, b66_dialogue_list

from .b66_company_profile_routes import b66_company_profile_get, b66_company_profile_put

from .b66_quote_asset_routes import b66_quote_asset_detail

from .b66_member_inquiries import (
    D1B66InquiryStore, b66_inquiries, b66_admin_inquiries,
    b66_admin_inquiry_status, b66_admin_inquiry_dispatch,
)

from .b66_admin_routes import b66_admin_me, b66_admin_members, b66_admin_member_access, b66_admin_member_detail, b66_admin_model_policy, b66_admin_dispatch_alerts

from .b66_quote_history_routes import (
    b66_quote_history_delete,
    b66_quote_history_detail,
    b66_quote_history_list,
    b66_quote_history_save,
)

from .b66_guided_draft import D1GuidedDraftStore, guided_draft_route, guided_transcript_route

from .b66_template_source_routes import (
    b66_template_source_detail,
    b66_template_source_list,
    b66_template_source_upload,
)

from .b66_certified_pdf_routes import b66_certified_pdf, b66_certified_preview_base

from .b66_native_sol_routes import b66_native_sol_pdf, b66_native_sol_scope

from .b66_pc_template_routes import PC_QUOTE_FILL_PATH, pc_quote_fill, pc_quote_pdf

from .b66_pc_form_routes import PC_QUOTE_FORMS_PATH, pc_quote_form_register

from .b66_pc_directory_routes import B66_PC_DIRECTORY_PATH, b66_pc_directory

from .b66_pc_txt_read_routes import (
    B66_PC_RESULT_PATH,
    B66_PC_TXT_READ_PATH,
    b66_pc_run_result,
    b66_pc_txt_read_request,
)

from .b66_quote_routes import (
    b66_quote_interpret,
    b66_quote_models,
    b66_runtime_config,
    b66_saved_skill_detail,
    b66_saved_skills,
)

from .b66_saved_skill_candidate_routes import (
    b66_saved_skill_candidate_detail,
    b66_saved_skill_candidate_list,
    b66_saved_skill_candidate_operator_decision,
    b66_saved_skill_candidate_operator_detail,
    b66_saved_skill_candidate_operator_list,
    b66_saved_skill_candidate_submit,
)

def register_b66_routes(routes: list) -> None:
    routes.extend([
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
        # #5895: the quote screen's "my PC Excel form" lane. Chat exchanges ids and the
        # model's cell mapping only; reading and filling the workbook happen in COM2.
        Route(PC_QUOTE_FILL_PATH, pc_quote_fill, methods=["POST"]),
        Route("/api/b66/pc-quote/pdf", pc_quote_pdf, methods=["GET"]),
        # #3180 ③: register the owner's own PC form into the same saved-quote asset
        # table the skill list already reads; the workbook itself stays on the PC.
        Route(PC_QUOTE_FORMS_PATH, pc_quote_form_register, methods=["POST"]),
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
    ])
