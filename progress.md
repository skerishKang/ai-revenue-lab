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
2026-11-09 step3 setup: lane folder E:\PADIEM\chat-r5-261109 cloned from origin/main 144ea2f7a; branch refactor/r5-step3-history-menu; baseline app.js 7928 lines (cap 8028).
2026-11-09 step3 map: r5_appjs_map.py run on current app.js; recent-conversations-menu area confirmed = 18 functions (494 lines incl. clawRunHistory presentation + renderTyping per map classifier) + top-level connection code block 3004-3015 (history actions click/Escape listeners, stays in app.js per map §8); the ~1,700-line identity is already documented in map §7 (added in step 1 #7226) so no new map text was needed.
2026-11-09 step3 move: 18 functions (489-line map area) moved to static/chat-history-module.js (window.PadiemChatHistoryModule); app.js keeps 18 one-line forwarders + one lazy factory (deps getters/setters); index.html loads the module before app.js; top-level history listeners stay in app.js per map rule; app.js 7928 -> 7529 lines.
2026-11-09 step3 tests: 22 app.js-string test files migrated to module-based/behavior checks (strength kept, nothing deleted/skipped); new contract tests: node-vm module behavior + getter-before-first-call + setters (test_r5_step3_history_module_7216) and one real-Chromium forwarder call per moved function + getter checks (test_r5_step3_history_browser_7216); b54 retry harness loader lists the module; size cap 8028 -> 7629.
2026-11-09 step3 verification: full chat suite parity with main (this machine has 40 pre-existing env failures identical on main, new failures 0); screenshots before (live=pre-change) captured at 1440/390 for logged-out first screen and logged-in recent-menu open; map doc section 9 added (area functions + top-level connection code confirmed; the 1,700-line identity was already documented in section 7).
