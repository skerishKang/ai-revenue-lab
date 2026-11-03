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
- 재기반 후 시험: Chat 계정 삭제 25 passed, Auth flow 21 passed, Control Plane Identity 관련 30 passed, 법률 보존 기간 guard 7 passed. LoveTree 계정 삭제 16 passed, 전체 `npm test` 277 passed·35 skipped (선택 통합 환경 미설정, 기존 실행 결과).
- 배포 인수: Identity DO schema v4, Auth·Chat·LoveTree 배포, Chat D1 migration 097, LoveTree PostgreSQL 두 표, RPC secret 이름은 운영 메모에 정리했다. 배포·운영 DB 접속·실제 계정 삭제는 수행하지 않았다.
- 현재 단계: `origin/main` 18a0e4de 재기반과 필수 시험을 마쳤다. 배포·운영 DB 접속·실제 계정 삭제는 하지 않는다. PR·merge 전 최종 diff와 저장소별 배포 메모를 확인한다.
