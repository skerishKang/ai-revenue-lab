2026-11-03 setup: created isolated worktree D:\PADIEM\mcp-shell-261103 from origin/main 2c4465e0f on feat/mcp-pc-shell-261103.
2026-11-03 research: traced MCP tools/list -> transport -> dispatch/approval -> execution -> Chat oracle_mesh command lane -> Connector MeshCentral run_command; read result size, timeout, audit and existing pc_* implementations.
2026-11-03 research: inspected DesktopCommanderMCP (MIT) terminal-manager and process-tree design (wait cap, bounded output, paginated read, force_terminate); no source copied.
2026-11-03 implementation: added pc_shell closed schema (command/cwd/shell/timeout_seconds), Base64 one-line dispatch worker for powershell/cmd/bash, separate stdout/stderr, exit-code capture, 12KB head/tail truncation, 1-600s limit with process-tree termination.
2026-11-03 implementation: reused MCP _tool registration, owner/device/grant checks, dispatch approval/audit, oracle_mesh command dispatch and result store; added numeric audit metadata and migration 094.
2026-11-03 tests: added 16 pc_shell tests (schema, delegation/disconnect denial, completed/timeout/truncation/error, audit privacy, Windows PowerShell/cmd/bash worker); fixed Windows cp949 test-environment reads and child PYTHONIOENCODING.
2026-11-03 verify: MCP suite 129 passed; help guide tests 19 passed; no production writes, no deploy, no PR.
2026-11-03 docs: added architecture replacement memo, help.html MCP connection section, updated MCP gateway handoff doc.
2026-11-03 setup: created isolated worktree from origin/main d123d14c8accf232d52bc0d4e813574bdbf5a6b7 on feat/6724-scenario-sim-261103.
2026-11-03 read: fetched #6724; read CLAUDE.md, AGENTS.md, AI_DEVELOPMENT_OPERATING_POLICY.md and TEST_SCOPE_AND_DELIVERY_POLICY.md; private Governance NOT_READ per machine constraint and supplied work order.
2026-11-03 docs: added six evidence-based scenario scripts and README; browser screens/copy checked in Chat and BookAI sources.
2026-11-03 runner: added live Playwright recording fixture with step screenshots, timing/status metadata, video, and account-state gating; public tests will use GET-only route guard.
2026-11-03 implementation: added guest GET-only browser scenarios, storage-state-gated first-question/PC/document/BookAI cases, tutorial storyboard generator, manual workflow_dispatch-only workflow, and isolated backup restore smoke script.
2026-11-03 resume: confirmed branch/worktree and prior artifacts; no new folder; no session or cookie stored.
2026-11-03 bookai: finished second-device resume step with a fresh browser profile, BookAI session check (skip test_account_missing), account sync assertion, TODAY/continue UI check, and second-device video artifact.
2026-11-03 docs: aligned 01/04 screenplay rows and caption mapping with the actual TODAY/continue flow; root live-artifacts is ignored.
2026-11-03 verify: guest live scenario passed on production GET-only; 5 account cases skipped; tutorial builder test passed; local browser regression 41 passed and 3 pre-existing admin-model icon-count failures reproduced unchanged.
2026-11-03 commit: docs 5f59d0bcc, runner/tutorial aee323d00; workflow and this log follow before fetch/rebase/push.
2026-11-03 ci-fix: (컴1로컬1 대행) live-scenarios 잡에 uv 부트스트랩·pinned Playwright·chromium 단계를 추가한다. cross_lane_test_dependency_guard가 잡은 MISSING_FIRST_PARTY_ROOT=padiem_control_plane·MISSING_THIRD_PARTY_DEP=starlette 2건이 로컬에서 11 passed로 풀렸고 guard는 PASS.
2026-11-03 setup: created isolated worktree D:\PADIEM\mcp-oauth-261103 from origin/main ad069bdf9 on feat/mcp-oauth-261103.
2026-11-03 research: read the pc_shell design memo, AUTH_STANDARD, existing MCP Bearer transport/account/store; confirmed MCP Authorization 2026-07-28 and Claude/ChatGPT connector requirements.
2026-11-03 decision: (a) Chat hosts MCP-specific OAuth endpoints using the existing Chat common login session; padiem-auth keys/clients untouched.
2026-11-03 implementation: added PRM/AS metadata, DCR, PKCE authorize + consent info/POST, code/token/refresh/revoke, 401 resource_metadata challenge, resource/scope audience checks; PAT path preserved.
2026-11-03 storage: migration 095 extends padiem_mcp_tokens (kind/expiry/refresh/client/scope/resource) and adds oauth_clients/oauth_codes; account deletion/purge updated.
2026-11-03 login/UI: added same-origin login-return cookie to shared login, consent page HTML/CSS/JS, ko/en locale keys, help.html web-connection guidance.
2026-11-03 tests: 12 OAuth tests plus 223 broad MCP/login/deletion/purge/help regression passed on this machine; no production writes/deploy/PR.
2026-11-03 docs: OAuth section 11 added to the replacement memo, operations handoff note updated, progress log created.
2026-11-03 front-audit: mapped every OAuth path through apps/padiem-chat-front worker.mjs; the static branch only matches "/" + root single-segment asset files + /static/, so /.well-known/oauth-*, /oauth/* and /api/mcp already reach COM2, but OAuth GET/POST/OPTIONS only got the 8s generic deadline (apiRead covers /api/ paths).
2026-11-03 front-change: added an oauthRequest predicate (/oauth/ and /.well-known/oauth- prefixes) that bypasses the static/cache branch and reuses API_READ_TIMEOUT_MS (30s); other /.well-known paths and consent static assets unchanged; no new wrangler vars.
2026-11-03 front-tests: new test/mcp-oauth-paths.test.mjs (7 tests: per-path COM2 target, no-store, POST body, 302 + login-return cookie pass-through, OPTIONS, timeout budget, jwks not broadened, consent asset still cached); full front suite 65 passed. Memo section 11.7/11.8 updated with the front redeploy item.


### 2026-11-03 · 공통 로그인 계정 삭제 경로
- 최초 작업 기준은 `origin/main` 7f22f99 이후였다. 원격 중복 브랜치는 없었다. 재개 시 `origin/main`이 18a0e4de까지 진행되어 최신 기준으로 재기반했고, BookAI subject 삭제는 upstream #6767에 이미 들어가 있어 중복 수정 커밋 87a95a19를 제외했다. 기능 구현 커밋은 2a8582fd다.
- 지도: Control Plane Identity DO가 canonical subject·제품 링크를 보관하고, Auth DO가 Google 계정 매핑·refresh 세션 색인을 보관한다. Chat D1에는 공유 subject와 서비스 데이터/북AI 서버 기록, LoveTree PostgreSQL에는 서비스 데이터, CGI에는 별도 회원·OAuth 계정이 있다.
- 구현: 서비스 탈퇴는 해당 제품 링크만 해제한다. 마지막 링크면 Auth에서 세션을 사전 폐기한 뒤 CP 연결·subject와 Auth Google 매핑을 정리한다. 전체 탈퇴는 Chat 설정 경로에서 서명된 LoveTree 삭제 요청 후 Chat·북AI 데이터를 지우고 연결을 해제한다. CGI는 별도 계정이라 대상에서 제외했다.
- 안전장치: Chat 중앙 관리자 이메일·`platform_admin_roles`, LoveTree 제품 관리자 차단 유지. RPC 서명·시각·UUID 재생 방지와 검증은 그대로 두고, 마지막 연결 해제에는 Auth 준비 식별자를 요구해 목록 조회와 삭제 사이의 경합을 닫았다. Auth prepare/complete/abort로 CP 해제 실패 시 계정 매핑을 보존하며 재시도할 수 있게 했다. 탈퇴 이력은 해시와 시각만 1년 보존한다.
- UI·문서: Chat 설정에 서비스별/전체 서비스 확인 경로를 추가하고 Help `#account`와 공통 약관·개인정보처리방침 및 Chat/Claw·북AI·러브트리·CGI 부록을 수정했다. CGI는 자체 계정으로 명시했다.
- 시험: Chat 계정 삭제 25 passed, Auth flow 21 passed, Control Plane Identity·ingress 30 passed, 법률 보존 기간 guard 7 passed. Schema v4 contract 갱신 후 Identity 관련 64 passed. Tutorial generator 21 passed. LoveTree 계정 삭제 16 passed, 전체 `npm test` 277 passed·35 skipped (선택 통합 환경 미설정, 기존 실행 결과).
- PR CI: 초기 run에서 Identity schema v4를 모르는 계약 기대값 3건을 갱신했다. Tutorial generator가 Help `#account`의 계정 이메일 불일치 차단 문구 누락을 찾아 복원했고, 관련 단위 시험 21건이 통과했다. 최신 PR CI 결과를 기다린다.
- 배포 인수: Identity DO schema v4, Auth·Chat·LoveTree 배포, Chat D1 migration 097, LoveTree PostgreSQL 두 표, RPC secret 이름은 운영 메모에 정리했다. 배포·운영 DB 접속·실제 계정 삭제는 수행하지 않았다.
- PR: ai-revenue-lab #6773, LoveTree #155를 열었다. ai-revenue-lab 기능 구현 SHA는 2a8582fd, 문서 갱신 SHA는 c4e34a22이며 LoveTree SHA는 32a46e4다. PR checks를 모두 확인한 뒤 이 저장소의 지정 merge 절차를 진행한다. 배포·운영 DB 접속·실제 계정 삭제는 수행하지 않았다.

### 2026-11-03 · P01 Engine 고정 지연
- setup: created isolated worktree E:\PADIEM\p01-latency-261103 from origin/main 18a0e4de6 on perf/p01-engine-latency-261103.
- measure: COM2 P01 local composition 54ms first / 6ms warm, service auth 1ms; a local host roundtrip with fake admission/B14 is 12.8ms total. The 10s is external: admission fetch 2.0-2.8s per call with a fresh TLS client, reserve and receipt are further sequential Control Plane RPCs.
- implementation: host authority transport now reuses one keep-alive httpx client per event loop (same signed proof and new service id per attempt), closed at lifespan shutdown; no authority check changed.
- observability: added engine_timing (run_hash, trace_id, admission/core/b14/receipt/total ms, bounded outcome) to the JSON orchestration lane and a host-visible stderr handler; Core exposes the last B14 duration in request context.
- verify: engine suite 4082 passed, 1 skipped; Core runtime/orchestration 101 passed; local Chat->P01 roundtrip 200 with engine_timing total_ms=12.8; COM2 pooled fetch probe 4.13s cold then 0.81/0.79/1.80s versus 2.85/2.59/2.04s per fresh client.
- PR: ai-revenue-lab #6774.

### 2026-11-03 · Chat model-first (#4651)
- setup: created isolated worktree E:\PADIEM\model-first-261103 from origin/main a8eff99 on feat/model-first-4651-261103.
- design: `PADIEM_CHAT_MODEL_FIRST` 기본 off. 켜지면 기존 `/api/orchestration` 검증·등급·usage gate·PC 문맥·grounding 뒤에 같은 B14 답변 모델로 질문+서버 도구 목록을 한 번에 보내고, tool_calls가 없으면 직행 저장, 있으면 기존 `execute_chat_pc_drive_lane`(P01)으로 넘긴다. 별도 분류 호출 없음.
- authority: 도구 목록은 `pc_context.pc_tools.allowed_scopes` 교집합, 쓰기 도구는 변경 요청일 때만. 모델이 제안하지 않은 도구 호출은 403. 소유자·Mesh grant·target·scope 재확인은 기존 lane 그대로. 꺼진 PC는 도구를 비우고 `pc_work_context` 안내를 모델 문맥에 넣는다. Gemma 등 tool 미지원 route는 엔진 경로 유지.
- usage: 기존 `UsageGate.authorize`와 `create_guard_from_request`/`apply_guard_to_client`(B14 원장)를 직행 경로에도 그대로 통과. 등급/모델/공급자 변경 없음.
- streaming: tool_calls 없는 답은 NDJSON meta/delta/done으로 흐른다. `stream` 표시는 라우트 검증에서 분리해 프론트의 `{"stream":1}`을 받는다. 화면 코드는 건드리지 않았다.
- timing: `orchestration_timing_com2`에 `path=engine|model_first_direct|model_first_tool` 추가.
- tests: model-first 14 passed (off 동일, 안녕 직행 엔진 0, PC tool lane, 웹 evidence, usage 거부, 꺼진 PC, Gemma, scope 교집합, 미제안 tool, 쓰기 규칙, guard, NDJSON). 기존 orchestration/PC/bridge/tier/identity subset 248 passed.
- local A/B (fake B14 0.84s + P01 고정비 9.96s 모사): engine 9973ms → model-first 867ms, engine calls 1→0.
- docs: docs/operations/CHAT_MODEL_FIRST_20261103.md, deploy/host-com2/chat/.env.example.
- PR: pending.
2026-11-09 setup: created isolated worktree E:\PADIEM\pc-read-latency-261109 from origin/main 80779936 on perf/pc-read-latency-261109; measurement tokens (CGI-1/COM1) minted via the owner session through the product settings API, values held only in protected local/COM2 files.
2026-11-09 measure: pc_read probes x13 (CGI-1 10, COM1 3) all refuse at the engine files dispatch with oracle_mesh_workspace_unavailable; identity 0-1144ms, P01 admission 954-1023ms observed before the refusal.
2026-11-09 fix: dispatch workspace resolves from the verified canonical session tenant when the non-authoritative memory shadow pointer is stale (the PC lane's #7161 fallback, applied to the engine files lane and the three intent lanes); contract tests pin the seam both sides + diff-proven.
2026-11-09 tooling: scripts/ops/pc_read_measure.py (probe + journal stage breakdown + 7-day JSONL store) installed on COM2 for the pre/post tables and the 30-minute monitor.
2026-11-09 monitor: added the 30-minute pc_read latency monitor package (scripts/ops/pc_read_measure.py with content-head proof + 30s/failure journal warning, deploy/host-com2/pc-read-metrics units+installer, docs/operations/PC_READ_LATENCY_MONITOR_261109.md) on feat/pc-read-metrics-261109; COM2 install waits for the #7232 deploy to finish.
2026-11-09 voice (ii) impl: new app/voice_stt_rpc.py receiver on the Chat Worker (/internal/rpc/voice_stt, v2 proof + history-store replay, secret PADIEM_CHAT_VOICE_RPC_SECRET, body bound = transcribe audio bound) dispatching to the existing VOICE_STT_SERVICE transport; host side app/local_voice_stt_transport.py wraps HttpRpcBinding (PADIEM_CHAT_VOICE_RPC_ORIGIN/_SECRET pair) and create_app(voice_stt_transport=...) fills app.state.voice_stt_transport; STT Worker untouched (no new HTTPS ingress). tests: rpc+transport 10 passed, voice subset 110 passed/21 skipped, password RPC regression 8 passed. next: PR, merge, secret pair, Worker deploy, com2 deploy, QA.
2026-11-09 marker: pc_queue_call INFO lines were dropped by the host's missing logging config; bound the same message-only stderr hook at the proxy's single log site (+ tests: host visibility + measure-tool queue_wait contract), log-only change.

## 261109 (가운데 glm3) — #7229 컴2 P01 Control Plane 바인딩 설계 (중단, 음성 장애 대응 우선)
- 이슈 #7229 생성 완료. 설계 문서 docs/operations/COM2_P01_CONTROL_PLANE_BINDINGS_20261109.md 작성 완료(방식: identity v2 RPC에 resolve_connector_workspace 추가 / Google OAuth는 기존 v2 RPC 재사용 + state Worker ingress에 select_calendar_binding 허용 선행 / grants는 호스트 엔진 DB 객체를 두 번째 이름으로).
- 코드: app/local_identity_binding.py(resolve_connector_workspace), app/local_google_oauth_binding.py(신규), app/local_runtime.py(두 바인딩), tests/test_com2_control_plane_bindings.py — 엔진 전체 4181 passed, 변이 2종 red 확인.
- 남은 일: p01.env.example 2개 이름 추가에 따른 packaging 화이트리스트 시험 재실행 확인 → 커밋 → Draft PR 생성(배포 없음).
- 261109 02:45 음성 장애 분석: COM2 Chat 호스트는 `app.state.voice_stt_transport`를 한 번도 바인딩한 적이 없음(전 커밋 이력 0, 운영 health `voice_stt_available=false`). relay 4503과 구 경로 `/api/voice/live-token` 503 `voice_stt_unavailable`이 같은 원인 → #7228 revert는 복구가 아님. 실제 복구는 STT Worker로 가는 호스트 인증 레인 신설(비밀 쌍 + Cloudflare 측 변경) 필요.
- 261109 상태 확인(가운데 glm3 재개): #7229 코드는 커밋 전 상태로 main 작업트리에 미커밋(엔진 4181 passed 기록), Draft PR 미생성(gh 확인 — 최신 open PR #7234). 음성: #7228 병합·release_33 배포 완료, relay WS 통과(4401) 확인됐으나 /health voice_stt_available=false — live-token 발급 경로 부재가 미해결 원인. Cloudflare padiem-chat Worker 최종 배포 2026-10-30T20:53Z version 56eb967d(롤백점), padiem-voice-stt는 10-14 이후 무변경(HTTPS 입구 추가 없음 확인). 컴2 .env에 rollback-voice261109 사본 존재, 배포 프로세스 없음. 운영 반쯤 바꾼 상태 없음 → 롤백 불필요, 즉시 진행.
261109 #7241 1단계 착수: 작업트리 tests-fixture-7241-261109(origin/main 84038b249)에서 공용 fixture(tests/fixtures/models_private_fixture.json, private-v1 3모델·2프로바이더·5등급) + conftest 최상단 스위치 주입(_registry_switch_default.py, 저장소 문서가 값 없는 상태가 되면 자동 활성) + 시험 공용 도우미(_registry_values.py: registry/model_rows/model_ids/group_ids/provider_row/requires_owner_document) 구축. main 기준선: 플랫폼 스위트 2119 passed.
261109 #7241 1단계 전환 test_alpha1.py: 값 리터럴 87줄 제거 → 등록부/카탈로그 유도(_catalog_route_id, _priced_catalog_model, _binding_env_name). 소유자 핀 2건은 requires_owner_document로 분리(본문 무변경). 107 passed.
261109 #7241 1단계 전환 test_opencode_go_wire.py: 어댑터 자체 wire 표(_WIRE)와 승인 origin 상수에서 모델·프로바이더·URL 유도, 데이터 나열 파라미터는 소유자 문서 전용으로 분리(14건). test_3977_serving_evidence.py: 서빙 근거 표(_GOOGLE_FIRST_PARTY_SOURCES 등)에서 로스터·호스트 유도, 카디널리티 단정 유지(6건 분리). 67 passed.
261109 #7241 1단계 전환 test_credential_slots_board.py: 슬롯→프로바이더 표를 보드 자체 유도(_providers_by_slot/SLOT_BINDINGS)로 대체, 슬롯 이름은 역할 상수+synthetic 값. test_worker.py: 등록부 조회 기반으로 바인딩 수집 확인, 소유자 핀 4건 분리. 34 passed.
261109 #7241 1단계 전환 test_b14_native_parameters.py: 모델 파라미터를 sorted(model_ids())로 확장, reasoning 문서 여부는 서빙 근거 표에서 판독(문서화 라우트는 skip 가드). test_b14_model_registry_file.py: 은퇴 집합을 retired_model_ids()로 유도, 프로바이더 로스터/호스트/바인딩 핀 1건 분리. 95 passed, 3 skipped.
261109 #7241 1단계 전환 test_owner_excluded_live_dispatch.py: 제외 계열·중립 쌍·바인딩을 등록부/카탈로그에서 유도, 소유자 핀 파라미터는 분리(11건), 식별자에서 프로바이더 이름 제거. test_5318_b14_call_ledger.py: 스트림 프리뷰 대상 행을 등록부에서 동적 선택(_stream_model_row), 바인딩 이름 유도. test_streaming_gateway.py: 모델·툴 문서 여부를 등록부/근거 표에서 유도, 소유자 핀 1건 분리. 503 passed(10파일 합계, 기준선 458 → 506 collected).
261109 #7241 1단계 완료: 플랫폼 전체 스위트 2164 passed, 3 skipped(main 기준선 2119 passed) — 신규 실패 0. conftest 스위치 주입은 저장소 문서가 값 없는 상태(3단계)에서 자동 활성되도록 게이트. 추가 줄 실값 대조(147토큰, b14_models.json+wrangler.toml 추출) 0건. 계약 시험 test_7241_registry_fixture_contract.py 추가(fixture 유효성·자리표시자 전용·게이트 무동작).
261109 #7241 2단계 착수: 작업트리 tests-fixture-7241-s2-261109(origin/main, 1단계 병합 후)에서 중형 파일 14개 전환. 기준선 main 2168 passed.
261109 #7241 2단계 전환 test_pilot.py: 레거시 파일럿 신원은 a_provider_id()+retired_model_ids() 유도(카탈로그 부재=BYOK 차선), SSRF 허용 origin 파라미터는 등록부 프로바이더 전집합. 106 passed(기준선 92).
261109 #7241 2단계 전환 test_opencode_go_session_bridge_gap.py: Go 로스터를 규칙 상수 소유 행에서 파라미터화, 업스트림/wire는 어댑터 자체 _WIRE 표 판독, 거부 사유는 앱 우선순위 계산. 소유자 핀 4건 분리. 43 passed(기준선 31).
261109 #7241 2단계 전환 test_google_aistudio_provider.py: 로스터·origin·호스트·바인딩·텍스트전용 행을 등록부 유도, 부정 사례는 등록부 코퍼스에서 생성. 소유자 핀 2건 분리. 60 passed.
261109 #7241 2단계 전환 test_tokenharbor_two_free_routes.py: 무료 로스터를 구조적 선택(무료 행+`:free` 표식)으로 유도, 은퇴 라우트 거부는 retired 로스터 합집합 단정. 소유자 핀 4건 분리. 60 passed.
261109 #7241 2단계 전환 test_5824_b14_user_credential.py: 사용자 자격 슬롯 검증을 등록부 프로바이더 행에서 유도. 302 passed(11파일 합계).
261109 #7241 2단계 전환 test_b62_free_routes.py: 무료 등급 라우트/후보를 effective_tier_default/fallback에서 유도, 자격 환경 슬롯은 프로바이더 행 바인딩 사용.
261109 #7241 2단계 전환 test_owner_pinned_tier_fallback_261015.py: 순서 계약을 effective_tier_fallback()/effective_tier_default()로 단정(로스터 나열 리터럴 제거).
261109 #7241 2단계 전환 test_2505_free_candidate_exclusion.py / test_5224_b14_external_auth_boundary.py: 제외·경계 표를 등록부/앱 권위 표 판독으로 대체.
261109 #7241 2단계 전환 test_4317_free_completed_tier_fallback.py: primary/로스터를 effective_tier_* 유도, 긴 로스터는 등록된 비로스터 행으로 구성(미등록 합성 id는 게이트웨이가 401로 거부). 8 passed.
261109 #7241 2단계 전환 test_pilot_phase2.py / test_multimodal.py: 레거시 단일 프로바이더 신원을 공용 상수로 통합, 이미지/텍스트 라우트·바인딩은 등록부 행에서 유도. 114 passed(기준선 동일).
261109 #7241 2단계 전환 test_platform_provider_credential_plane.py / test_b14_uniform_model_first_response_timeout.py: 은퇴 신원은 retired_model_ids() 판독, 타임아웃 파라미터는 등록부+앱 허용 권위(카탈로그 설치·소유자 제외·wire 계열) 필터로 유도. 소유자 핀 2건 분리.
261109 #7241 2단계 보류 test_b14_provider_onboarding.py: 기대가 "은퇴 후 등록 유지/제거된 프로바이더 선택"이라는 소유자 결정이라 등록부만으로 유도 불가 → main 상태 유지, 3단계(문서 전환)에서 처리.
261109 #7241 2단계 완료: 플랫폼 전체 스위트 2244 passed, 3 skipped(main 기준선 2168 passed) — 신규 실패 0. 추가 줄 실값 대조(147토큰) 0건.
261109 #7241 3a PR1 착수: 작업트리 tests-7241-s3a1-261109(origin/main 4d3b752f7)에서 중형 24파일 전환. 기준선 main 2244 passed.
261109 #7241 3a test_alpha1.py: 게이트웨이 경로 19개를 라우트 표면에서 판독(chat_surface), SSRF 네트워크 차단 검사는 등록부 문서 호스트 전집합으로 확장.
261109 #7241 3a test_opencode_go_wire.py: 어댑터 자체 _WIRE/승인 origin 표 + 등록부 행에서 전값 유도, 파라미터는 wire 표 순서 기반 선택.
261109 #7241 3a test_owner_excluded_live_dispatch.py: 차단 게이트(_require_owner_allowed_live_model)로 (프로바이더,업스트림) 쌍 필터, 은퇴 별칭 5종 전개는 retired_model_ids() 기준 생성.
261109 #7241 3a test_5318_b14_call_ledger.py: wire/경로/호스트 리터럴 제거(라우트 표면 판독+합성), 시계 nondeterminism(time.monotonic 고정) 수정.
261109 #7241 3a test_pilot.py/test_pilot_phase2.py: chat 경로를 마운트 라우트에서 구조 선택(_pilot_lane_paths.chat_surface 신규), BYOK 신원은 비카탈로그/retired 유도.
261109 #7241 3a test_b14_provider_onboarding.py: 온보딩 후보를 등록부 행에서 유도(비로스터 행), 제거/생존 핀은 은퇴 신원+프로바이더 행 존재 여부 구조 선택, 자격 격리 유지.
261109 #7241 3a test_b14_model_registry_file.py: 소유자 핀을 구조 선택(비활성 형제 보유 활성 행), 경로/호스트/바인딩·모듈 경로 리터럴 제거, 0600 배포 모드 가드.
261109 #7241 3a test_5224_b14_external_auth_boundary.py: wire 경로를 라우트 표면/엔드포인트 상수에서 유도, 소유자 핀은 앱 자체 선언에서 판독.
261109 #7241 3a test_owner_pinned_tier_fallback_261015.py: 순서 계약을 effective_tier_fallback() 기반 구조 단정(고유성/공유 paid 체인/primary 헤딩)으로 유지.
261109 #7241 3a test_platform_provider_credential_plane.py: wire/URL 리터럴을 선택자로 대체, 소유자 핀은 프로바이더 모듈 자체 상수 판독.
261109 #7241 3a test_kilo_provider.py: 은퇴 로스터를 어댑터 메타데이터(adapter_declaring_retired 신규 도우미)에서 유도, 모듈·프로바이더 이름 미기재.
261109 #7241 3a test_kira_qwen38_free_onboarding.py: 단일 라우트 프로바이더의 채팅전용 무가격 행을 구조 선택, 바인딩/호스트 유도, 타 프로바이더 키 미차용 케이스는 등록부에서 임의 선택.
261109 #7241 3a test_4727_b14_native_tool_calling.py: 툴 행을 캐퍼빌리티+어댑터 wire 표로 선택(네이티브/Go 어댑터 구분), 미태그/무접근 케이스 유지.
261109 #7241 3a test_4727_google_native_roundtrip.py: 네이티브 래인 프로바이더를 캐퍼빌리티 행에서 선택, 엔드포인트 프리픽스는 행 base_origin에서 유도.
261109 #7241 3a test_exlab_qwen38_registration.py: 등록 라우트를 제외/로스터/가격 근거 필터로 단일 선택, origin/호스트/바인딩/표시명을 행에서 판독.
261109 #7241 3a test_modelscope_deepseek_v41_flash_onboarding.py: 어댑터 게이트 통과+벤더 네임스페이스 업스트림 행 선택, 소스 판정은 업스트림 신원에서 유도.
261109 #7241 3a test_2505_b14_free_candidate_execution_block.py: 계열 프로바이더/유료 행을 FREE_CANDIDATE_PROVIDER+제외 권위에서 유도, wire는 어댑터 표 판독.
261109 #7241 3a test_5824_b14_user_credential.py: 핀 대상/플랫폼 평면을 등록부 구조 마커로 선택, Go 래인/풀 래인 모델은 어댑터 상수+effective_tier_default().
261109 #7241 3a test_b14_thought_summary_stream.py: 요약 스트림 대상 행을 캐퍼빌리티/근거 표에서 유도, 경로 리터럴 제거.
261109 #7241 3a test_poolside_provider.py: 프로바이더 행 구조 선택 + 어댑터 상수 판독으로 값 유도.
261109 #7241 3a test_opencode_go_free_longcat_step5_eval.py: 평가 대상 행을 wire/무료 캐퍼빌리티/upstream 동일 접미사 구조로 선택, 프로바이더 id는 wire 표 판독.
261109 #7241 3a test_b14_openai_compatible_registry_adapter.py: 호환 어댑터 행/경로/바인딩을 등록부+라우트 표면에서 유도.
261109 #7241 3a 공용: tests/_registry_values.py에 adapter_modules/adapter_for/adapter_declaring_retired 추가(어댑터를 이름 대신 상수로 선택), tests/_pilot_lane_paths.py 추가(게이트웨이 표면 구조 선택).
261109 #7241 3a PR1 검증: 플랫폼 전체 2292 passed, 3 skipped(main 2244) — 신규 실패 0. 추가 줄 실값 0건. 전환 파일 내 실값 줄 0.
2026-11-09 journal-host: one shared helper (app/journal_host.py) owns the host-visibility fix (handler + INFO level gate + stand-aside); the four earlier copies delegate and the five audited loggers bind at their call sites — 18 tests pin one stderr line per logger and forbid a private copy.
2026-11-09 measure-leg: the receipt leg started at the executor's submit_ok, but Chat prints pc_result received BEFORE that ack (measured -96..-2262ms), so the leg was negative; it now starts at the submit marker and the two legs partition the assembly window exactly (contract tests updated + new ack-after-receipt case).
261109 #7241 3a PR2 상태 확인(윈도우 경로 E:\PADIEM\tests-7241-s3a2-261109, 브랜치 test/7241-stage3a-pr2-261109): main 8310c4152 위에서 시험 30파일 + _registry_values.py 도우미 변경 미커밋. 이어서 윈도우에서 해당 30파일만 시험하고 PR로 마무리한다.
261109 #7241 3a PR2 test_3554_kira_504_envelope_fingerprint.py: 모델·프로바이더를 등록부/어댑터 표에서 유도, 경로는 라우트 표면 판독.
261109 #7241 3a PR2 test_3554_kira_connect_timeout_scope.py: 타임아웃 계약 대상 행을 등록부에서 구조 선택.
261109 #7241 3a PR2 test_3554_provider_timeout_phase.py: 페이즈 표 대상을 등록부 행에서 유도.
261109 #7241 3a PR2 test_3554_whitespace_stream_commit.py: 스트림 공백 커밋 케이스를 어댑터 wire 표에서 유도.
261109 #7241 3a PR2 test_4176_modelscope_timeout_scope.py: 타임아웃 스코프 대상을 등록부 행+어댑터 게이트로 선택.
261109 #7241 3a PR2 test_4317_free_completed_tier_fallback.py: primary/로스터를 effective_tier_* 유도, 긴 로스터는 등록된 비로스터 행으로 구성.
261109 #7241 3a PR2 test_5784_b14_local_runtime.py: 엔드포인트 chat_surface(), 원장 프로토콜은 _PROTOCOLS 바인딩 사용.
261109 #7241 3a PR2 test_6460_gemini_native_tools.py: 네이티브 툴 행을 캐퍼빌리티+어댑터 표로 선택.
261109 #7241 3a PR2 test_6858_overlay_reasoning_validation.py: 추론 오버레이 검증 대상을 등록부 행에서 유도.
261109 #7241 3a PR2 test_7156_empty_answer_chain_advance.py: 로스터는 effective_tier_*, 자격은 라우트된 프로바이더 스펙에서 확인.
261109 #7241 3a PR2 test_7156_final_completed_first_byte.py: 타임아웃 핀은 get_timeout_policy(), 단일 후보 라우트는 등록부 구조 선택(없으면 skip).
261109 #7241 3a PR2 test_b14_malformed_upstream.py: 모델/업스트림/프로바이더/바인딩을 등록부 행에서 유도, 네이티브 계약은 설치된 wire 가드.
261109 #7241 3a PR2 test_b14_shared_timeout_policy.py: 케이스를 등록부(어댑터 보유·비제외·공유 wire)에서 파라미터화, wire 접미사는 어댑터 AST 판독.
261109 #7241 3a PR2 test_b14_tool_channel.py: 툴 채널 대상 행을 어댑터 wire 표와 캐퍼빌리티에서 유도.
261109 #7241 3a PR2 test_b62_free_routes.py: 은퇴 무료 로스터는 adapter_declaring_retired(), 소유자 핀 유지.
261109 #7241 3a PR2 test_capability_evidence.py: 채팅 전용 등록 행을 등록부에서 구조 선택.
261109 #7241 3a PR2 test_deployment_scope.py: 리포 루트·감시 경로·공유 패키지 목록을 앱 자체 임포트 그래프와 모노레포 배치에서 유도.
261109 #7241 3a PR2 test_exlab_429_diagnostics.py: 프로바이더 id/호스트/표시명을 어댑터+등록부 행에서 유도, 분류 케이스는 유도 id로 파라미터화.
261109 #7241 3a PR2 test_multimodal.py: 이미지/텍스트 라우트와 바인딩을 등록부 행에서 유도.
261109 #7241 3a PR2 test_openrouter_retired.py: chat/스트림 표면은 라우트 표면 판독, 은퇴 신원은 retired_model_ids().
261109 #7241 3a PR2 test_registered_routes_truth.py: 라우트 id를 등록부 유도, 은퇴 프로바이더는 adapter_declaring_retired().
261109 #7241 3a PR2 test_routing_evidence.py: 라우트 id 2건을 등록부 model_ids()에서 유도.
261109 #7241 3a PR2 test_sensenova_provider.py: 프로바이더/캐퍼빌리티/가격을 등록부 행 스냅샷으로 단정, 은퇴 차선은 어댑터 상수.
261109 #7241 3a PR2 test_space_bunny_vision_primary.py: 은퇴 차선 신원·업스트림·바인딩을 adapter_declaring_retired()로 유도.
261109 #7241 3a PR2 test_stream_error_contract_5263.py: 스트림 표면을 마운트 라우트에서 판독.
261109 #7241 3a PR2 test_streaming_gateway.py: CHAT/STREAM 표면과 네이티브 엔드포인트 프리픽스를 등록부 행에서 유도.
261109 #7241 3a PR2 test_streaming_provider.py: 완료 URL은 chat_surface() 꼬리+합성 픽스처, 네이티브 wire 시험은 설치 wire 가드.
261109 #7241 3a PR2 test_upstream_retry.py: 모델/업스트림/프로바이더/바인딩을 첫 활성 등록부 행에서 유도(재시도 정책은 프로바이더 무관).
261109 #7241 3a PR2 test_worker.py: 소유자 핀의 슬롯/프로바이더를 wrangler secrets 표와 어댑터 선언에서 선택, 라우트 집합은 프로바이더 행 기준.
261109 #7241 3a PR2 test_workspace_phase3.py: chat 표면을 모듈 상수로 1회 판독해 POST 경로 대체.
261109 #7241 3a PR2 검증: 윈도우에서 변경 30파일만 실행 499 passed, 2 skipped(둘 다 문서화된 가드 skip). 추가 줄 실값 0건, 변경 파일 잔여 실값 줄 0.
261109 #7241 3a PR2 수정 test_4317_free_completed_tier_fallback.py: 확장 로스터 행 삽입을 monkeypatch.setitem으로 바꿔 프로세스 전역 CATALOG_BY_ID 오염 제거(CI의 test_6828b_registry_wiring 실패 원인). 전체 스위트 재실행 2301 passed, 11 skipped — 이후 test_streaming_gateway chain_budget 1건은 시간 민감 flaky(재실행 시 통과)로 확인.
261109 #7241 3a PR3 test_2107_com2_admin_auth_boundary.py: 관리 진입점을 앱 디렉터리 기준 상대경로로 참조(리포 경로 리터럴 제거).
261109 #7241 3a PR3 test_3554_canonical_wire_parity.py: 기대 업스트림 URL을 chat_wire_tail()(어댑터 자체 조합 표)로 유도.
261109 #7241 3a PR3 test_3554_empty_answer_contract.py: 게이트웨이 POST 대상을 마운트 라우트(chat_surface)에서 판독.
261109 #7241 3a PR3 test_3977_eleven_model_wire_parity.py: URL 단정을 chat_wire_tail() 말단 세그먼트 비교로 전환.
261109 #7241 3a PR3 test_3977_serving_evidence.py: 문서화 호스트를 근거 모듈 자체 1차 출처 로스터에서 유도, 소유자 핀 유지.
261109 #7241 3a PR3 test_4727_signature_and_outcome_contract.py: 모델/업스트림/바인딩을 네이티브 툴 wire 어댑터가 서빙하는 등록 행에서 유도.
261109 #7241 3a PR3 test_6812_stream_usage_option.py: 원장 endpoint는 chat_surface(), protocol은 표면 말단에서 유도.
261109 #7241 3a PR3 test_6838_reasoning_policy.py: 원장 endpoint를 chat_surface()로 대체.
261109 #7241 3a PR3 test_7215_stream_final_first_token.py: URL/대상 행/자격 슬롯을 라우트 표면+등록부 행에서 유도.
261109 #7241 3a PR3 test_agnes_429_diagnostics.py: 프로바이더/모델/업스트림/표시명을 어댑터 선언+등록부 행에서 유도.
261109 #7241 3a PR3 test_agnes_provider.py: 완료 URL을 chat_wire_tail()로 조립(경로 리터럴 제거).
261109 #7241 3a PR3 test_atria_stream_optin.py: UI 요소/DOM 핸들/모델 가드/폴백 플래그/표면을 템플릿·스크립트·마운트 라우트에서 판독.
261109 #7241 3a PR3 test_b14_add_model_tool.py: 기존 프로바이더/바인딩/표시명을 등록부+어댑터에서 유도, 신규 픽스처는 합성(.invalid).
261109 #7241 3a PR3 test_b14_completed_response_bounds.py: 대상 행을 어댑터 wire 표·플레인 채팅 봉투로 구조 선택(소유자 핀).
261109 #7241 3a PR3 test_b14_health_truth.py: models 표면 신원을 유효 등록부의 설치/활성 집합과 대조.
261109 #7241 3a PR3 test_b14_uniform_model_first_response_timeout.py: chat wire를 공유 표면 말단 조합으로 유도, 문서 문구 중립화.
261109 #7241 3a PR3 test_b14_worker_secret_rotation.py: 대상 모델 id를 프로바이더 바인딩과 일치하는 등록부 행에서 유도.
261109 #7241 3a PR3 test_bai_provider.py: 은퇴 신원을 retired_model_ids()에서 구조 선택(프로바이더 미등록 조건).
261109 #7241 3a PR3 test_capability_routing.py: 채팅 전용 대상 행을 카탈로그+라우터 판정으로 선택.
261109 #7241 3a PR3 test_google_aistudio_provider.py: 경로를 어댑터 자체 origin 세그먼트+공유 chat tail로 조립.
261109 #7241 3a PR3 test_kilo_activation.py: 활성 로스터를 adapter_declaring_retired()로 구조 선택(소유자 핀).
261109 #7241 3a PR3 test_kilo_route_retirement.py: 은퇴 로스터를 어댑터 메타데이터에서, 서빙 신원을 registered_model_id_within으로 유도.
261109 #7241 3a PR3 test_opencode_go_session_bridge_gap.py: chat wire를 표면 말단 조합으로, POST 경로를 chat_surface()로 대체.
261109 #7241 3a PR3 test_pc_work_metrics.py: endpoint는 chat_surface(), 배포 스크립트는 앱 디렉터리 기준 경로.
261109 #7241 3a PR3 test_pc_work_metrics_com2_staging.py: APP_DIR/APP_REL을 시험 파일 위치에서 유도.
261109 #7241 3a PR3 test_space_bunny_text_route.py: 은퇴 로스터/무료 라우트/금지 토큰을 어댑터 선언+등록부에서 유도, 소유자 핀 유지.
261109 #7241 3a PR3 test_streaming_router.py: endpoint는 chat_surface(), 미설치 신원은 a_model_id()+접미사 합성.
261109 #7241 3a PR3 test_tier_route_consumer_coverage.py: B14 앱 경로를 리포 루트 대비 상대경로로 유도.
261109 #7241 3a PR3 test_tokenharbor_two_free_routes.py: 업스트림 요청 경로를 origin+chat_wire_tail() 조합으로 대체.
261109 #7241 3a PR3 공용: _registry_values.py에 registered_model_id_within()/chat_wire_tail() 추가(읽기 전용 도우미), 문서 문구에서 경로 리터럴 제거.
261109 #7241 3a PR3 검증: 윈도우 변경 29파일 491 passed, 4 skipped. 전체 스위트 2303 passed, 11 skipped. 추가 줄 실값 0건. 시험 잔여 실값 conftest.py 1줄만 남김(3b 범위).
2026-11-09 step3 release: PR #7249 merged (4a73d21c6) after 50/50 checks; release_chat.ps1 43 (DryRun first) shipped main SHA 4a73d21c6 -> front dbebf0f1 (rollback eb89bb40), COM2_DEPLOY_SUMMARY chat:PASS p01:SKIP b14:PASS executor:PASS tools_serialization:PASS ai:PASS; QA account menu QA (rename/pin/unpin/delete) verified, console errors 0 apart from the pre-existing /api/claw/verified-model-choices?tier=free 503 seen before the deploy; before/after 1440+390 screenshots equal except button/border tints from the same-release R3 css commit e2ff2a1da.
2026-11-09 step4 move: 41 login-session functions (map area, 693 lines) moved to static/chat-auth-module.js (window.PadiemChatAuthModule); app.js keeps 41 one-line forwarders + lazy factory (115 deps: 9 get+set); mechanical-substitution proven (deps.x stripped == originals byte-for-byte; 0 missed closure refs after fixing the mover's if(x){ local-shadow bug); app.js 7529 -> 7012 lines.
2026-11-09 step4 argon(d) fix: test_ui_request_speed_261101 gains get readClawRuns + a "stub called exactly once" assertion (mutation-verified: removing the getter fails the test); shared strict Proxy helper tests/_r5_strict_deps.js applied to the settings/sidebar/calendar/history R5 test deps (no new omissions surfaced).
2026-11-09 step4 tests: 12 app.js-string/behavior test files migrated (strength kept); new contract tests test_r5_step4_auth_module_7216 (vm behavior/getter/setter) + test_r5_step4_auth_browser_7216 (41 forwarder calls in real Chromium + behavior + getter); size cap 7629 -> 7107.
2026-11-09 glm2 handover: R3 3차는 main 66b61c7b3 (#7277)에 머지되어 본 워크트리 기준 진행 중 단계 없음 — R5 step4-auth #7275(HEAD afa66b139, main 11 ahead)를 우선 이어받음. 아르곤 수정 1(test_4488 app 단언)·2(test_5479 파일별 deps. 매칭)·3(authModule deps projects/resetConversation 제거) 모두 미적용 확인, §11 대화 구역 기록은 보존하고 형식만 정리.
2026-11-09 diff-base: the plan diffs the ops checkout HEAD against the target; a dry run or earlier run of the same sha left HEAD at the target so the diff was empty and a #7243 deploy printed p01:SKIP reason_files=0 (the P01 path mapping at :331 was correct and the cap was already installed). The plan now falls back to state/last_applied_sha then the parent commit, prints DIFF_BASE, and records last_applied_sha on a clean apply — 5 tests (P01-only selects, docs-only skips, stale release still not skipped) + mutation check.
2026-11-09 queue-code: the queue is rsynced, so the checkout diff could never see a stale copy; added queue_matches_target (per-file compare of the shipped tree, runtime state ignored) wired like chat/p01/b14 with reason=RUNNING_CODE_MISMATCH — stale-file test + wiring test + mutation check.
2026-11-09 queue-install-marker: #7270's per-file queue comparison treated any directory as a stale mirror; a partial/foreign tree (and an unresolvable default path) made documentation-only plans redeploy the queue. It now requires the installer's markers (app + padiem_ai_core links, service.py) and tests the configured path before resolving it — 9 tests, two of them load-bearing under mutation.
2026-11-09 identity-parallel: the two post-gate identity reads (B54 bridge session, memory workspace) are issued together; the b62 read stays first because its gate decides whether anything else may be asked. Each identity RPC now logs one bounded line (ttfb_ms, reused, cf-ray colo) via journal_host. Concurrency, precedence and the "no second call after a refused b62" contracts are pinned; mutations caught both changes.
2026-11-09 glm2 merge: origin/main dfa5ac8a1 (11 commits) into refactor/r5-step4-auth by merge (no force push); sole conflict progress.md — both sides kept, no JS/test conflicts (main did not touch app.js). app.js still 7012 lines, cap 7107 unchanged.
2026-11-09 glm2 argon: test_4488 app 단언 추가(모듈 본문 1+app 전달 1, 중복 시 실패)·test_5479 파일별 deps. 매칭(APP+AUTH 결합 0)·authModule deps projects/resetConversation 제거(115→113, strict browser/module 82 passed)·뮤테이션 2건 검증(본문 복제→test_4488 실패, deps. 제거→test_5479 실패). 상한 재계산: app.js 7010+100=7110(기존 7107의 5줄 과소 계수 정정).
261109 3b 재개: E:\PADIEM\b14-registry-3b-261109, fix/registry-public-value-removal-261109(HEAD 378bcfc55 = #7238 main rebase)에서 git status 74파일(수정 73+신규 test_7241_3b_registry_required.py) 확인 — 현재 상태 그대로 커밋·push.
261109 3b 수정: 문서 전환 fixture가 env·스냅샷·카탈로그·Provider 표를 모두 원복하도록 공용 process_catalog_restored 적용(admin·retry·2107 2건·6828b·registry_file), 기본 스위치 복사본을 바이트 동일하게 수정, retry/2107/킬로 시험의 실행 시점 문서 기준 유도 수정. 전체 1377 passed, 233 skipped.
261109 3b 실값: 추가 줄 히트 0, 플랫폼 시험 .py 모델/호스트/바인딩 0(토큰 147). 픽스처 슬롯명은 합성 76-91, 잔여 12파일 55줄은 슬롯/어댑터 유도로 전환. write_registry는 POSIX에서 기존 소유자·그룹 보존(chown) + fsync/replace 실패 시 원자 교체로 기존 파일 보존 시험 2건 추가.
2026-11-09 3b merge: origin/main 04e935faa를 merge-forward(force 없음). progress.md는 main 개편본을 채택하고 3b 기록 3줄만 덧붙임. app/test 충돌 0.
261109 3b 재개2(오른쪽 glm4): git status 0·HEAD e7dcd1b85(push 완료) 확인. B14 번들 preflight 실패 원인 확정 — worker.py:76이 import 시 credential_binding_names()→model_registry_file.py:340 registry_switch_missing. Cloudflare B14 Worker는 운영 배포 대상(wrangler.toml:1, deploy.sh:1-8, b14-production-deploy-gate.yml dispatch-only, COM2 chat B14_SERVICE 바인딩, 7일 3,313요청)이라 지시대로 검사 미수정·보고. 남은 일 확인: write_registry 소유자/원자성 시험 43 passed 3 skipped, 추가 줄 실값 0/147토큰, PR 본문 갱신, 아르곤 패킷 작성. CI 잔여 실패 3계열(B62 chat 5파일·B62 Worker probe·KAgent 126) 원인 기록. 머지·배포 없음.
