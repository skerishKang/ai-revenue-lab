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


## ?? Claw Queue ??? ?? ?? (??)

# Claw 작업 영수증 보존 및 계정 탈퇴 정리

## 작업 정보
- 작업 트리: `D:\PADIEM\claw-jobs-retention-261103`
- 브랜치: `feat/claw-jobs-retention-261103`
- 최신 재기반 기준: `origin/main` 165269e70c2fb4ed4f8b3276cb22bf82f35d7afc
- 작업 시작 때 동일 목적 원격 브랜치는 없었다. main #6763의 B14 만료·캡처 코드와 Claw 코드 경로는 다르다. 최신 #6767은 탈퇴 경로와 `test_queue_internal_store_rpc.py`를 수정해 같은 테스트 파일에서 두 변경을 함께 보존하고 재검증했다.

## 기존 MCP 설계와 통합 기준 비교
| 항목 | MCP 3단계(096, CGI-1 브랜치) | main의 Claw 공통 경로 |
|---|---|---|
| 저장소 | DB에 소유·상태 메타데이터, PC `%LOCALAPPDATA%\padiem-mcp-jobs`에 작업 파일 | executor `pending_dir/background-jobs`의 JSON 영수증·로그, Queue `pc-outputs` OutputStore |
| 소유 확인 | DB 행이 user/token/PC를 묶고 read/stop 접근을 확인 | 영수증의 account/node/run, 출력의 계정 해시 인덱스·Queue RPC |
| PC 출력 | 본문은 DB에 저장하지 않고 PC 파일에 저장 | 대용량 출력은 공통 PC OutputStore 파일 |
| 취소 | `pc_shell_stop`이 프로세스 트리를 멈추고 대기 디스패치를 취소 | 공통 영수증/status/output 경로에는 MCP 전용 stop 도구 없음 |
| 보존·감사 | PC 파일 30일, DB에는 명령 digest와 상태만 | OutputStore 기존 7일 TTL을 공유하고 영수증/출력 본문은 파일, 로그는 정리 건수만 |

통합 기준은 main Claw 경로다. 이미 executor와 Mesh OutputStore가 쓰는 경로이며, 별도 job 저장소와 추가 migration을 만들지 않는다. MCP 레인은 start/read/stop을 공통 영수증·출력 저장소에 연결하고, DB 소유 확인과 명령 digest 감사는 유지하며, 출력 본문을 DB에 넣지 않고 7일 TTL 및 계정 삭제 Queue RPC에 맞추면 된다.

## 보존 기간과 탈퇴
- Claw 영수증·로그와 PC 출력은 기존 OutputStore 기본값 604800초(7일) 및 `PADIEM_OUTPUT_STORE_RETENTION_SECONDS`를 공유한다. 승인 보존 초안의 90일은 본문 없는 B14 집계/캡처에만 적용된다.
- 만료 경계는 `finished_at <= now - retention`; 실행 중 작업은 보존한다. 파일만 정리하고 정리 건수만 기록한다. 실패는 0이 아닌 종료 코드다. migration 097은 추가하지 않았다.
- Chat `account_deletion.py`는 세션 폐기 후 Queue `delete_account_pc_data` RPC를 호출하고 성공한 뒤 Chat DB를 정리한다. Queue 오류 시 503으로 멈춰 Chat 기록은 보존된다.
- Queue RPC는 계정의 Claw 영수증·로그와 색인된 pc-outputs 파일을 지운 뒤 tombstone으로 재쓰기를 막고 기존 PC SQL 정리를 수행한다. Queue와 executor는 같은 `ORACLE_MESH_WORK_DIR`이 필요하며 미설정이면 RPC는 fail-closed다. 설치 스크립트는 기존 설정을 보존하거나 설치 환경에서 받는다.
- 기존 계정 인덱스 없는 pc-outputs 파일은 계정 소유를 안전하게 판별할 수 없어 탈퇴 때 계정별 제거를 하지 않는다. 다른 계정 파일은 보존하고 기존 7일 만료 정리를 따른다.

## Astra3 겹침 확인
- `feat/retention-enforce-261103` 및 `expired-purge-261103` 작업 트리를 읽기 전용으로 살폈다. 대상은 B14 집계·캡처와 `expired_purge`; 이 변경은 Claw 영수증·Queue pc-outputs다. 파일 충돌이 없으며 Astra3 작업 트리를 수정하지 않았다. main #6763 및 탈퇴 경로 #6767의 변경을 재기반으로 포함했다.

## 검증
- Queue/Claw/OutputStore 표적 시험: 55 passed.
- Claw executor 전달·출력 통합: 21 passed.
- 최신 main 재기반 후 Queue/Claw/OutputStore, executor, Chat 계정 탈퇴 회귀: 845 passed, 3 skipped, 1 failed. 유일한 실패는 로컬 `websockets` 17.4와 기존 시험의 고정 요구값 17.2 차이다. 시험과 의존성 조건은 바꾸지 않았다.
- 7일 전후 경계, 실행 중 보존, 사용자 격리, 정리 오류 종료 코드 및 Queue RPC 탈퇴 연결을 시험했다.

## Push 확인
- 최신 `origin/main` 165269e70c2fb4ed4f8b3276cb22bf82f35d7afc 위로 재기반했고, 원격 브랜치가 이전에 본 작업에서 push한 SHA 그대로인지 lease로 확인해 갱신했다.
- 구현 커밋 81133954d0463809415f780e8d08e1781ec8fe2b의 `git ls-remote` 결과가 로컬 SHA와 일치했다. PR·merge·배포는 하지 않았다.

## 2026-11-03 · Chat Claw 작업 보관기간 적용
- setup: 기존 원격 `feat/claw-jobs-retention-261103`의 두 커밋을 보존하고 최신 `origin/main` (`b0b869994`)을 merge commit `344b3db72`로 통합했다. `progress.md` 충돌은 main 기록과 기존 Claw Queue 기록을 함께 보존해 해결했다.
- map: Chat migrations에서 Claw runtime 표와 작업·run·결과 연결을 조사했다. 별도 Claw event/step log 표는 없고, `claw_task_alert`만 사용자 task 및 알림 상태가 섞여 있다. 사용자 정의·결과·권한·중복 방지 자료는 docs 표대로 분류했다.
- retention: 90일 지난 dismissed alert만 `claw_task_alert.created_at` 기준으로 표당 최대 1배치 정리한다. task 행과 active alert, PENDING/RUNNING `claw_runs`, 사용자 run history·artifact 링크는 보존한다. 출력에는 표 이름과 건수만 남긴다.
- migration: 098 `idx_claw_task_alert_retention(kind,status,created_at)`을 추가했다. 기존 inbox 인덱스는 전역 만료 범위 검색에 맞지 않는다.
- tests: retention 전용 18 passed. 전체 Chat Python Claw + retention 2,039건 중 2,037 passed, 2 failed. 실패 2건은 두 기존 scheduler source test가 `wrangler.toml`에 이미 있는 `17 3 * * *` trigger를 미등록으로 기대한다. `padiem_ai_engine_client` 경로를 추가해 worker composition test 포함 회귀를 재실행했다. 경계·active/task·PENDING/RUNNING·완료 결과·run history/artifact FK child·missing table·batch·inbox 조회·098 인덱스 적용을 확인했다.
- test-environment: 기존 Claw run-history UI의 locale guard가 앱 주석의 한국어를 거부해 주석을 영어로 정리했다. Node 출력 재시험에는 `PYTHONUTF8=1`을 지정했다.
- docs: `docs/operations/RETENTION_ENFORCE_20261103.md`에 Claw (a)/(b) 분류와 배포 시 migration 적용 항목을 추가했다.
- delivery: 운영 스키마에는 migration 098 적용이 필요하다. PR·병합·배포는 수행하지 않고 지정 브랜치에 commit/push만 한다.

## 2026-11-03 · scheduler cron allowlist 시험 정합화
- baseline: detached `origin/main` `d5caa3354`에서 기존 scheduler 시험 2개를 실행해 둘 다 실패함을 재현했다. 두 실패 모두 checked-in `wrangler.toml`의 `17 3 * * *` retention cron을 “cron 미등록”으로 단정하던 기대값 때문이다.
- merge: 최신 `origin/main` `d5caa3354`를 `feat/claw-jobs-retention-261103`에 merge했다.
- fix: scheduler 시험 두 곳에서 TOML을 파싱해 `triggers`가 `crons=["17 3 * * *"]` 하나만 포함할 때만 통과하도록 allowlist로 바꿨다. 추가/변경 cron은 실패한다. 기능과 cron 설정은 바꾸지 않았다.
- verify: 두 대상 시험 2 passed. 최신 main merge 후 전체 Chat Python Claw + retention 2,039 passed.
