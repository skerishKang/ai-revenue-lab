# Chat CPython route inventory — 2026-10-29

상태: 검토 중. 로컬 CPython 앱 구성에서 추출한 라우트이며 Worker 전용 진입점은 포함하지 않는다. GET 쓰기 여부가 미검토인 행은 REVIEW로 표시한다. 이 목록 자체는 동결 완료의 증거가 아니다.

| 경로 | 메서드 | 핸들러 | GET 쓰기 판정 |
|---|---|---|---|
| `/health` | GET, HEAD | `health` | REVIEW |
| `/api/admin/models/me` | GET, HEAD | `central_model_admin_me` | REVIEW |
| `/api/admin/models/snapshot` | GET, HEAD | `central_model_admin_snapshot` | REVIEW |
| `/api/admin/models/preview` | POST | `central_model_admin_preview` | — |
| `/api/admin/models/change-preview` | POST | `central_model_change_preview` | — |
| `/api/admin/models/change-apply` | POST | `central_model_change_apply` | — |
| `/api/admin/models/rollback-preview` | POST | `central_model_rollback_preview` | — |
| `/api/admin/models/audit` | GET, HEAD | `central_model_change_audit` | REVIEW |
| `/api/admin/models/routes` | GET, HEAD | `central_model_routes_get` | REVIEW |
| `/api/admin/models/route-preview` | POST | `central_model_route_preview` | — |
| `/api/admin/models/route-apply` | POST | `central_model_route_apply` | — |
| `/api/admin/models/route-rollback-preview` | POST | `central_model_route_rollback_preview` | — |
| `/api/admin/session` | GET, HEAD | `platform_admin_session` | REVIEW |
| `/api/admin/roles` | POST | `platform_admin_role_assign` | — |
| `/api/admin/roles/{user_id}` | DELETE | `platform_admin_role_revoke` | — |
| `/api/models/owner-name-preview` | GET, HEAD | `owner_model_name_preview` | REVIEW |
| `/api/claw/verified-model-choices` | GET, HEAD | `claw_verified_model_choices` | REVIEW |
| `/api/auth/status` | GET, HEAD | `auth_status` | REVIEW |
| `/api/voice/identity` | GET, HEAD | `voice_identity` | REVIEW |
| `/api/voice/transcribe` | POST | `voice_transcribe` | — |
| `/api/voice/live-token` | POST | `voice_live_token` | — |
| `/api/claw/voice/identity` | GET, HEAD | `voice_identity` | REVIEW |
| `/api/claw/voice/transcribe` | POST | `voice_transcribe` | — |
| `/api/claw/voice/live-token` | POST | `voice_live_token` | — |
| `/api/home/product-access` | GET, HEAD | `home_product_access` | REVIEW |
| `/auth/google/start` | GET, HEAD | `google_start` | REVIEW |
| `/auth/google/callback` | GET, HEAD | `google_callback` | WRITE |
| `/auth/android/handoff` | POST | `android_handoff_create` | — |
| `/auth/android/handoff/{handoff_id}` | GET, HEAD | `android_handoff_status` | REVIEW |
| `/auth/android/handoff/{handoff_id}/claim` | POST | `android_handoff_claim` | — |
| `/auth/android/confirm` | POST | `android_handoff_confirm` | — |
| `/auth/lovetree/start` | GET, HEAD | `lovetree_handoff_start` | WRITE |
| `/api/auth/password/register` | POST | `password_register` | — |
| `/api/auth/password/login` | POST | `password_login` | — |
| `/api/auth/password/change` | POST | `password_change` | — |
| `/api/auth/password/reset/request` | POST | `password_reset_request` | — |
| `/api/auth/password/reset/confirm` | POST | `password_reset_confirm` | — |
| `/api/auth/logout` | POST | `logout` | — |
| `/api/connectors/google/ticket` | POST | `google_connector_ticket` | — |
| `/api/claw/meeting/drive-upload-session` | POST | `meeting_drive_upload_session` | — |
| `/api/claw/meetings` | GET, HEAD, POST | `claw_meetings` | REVIEW |
| `/api/claw/meetings/{meeting_ref}` | DELETE, GET, HEAD, PATCH | `claw_meeting_detail` | REVIEW |
| `/api/claw/meetings/{meeting_ref}/end` | POST | `claw_meeting_end` | — |
| `/api/claw/meetings/{meeting_ref}/artifacts` | POST | `claw_meeting_artifact` | — |
| `/api/claw/meetings/{meeting_ref}/actions` | POST | `claw_meeting_action_create` | — |
| `/api/claw/meeting-actions/{action_ref}` | DELETE, PATCH | `claw_meeting_action` | — |
| `/api/connectors/google/calendar/activate-read` | POST | `activate_google_calendar_read` | — |
| `/api/connectors/status` | GET, HEAD | `connectors_status` | REVIEW |
| `/api/connectors/google/drive/disconnect` | POST | `disconnect_google_drive` | — |
| `/api/b66/drive/status` | GET, HEAD | `b66_drive_status` | REVIEW |
| `/api/b66/drive/connect` | POST | `b66_drive_connect` | — |
| `/api/b66/drive/connect/callback` | GET, HEAD | `b66_drive_connect_callback_return` | REVIEW |
| `/api/b66/drive/disconnect` | POST | `b66_drive_disconnect` | — |
| `/api/connectors/github/start` | GET, HEAD | `github_start` | WRITE |
| `/api/connectors/github/callback` | GET, HEAD | `github_callback` | WRITE |
| `/api/connectors/github/status` | GET, HEAD | `github_status` | REVIEW |
| `/api/connectors/github/installations` | GET, HEAD | `github_installation_settings` | REVIEW |
| `/api/connectors/github/repositories` | GET, HEAD | `github_repositories` | REVIEW |
| `/api/connectors/github/disconnect` | POST | `github_disconnect` | — |
| `/api/connectors/github/pause` | POST | `github_pause` | — |
| `/api/connectors/github/resume` | POST | `github_resume` | — |
| `/api/projects` | GET, HEAD, POST | `projects_collection` | REVIEW |
| `/api/project-files` | GET, HEAD | `owner_files_collection` | REVIEW |
| `/api/projects/{project_id}` | DELETE, GET, HEAD, PATCH | `project_detail` | REVIEW |
| `/api/projects/{project_id}/files` | GET, HEAD, POST | `project_files_collection` | REVIEW |
| `/api/projects/{project_id}/files/{file_id}/original` | GET, HEAD | `project_file_original` | REVIEW |
| `/api/projects/{project_id}/files/{file_id}` | DELETE, GET, HEAD, PUT | `project_file_detail` | REVIEW |
| `/api/document-conversions` | GET, HEAD, POST | `convert_jobs_collection` | REVIEW |
| `/api/document-conversions/{job_id}` | GET, HEAD | `convert_job_detail` | REVIEW |
| `/api/document-conversions/{job_id}/files` | POST | `convert_job_files` | — |
| `/api/document-conversions/{job_id}/archive` | GET, HEAD | `convert_job_archive` | REVIEW |
| `/api/document-conversions/items/{item_id}` | GET, HEAD | `convert_item_detail` | REVIEW |
| `/api/document-conversions/items/{item_id}` | DELETE | `convert_item_delete` | — |
| `/api/document-conversions/items/{item_id}/run` | POST | `convert_item_run` | — |
| `/api/document-conversions/items/{item_id}/review` | POST | `convert_item_review` | — |
| `/api/document-conversions/items/{item_id}/markdown` | GET, HEAD | `convert_item_markdown` | REVIEW |
| `/api/document-conversions/items/{item_id}/original` | GET, HEAD | `convert_item_original` | REVIEW |
| `/api/projects/{project_id}/drive-case-folder` | GET, HEAD | `drive_case_folder_status` | REVIEW |
| `/api/projects/{project_id}/drive-case-folder` | PUT | `drive_case_folder_put` | — |
| `/api/projects/{project_id}/drive-case-folder` | DELETE | `drive_case_folder_delete` | — |
| `/api/projects/{project_id}/drive-folders` | GET, HEAD | `drive_folders_collection` | REVIEW |
| `/api/projects/{project_id}/drive-case-pdfs` | GET, HEAD | `drive_case_pdfs_collection` | REVIEW |
| `/api/projects/{project_id}/drive-case-pdfs/{file_id}` | GET, HEAD | `drive_case_pdf_detail` | REVIEW |
| `/api/projects/{project_id}/drive-case-pdfs/{file_id}/browser-extraction` | POST | `drive_case_pdf_extraction_review` | — |
| `/api/outputs` | GET, HEAD, POST | `outputs_collection` | REVIEW |
| `/api/outputs/{output_id}` | DELETE, GET, HEAD, PATCH | `output_detail` | REVIEW |
| `/api/conversations` | GET, HEAD | `api_conversations` | REVIEW |
| `/api/conversations/search` | GET, HEAD | `api_conversation_search` | REVIEW |
| `/api/conversations/{conversation_id}` | DELETE, GET, HEAD | `api_conversation_detail` | REVIEW |
| `/api/desktop/conversations` | GET, HEAD | `desktop_conversations` | REVIEW |
| `/api/desktop/conversations/{conversation_id}` | GET, HEAD | `desktop_conversation_detail` | REVIEW |
| `/api/chat/stream` | POST | `api_chat_stream` | — |
| `/api/chat` | POST | `api_chat` | — |
| `/api/byok/detect` | POST | `byok_detect` | — |
| `/api/byok/register` | POST | `byok_register` | — |
| `/api/files/ticket` | POST | `file_upload_ticket` | — |
| `/api/files/capabilities` | GET, HEAD | `file_capabilities` | REVIEW |
| `/api/chat/custom/credential` | GET, HEAD | `custom_credential_status` | REVIEW |
| `/api/chat/custom/credential` | PUT | `custom_credential_save` | — |
| `/api/chat/custom/credential` | DELETE | `custom_credential_delete` | — |
| `/api/chat/custom/credential/test` | GET, HEAD | `custom_credential_test` | REVIEW |
| `/api/chat/custom/models` | GET, HEAD | `custom_provider_models` | REVIEW |
| `/api/account/model-selection` | GET, HEAD | `account_model_selection_get` | REVIEW |
| `/api/account/model-selection` | PUT | `account_model_selection_put` | — |
| `/api/b66/runtime-config` | GET, HEAD | `b66_runtime_config` | REVIEW |
| `/api/b66/connect/devices` | GET, HEAD | `b66_pc_directory` | REVIEW |
| `/api/b66/connect/txt-reads/request` | POST | `b66_pc_txt_read_request` | — |
| `/api/b66/runs/{run_id}/pc-result` | POST | `b66_pc_run_result` | — |
| `/api/b66/company-profile` | GET, HEAD | `b66_company_profile_get` | REVIEW |
| `/api/b66/company-profile` | PUT | `b66_company_profile_put` | — |
| `/api/b66/saved-skills` | GET, HEAD | `b66_saved_skills` | REVIEW |
| `/api/b66/saved-skills/{saved_skill_id}` | GET, HEAD | `b66_saved_skill_detail` | REVIEW |
| `/api/b66/saved-skill-candidates` | POST | `b66_saved_skill_candidate_submit` | — |
| `/api/b66/saved-skill-candidates` | GET, HEAD | `b66_saved_skill_candidate_list` | REVIEW |
| `/api/b66/saved-skill-candidates/{candidate_id}` | GET, HEAD | `b66_saved_skill_candidate_detail` | REVIEW |
| `/api/b66/admin/saved-skill-candidates` | GET, HEAD | `b66_saved_skill_candidate_operator_list` | REVIEW |
| `/api/b66/admin/saved-skill-candidates/{candidate_id}` | GET, HEAD | `b66_saved_skill_candidate_operator_detail` | REVIEW |
| `/api/b66/admin/saved-skill-candidates/{candidate_id}/decision` | POST | `b66_saved_skill_candidate_operator_decision` | — |
| `/api/b66/assets/{asset_id}` | GET, HEAD | `b66_quote_asset_detail` | REVIEW |
| `/api/b66/template-sources` | POST | `b66_template_source_upload` | — |
| `/api/b66/template-sources` | GET, HEAD | `b66_template_source_list` | REVIEW |
| `/api/b66/template-sources/{template_source_id}` | GET, HEAD | `b66_template_source_detail` | REVIEW |
| `/api/b66/quote/interpret` | POST | `b66_quote_interpret` | — |
| `/api/b66/pc-quote/fill` | POST | `pc_quote_fill` | — |
| `/api/b66/ai/chat` | POST | `b66_ai_chat` | — |
| `/api/b66/ai/conversation` | POST | `conversation_turn` | — |
| `/api/b66/ai/conversation` | GET, HEAD | `conversation_state` | REVIEW |
| `/api/b66/ai/dialogues` | GET, HEAD | `b66_dialogue_list` | REVIEW |
| `/api/b66/ai/dialogues/{conversation_id}` | DELETE, GET, HEAD | `b66_dialogue_detail` | REVIEW |
| `/api/b66/quote/models` | GET, HEAD | `b66_quote_models` | REVIEW |
| `/api/b66/inquiries` | GET, HEAD, POST | `b66_inquiries` | REVIEW |
| `/api/b66/admin/inquiries` | GET, HEAD | `b66_admin_inquiries` | REVIEW |
| `/api/b66/admin/inquiries/dispatch` | POST | `b66_admin_inquiry_dispatch` | — |
| `/api/b66/admin/inquiries/{inquiry_id}` | PATCH | `b66_admin_inquiry_status` | — |
| `/api/b66/admin/me` | GET, HEAD | `b66_admin_me` | REVIEW |
| `/api/b66/admin/members` | GET, HEAD | `b66_admin_members` | REVIEW |
| `/api/b66/admin/model-policy` | GET, HEAD, PUT | `b66_admin_model_policy` | REVIEW |
| `/api/b66/admin/alerts/dispatch` | POST | `b66_admin_dispatch_alerts` | — |
| `/api/b66/admin/members/{user_id}` | PATCH | `b66_admin_member_access` | — |
| `/api/b66/admin/members/{user_id}/detail` | GET, HEAD | `b66_admin_member_detail` | REVIEW |
| `/api/b66/quote/preview-base` | GET, HEAD | `b66_certified_preview_base` | REVIEW |
| `/api/b66/quote/pdf` | POST | `b66_certified_pdf` | — |
| `/api/b66/quote/native-sol-pdf` | POST | `b66_native_sol_pdf` | — |
| `/api/b66/quote/native-sol-scope` | GET, HEAD | `b66_native_sol_scope` | REVIEW |
| `/api/b66/quotes` | GET, HEAD | `b66_quote_history_list` | REVIEW |
| `/api/b66/quotes` | POST | `b66_quote_history_save` | — |
| `/api/b66/guided-draft` | DELETE, GET, HEAD, PUT | `guided_draft_route` | REVIEW |
| `/api/b66/guided-conversations` | GET, HEAD | `guided_transcript_route` | REVIEW |
| `/api/b66/guided-conversations/{conversation_id}` | DELETE, GET, HEAD | `guided_transcript_route` | REVIEW |
| `/api/b66/quotes/{quote_history_id}` | GET, HEAD | `b66_quote_history_detail` | REVIEW |
| `/api/b66/quotes/{quote_history_id}` | DELETE | `b66_quote_history_delete` | — |
| `/api/claw/office/web-sources` | GET, HEAD, POST | `web_xlsx_sources` | REVIEW |
| `/api/claw/office/web-sources/{document_id}/download` | GET, HEAD | `web_xlsx_download` | REVIEW |
| `/api/claw/office/web-selections` | GET, HEAD, POST | `web_xlsx_selections` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}` | GET, HEAD | `web_xlsx_selection_detail` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/request-p01` | POST | `web_xlsx_request_p01` | — |
| `/api/claw/office/web-selections/{selection_ref}/start-p01` | POST | `web_xlsx_start_p01` | — |
| `/api/claw/office/web-selections/{selection_ref}/p01-decision` | POST | `web_xlsx_p01_owner_decision` | — |
| `/api/claw/office/web-selections/{selection_ref}/p01-status` | GET, HEAD | `web_xlsx_p01_owner_status` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/workcopy/download` | GET, HEAD | `web_xlsx_p01_workcopy_download` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/preview` | POST | `web_xlsx_quote_edit_preview` | — |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/commit` | POST | `web_xlsx_quote_edit_commit` | — |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/request` | POST | `request_quote_write` | — |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/decision` | POST | `decide_quote_write` | — |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/approval-status` | GET, HEAD | `quote_write_approval_status` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/status` | GET, HEAD | `web_xlsx_quote_edit_status` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/download` | GET, HEAD | `web_xlsx_quote_edit_download` | REVIEW |
| `/api/claw/office/web-selections/{selection_ref}/quote-edit/pdf` | GET, HEAD | `web_xlsx_quote_pdf_download` | REVIEW |
| `/api/claw/manual-intake/preview` | POST | `claw_manual_intake_preview` | — |
| `/api/claw/manual-intake/execute` | POST | `claw_manual_intake_execute` | — |
| `/api/claw/general/capabilities` | GET, HEAD | `claw_general_capabilities` | REVIEW |
| `/api/claw/general` | POST | `claw_general_execute` | — |
| `/api/claw/manual-intake/quote-compare` | POST | `claw_manual_intake_quote_compare` | — |
| `/api/claw/manual-intake/artifact/{document_id}` | GET, HEAD | `claw_manual_intake_artifact` | REVIEW |
| `/api/claw/manual-intake/artifact/{document_id}/preview` | GET, HEAD | `claw_artifact_inline_preview` | REVIEW |
| `/api/claw/telegram/ingest/{binding_ref}` | POST | `claw_telegram_ingest` | — |
| `/api/claw/conversations/{conversation_id}/artifact-followup` | GET, HEAD | `claw_conversation_artifact_followup` | REVIEW |
| `/api/claw/conversations/{conversation_id}/artifact-followup/adopt` | POST | `claw_conversation_artifact_adopt` | — |
| `/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/download` | GET, HEAD | `claw_drive_artifact_download` | REVIEW |
| `/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/preview` | GET, HEAD | `claw_drive_artifact_preview` | REVIEW |
| `/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/telegram` | POST | `claw_telegram_artifact_delivery` | — |
| `/api/claw/runs` | GET, HEAD | `claw_runs_history` | REVIEW |
| `/api/claw/runs/{run_id}/pending-result` | GET, HEAD | `claw_pending_result` | REVIEW |
| `/api/claw/approvals/decision` | POST | `claw_approval_decision` | — |
| `/api/claw/memory/approve` | POST | `claw_memory_approve` | — |
| `/api/claw/memory/reject` | POST | `claw_memory_reject` | — |
| `/api/claw/memory` | GET, HEAD | `claw_memory_list` | REVIEW |
| `/api/claw/memory/{memory_id}` | GET, HEAD | `claw_memory_detail` | REVIEW |
| `/api/claw/automation/rules` | GET, HEAD | `claw_automation_rules` | REVIEW |
| `/api/claw/automation/rules` | POST | `claw_automation_rule_create` | — |
| `/api/claw/automation/rules/{rule_id}/enabled` | PATCH | `claw_automation_rule_set_enabled` | — |
| `/api/claw/automation/rules/{rule_id}` | PATCH | `claw_automation_rule_edit` | — |
| `/api/claw/local-access` | GET, HEAD | `claw_local_access` | REVIEW |
| `/api/claw/local-access/devices` | GET, HEAD | `claw_device_directory` | REVIEW |
| `/api/claw/local-access/devices/pause` | POST | `claw_pc_pause` | — |
| `/api/claw/local-access/devices/resume` | POST | `claw_pc_resume` | — |
| `/api/claw/local-access/devices/select` | POST | `claw_pc_select` | — |
| `/api/claw/local-access/connect` | POST | `claw_local_connect` | — |
| `/api/claw/local-access/connect` | GET, HEAD | `claw_local_connect_status` | REVIEW |
| `/api/claw/office/candidates` | GET, HEAD | `candidates` | REVIEW |
| `/api/claw/office/candidates/select` | POST | `select_candidate` | — |
| `/api/claw/office/runs/{run_id}/pdf` | GET, HEAD | `claw_office_pdf_preview` | REVIEW |
| `/api/claw/office/runs/{run_id}/xlsx` | GET, HEAD | `claw_office_xlsx_download` | REVIEW |
| `/api/claw/office/runs/{run_id}/outputs` | GET, HEAD | `claw_office_outputs_query` | REVIEW |
| `/api/claw/runs/{run_id}/local-result` | POST | `local_runner_result` | — |
| `/api/claw/inbox/{kind}` | GET, HEAD | `claw_inbox_list` | REVIEW |
| `/api/claw/inbox/{kind}/{item_id}` | PATCH | `claw_inbox_status` | — |
| `/api/claw/inbox/push/capability` | GET, HEAD | `claw_push_capability` | REVIEW |
| `/api/claw/inbox/push/subscription` | POST | `claw_push_subscription_register` | — |
| `/api/claw/inbox/push/subscription` | DELETE | `claw_push_subscription_unregister` | — |
| `/api/calendar/today` | GET, HEAD | `calendar_today` | REVIEW |
| `/api/calendar/upcoming` | GET, HEAD | `calendar_upcoming` | REVIEW |
| `/api/calendar/items` | GET, HEAD | `calendar_items` | REVIEW |
| `/api/calendar/items/{calendar_item_id}` | GET, HEAD | `calendar_item_detail` | REVIEW |
| `/api/calendar/work-logs` | GET, HEAD | `calendar_work_logs_list` | REVIEW |
| `/api/calendar/work-logs` | POST | `calendar_work_logs_create` | — |
| `/api/calendar/appointments` | GET, HEAD | `calendar_appointments_list` | REVIEW |
| `/api/calendar/appointments` | POST | `calendar_appointments_create` | — |
| `/api/calendar/appointments/{appointment_id}` | DELETE, PUT | `calendar_appointment_manage` | — |
| `/api/calendar/work-logs/{log_id}` | DELETE, PUT | `calendar_work_log_manage` | — |
| `/api/pc/pairings` | POST | `pc_pairing_issue` | — |
| `/api/pc/pairings` | GET, HEAD | `pc_pairing_list` | REVIEW |
| `/api/pc/pairings/claim` | POST | `pc_pairing_claim` | — |
| `/api/pc/pairings/handoff` | POST | `pc_pairing_handoff` | — |
| `/api/pc/pairings/install-file` | POST | `pc_pairing_install_file` | — |
| `/api/pc/pairings/install-exe` | POST | `pc_pairing_install_exe` | — |
| `/api/pc/pairings/adopt` | POST | `pc_pairing_adopt` | — |
| `/api/pc/pairings/{link_id}` | DELETE | `pc_pairing_revoke` | — |
| `/api/pc/pairings/{link_id}/label` | POST | `pc_pairing_label` | — |
| `/api/pc/pairings/{link_id}/pause` | POST | `pc_pairing_pause` | — |
| `/api/pc/pairings/{link_id}/resume` | POST | `pc_pairing_resume` | — |
| `/api/pc/pairings/{link_id}/roots` | POST | `pc_pairing_approve_root` | — |
| `/api/pc/pairings/{link_id}/roots/{root_ref}` | DELETE | `pc_pairing_revoke_root` | — |
| `/api/pc/browse` | POST | `pc_file_exchange_browse` | — |
| `/api/pc/find` | POST | `pc_file_exchange_find` | — |
| `/api/pc/fetch` | POST | `pc_file_exchange_fetch` | — |
| `/api/pc/save` | POST | `pc_file_exchange_save` | — |
| `/api/pc/move` | POST | `pc_file_exchange_move` | — |
| `/api/pc/delete` | POST | `pc_file_exchange_delete` | — |
| `/api/pc/cancel` | POST | `pc_file_exchange_cancel` | — |
| `/api/pc/reference` | POST | `pc_file_exchange_reference` | — |
| `/api/pc/result` | GET, HEAD | `pc_file_exchange_result` | REVIEW |
| `/api/pc/file` | GET, HEAD | `pc_file_exchange_file` | REVIEW |
