# Chat 계정 탈퇴 1단계 설계·근거 (2026-11-03, #6659 3번)

범위: 로그인한 이용자가 자기 PADIEM Chat 계정과 Chat DB 안의 자기 데이터를
스스로 지우는 경로. 구현: `POST /api/account/delete`
(`apps/padiem-chat/app/account_deletion.py`), 화면: 설정 > 계정 탈퇴.

## 0. 경로 계약

- 로그인 세션 필수. SameOriginGuardMiddleware(#3476)가 쿠키 붙은 POST의 출처를 검사한다.
- 본문 `{"confirm": "<본인 이메일>"}`가 저장된 계정 이메일과 정확히(대소문자까지) 일치할 때만 실행된다. 이것이 "복구 불가 파괴는 실행 전 한 번 확인"이다.
- 삭제는 **한 번의 `db.batch()` 트랜잭션**이다. 중간에 실패하면 전부 되돌려진다(시험 `test_a_mid_batch_failure_rolls_the_whole_deletion_back`).
- 실행 순서: 출처 검사 → 본문 확인 → 이메일 일치 → 관리자 차단 → 현재 세션 종료(`_revoke_canonical_session`, 실패 시 아무것도 지우지 않음) → 배치 삭제 → 계정 전체 canonical 세션 해제(#5441 헬퍼, best-effort) → 검증 캐시·PC 스코프 캐시 무효화 → `private, no-store` 응답 + 세션 쿠키 삭제.
- 관리자 차단: 세션 이메일이 중앙 관리자 이메일(`PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL`, `app_factory`가 state에 넣은 값)과 일치하거나 `platform_admin_roles` 행을 가진 계정은 403 `account_delete_admin_blocked`.
- 남기는 기록은 최소: `account_deletion_audit`(마이그레이션 092)에 탈퇴 시각과 사용자 id의 SHA-256 해시 1행. 이메일·이름·subject 저장 금지(시험이 응답·행에 `@` 부재를 단정).

## 1. 왜 CASCADE에 기대지 않는가 (foreign_keys 확인 결과)

| 경로 | foreign_keys 상태 | 근거 |
|---|---|---|
| Production D1 | 강제하지 않음 | `apps/padiem-chat/app/local_cpython.py:229` 주석("production D1 never enforces it") |
| 로컬 CPython 호스트 | 일부러 켜지 않음(production 동등성) | `local_cpython.py:229-236` |
| 로컬 D1 에뮬레이터(`d1_sqlite.py`) | 켬 | `apps/padiem-chat/app/d1_sqlite.py:39` |
| 마이그레이션 001 | 스크립트 안에 `PRAGMA foreign_keys = ON` 포함(연결 상태를 바꿈) | `migrations/001_auth_history.sql:5` |

결론: `ON DELETE CASCADE` 선언은 문서일 뿐 실행 보장이 없으므로, 경로는 표의
모든 테이블을 **이름을 걸어 명시 삭제**한다. 자식→부모 순서로 나열하고 users
행은 마지막에 지운다.

## 2. 사용자 데이터 테이블 전수 조사 (migrations 001~093)

총 106개 테이블 중 사용자 키를 가진 **살아있는 테이블 63개**를 경로가 지운다.
조사 방법: 93개 마이그레이션 전체에서 `CREATE TABLE` 본문의 사용자 키 컬럼
(`user_id`·`member_id`·`owner_id`·`product_user_id`)을 추출. `_next`·
`_rebuilt_*` 그림자 테이블은 각 마이그레이션이 끝나기 전에 rename/drop되므로
살아있는 이름만 표에 넣었다(060·061·063·068·069·077·081·083 끝의
`ALTER TABLE ... RENAME` 확인).

### 2.1 `user_id = ?`로 지우는 표 (56)

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
| oracle_mesh_dispatch | 047(063 리빌드) | FK 없음 → 명시 삭제 |
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
| bookai_records | **이번 단계에서 지우지 않는다** — 아래 3번 참조 |

## 3. 이번에 지우지 않은 것과 다음 단계 제안

| 대상 | 상태 | 다음 단계 제안 |
|---|---|---|
| 공통 로그인 계정(Control Plane identity, 타 앱 공유) | Chat 세션은 전부 무효화됨. CP 계정·다른 앱 세션은 남음 | 2단계: CP identity 계정 삭제·연결 해제 경로(별도 설계) |
| B14 원장 | 미포함 | B14 원장의 사용자 식별자 조사 후 별도 단계 |
| R2 파일 객체(대화 첨부·프로젝트 원본·생성문서) | Chat DB의 참조 행은 지움. R2 객체 자체는 남음 | 객체 TTL·즉시 삭제 정책 결정(`workspace_storage.py`의 생성문서 30일 TTL은 참조 행 기준) |
| 외부 백업(Cloudflare R2 offsite, 매일 암호화 전체 백업) | 탈퇴 사용자 데이터가 최근 백업에 남음 | 백업 보관 기간 정책을 대표 결정으로 확정(`deploy/host-com2/offsite-backup/`) |
| 이용자 PC의 `.padiem-backup` | 이용자 PC에 남음(경로가 닿지 않는 영역) | 탈퇴 안내 문구로 이용자가 직접 지우도록 안내(이미 화면 설명에 포함) |
| bookai_records(082) | `subject` 키는 클라이언트가 발행한 불투명 값이고 Chat DB에 subject↔users.id 매핑이 없다(`bookai_records.py`는 단일 공유 시크릿 서명만 검증). 사용자별 삭제가 불가능하므로 이번에 지우지 않았다 | subject와 사용자의 매핑을 만들거나, 북AI 데이터 보관 기간을 대표 결정으로 정한 뒤 별도 경로로 지운다 |
| MeshCentral 장치·에이전트 | Chat DB의 연결·위임 행만 지워짐 | 운영 영역: 장치 문서·에이전트 제거는 별도 절차 |

## 4. 개인정보처리방침 초안 갱신 메모

`docs/legal/drafts/`(브랜치 `docs/legal-drafts-261103`)의 README
"코드에서 확인 못 한 사실" 2번 — "계정 전체 탈퇴(계정 삭제) 라우트 — 확인하지
못했습니다" — 는 이 경로가 채운다. 법률 문서 레인에서 다음 문구로 갱신해야
한다: "계정 탈퇴는 설정 > 계정 탈퇴에서 본인 이메일을 다시 입력해 실행할 수
있으며, Chat DB의 사용자 데이터는 즉시 삭제된다. 공통 로그인 계정·외부
백업·이용자 PC 백업은 남는다(보관 기간은 대표 결정)."

## 5. 시험

`apps/padiem-chat/tests/test_account_deletion_261103.py` — 9건:

- (a) 정상 탈퇴: 표의 모든 테이블에서 그 사용자 행 0, 다른 사용자 행은 삭제 전 스냅샷과 동일. 사용자 1명당 표의 모든 테이블에 1행을 넣고 시작한다(platform_admin_roles는 권한 표식이라 제외).
- (b) 이메일 불일치 → 400, 아무것도 지워지지 않음
- (c) 로그인 없음 → 401, 다른 출처 Origin → 403(출처 검사)
- (d) 중간 실패(테이블 1개 제거) → 503 + 전체 롤백(스냅샷 대비 동일)
- (e) 탈퇴 뒤 옛 쿠키 → 401, /api/auth/status 미인증
- (f) 중앙 관리자 이메일·platform_admin_roles 보유 계정 → 403
- (g) 마이그레이션 092 재적용(멱등)
- (h) Mesh 기기 소유자 목록에서 탈퇴자만 제거하고 다른 계정 참조 보존

스키마 드리프트 방지 시험이 포함되어 있다: 경로가 지우는 표의 테이블·키 컬럼이
실제 스키마에 존재하지 않으면 수집 시점에 실패한다. `pc_install_tokens`도 사용자
키 목록에 명시되었는지 단언하므로 이 표의 삭제 누락도 실패한다.

실행(이 저장소에서 확인한 명령):

```bash
cd apps/padiem-chat
PYTHONPATH="../../packages/padiem-control-plane;../../packages/padiem-ai-core;../padiem-ai-engine/clients/python;../korean-ai-code-agent/src" \
  python -m pytest tests/test_account_deletion_261103.py \
    tests/test_5225_logout_session_revocation.py tests/test_5434_password_change.py \
    tests/test_5441_password_reset.py tests/test_5441_password_reset_mail_credential.py \
    tests/test_6446_account_isolation_sweep.py -q
# 67 passed
```
