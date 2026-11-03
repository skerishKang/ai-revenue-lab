# Chat 계정 탈퇴 1단계 설계·근거 (2026-11-03, #6659 3번)

범위: 로그인한 이용자가 자기 PADIEM Chat 계정과 Chat DB 안의 자기 데이터를
스스로 지우는 경로. 구현: `POST /api/account/delete`
(`apps/padiem-chat/app/account_deletion.py`), 화면: 설정 > 계정 탈퇴.

## 0. 경로 계약

- 로그인 세션 필수. SameOriginGuardMiddleware(#3476)가 쿠키 붙은 POST의 출처를 검사한다.
- 본문 `{"confirm": "<본인 이메일>"}`가 저장된 계정 이메일과 정확히(대소문자까지) 일치할 때만 실행된다. 이것이 "복구 불가 파괴는 실행 전 한 번 확인"이다.
- Cloudflare D1은 Chat DB의 사용자 행, PC 테이블, Mesh presence를 하나의 db.batch 트랜잭션으로 처리한다. COM2는 현재 세션 종료 → 큐 DB의 PC 테이블과 Mesh presence 정리 → Chat DB batch 순서다. 큐 정리가 실패하면 account_delete_queue_unavailable을 돌려주고 Chat 데이터 배치를 시작하지 않는다. Chat batch가 실패해도 큐 정리는 멱등이므로 재로그인 후 다시 시도하면 완료할 수 있다.
- 실행 순서: 출처 검사 → 본문 확인 → 이메일 일치 → 관리자 차단 → 현재 세션 종료 → COM2일 때 큐 정리 → 경로별 DB 배치(users 행은 마지막) → 계정 전체 canonical 세션 해제(#5441 헬퍼, best-effort) → 검증 캐시·PC 스코프 캐시 무효화 → private, no-store 응답 + 세션 쿠키 삭제.
- 관리자 차단: 세션 이메일이 중앙 관리자 이메일(`PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL`, `app_factory`가 state에 넣은 값)과 일치하거나 `platform_admin_roles` 행을 가진 계정은 403 `account_delete_admin_blocked`.
- 남기는 기록은 최소: `account_deletion_audit`(마이그레이션 092)에 탈퇴 시각과 사용자 id의 SHA-256 해시 1행. 이메일·이름·subject 저장 금지(시험이 응답·행에 `@` 부재를 단정).

Cloudflare D1 경로에서는 아래 PC 테이블이 Chat D1 안에 있다. COM2 호스트에서는 같은 접근이 queue_store_proxy를 거쳐 padiem-mesh-queue의 PC 큐 DB로 전달된다. 탈퇴 경로도 저장 위치에 맞춰 정리한다.

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

## 2. 사용자 데이터 테이블 전수 조사 (migrations 001~093)

총 106개 테이블 중 사용자 키를 가진 살아있는 테이블은 63개다. 그중 62개는 경로가 지우고, oracle_mesh_dispatch는 재생 방지에 필요한 행만 남기고 계정 식별 칸은 지운다(2.4절).
조사 방법: 93개 마이그레이션 전체에서 `CREATE TABLE` 본문의 사용자 키 컬럼
(`user_id`·`member_id`·`owner_id`·`product_user_id`)을 추출. `_next`·
`_rebuilt_*` 그림자 테이블은 각 마이그레이션이 끝나기 전에 rename/drop되므로
살아있는 이름만 표에 넣었다(060·061·063·068·069·077·081·083 끝의
`ALTER TABLE ... RENAME` 확인).

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

### 2.2 다른 키로 지우는 표

| 테이블 | 키 | 마이그레이션 | 지우는 방식 |
|---|---|---|---|
| messages | `conversation_id IN (SELECT id FROM conversations WHERE user_id = ?)` | 001 | FK(messages→conversations) CASCADE 선언, 명시 삭제 |
| claw_task_alert | `member_id = ?` | 010 | FK 없음 → 명시 삭제(member_id=''=전체 경보 행은 워크스페이스 공용이라 남음) |
| claw_push_subscription | `member_id = ?` | 065 | FK 없음 → 명시 삭제 |
| padiem_calendar_work_log | `owner_id = ?` | 013 | FK 없음(owner_id="owner user id" 주석) → 명시 삭제 |
| padiem_calendar_appointment | `owner_id = ?` | 013 | 같음 |
| auth_validation_cache | `product_user_id = ?` | 087 | FK 없음 → 명시 삭제 + 런타무 무효화 헬퍼 |
| auth_account_link_cache | `product_user_id = ?` | 088 | FK 없음 → 명시 삭제 |

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

## 3. 이번에 지우지 않은 것과 다음 단계 제안

| 대상 | 상태 | 다음 단계 제안 |
|---|---|---|
| mesh_device_drives | 사용자 키가 없는 PC 단위 드라이브 목록. PC를 공유할 수 있어 계정 탈퇴에서 특정 사용자 행만 안전하게 고를 수 없음 | 장치 제거 때 함께 정리할지 별도 결정 |

| 대상 | 상태 | 다음 단계 제안 |
|---|---|---|
| 공통 로그인 계정(Control Plane identity, 타 앱 공유) | Chat 세션은 전부 무효화됨. CP 계정·다른 앱 세션은 남음 | 2단계: CP identity 계정 삭제·연결 해제 경로(별도 설계) |
| B14 원장 | 미포함 | B14 원장의 사용자 식별자 조사 후 별도 단계 |
| R2 파일 객체(대화 첨부·프로젝트 원본·생성문서) | Chat DB의 참조 행은 지움. R2 객체 자체는 남음 | 객체 TTL·즉시 삭제 정책 결정(`workspace_storage.py`의 생성문서 30일 TTL은 참조 행 기준) |
| 외부 백업(Cloudflare R2 offsite, 매일 암호화 전체 백업) | 탈퇴 사용자 데이터가 최근 백업에 남음 | 백업 보관 기간 정책을 대표 결정으로 확정(`deploy/host-com2/offsite-backup/`) |
| 이용자 PC의 `.padiem-backup` | 이용자 PC에 남음(경로가 닿지 않는 영역) | 탈퇴 안내 문구로 이용자가 직접 지우도록 안내(이미 화면 설명에 포함) |
| oracle_mesh_dispatch | **해결됨 (2026-11-03)** — 행은 재생 방지(047)를 위해 남기고, `user_id`·`account_ref`·기기·경로·명령 본문 등 사람을 가리키는 칸은 지운다(2.4절). 남은 행으로는 누구의 것인지 알 수 없다 | 보관 기간은 대표 결정(개인정보처리방침). 지금은 만료 행도 지우지 않는다 |
| bookai_records(082) | **해결됨 (2026-11-03)** — 매핑은 이미 있었다: 공유 로그인으로 만든 Chat 계정은 `provider_subject='shared:'+subject`로 저장된다(`history.upsert_shared_user`). 1단계가 이 매핑을 못 본 이유는 세션 해제가 링크 캐시 행을 먼저 지우기 때문이며, 이제 배치 전에 읽는다. 매핑이 없는 계정(구글 단독 로그인)은 지울 subject가 없어 그대로 남는다 | 남은 것: 기기에만 저장된 북AI 기록(브라우저 저장소)은 서버가 지울 수 없다 — 탈퇴 안내 문구로 이용자가 지운다 |
| MeshCentral 장치·에이전트 | Chat/COM2 큐 DB의 사용자 연결 행은 지워짐. presence는 탈퇴 사용자만 제거하고 남은 소유자가 없으면 행 삭제 | 운영 영역: 장치 문서·에이전트 제거는 별도 절차 |

## 4. 개인정보처리방침 초안 갱신 메모

`docs/legal/drafts/`(브랜치 `docs/legal-drafts-261103`)의 README
"코드에서 확인 못 한 사실" 2번 — "계정 전체 탈퇴(계정 삭제) 라우트 — 확인하지
못했습니다" — 는 이 경로가 채운다. 법률 문서 레인에서 다음 문구로 갱신해야
한다: "계정 탈퇴는 설정 > 계정 탈퇴에서 본인 이메일을 다시 입력해 실행할 수
있으며, Chat DB의 사용자 데이터와 계정에 저장된 북AI 기록은 즉시 삭제된다. 기기에만 저장된 북AI 기록, 공통 로그인 계정·외부
백업·이용자 PC 백업은 남는다(보관 기간은 대표 결정). PC 명령 중복 실행 방지
기록은 누구의 것인지 알 수 없게 처리한 뒤 남는다."

## 5. 시험

apps/padiem-chat/tests/test_account_deletion_261103.py — 18건:

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
