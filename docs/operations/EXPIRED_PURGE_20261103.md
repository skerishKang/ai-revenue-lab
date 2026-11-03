# 만료 데이터 자동 삭제 1단계 (2026-11-03)

대상은 **기한이 지나면 의미가 없어지는 일회성 데이터**만이다: 인증·로그인 넘김,
비밀번호 재설정 토큰, 페어링 코드, 승인 넘김, 임대·claim, 연결 대기, OAuth
state. 대화·메시지·첨부·프로젝트 파일·북AI 기록·PC 작업 기록·감사·동의 기록은
개인정보처리방침의 보관 기간이 대표 결정으로 정해진 뒤에 다룬다 — 이번 단계는
그쪽을 전혀 건드리지 않는다.

구현: `apps/padiem-chat/app/expired_purge.py` (`python -m app.expired_purge
--once`, `--dry-run` 지원). 예약 실행 틀: `deploy/host-com2/cron/`의
`expired_purge` 작업(`com2_only` — Cloudflare Worker cron 없음).

## 전수 조사 — 만료 컬럼이 있는 19개 마이그레이션의 테이블 분류

조사 대상: `apps/padiem-chat/migrations`의 006 007 008 016 029 030 034 043 046
047 058 060 062 063 072 074 076 081 085. 재구성 마이그레이션(060·063·081)은 같은
테이블의 후속 형태라 최종 테이블 기준으로 한 줄로 정리한다.

| 마이그레이션 | 테이블 | 만료 컬럼 | 데이터 성격 | 이미 지우는 코드 | 이번 판정 | 이유·유예 판단 |
| --- | --- | --- | --- | --- | --- | --- |
| 006 | `orchestration_continuations` | `expires_at` | 일회성 (오케스트레이션 스냅샷) | 없음 | **지움** | 만료·종료 상태의 스냅샷은 재개가 무효. 기본 유예 7일로 충분 |
| 006 | `orchestration_decisions` | 없음 | 결정 기록 | — | 대상 아님 | 만료 컬럼 자체가 없다 |
| 007 | `control_plane_identity_shadow` | `session_expires_at` | 현재 상태 프로젝션 (사용자당 1행) | 없음 | **제외** | 일회성 데이터가 아니다: 행은 사용자별 identity 매핑이고 세션 만료는 행의 속성일 뿐. 지우면 매핑이 상실된다 |
| 008→060 | `claw_document_metadata` | `expires_at` | 이용자 내용 (문서 메타데이터) | `workspace_storage.py`가 만료를 판정해 접근 차단 | **제외** | 이용자 내용 범주 — 보관 기간이 대표 결정 대기 |
| 016 | `claw_approval_handoff` | `pause_expires_at` | 일회성 (승인 넘김 컨텍스트) | 없음 | **지움** | 정확 재생(idempotent replay)은 만료 전까지만 유효. 기본 유예 7일로 충분 |
| 029→081 | `claw_web_xlsx_selections` | `expires_at` | 일회성 (XLSX 소스 선택) | 없음 | **지움** | 만료된 선택은 P01 시작 불가. 7일 유예 |
| 030 | `claw_web_xlsx_p01_requests` | `pause_expires_at` (NULL 허용) | 일회성 (P01 디스패치 영수증) | 없음 | **지움** | 일시정지된 행만 대상. `NULL`(dispatching) 행은 만료 기준이 없어 건드리지 않는다 |
| 034 | `claw_web_xlsx_quote_write_pauses` | `pause_expires_at` (NULL 허용) | 일회성 (견적 쓰기 일시정지) | 없음 | **지움** | 030과 동일 규칙 |
| 043 | `claw_coding_conversation_grant` | `expires_at` | 일회성 (대화 예약) | **있음** — `claw_first_turn_authority.py:369` (`cleanup_abandoned` / `release_expired`, 실행마다 상한 20행) | **뺌 (중복 금지)** | 자기 코드의 정리 방식을 그대로 둔다. 이 모듈이 중복으로 지우지 않는다 |
| 046 | `claw_github_oauth_states` | `expires_at` (epoch 초) | 일회성 (OAuth state) | 소비 시만 삭제 (`github_oauth_store.py:51`) | **지움** | 만료된 state는 소비 조건(`expires_at>?`)을 통과하지 못해 이미 무효. epoch 비교는 같은 epoch cutoff로 |
| 046 | `claw_github_connections` | `access_expires_at`·`refresh_expires_at` | 연결 자격 (토큰) | — | **제외** | 토큰 만료는 갱신 대상이지 행 삭제 대상이 아니다. 행은 사용자의 GitHub 연결 자체 |
| 047→063→074 | `oracle_mesh_dispatch` | `expires_at` | 일회성 디스패치 + 재생 방지 | 없음 (정책상 없음) | **제외** | 마이그레이션 047이 명시한다: "Expired or consumed rows stay fail-closed; they are never deleted by the application". 만료 행이 남아 있어야 nonce 재생 시도가 fail-closed로 거부된다 |
| 058 | `padiem_android_auth_handoffs` | `expires_at` | 일회성 (Android 로그인 넘김) | 없음 | **지움** | 1회 claim 계약, 만료 행은 claim 불가. HMAC 해시만 저장 — 원본도 없고 지울 내용도 없다. 7일 유예 |
| 060 | `claw_conversation_artifact_index` | 없음 | 대화 아티팩트 | — | 대상 아님 | 이용자 내용이고 만료 컬럼도 없다 |
| 062 | `password_reset_tokens` | `expires_at` | 일회성 (재설정 토큰) | 없음 | **지움** | `consumed_at`·`revoked_at`·`attempts` 표시는 유예 7일 동안 보존되므로 재시도 판단·횟수 기록이 사라질 시간이 충분하다 |
| 062 | `password_reset_audit` | 없음 | 감사 | — | 대상 아님 | 감사 기록 |
| 072 | `pc_pairing_codes` | `expires_at` | 일회성 (PC 페어링 코드) | 없음 | **지움** | 소비된 코드가 어느 노드를 소비했는지의 기록(`mesh_node_id`)은 유예 7일 동안 남는다 — 그 뒤의 소멸은 감사 대체(`mcp_audit`류) 없이도 코드 자체가 일회성 증명이므로 허용된다 |
| 072 | `pc_device_links` | 없음 | 연결 (R1 링크) | — | 대상 아님 | 연결 자격, 만료 컬럼 없음 |
| 076 | `lovetree_login_handoffs` | `expires_at` | 일회성 (LoveTree 로그인 넘김) | 없음 | **지움** | 1회 claim, 상태 전이가 조건부 UPDATE로만 가능. 7일 유예 |
| 085 | `padiem_mcp_approvals` | `expires_at` | 일회성 (도구 승인 결정) | 없음 | **지움** | 승인 소재는 `padiem_mcp_audit`이 별도로 남긴다 — approvals 행 자체는 일회성 결정. 7일 유예 |
| 085 | `padiem_mcp_tokens` | 없음 | 디바이스 인증 토큰 | — | 대상 아님 | 만료 컬럼 없음 (폐기는 `revoked_at`) |
| 085 | `padiem_mcp_audit` | 없음 | 감사 | — | 대상 아님 | 감사 기록 |

분류 수: **지움 11 / 이미 자기 코드가 지움(중복 금지) 1 / 제외 6 / 만료 컬럼 없음(대상 자격 없음) 6**.

### 유예 시간을 늘리거나 대상에서 뺀 결정 요약

- **`oracle_mesh_dispatch` — 대상 제외.** 만료 행의 존재가 재생 방지의
  일부이고, 마이그레이션 047이 애플리케이션 삭제를 금지한다. 이 정책을
  바꾸는 것은 이번 단계의 권한 밖이다.
- **`claw_web_xlsx_p01_requests`·`claw_web_xlsx_selections` — 영수증이
  가리키는 행은 남긴다.** 두 테이블은 각각 `claw_web_xlsx_p01_decision_receipts`·
  `claw_web_xlsx_quote_edit_receipts`가 `NO ACTION` 외래 키로 참조한다. 만료된
  부모 행을 영수증이 아직 인용하고 있으면 삭제가 외래 키 위반으로 실패해 그 회차의
  남은 테이블까지 멈춘다(11-03 운영 첫 실행에서 확인). 그래서 영수증이 가리키지
  않는 만료 행만 지우고, 인용된 쌍은 영수증 보관 기간이 정해질 때 함께 다룬다.
- **`claw_coding_conversation_grant` — 중복 방지로 제외.** 자기 스토어가
  이미 상한 있는 정리를 한다. 두 경로가 같은 행을 지우면 "누가 지웠는가"가
  흐려진다.
- **`control_plane_identity_shadow`·`claw_github_connections`·
  `claw_document_metadata` — 제외.** 만료 시각이 행의 수명이 아니라 세션·토큰·
  문서의 속성이거나(007·046), 이용자 내용(008/060)이라 보관 기간 결정이 먼저다.
- **나머지 지움 대상 11개 — 기본 유예 7일 유지.** 표에서 확인한 보존 이유
  (재시도 판단·소비 기록·횟수 기록)는 전부 7일 안에 충족된다.
  `PADIEM_CHAT_EXPIRED_PURGE_GRACE_DAYS` 환경 변수로 운영 중 조정 가능.

## 제외 데이터와 그 이유 (대표 결정 대기)

대화·메시지·첨부·프로젝트 파일·북AI 기록·PC 작업 기록·감사(audit)·동의(consent)
기록은 이번 단계의 대상이 아니다. 이것들은 기능상 일회성이 아니라 이용자의
기록이며, 개인정보처리방침의 보관 기간이 대표 결정으로 정해진 뒤 별도 단계로
다룬다. 이 모듈의 대상 목록(`PURGE_TARGETS`)은 코드 안에 명시되어 있고 스키마를
동적으로 추정하지 않으므로, 위 범주가 실수로 들어올 경로가 없다.

## 법무 초안 갱신 메모

**현재 확인 상태:** 개인정보처리방침 초안이 놓일 `docs/legal/drafts/` 디렉터리가
이 저장소(2026-11-03 기준 main `568aa0043`)에 존재하지 않고, "만료 행 자동 삭제
경로 미확인" 항목의 위치를 저장소 안에서 찾을 수 없었다. 해당 초안이 컴1 거버넌스
측 자료라면 이 기계에서는 읽을 수 없다.

**갱신할 내용:** 초안을 찾았을 때 "만료 행 자동 삭제 경로 미확인" 항목을 아래로
갱신한다 — "일회성 만료 행은 `app.expired_purge`(컴2 타이머, 유예 7일, 테이블당
1배치/일)가 삭제한다. 대상 목록과 근거는 `docs/operations/EXPIRED_PURGE_20261103.md`
2단계 표. 대화·메시지·첨부·북AI·PC 작업·감사·동의 기록은 보관 기간 대표 결정까지
삭제 경로 없음(의도적)."

## 컴2 설치 절차 (컴2 레인이 나중에 실행 — 이번 단계에서는 설치하지 않았다)

1. 체크아웃 갱신 후 렌더 검토: `sudo bash deploy/host-com2/cron/install-cron.sh
   --profile production --schedule '<일 1회 UTC OnCalendar>' --dry-run`
   — 만료 정리용 유닛 `padiem-chat-expired-purge-com2`가 같이 렌더되는지 확인.
2. 모듈 단독 확인 (타이머 없이): `cd /opt/padiem/chat-com2 &&
   PADIEM_CHAT_CPYTHON_HOST=1 venv/bin/python -m app.expired_purge --dry-run`
   — `CHAT_EXPIRED_PURGE=dry_run detail={<table>: <rows>}` 형태의 카운트만 나오는지
   확인. 처음에는 적지 않은 만료 행이 나올 수 있다(누적분).
3. 실제 1회 실행: `PADIEM_CHAT_CPYTHON_HOST=1 venv/bin/python -m app.expired_purge
   --once` — 테이블당 최대 1000행(`PADIEM_CHAT_EXPIRED_PURGE_BATCH`)씩 줄어든다.
4. 유닛 설치: 같은 명령에 `--apply` — 서비스·타이머 파일 복사 + `daemon-reload`.
   시작·활성화는 하지 않는다.
5. 타이머 활성화(승인된 별도 행위): `sudo systemctl enable --now
   padiem-chat-expired-purge-com2.timer`
6. 확인: `journalctl -u padiem-chat-expired-purge-com2.service`에서
   `CHAT_EXPIRED_PURGE_RUN=START/END`와 `CHAT_EXPIRED_PURGE=ok detail=...` 쌍,
   그리고 다음날 같은 detail이 0에 가까워지는지(배치 단위 감소 확인).

롤백: `sudo systemctl disable --now padiem-chat-expired-purge-com2.timer` —
삭제된 행은 복구 대상이 아니므로 롤백은 "더 이상 지우지 않게 하는 것"만 의미한다.
