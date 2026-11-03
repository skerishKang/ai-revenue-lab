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

# 공통 로그인 계정 탈퇴 — 진행 기록

## 범위와 기준

- `ai-revenue-lab`: `feat/shared-account-delete-261103`, 기준 `origin/main` `a8eff99d1`.
- `lovetree-4.0`: `feat/shared-account-delete-receiver-261103`, 기준 `origin/main` `d60a1fa`.
- 두 요청 브랜치는 원격에 없어 최신 `origin/main`에서 만들었다. 운영 접속·배포와 실제 계정 삭제는 하지 않았다.
- 최신 main에 공통 계정 삭제 구현이 이미 포함되어 있어 이 브랜치에서는 기존 경로를 보존하고, 실패 후 재시도 및 서명 만료 회귀시험과 Lovetree Pages 진입 경로를 보강했다.

## 코드 지도

1. **공통 계정과 세션 — Auth**: `apps/padiem-auth/worker.mjs`가 `google-account-registry`를 통해 canonical 계정 상태를 관리하고, `AuthStateObject`가 세션을 관리한다. 서명된 `/internal/account-delete/prepare`는 계정 삭제 lease를 잡고 연결된 모든 세션을 폐기한다. `/complete`는 삭제를 확정하고 해시와 시각만 남긴다. 실패하면 `/abort`로 lease를 풀며, 연결이 복구되지 않아도 5분 lease 만료 뒤 재시도할 수 있다.
2. **서비스 연결 — Control Plane Identity**: `packages/padiem-control-plane/identity_authority_durable.py`의 schema v4가 canonical subject와 `(product_id, product_user_id)` 연결을 관리한다. Chat은 `list_active_product_links_for_subject`와 `remove_product_link`를 호출한다. 마지막 연결 삭제에는 Auth 삭제 operation ID가 필요하며, 다른 제품 연결이 남으면 공통 계정은 유지된다.
3. **Chat 및 북AI**: `apps/padiem-chat/app/account_deletion.py`가 `/api/account/delete`와 `/api/account/shared-delete`를 처리한다. Chat 데이터는 D1 batch로 지우고, 서비스별 탈퇴는 Chat 연결만 해제한다. `users.provider_subject`와 `auth_account_link_cache`를 통해 공통 subject를 찾으며, 북AI subject를 세션/연결 캐시 해제 전에 읽는 #6767 경로를 유지한다. 북AI 전용 수신기는 만들지 않았다.
4. **LoveTree**: `server/index.js`가 서명된 `/internal/account/delete`를 받는다. `server/shared-account-deletion.js`가 HMAC v2, 300초 timestamp, UUID, body 서명, replay claim을 검증하고 `server/account-service.js`의 기존 `deleteTrustedSubject`로 위임한다. 기존 12개 표 트랜잭션·탈퇴 감사·미디어 폴더 정리를 재사용한다. `server/db/schema.sql`은 해시·시각 감사 표와 만료되는 요청 ID 표를 정의한다. 공개 `/api/account/delete`는 Pages allowlist에 추가했다.
5. **CGI 쇼핑몰**: `kbs261022` main의 `backend/migrations/0002_customer_auth_schema.sql`은 자체 `members`, `auth_tokens` 및 로그인 제한 표를 만들고, `0004_google_oauth.sql`은 자체 회원 표에 Google ID를 추가한다. `/auth/shared`나 PADIEM Auth 경로 사용은 확인되지 않아 공통 계정 탈퇴에서 제외한다.

## 정책 및 문구 대조

- 서비스별 탈퇴는 해당 서비스 데이터만 지우고 해당 제품 연결만 해제한다. 다른 연결이 남으면 공통 계정을 유지하고, 마지막 연결이면 Auth에서 세션을 모두 폐기한 뒤 공통 계정을 파기한다.
- 모든 서비스 탈퇴는 Chat이 연결 서비스 삭제를 요청한다. LoveTree 응답과 Chat의 트랜잭션이 모두 성공해야 마지막 연결을 제거한다. 중간 실패에는 공통 계정을 보존한다. 일부 제품 데이터가 이미 지워졌어도 남은 연결로 로그인해 재시도할 수 있다.
- 중앙 관리자 설정, Chat `platform_admin_roles`, LoveTree 제품 관리자 확인이 탈퇴 전에 실행된다. BookAI 서버 기록은 Chat 계정 트랜잭션에서 처리하며 CGI 쇼핑몰은 별도 회원 계정이다.
- Chat D1 탈퇴 기록은 `user_id_hash`, `deleted_at`만 1년 보관한다. LoveTree 기록은 subject hash와 시각만 저장한다. 서비스 요청 replay 표에는 만료되는 service ID만 기록한다.
- 도움말 `#account`, 공통 약관, LoveTree 약관의 현재 문구가 위 동작과 일치함을 확인했다. 도움말의 `PADIEM` 금지 검사는 그대로 유지했다.

## 변경 및 시험

- Chat 회귀시험: LoveTree 삭제와 연결 해제가 성공한 뒤 Chat batch가 실패해도 Chat 연결 및 공통 계정이 남고, 새 세션으로 재시도하면 마지막 연결·공통 계정 삭제가 완료되는 경우를 추가했다. 약관 문구 일치 검사도 추가했다.
- LoveTree 회귀시험: 수신 서명이 맞아도 300초 창을 벗어난 요청은 거부하고 replay ID를 점유하지 않는지 추가했다. 원격 `fix/lovetree-account-delete-pages-proxy-261103`의 `/api/account` GET 및 `/api/account/delete` POST allowlist 변경을 반영했다.
- Chat + Control Plane targeted suite: `45 passed`. `PYTHONPATH`는 이 worktree의 Chat, Control Plane, AI Core로 제한했고 `--basetemp C:\pt\a4`를 사용했다.
- Auth Node suite: `42 passed`; 잘못된 서명·만료·replay, 세션 폐기 실패 뒤 계정 연결 보존 및 재시도를 포함한다.
- LoveTree 전체 Node suite: `278 passed`, `0 failed`, `35 skipped`. PostgreSQL 테스트 DB와 relay worker 설정이 없는 환경에 의존하는 시험만 실행 불가로 보고됐다. 계정 탈퇴 및 Pages 프록시 시험은 통과했다.
- 새 migration은 필요하지 않다. `ai-revenue-lab` 최신 번호는 097이며, `097_account_deletion_audit_hash_time_only.sql`이 탈퇴 감사 형식을 정의한다. 098은 만들지 않았다. Identity schema는 v4이며 LoveTree Postgres의 탈퇴/replay 표는 기존 `schema.sql`에 있다.

## 배포 뒤 확인할 것

1. Cloudflare의 `padiem-auth`, `padiem-control-plane-identity`, `padiem-chat` Worker/service binding을 같은 릴리스 기준으로 검토한다. Identity Authority Durable Object schema v4가 준비돼 있어야 한다.
2. Chat D1 `padiem-chat-db`에서 migration 기록을 확인하고, 097이 아직 적용되지 않은 환경에만 `apps/padiem-chat/migrations/097_account_deletion_audit_hash_time_only.sql`을 적용한다. 이 작업에서 새 098 migration은 없다.
3. 환경 변수 이름과 secret 연결을 확인한다. Auth: `PADIEM_ACCOUNT_DELETE_RPC_SECRET`; Chat: `PADIEM_CHAT_ACCOUNT_DELETE_RPC_SECRET`, `PADIEM_CHAT_LOVETREE_ACCOUNT_DELETE_URL`; LoveTree API: `LOVETREE_ACCOUNT_DELETE_RPC_SECRET`, `LOVETREE_IDENTITY_RPC_URL`, `LOVETREE_IDENTITY_RPC_SECRET`. Account-delete secret 값은 Auth·Chat·LoveTree 사이에서 일치해야 한다. 값은 문서·로그에 기록하지 않는다.
4. LoveTree의 `server/db/schema.sql`을 확인하고 COM2 `lovetree-api.service`를 재배포한다. Cloudflare Pages의 Lovetree 사이트도 재배포해 `/api/account/delete` 프록시 allowlist를 반영한다.
5. 비운영 계정으로 Chat 단독 탈퇴, LoveTree 단독 탈퇴, 모든 서비스 탈퇴, 중간 서비스 오류 후 재시도, 관리자 차단, 모든 세션 폐기, hash/time 감사값을 확인한다. 실제 계정으로 시험하지 않는다.
