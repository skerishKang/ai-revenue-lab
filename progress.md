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

### 2026-11-03 — shared login callback and identity latency
- Contract: `skerishKang/ai-revenue-lab`, base `a8eff99d125215fa0f113488af54573a2e2ca894`, branch `perf/login-callback-261103`, worktree `D:\PADIEM\login-identity-261103`.
- Allowed paths: Chat shared-login/auth adapter, WorkerES256 key import cache, session revocation guard, timing helpers, focused auth tests, and this progress log. Forbidden paths: Engine/P01, unrelated products, secrets/bindings, deployment and production data.
- Acceptance: preserve state/signature/PKCE/session-revocation checks; cache session identity for at most 30–60s with logout/revoke invalidation; pool reusable host HTTP clients; log request id and safe stage durations; run focused auth/security tests; push branch only.
- Private Governance: NOT_READ from CGI-1 per multi-machine policy; scope is the supplied technical work order. No production access or deployment.
- 지도: `/auth/shared/callback` → `SharedLoginFlow.finish_login` → assertion → Auth `/token` exchange → signed token verification + Control Plane `resolve_product_user_for_subject` → `provision_shared_profile` verifies the token and checks/stores the opted-in profile in Chat SQLite → cookie issue. B62's current config opts into profile claims.
- 지도: ordinary shared-cookie requests pass `SharedSessionMiddleware` (signature/expiry + account link) and legacy canonical-session requests pass `SessionRevocationGuardMiddleware` (`resolve_auth_session`). Host identity RPC uses the 75s `HttpRpcBinding` pool; host token exchange uses one 75s HTTPX pool; host signer retains the prepared key and re-derives on JWK material change. Worker assertion signing now retains one non-extractable WebCrypto `CryptoKey`, keyed by the full JWK digest and refreshed when the JWK changes. Worker portal HTTP uses runtime `fetch`; Control Plane calls use the Service Binding.
- 원인/수정: callback 단계명을 `*_ms`로 맞추고, shared token identity와 canonical session 폐기 확인마다 요청 ID·단계 ms 로그를 추가했다. 출력은 안전한 요청 ID와 고정 단계 이름·시간만 포함한다. 같은 세션 결과 30초 캐시, cache revision fence, logout/revoke 무효화 경로는 그대로 유지한다.
- 계정 링크 캐시는 migration 088의 `owner_id` primary-key 인덱스를 사용하고, user-id/expiry 인덱스도 이미 있다. latest migration is 097; no migration added.
- Fake portal (localhost HTTP, no TLS): 12 sequential exchanges used 12 connections / 1829.1ms with one client per exchange; pooled client used 1 connection / 166.1ms. This demonstrates local connection reuse only; it does not model TLS or remote Worker startup.
- Verify: import paths pinned to this worktree's Chat, Control Plane and AI Core; `pytest --basetemp C:\pt\a4` on focused login, auth, cache, revocation, WebCrypto and host-composition suites: 175 passed, 7 existing deprecation warnings. Earlier common pytest temp path failed with WinError 5; the short local basetemp resolved it.
- 배포 뒤 확인할 것: compare callback `assertion_sign_ms`, `exchange_total_ms`, `identity_rpc_ms`, `sqlite_auth_*_ms`, and identity `session_revocation_authority_ms` by request ID; verify the 30s result-cache hit/expiry and immediate cross-worker logout/revoke invalidation; confirm the Worker token exchange and Control Plane calls reuse connections. No deployment performed in this task.
