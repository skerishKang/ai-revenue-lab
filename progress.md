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
261109 #7241 1단계 머지: PR #7253 → main 7ff2aedd2(스쿼시). 전환 10개 시험 파일+fixture·스위치·도우미·계약시험(16파일, +1380/−451). 플랫폼 전체 2168 passed·3 skipped(main 기준선 2119) 신규 실패 0, 추가 줄 실값 0건(147토큰 대조). 이슈 #7241 3단계에 admin 등급 부재 시 ADMIN 대체값 항목 추가. 주의: 이 환경 gh 2.45.0에는 `gh pr checks --json`이 없어 tools/cto/automerge.py 검사 폴링이 실패(검사 전부 통과 후 squash 머지로 대체).
