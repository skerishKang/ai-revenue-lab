# app_factory split PR0: baseline and ownership map (CGI-1, 2026-11-28)

- Exact main SHA: `c98dd903d2a383ea9c0f17aaf88cfcb80307c21e`. PR0 changes tests/ only, moves zero application definitions.
- `app/app_factory.py`: 2562 physical lines, 41 top-level function/class definitions, 91 create_app parameters.
- Factory file changed since the prior design base: False.

## CI baseline for exact main SHA

- [B62 Chat main CI](https://github.com/skerishKang/ai-revenue-lab/actions/runs/46086131886): completed/success, SHA `c98dd903d2a383ea9c0f17aaf88cfcb80307c21e`.
- `B14 changeset classifier (fail-closed)`: completed / success.
- `B62 date-dependent golden contract`: completed / success.
- `b62-test`: completed / success.
- `B62 Chat full pytest (app change) ${{ matrix.shard }}/4`: completed / skipped.
- Full Chat pytest that was skipped is NOT a pass. CI job success is not per-test-file evidence.

## Previous CGI full-suite attempt is INCOMPLETE, not green

- Earlier main `3bdec526b38de6fad0c14ad61a431a3c6b9dc681`: 2026-11-28T07:17:07+09:00 to 2026-11-28T07:34:02+09:00, status incomplete, last progress 6%.
- Partial progress only: 988 dots, 14 skips; F/E observed 0. No final pass/fail, failure IDs, or JUnit.
- Do not count this partial observation as a complete baseline.

## Related existing test-file inventory

- Source/AST/path-sensitive candidates from prior design: 31; existing direct app_factory importer files: 116; focused regression modules selected here: 81.
- Each file listed below is a CANDIDATE, not an individually verified PASS:
- `tests/test_2505_chat_claw_shared_tier_routes.py`
- `tests/test_2824_isolated_parser_transport.py`
- `tests/test_3476_same_origin_guard.py`
- `tests/test_3580_claw_office_chooser_routes.py`
- `tests/test_3580_web_xlsx_selection_routes.py`
- `tests/test_3782_pc_browser_routes.py`
- `tests/test_3932_artifact_owner_preview_boundary.py`
- `tests/test_3933_b54_first_turn_grant.py`
- `tests/test_3933_existing_result_reuse_adopt.py`
- `tests/test_4139_claw_device_directory_route.py`
- `tests/test_4139_connector_enrollment_async_routes.py`
- `tests/test_4139_connector_enrollment_consent_routes.py`
- `tests/test_4139_connector_enrollment_server_routes.py`
- `tests/test_4139_connector_one_click_approval_route.py`
- `tests/test_4139_connector_owner_source_composition.py`
- `tests/test_4139_connector_txt_read_routes.py`
- `tests/test_4139_gateway_first_pairing_tls_review.py`
- `tests/test_4139_private_rpc_export_parity.py`
- `tests/test_4428_central_tier_routes_261019.py`
- `tests/test_4434_b66_product_pc_directory_routes.py`
- `tests/test_4434_office_xlsx_web_return.py`
- `tests/test_4469_claw_worker_search_activation.py`
- `tests/test_4483_b66_guard_route_contract.py`
- `tests/test_4647_latest_sidebar_integration.py`
- `tests/test_4745_native_calendar_chat_claw_routes.py`
- `tests/test_4862_claw_route_refresh.py`
- `tests/test_5080_android_device_enrollment_routes.py`
- `tests/test_5108_admin_route_projection.py`
- `tests/test_5108_admin_route_revision_visibility.py`
- `tests/test_5108_chat_central_route_execution.py`
- `tests/test_5228_blocked_tier_route_candidates.py`
- `tests/test_5568_document_convert_routes.py`
- `tests/test_5574_frontend_pc_route_harness.py`
- `tests/test_5881_claw_file_lane_admission.py`
- `tests/test_7543_worker_state_guard.py`
- `tests/test_7680_feedback_routes.py`
- `tests/test_7690_site_feedback_routes.py`
- `tests/test_7809_app_factory_split_guards.py`
- `tests/test_7814_create_app_route_table.py`
- `tests/test_8204_pc_helper_update_routes.py`
- `tests/test_auth_abuse.py`
- `tests/test_b54_claw_execute_retry_ui.py`
- `tests/test_b54_claw_general_p01_routing.py`
- `tests/test_b54_claw_general_route_ordering.py`
- `tests/test_b54_claw_run_history_ui.py`
- `tests/test_b62_1732_capability_navigation.py`
- `tests/test_b62_1738_readme_contract.py`
- `tests/test_b62_3094_local_access_source_adapter.py`
- `tests/test_b62_app_entry_staging.py`
- `tests/test_b62_host_grounded_chat_parity_261105.py`
- `tests/test_b66_admin_routes.py`
- `tests/test_b66_ai_chat_routes_4466.py`
- `tests/test_b66_ai_conversation_routes_4412.py`
- `tests/test_browser_message_lifecycle_contract.py`
- `tests/test_browser_orchestration_lifecycle_contract.py`
- `tests/test_calendar_read_activation_routes.py`
- `tests/test_calendar_ui_appointment_create.py`
- `tests/test_calendar_ui_work_log_create.py`
- `tests/test_chat_slow_routes_2_261102.py`
- `tests/test_claw_attachment_canary_composition.py`
- `tests/test_claw_quote_compare_http.py`
- `tests/test_com2_edge_middleware.py`
- `tests/test_conversation_export_lifecycle.py`
- `tests/test_council_unification_261101.py`
- `tests/test_drive_case_folder_routes.py`
- `tests/test_drive_case_pdf_routes.py`
- `tests/test_health_detail_gate.py`
- `tests/test_lovetree_handoff_routes.py`
- `tests/test_oracle_mesh_read_return.py`
- `tests/test_owner_model_preview_contract.py`
- `tests/test_private_stream_client.py`
- `tests/test_public_streaming_route_contract.py`
- `tests/test_request_telemetry.py`
- `tests/test_saved_outputs_lifecycle.py`
- `tests/test_search_health_3523.py`
- `tests/test_shared_auth_compare_routes.py`
- `tests/test_shared_session_middleware.py`
- `tests/test_tier_route_consumer_coverage.py`
- `tests/test_util_quote_preview_routes_7173.py`
- `tests/test_voice_live_token_route_4643.py`
- `tests/test_voice_stt_wiring_4643.py`

## PR0 proof and per-slice gate

- PR0 new `test_7809_app_factory_split_guards.py`: registry matches owner files; unique AST-defined owners; facade import identity; import levels; public create_app signature; route order and registrar call order; conditional middleware security order; negative vacuous patch simulation.
- PR0 new `_support/app_factory_modules.py`: staged module registry, planned module order, exported names, registrar call order, exact block-and-AST comparison helpers, patch targets that are real global readers.
- PR0 moved definitions: 0. Actual future moves must compare source block and AST to parent-main, reexport original object names at app.app_factory, preserve route/middleware/state/hook order, and contain no behavior changes.
- No new arbitrary raw-string source assertion; structural AST guards only. Existing source-reading checks must not be silently weakened.
- CGI local tests have not been run during pending or running CI. GitHub PR check-runs determine PR0 pass/fail after all check jobs settle.
