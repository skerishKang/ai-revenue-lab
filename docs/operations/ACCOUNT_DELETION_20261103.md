# 공통 로그인 계정 탈퇴 구현·운영 반영 메모 (2026-11-03)

이 문서는 기존 Chat 서비스 데이터 삭제 전수표와 공통 로그인 계정 삭제 연결을 함께 기록한다.
Chat의 서비스별 탈퇴와 전체 서비스 탈퇴는 설정 > 계정에서 제공하며,
`apps/padiem-chat/app/account_deletion.py`가 요청을 조정한다.

## 0. Chat 서비스 데이터 삭제 경로 계약

- 로그인 세션 필수. SameOriginGuardMiddleware(#3476)가 쿠키 붙은 POST의 출처를 검사한다.
- 본문 `{"confirm": "<본인 이메일>"}`가 저장된 계정 이메일과 정확히(대소문자까지) 일치할 때만 실행된다. 이것이 "복구 불가 파괴는 실행 전 한 번 확인"이다.
- Cloudflare D1은 Chat DB의 사용자 행, PC 테이블, Mesh presence를 하나의 db.batch 트랜잭션으로 처리한다. COM2는 현재 세션 종료 → 큐 DB의 PC 테이블과 Mesh presence 정리 → Chat DB batch 순서다. 큐 정리가 실패하면 account_delete_queue_unavailable을 돌려주고 Chat 데이터 배치를 시작하지 않는다. Chat batch가 실패해도 큐 정리는 멱등이므로 재로그인 후 다시 시도하면 완료할 수 있다.
- 실행 순서: 출처 검사 → 본문 확인 → 이메일 일치 → 관리자 차단 → 현재 세션 종료 → COM2일 때 큐 정리 → 경로별 DB 배치(users 행은 마지막) → 계정 전체 canonical 세션 해제(#5441 헬퍼, best-effort) → 검증 캐시·PC 스코프 캐시 무효화 → R2 객체·COM2 파일 레인 접두사 정리(2026-11-11, best-effort) → private, no-store 응답 + 세션 쿠키 삭제.
- 관리자 차단: 세션 이메일이 중앙 관리자 이메일(`PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL`, `app_factory`가 state에 넣은 값)과 일치하거나 `platform_admin_roles` 행을 가진 계정은 403 `account_delete_admin_blocked`.
- 남기는 기록은 최소: `account_deletion_audit`(마이그레이션 092)에 탈퇴 시각과 사용자 id의 SHA-256 해시 1행. 이메일·이름·subject 저장 금지(시험이 응답·행에 `@` 부재를 단정).

Cloudflare D1 경로에서는 아래 PC 테이블이 Chat D1 안에 있다. COM2 호스트에서는 같은 접근이 queue_store_proxy를 거쳐 padiem-mesh-queue의 PC 큐 DB로 전달된다. 탈퇴 경로도 저장 위치에 맞춰 정리한다.

## 0.1 공통 로그인 연결 해제

- 대상 판정(2026-11-11): `provider_subject`의 `shared:` 표식만으로는 소셜 로그인으로 먼저 만들어진 계정(`history.upsert_google_user`는 원문 subject를 저장)이 공통 계정 흐름을 건너뛰었다. 이제 표식이 없어도 identity shadow 투영(007, `product_user_id` 역방향)과 계정 링크 캐시(088)에서 canonical subject를 역방향 조회하고, 해석되면 서비스별·전체 탈퇴 모두 같은 연결 해제·준비·세션 폐기 흐름을 실행한다. 역방향 해석 subject에 활성 연결이 없으면(서비스별 탈퇴) 지울 링크가 없는 것이므로 데이터 삭제는 계속 진행된다. 어느 근거로도 subject를 찾지 못한 계정의 공통 계정은 여전히 닿지 않는다(3장 남는 항목).
- 서비스별 탈퇴: 해당 서비스의 데이터를 먼저 삭제한 뒤 Control Plane Identity에서 그 제품 연결만 해제한다. 다른 활성 연결이 남으면 공통 계정은 유지된다.
- 마지막 연결: Auth의 서명 검증된 prepare가 계정별 refresh 세션 색인을 이용해 모든 세션을 폐기하고 5분 잠금을 건다. Control Plane은 직렬화된 연결 상태를 다시 읽어 Auth 준비 식별자가 없으면 마지막 연결을 해제하지 않는다. 준비가 확인되면 연결 해제 트랜잭션이 마지막 subject·제품 링크를 파기하고 해시·시각 감사 행을 남긴 뒤, Auth complete가 Google 계정 매핑을 제거한다. 연결 해제가 실패하면 Auth abort로 잠금을 풀어 매핑을 보존하고 다시 시도할 수 있다.
- 전체 탈퇴: Chat 설정 > 계정에서 요청한다. LoveTree에 서명된 삭제 RPC를 보내고, Chat·Claw 및 계정에 저장된 북AI 데이터를 삭제한 뒤 LoveTree 연결과 Chat 연결을 정리한다. CGI 쇼핑몰은 별도 계정으로 이 경로에서 제외된다.
- 보안 경계: Chat 중앙 관리자 이메일·`platform_admin_roles`와 LoveTree 제품 관리자 역할을 차단한다. 서비스 RPC는 HMAC 서명·요청 시각·UUID 재생 방지·엄격한 계약 검증을 사용한다.
- 이력: Chat·Auth·Control Plane·LoveTree에 사용자 식별자 원문 없이 SHA-256 해시와 시각만 남기며 1년 뒤 제거한다.


## 1. 왜 CASCADE에 기대지 않는가 (foreign_keys 확인 결과)

| 경로 | foreign_keys 상태 | 근거 |
|---|---|---|
| Production D1 | 강제하지 않음 | `apps/padiem-chat/app/local_cpython.py:229` 주석("production D1 never enforces it") |
| 로컬 CPython 호스트 | 일부러 켜지 않음(production 동등성) | `local_cpython.py:229-236` |
| 로컬 D1 에뮬레이터(`d1_sqlite.py`) | 켬 | `apps/padiem-chat/app/d1_sqlite.py:39` |
| 마이그레이션 001 | 스크립트 안에 `PRAGMA foreign_keys = ON` 포함(연결 상태를 바꿈) | `migrations/001_auth_history.sql:5` |

결론: ON DELETE CASCADE 선언은 문서일 뿐 실행 보장이 없으므로, 재생 방지
기록인 oracle_mesh_dispatch를 뺀 사용자 테이블을 명시 삭제한다. dispatch 행은
지우지 않고 계정을 가리키는 칸만 덮어쓴다(2.4절). D1은 PC 테이블과
presence까지 Chat batch에서 처리하고, COM2는 큐 DB를 먼저 정리한 뒤 Chat batch를
실행한다. 각 DB 안에서는 자식→부모 순서이며 users 행은 Chat batch의 마지막이다.

## 2. 사용자 데이터 테이블 전수 조사 (migrations 001~106)

총 표 중 사용자 키(`user_id`·`member_id`·`owner_id`·`product_user_id`) 또는 subject 계열 열(`subject`·`canonical_subject_id`·`provider_subject`·`approved_by`)을 가진 살아있는 표는 71개다(2026-11-11 재조사). 그중 69개는 경로가 지우고, oracle_mesh_dispatch는 재생 방지에 필요한 행만 남기고 계정 식별 칸은 지운다(2.4절), users와 bookai_records는 각각 배치의 마지막 문과 subject 문으로 지운다.
조사 방법: 106개 마이그레이션 전체에서 `CREATE TABLE` 본문과 `ALTER TABLE ADD COLUMN`의 사용자 키 컬럼을 추출. `_next`·
`_rebuilt_*` 그림자 테이블은 각 마이그레이션이 끝나기 전에 rename/drop되므로
살아있는 이름만 표에 넣었다(060·061·063·068·069·077·081·083 끝의
`ALTER TABLE ... RENAME` 확인). 이 대조는 매 실행마다 다시 계산되는 가드 시험
(`apps/padiem-chat/tests/test_account_deletion_survey_guard_261111.py`)로 강제된다.
새 사용자 키 표가 생기면 삭제 목록에 넣거나 예외 목록에 이유를 적어야 시험이 통과한다.

### 2.1 user_id 조건으로 지우는 표 (55)

| 테이블 | 마이그레이션 | 지우는 방식 |
|---|---|---|
| conversations | 001 | FK CASCADE 선언, 명시 삭제 |
| projects | 002 | FK CASCADE 선언, 명시 삭제 |
| project_files | 003(083 리빌드) | FK 선언에 CASCADE 없음 → 명시 삭제 |
| saved_outputs | 004 | FK CASCADE 선언, 명시 삭제 |
| orchestration_continuations | 006 | FK 없음 → 명시 삭제 |
| orchestration_decisions | 006 | FK 없음 → 명시 삭제 |
| password_credentials | 012 | FK CASCADE 선언, 명시 삭제 |
| claw_run_history | 009 | FK 없음 → 명시 삭제 |
| claw_document_metadata | 008(060 리빌드, 080 user_id 추가·080a 백필) | FK 없음 → `user_id = ?` 명시 삭제 |
| claw_approved_memory | 011 | FK 없음 → 명시 삭제 |
| claw_approval_handoff | 016 | FK 없음 → 명시 삭제 |
| claw_local_task_correlation | 020 | FK 없음 → 명시 삭제 |
| b66_saved_quote_skill | 021 | FK CASCADE 선언, 명시 삭제 |
| b66_quote_asset | 022(061 리빌드) | FK CASCADE 선언, 명시 삭제 |
| b66_company_profile | 023 | FK CASCADE 선언, 명시 삭제 |
| b66_quote_history | 025 | FK CASCADE 선언, 명시 삭제 |
| claw_conversation_artifact_index | 026(060 리빌드) | FK CASCADE 선언, 명시 삭제 |
| b66_template_source | 027(060 리빌드) | FK CASCADE 선언, 명시 삭제 |
| b66_guided_draft | 028 | FK CASCADE 선언, 명시 삭제 |
| claw_web_xlsx_selections | 029(081 리빌드) | FK 없음 → 명시 삭제 |
| claw_web_xlsx_p01_requests | 030 | FK 없음 → 명시 삭제 |
| claw_web_xlsx_p01_decision_receipts | 031 | FK 없음 → 명시 삭제 |
| claw_web_xlsx_quote_edit_receipts | 032 | FK 없음 → 명시 삭제 |
| claw_web_xlsx_quote_write_decisions | 033 | FK 없음 → 명시 삭제 |
| claw_web_xlsx_quote_write_pauses | 034 | FK 없음 → 명시 삭제 |
| b66_saved_skill_candidate | 035 | FK CASCADE 선언, 명시 삭제 |
| claw_artifact_delivery_receipts | 036 | FK 없음 → 명시 삭제 |
| b66_memberships | 037 | FK CASCADE 선언, 명시 삭제(037 트리거가 만든 행 포함) |
| b66_membership_audit | 037 | FK CASCADE 선언, 명시 삭제 |
| b66_signup_alert_outbox | 037 | FK CASCADE 선언, 명시 삭제(트리거 생성 행 포함) |
| b66_signup_alert_delivery | 037 | FK CASCADE 선언, 명시 삭제 |
| b66_member_inquiries | 038(051 리빌드) | FK CASCADE 선언, 명시 삭제 |
| claw_coding_conversation_grant | 043 | FK 없음 → 명시 삭제 |
| b66_ai_conversation | 041 | FK CASCADE 선언, 명시 삭제 |
| b66_ai_turn_attempt | 044 | FK CASCADE 선언, 명시 삭제 |
| b66_guided_transcript | 045 | FK CASCADE 선언, 명시 삭제 |
| claw_github_oauth_states | 046 | FK CASCADE 선언, 명시 삭제 |
| claw_github_connections | 046 | FK CASCADE 선언, 명시 삭제 |
| platform_admin_roles | 052 | FK CASCADE 선언, 명시 삭제(관리자는 애초에 경로가 거부) |
| chat_custom_provider_credentials | 053 | FK CASCADE 선언, 명시 삭제 — BYOK 키 행 |
| claw_pc_device_selection | 054 | FK CASCADE 선언, 명시 삭제 |
| claw_meetings | 055 | FK CASCADE 선언, 명시 삭제 |
| claw_meeting_artifacts | 056 | FK CASCADE 선언, 명시 삭제 |
| claw_meeting_actions | 057 | FK CASCADE 선언, 명시 삭제 |
| padiem_account_model_selections | 059 | FK CASCADE 선언, 명시 삭제 |
| password_reset_tokens | 062 | FK CASCADE 선언, 명시 삭제 |
| password_reset_audit | 062 | FK 없음(user_id NULL 가능) → 명시 삭제 |
| document_convert_jobs | 066 | FK CASCADE 선언, 명시 삭제 |
| document_convert_items | 066 | FK CASCADE 선언, 명시 삭제 |
| pc_pairing_codes | 072 | FK 없음 → 명시 삭제 |
| pc_install_tokens | 093 | 토큰 해시와 user_id만 저장 → 명시 삭제 |
| pc_device_links | 072 | FK 없음 → 명시 삭제 |
| padiem_pc_delegations | 084 | FK CASCADE 선언, 명시 삭제 |
| padiem_mcp_tokens | 085 | FK CASCADE 선언, 명시 삭제 |
| padiem_mcp_approvals | 085 | FK CASCADE 선언, 명시 삭제 |
| padiem_mcp_audit | 085 | FK CASCADE 선언, 명시 삭제 |
| padiem_mcp_oauth_codes | 095 | FK 없음 → 명시 삭제 |
| shared_session_revoke_pending | 106 | FK 없음 → 명시 삭제(계정이 사라진 뒤 의미 없는 재시도 표식) |

### 2.2 다른 키로 지우는 표

| 테이블 | 키 | 마이그레이션 | 지우는 방식 |
|---|---|---|---|
| messages | `conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)` | 001 | FK(messages→conversations) CASCADE 선언, 명시 삭제 |
| claw_task_alert | `member_id = ?` | 010 | FK 없음 → 명시 삭제(member_id=''=전체 경보 행은 워크스페이스 공용이라 남음) |
| claw_push_subscription | `member_id = ?` | 065 | FK 없음 → 명시 삭제 |
| padiem_calendar_work_log | `owner_id = ?` | 013 | FK 없음(owner_id="owner user id" 주석) → 명시 삭제 |
| padiem_calendar_appointment | `owner_id = ?` | 013 | 같음 |
| lovetree_login_handoffs | `pending_user_id = ?` | 076 | FK 선언(CASCADE 미강제) → 명시 삭제(일회용 로그인 근거가 계정보다 오래 남지 않는다) |
| auth_validation_cache | `product_user_id = ?` | 087 | FK 없음 → 명시 삭제 + 런타무 무효화 헬퍼 |
| auth_account_link_cache | `product_user_id = ?` | 088 | FK 없음 → 명시 삭제 |
| control_plane_identity_shadow | `product_user_id = ?` | 007 | FK CASCADE 선언, 명시 삭제 |
| claw_rules | `canonical_subject_id = ?`(공통 로그인 subject) | 018(019 열 추가) | 명시 삭제 — 자동화 규칙은 워크스페이스 소유자만 만들 수 있어 subject가 곧 소유자다. 019 이전 생성 행의 canonical_subject_id는 NULL이라 subject 근거가 없고 남는다(3장 잔여) |
| claw_runs | `rule_id IN (SELECT rule_id FROM claw_rules WHERE canonical_subject_id = ?)` | 018 | 규칙 체인 명시 삭제(claw_rules보다 먼저) |
| claw_occurrences | `run_id IN (SELECT run_id FROM claw_runs WHERE rule_id IN (…))` | 018 | 규칙 체인 명시 삭제(가장 먼저) |
| claw_proposals | 규칙 체인 + `approved_by = ?` | 018 | 규칙 체인 명시 삭제 + 이 계정이 승인한 남의 워크스페이스 제안도 삭제 |

### 2.3 마지막에 지우는 행과 남기는 행

| 대상 | 방식 |
|---|---|
| users | `DELETE FROM users WHERE id = ?` — 배치의 마지막 문 |
| account_deletion_audit | 마이그레이션 092. 같은 배치에서 `INSERT` 1행(시각 + 사용자 id SHA-256 해시) |
| oracle_mesh_dispatch | 행은 남긴다. 같은 배치에서 먼저 `state`/`termination`을 정리하고, `user_id`·`account_ref`·`workspace_ref`·`device_id`·`binding_ref`·`node_ref`·`root_ref`를 삭제 1회용 무작위 `deleted:<32hex>` 토큰으로, `path_relative`·`file_path`를 `deleted`로 덮고 `evidence_ref`·`command_text`를 NULL로 만든다(2.4절) |
| bookai_records | 공통 로그인 subject로 지운다. 배치 전에 `users.provider_subject`(공유 로그인 계정은 `'shared:'+subject`, `history.upsert_shared_user`)와 계정 링크 캐시(`auth_account_link_cache.owner_id`)를 읽어 `DELETE FROM bookai_records WHERE subject = ?`를 같은 배치에 넣는다 |

### 2.4 탈퇴 뒤 남는 oracle_mesh_dispatch 행의 칸 분류 (2026-11-03 CTO 결정)

행은 남기되 사람을 가리키는 값은 되돌릴 수 없게 지운다. 구현은
`pc_device_pairing_store.oracle_mesh_dispatch_identity_cleanup_statements`이며,
D1 경로는 Chat batch 안에서, COM2 경로는 큐 DB 정리
(`D1PcPairingStore.delete_account_pc_data`)에서 같은 문장을 실행한다.

| 분류 | 칸 | 탈퇴 시 처리 |
|---|---|---|
| 재생 방지에 필요 | `dispatch_id`, `run_id`, `tool_request_ref`, `tool_call_ref`, `request_fingerprint`, `nonce_sha256`, `claimed_until`, `state`, `result_sha256`, `result_bytes`, `termination`, `exit_code`, `created_at`, `expires_at` | 그대로 둔다. 047·063의 고유 인덱스가 같은 run·같은 도구 호출의 재등록을 계속 거부한다 |
| 사람을 가리킴 | `user_id`, `account_ref`, `workspace_ref`, `device_id`, `binding_ref`, `node_ref`, `root_ref` | 삭제 1회당 무작위 128비트 `deleted:<hex>` 토큰 하나로 덮는다. 원래 id로 재계산할 수 없고 다른 계정과 겹치지 않는다 |
| 명령·경로 본문 | `command_text`, `evidence_ref` | NULL |
| 경로(NOT NULL) | `path_relative`, `file_path` | `deleted` 고정값 |
| 실행 상관 참조 | `command_id`, `request_id`, `revision_ref` | 그대로 둔다(계정을 가리키지 않는 상관값) |

아직 실행되지 않은 `pending` 행은 실행 대상에서 뺀다. executor가 한 번도 받지
않은 행(`nonce_sha256 IS NULL`)은 `state='failed'`, `termination='cancelled'`로
바꿔 poll이 건네지 않게 하고, 이미 받아 간 행(`nonce_sha256` 있음)은
`state='pending'`을 유지한 채 `termination='cancelled'`만 써서 결과 제출이 기존
nonce 검사로 정상 착지하게 한다(#5895 취소와 같은 규칙).

## 3. 이번에 지우지 않은 것과 별도 운영 항목

| 대상 | 상태 | 다음 단계 제안 |
|---|---|---|
| mesh_device_drives | 사용자 키가 없는 PC 단위 드라이브 목록. PC를 공유할 수 있어 계정 탈퇴에서 특정 사용자 행만 안전하게 고를 수 없음 | 장치 제거 때 함께 정리할지 별도 결정 |
| 공통 로그인 계정(Control Plane identity, 타 앱 공유) | 구현됨: 서비스 연결을 개별 해제하고 마지막 연결이면 Auth 세션·CP subject·Google 계정 매핑을 파기한다. 전체 탈퇴는 러브트리 삭제 요청 후 Chat·북AI 데이터와 연결을 정리한다. | 배포 전 운영 반영 필요: CP DO schema v4, Auth/Chat Worker, LoveTree API·PostgreSQL schema 및 비밀 설정 |
| B14 원장 | 미포함 | B14 원장의 사용자 식별자 조사 후 별도 단계 |
| R2 파일 객체(대화 첨부·프로젝트 원본·생성문서) | **부분 구현 (2026-11-11)** — 배치 전 `claw_document_metadata`·`b66_quote_asset`·`b66_template_source`에서 `user_id = ?`로 객체 키를 수집하고(`account_object_cleanup.collect_account_object_keys`), 배치 뒤 키 단위 best-effort 삭제한다. 배치가 실패하면 수집만 되고 삭제는 없다(재시도 시 다시 수집) | 남는 것: 080 이전 생성·080a 백필이 user_id를 못 채운 객체(user_id NULL), 키 수집 한도(1,000) 초과분, COM2 호스트 로컬 tus 임시 업로드. 객체 TTL 정책(`workspace_storage.py` 생성문서 30일 TTL은 참조 행 기준)은 별도 결정 |
| COM2 파일 레인(apps/padiem-file-lane) | **구현됨 (2026-11-11)** — 레인이 소유자 1명분 파일을 단일 디렉터리(sha256(user_id) 접두사)로 보관하므로, 서명된 티켓 1장으로 `/users/purge`가 그 접두사 전체를 지운다. Chat은 배치 뒤 같은 티켓 발행점(`FileLaneClient.purge_user`)에서 요청하고, 레인 미설정 배포에서는 건너뛴다 | 남는 것: 레인이 구성되지 않은 배포의 기존 파일, R2 offsite 백업 사본(일일 7·주간 4세대 순환, 원본 삭제 뒤 최대 28일) |
| 서버 백업(COM2 로컬 Chat·큐, Cloudflare R2 offsite) | Chat·큐 로컬 스냅샷은 코드 기준 일일 7세대, 설치 상태는 미확인. R2 외부 백업은 일일 7세대·주간 4세대이며 원본 삭제 뒤 백업 사본은 최대 28일 안에 순환 삭제됨 | 보존 기간은 공통 방침에 정함. 운영 반영 필요: 로컬 백업 작업 설치 상태와 실제 R2 설정 확인(`deploy/host-com2/offsite-backup/`) |
| 이용자 PC의 `.padiem-backup` | 이용자 PC에 남음(경로가 닿지 않는 영역) | 탈퇴 안내 문구로 이용자가 직접 지우도록 안내(이미 화면 설명에 포함) |
| oracle_mesh_dispatch | **해결됨 (2026-11-03)** — 행은 재생 방지(047)를 위해 남기고, `user_id`·`account_ref`·기기·경로·명령 본문 등 사람을 가리키는 칸은 지운다(2.4절). 남은 행으로는 누구의 것인지 알 수 없다 | 공통 방침의 서비스 오류·감사 로그 90일 상한과 실제 분류를 대조해야 한다. 현재 `expired_purge.py`는 이 표를 제외해 만료 행이 삭제되지 않으므로 정리 경로 반영이 필요하다. 이번 변경에서 운영은 바꾸지 않았다. |
| bookai_records(082) | **해결됨 (2026-11-03)** — 매핑은 이미 있었다: 공유 로그인으로 만든 Chat 계정은 `provider_subject='shared:'+subject`로 저장된다(`history.upsert_shared_user`). 1단계가 이 매핑을 못 본 이유는 세션 해제가 링크 캐시 행을 먼저 지우기 때문이며, 이제 배치 전에 읽는다. 매핑이 없는 계정(구글 단독 로그인)은 지울 subject가 없어 그대로 남는다 | 남은 것: 기기에만 저장된 북AI 기록(브라우저 저장소)은 서버가 지울 수 없다 — 탈퇴 안내 문구로 이용자가 지운다 |
| MeshCentral 장치·에이전트 | Chat/COM2 큐 DB의 사용자 연결 행은 지워짐. presence는 탈퇴 사용자만 제거하고 남은 소유자가 없으면 행 삭제 | 운영 영역: 장치 문서·에이전트 제거는 별도 절차 |

## 4. 법률 초안 갱신 결과

`docs/legal/drafts/`의 공통 약관·개인정보처리방침과 Chat/Claw·북AI·러브트리·CGI 부록을
이 브랜치에서 실제 구현에 맞춰 수정했다. 공통 로그인 계정은 Chat 설정 > 계정의 전체 서비스
탈퇴 경로에서 삭제 요청할 수 있고, 서비스별 탈퇴는 해당 서비스 연결만 해제한다. 마지막
연결 해제 때 공통 계정과 세션을 파기한다. CGI 쇼핑몰은 공통 계정과 연결되지 않으며 별도
탈퇴 경로를 따른다. 보존 기록은 사용자 식별자의 SHA-256 해시와 시각만 1년이다.

## 5. 시험

apps/padiem-chat/tests/test_account_deletion_261103.py — 31건:

- (a) 정상 탈퇴: 표의 모든 테이블에서 그 사용자 행 0, 다른 사용자 행은 삭제 전 스냅샷과 동일. 사용자 1명당 표의 모든 테이블에 1행을 넣고 시작한다(platform_admin_roles는 권한 표식이라 제외).
- (b) 이메일 불일치 → 400, 아무것도 지워지지 않음
- (c) 로그인 없음 → 401, 다른 출처 Origin → 403(출처 검사)
- (d) 중간 실패(테이블 1개 제거) → 503 + 전체 롤백(스냅샷 대비 동일)
- (e) 탈퇴 뒤 옛 쿠키 → 401, /api/auth/status 미인증
- (f) 중앙 관리자 이메일·platform_admin_roles 보유 계정 → 403
- (g) 마이그레이션 092 재적용(멱등)
- (h) Mesh 기기 소유자 목록에서 탈퇴자만 제거하고 다른 계정 참조 보존
- (i) COM2에서는 큐 정리 후 Chat batch가 실행되고 큐 실패 시 Chat DB 데이터는 유지
- (j) oracle_mesh_dispatch 재생 방지 행은 탈퇴 뒤에도 남고, 원래 `user_id`·`account_ref`·기기·경로·명령 본문은 0건이다. 같은 run 재등록은 고유 인덱스가 계속 거부하고, 미실행 pending 행은 쌓이지 않으며, 이미 넘겨진 행의 결과 제출은 nonce로 착지한다
- (k) Chat 연결 해제는 LoveTree 연결을 유지하고 Auth 준비를 시작하지 않는다.
- (l) 마지막 Chat 연결 해제는 Auth 세션 폐기 → CP 연결·subject 파기 → Auth 매핑 삭제 순으로 진행한다.
- (m) 전체 탈퇴는 서명된 LoveTree 삭제 요청을 먼저 보내고 마지막 연결을 정리한다.
- (n) LoveTree RPC 실패 때 Chat 행과 두 공통 연결은 유지한다.
- (o) CP 해제 실패 때 공통 연결을 보존하고 Auth 잠금을 해제해 재시도할 수 있다.
- (p) 탈퇴 감사 기록은 해시·시각 두 열만 남기며 365일이 지난 행을 제거한다.
- (q) 설정·도움말에 서비스별·전체 서비스 탈퇴 경로가 있고 Help의 브랜드 표기 제한을 유지한다.

apps/padiem-chat/tests/test_account_deletion_survey_guard_261111.py — 6건(2026-11-11 가드):

- 마이그레이션 전수 조사를 매 실행마다 다시 계산해, 살아있는 사용자 키·subject 키 표가 삭제 목록이나 `_DELETION_EXCEPTIONS`(이유 포함)에 없으면 실패한다.
- 운영 문서 2장이 지운다고 적은 표를 코드가 지우지 않으면 실패하고, 코드가 지우는 표가 문서에 없어도 실패한다(양방향).
- 삭제 목록이 스키마에 없는 표·키 컬럼을 가리키면 실패한다.
- subject 키 문장이 claw 규칙 체인(runs·occurrences·proposals)과 북AI 기록을 실제로 지우고 다른 subject의 행을 남기는지 단언한다.

apps/padiem-chat/tests/test_account_deletion_object_cleanup_261111.py — 8건(2026-11-11 역방향 판정·객체 정리):

- 소셜 로그인 선행 계정(원문 provider_subject)이 shadow 역방향 조회로 공통 흐름(prepare→연결 해제→complete)을 실행하고 subject 표(claw 체인·북AI)까지 지운다.
- 역방향 근거가 전혀 없는 계정은 공통 흐름 없이 데이터 삭제를 진행한다.
- 역방향 해석 subject에 활성 연결이 없으면(서비스별 탈퇴) 데이터 삭제는 계속된다.
- 배치 실패 때 R2 삭제도 파일 레인 정리도 일어나지 않고, 롤백 뒤 수집 행이 남는다.
- 파일 레인 실패·미설정은 탈퇴를 실패시키지 않는다.
- 서명된 내부 삭제 RPC(/internal/account-delete)도 같은 객체·레인 정리를 실행한다.

apps/padiem-file-lane/tests/test_file_lane.py — `/users/purge` 3건(2026-11-11):

- 소유자 디렉터리 전체를 지우고 다른 소유자 파일을 남긴다.
- 티켓 없음·변조 티켓 → 401.
- 없는 소유자는 0카운트 정상 응답.

스키마 드리프트 방지 시험이 포함되어 있다: 경로가 지우는 표의 테이블·키 컬럼이
실제 스키마에 존재하지 않으면 수집 시점에 실패한다. `pc_install_tokens`도 사용자
키 목록에 명시되었는지 단언하므로 이 표의 삭제 누락도 실패한다.

실행(이 저장소에서 확인한 명령):

큐 RPC와 큐 서비스의 삭제 경로는 apps/padiem-mesh-queue/tests 전체를 실행한다.

```bash
cd apps/padiem-chat
PYTHONPATH="../../packages/padiem-control-plane;../../packages/padiem-ai-core;../padiem-ai-engine/clients/python;../korean-ai-code-agent/src" \
  python -m pytest tests/test_account_deletion_261103.py \
    tests/test_5225_logout_session_revocation.py tests/test_5434_password_change.py \
    tests/test_5441_password_reset.py tests/test_5441_password_reset_mail_credential.py \
    tests/test_6446_account_isolation_sweep.py -q
# 69 passed
```


## 6. 운영 반영 목록

이 브랜치에서는 운영 DB·Worker에 적용하지 않는다. 승인된 배포 작업에서 다음 항목을 반영한다.

| 대상 | 배포·스키마 |
|---|---|
| Control Plane Identity | `padiem-control-plane-identity`, Identity Durable Object schema v4, ingress secret 이름 `PADIEM_IDENTITY_RPC_INGRESS_SECRET` |
| 공통 Auth | `padiem-auth` Worker와 `AuthStateObject`, secret 이름 `PADIEM_ACCOUNT_DELETE_RPC_SECRET` |
| Chat | Chat Worker, D1 migration 097, `PADIEM_CHAT_ACCOUNT_DELETE_RPC_SECRET`, URL 변수 `PADIEM_CHAT_LOVETREE_ACCOUNT_DELETE_URL` |
| LoveTree | COM2 LoveTree API, PostgreSQL의 `lovetree_account_deletions` 및 `lovetree_account_delete_rpc_requests`; 호스트 변수 이름 `LOVETREE_ACCOUNT_DELETE_RPC_SECRET`, `LOVETREE_IDENTITY_RPC_URL`, `LOVETREE_IDENTITY_RPC_SECRET` |

비밀 값은 저장소나 PR에 넣지 않고 배포 비밀 관리 절차로 주입한다. 순서는 PostgreSQL schema 준비,
Identity/Auth 배포와 내부 경로 확인, LoveTree 수신기 배포, Chat D1 migration 097 및 Chat Worker
배포로 잡는다. 배포 후 비운영 계정에서 다른 연결 유지·마지막 연결 파기·전체 탈퇴·관리자 차단·
실패 뒤 재시도를 확인한다.
