# 보관 기간을 실제로 지키는 정리 코드 (2026-11-03)

배경: `docs/legal/drafts/`(브랜치 `docs/legal-retention-261103`, `54bf1e7`)에서
공통 약관·개인정보처리방침의 보관 기간을 확정했고, 그 브랜치의 README
"운영 반영 필요" 표가 문서와 실제가 다른 곳 10행을 남겼다. 이 문서는 그 10행을
**저장소 코드로 고칠 수 있는 것 / 서버 설정(배포 때 적용) / 대표 결정이 남은 것**으로
나누고, 코드로 고친 것의 구현과 시험을 적는다.

운영 서버는 건드리지 않았다. 배포·설치·타이머 활성화도 하지 않았다.

## 1. 10행 분류

| # | 대상 | 확정 기간 | 이번 작업의 분류 | 처리 |
|---|---|---|---|---|
| 1 | Chat 접속 기록(journald) | 3개월 | **서버 설정** | `deploy/host-com2/journald/99-padiem-retention.conf.example`(MaxRetentionSec=90d) — 배포 때 적용 |
| 2 | B14 파일 로그 | 7일 | **서버 설정** | `deploy/host-com2/b14/logrotate.conf.example`의 `rotate 90` → `rotate 7` — 배포 때 적용 |
| 3 | B14 모델 호출 원장 | 90일 | **코드로 해결** | `apps/korean-ai-platform/app/pilot/call_ledger_retention.py` |
| 4 | 탈퇴 기록 | 1년 | **코드로 해결** | `apps/padiem-chat/app/retention_purge.py`(`account_deletion_audit`) |
| 5 | 러브트리 서버 접속 기록 | 3개월 | **대표 결정·다른 저장소** | 러브트리 저장소·Cloudflare 측 설정. 이 저장소에서 지울 표가 없다 |
| 6 | CGI 쇼핑몰 로그·백업 | 3개월 / 28일 | **대표 결정·다른 저장소** | 쇼핑몰 저장소·Cloudflare 대시보드 |
| 7 | 북AI 계정 기록의 탈퇴 삭제 | 즉시 파기 | **대표 결정** | Chat 계정 탈퇴(#6734)의 삭제 표에 북AI 기록 표가 들어가는지 컴2에서 확인해야 한다 |
| 8 | MCP 감사 기록 | 90일 | **코드로 해결** | `retention_purge.py`(`padiem_mcp_audit`) |
| 9 | PC 화면 캡처 | 90일 | **코드 대상 아님** | 서버 표가 없다: 캡처는 이용자 PC에 저장되고 서버에는 표가 없다(`pc_browser_tools.py`, `claw_pc_browser_routes.py`) |
| 10 | PC 작업 기록(카운터) | 90일 | **코드 대상 아님** | 서버 표가 아니라 지표다(`pc_work_metrics.py`에 CREATE TABLE·INSERT 0건) |

5·6·7번은 다른 저장소나 운영 설정이고, 9·10번은 지울 서버 표가 없다. 표를
새로 만들어 지우는 것은 "지킬 대상"이 아니라 "없는 데이터"이므로 만들지 않았다.

## 2. 코드로 고친 것

### 2.1 `apps/padiem-chat/app/retention_purge.py` (새 파일)

`app.expired_purge`의 1단계(기한이 지나면 의미가 없어지는 일회성 행)에 이어,
**기간이 확정된 기록**을 지우는 2단계다. 대상은 코드에 명시된 3개 표뿐이다.

| 표 | 컬럼 | 기간 | 왜 여기인가 |
|---|---|---|---|
| `account_deletion_audit` | `deleted_at` | 365일 | 탈퇴 기록은 옛 세션을 거부하는 근거라 확정된 1년을 채워야 하고, 그 뒤에는 남길 이유가 없다. 저장값은 사용자 id 해시·시각뿐 |
| `padiem_mcp_audit` | `created_at` | 90일 | 확정된 "서비스 로그(오류·감사) 90일" |
| `claw_task_alert` | `created_at` | 90일 | 혼합 표에서 `kind='alert' AND status='dismissed'`인 행만 만료한다. 사용자 작업과 활성 알림은 보존 |

지우지 않는 것과 이유:

- 대화·메시지·첨부·프로젝트 파일·북AI 기록·동의 표: 기간이 "이용자가 삭제할 때까지"라
  타이머가 자를 수 있는 컷오프가 아니다. 사용자 행동의 몫이다.
- 시각을 읽을 수 없는 행(NULL·형식 오류): 나이를 모르는 것은 만료의 증거가 아니다.
  `WHERE` 절이 `>= '1000-01-01'`을 요구해 이런 행은 남는다.
- 표가 없는 환경(마이그레이션 전): 0행으로 건너뛴다. DELETE가 실패하면 실제
  저장소 장애이므로 그대로 예외로 올려 타이머가 실패로 기록한다.

한 번에 표당 1배치(기본 1000행)만 지워 쌓인 잔량이 여러 날에 걸쳐 줄어든다.
결과 줄은 `CHAT_RETENTION_PURGE=ok detail={"account_deletion_audit":0,...}`처럼
**표 이름과 건수만** 담고 행 내용·식별자는 담지 않는다.

### 2.2 `apps/korean-ai-platform/app/pilot/call_ledger_retention.py` (새 파일)

B14 호출 원장(`/opt/padiem/b14/ledger/b14-call-ledger.db`, SQLite)에서 90일이 지난
호출을 지운다. 원장에는 지금까지 삭제 경로가 0건이었다.

- 시도(`b14_model_call_attempt`)는 `log_id`로만 호출에 매달려 있으므로 부모와 함께
  한 트랜잭션에서 지운다. 남는 호출의 시도는 그대로 둔다.
- `started_at`이 NULL이거나 읽을 수 없는 호출은 남긴다(원장 실측에서 시도 행의
  `started_at`이 전부 NULL이었다).
- 상태 줄은 `B14_LEDGER_RETENTION=ok b14_model_call=38 b14_model_call_attempt=43`
  처럼 표 이름과 건수만 담는다.
- DB 파일이 없으면 `SKIPPED reason=database_missing`(exit 2), SQLite 오류는
  `STORAGE_ERROR`(exit 1)로 실패를 성공으로 보고하지 않는다.

### 2.3 기존 03:00 타이머에 붙임

`deploy/host-com2/cron/run-expired-purge.sh`가 1단계(`app.expired_purge`)에 이어
2단계(`app.retention_purge`)를 같은 실행에서 돌리고, B14 원장 정리는 설정이 갖춰진
경우에만 세 번째로 돈다.

- 3단계는 `B14_LEDGER_PYTHON`과 `B14_LEDGER_APP_ROOT`가 둘 다 있을 때만 실행하고,
  없으면 `B14_LEDGER_RETENTION=SKIPPED reason=not_configured` 한 줄을 남긴다.
  (배포 때 env에 두 값을 넣는 것이 "적용"이다.)
- 어느 단계든 실패하면 스크립트 종료 코드는 실패(≠0)다. 앞 단계가 성공해도 실패를
  덮지 않는다.
- 한 단계가 실패해도 뒤 단계는 계속 돈다: 남은 정리를 굶기지 않기 위해서다.

## 3. 서버 설정 (배포 때 적용 — 이번에는 설치하지 않음)

| 대상 | 파일 | 값 | 적용 방법 |
|---|---|---|---|
| journald 보관 | `deploy/host-com2/journald/99-padiem-retention.conf.example` | `MaxRetentionSec=90d`, `SystemMaxUse=2G`, `SystemMaxFileSize=128M` | 컴2에서 `/etc/systemd/journald.conf.d/`에 복사 후 `systemctl restart systemd-journald` |
| B14 파일 로그 회전 | `deploy/host-com2/b14/logrotate.conf.example` | `daily`, `rotate 7`(7일), `maxsize 50M` | `install.sh`로 스테이징 후 승인된 설치 |

두 파일 모두 "template; not installed by this repo" 성격을 유지했다. 실제 설치·재시작은
운영 승인 절차의 몫이다.

접속 기록 3개월과 서비스 로그 90일이 한 파일에 같이 걸리는 이유: journald는 전역
보관 창을 하나만 둔다. 더 긴 쪽(90일)을 상한으로 두고, 접속 기록을 3개월로 더 짧게
가져가려면 별도 파일 싱크가 필요하다. 그 설계는 이번에 만들지 않았고, 이 사실을
템플릿 주석에 남겼다.

## 4. 남은 것 (이번 작업 밖)

1. **journald·logrotate 설치**: 위 두 파일을 컴2에 적용하고 `journalctl --disk-usage`로
   상한이 걸렸는지 확인한다.
2. **B14 원장 정리 연결**: `B14_LEDGER_PYTHON`·`B14_LEDGER_APP_ROOT`를 컴2 env에 넣고
   첫 실행에서 `B14_LEDGER_RETENTION=ok`가 찍히는지 확인한다.
3. **북AI 기록 표가 탈퇴 삭제 대상인지** 컴2에서 확인한다(7번 행).
4. **러브트리·쇼핑몰·Cloudflare 로그**(5·6번)는 각 저장소·대시보드의 몫이다.
5. **1단계 정리의 남은 판단**: `expired_purge`가 남긴 영수증 인용 쌍과
   `expires_at` 자동 정리 경로는 `docs/operations/EXPIRED_PURGE_20261103.md`를 따른다.

## 5. 시험

| 시험 | 확인하는 것 |
|---|---|
| `apps/padiem-chat/tests/test_retention_purge.py` | 1년·90일 경계 하루 전/후, 읽을 수 없는 시각 보존, 사용자 내용·신원 표 불변, 배치 상한, dry-run 무삭제, 표 없음 건너뛰기, 상태 줄에 건수만, exit 0/1/2 |
| `apps/korean-ai-platform/tests/test_b14_call_ledger_retention.py` | 90일 경계, 시도가 부모와 함께만 삭제, 시각 없는 호출 보존, dry-run, 반복 실행 멱등, DB 없음 SKIPPED, 상태 줄에 식별자 없음 |

두 시험 모두 임시 SQLite 파일만 사용한다. 운영 DB·호스트에 접속하지 않는다.

## 6. Claw 작업 표 분류와 90일 적용

Chat migrations와 앱 실행 코드의 DDL을 확인했다. Claw 전용 `CREATE TABLE`은 migration에서 관리하며 Chat 앱 실행 중 Claw 표를 동적으로 만들지 않는다. 별도 Claw `*_events`나 `*_steps` 표는 없다. migration 081의 `_next`/backup 테이블은 마이그레이션 중 재구성용 객체라 런타임 표 목록에서 제외했다. `claw_task_alert`만 작업 정의와 알림 상태 기록이 함께 있는 혼합 표다.

### (a) 사용자 내용·결과·권한 자료: 보관

아래 표는 사용자가 만든 정의·결과·대화·파일, 또는 이를 안전하게 조회·승인·중복 방지하는 권한 자료다. 이 정리 작업에서 지우지 않는다.

| 표 | 분류 근거 |
|---|---|
| `claw_document_metadata` | 사용자가 보관하는 문서의 저장·소유 메타데이터. 문서 삭제와 기존 파일 정리 수명주기를 따른다. |
| `claw_run_history` | 사용자 실행 이력과 결과 요약·대화 연결·산출물 이름을 제공한다. 결과 보존 대상이며 `claw_conversation_artifact_index`의 참조 부모다. |
| `claw_task_alert` (`kind='task'`) | 사용자가 만든 작업 정의와 상태다. open/done/cancelled를 포함해 사용자 삭제까지 보관한다. |
| `claw_task_alert` (`kind='alert' AND status='active'`) | 아직 사용자가 닫지 않은 알림이다. 기간이 지나도 삭제하지 않는다. |
| `claw_approved_memory`, `claw_rules`, `claw_proposals` | 승인된 사용자 메모, 자동화 작업 정의, 사용자 검토가 필요한 제안이다. |
| `claw_runs` | 스케줄 실행의 canonical 결과·오류·상태가 한 행에 함께 있다. 사용자 결과를 잃지 않도록 표 전체를 지우지 않는다. `started_at`만 있고 공통 `created_at`은 없어 이번 purge 기준에도 맞지 않는다. |
| `claw_occurrences`, `claw_local_task_correlation` | 실행 dedup 권위와 사용자 결과/로컬 작업 연결 참조다. 지우면 재실행 방지 또는 결과 조회가 깨질 수 있다. |
| `claw_conversation_artifact_index` | 대화에서 결과 파일을 다시 여는 참조다. `claw_run_history`의 실행 이력과 함께 보존한다. |
| `claw_approval_handoff` | 사용자 승인 전달과 소비 상태를 묶는 보안·재생 방지 자료다. |
| `claw_web_xlsx_selections`, `claw_web_xlsx_p01_requests`, `claw_web_xlsx_p01_decision_receipts`, `claw_web_xlsx_quote_edit_receipts`, `claw_web_xlsx_quote_write_decisions`, `claw_web_xlsx_quote_write_pauses` | 사용자 파일 선택과 승인·쓰기 흐름에 필요한 연결 및 중복 방지 자료다. |
| `claw_artifact_delivery_receipts` | 외부 산출물 전송의 중복 발송을 막는 unique receipt다. 삭제하면 같은 전송을 다시 시도할 수 있어 보존한다. |
| `claw_coding_conversation_grant` | 대화 접근 권한 자료다. |
| `claw_github_oauth_states`, `claw_github_connections`, `claw_pc_device_selection`, `claw_push_subscription` | OAuth·기기 선택·알림 구독 등 접근 및 설정 자료다. 사용자 파일·실행 로그 90일 정리 대상과 역할이 다르다. |
| `claw_meetings`, `claw_meeting_artifacts`, `claw_meeting_actions` | 사용자가 보관하는 회의 내용·산출물·후속 조치다. |
| `document_convert_jobs`, `document_convert_items` | 일반 문서 변환의 상태·파일 키·검증 결과다. Claw 전용 표는 아니며 사용자 파일 결과를 가리키므로 계정 삭제 cascade 경로에 맡긴다. |

### (b) 실행 상태 기록: 90일 뒤 삭제

`claw_task_alert`에서 `kind='alert' AND status='dismissed'`인 행만 `created_at < now - 90 days`일 때 삭제한다. 이 범위는 사용자가 닫은 알림 상태 기록이다. alert가 active이면 나이와 관계없이 남고, 같은 표의 `kind='task'`는 어떤 상태든 남는다. `claw_runs`의 PENDING/RUNNING 기록도 target 목록에 없으므로 삭제되지 않는다.

Claw 결과 이력과 알림 목록은 서로 다른 저장소 표면이다. purge가 `claw_task_alert`에서 만료된 dismissed 행만 지우며, run history, result artifact index, task 정의를 건드리지 않는다. `claw_task_alert`에는 해당 표의 부모를 cascade 삭제하는 외래 키가 없고 다른 migration에도 이를 참조하는 외래 키가 없다. 회귀 시험은 purge 뒤 실제 `D1ClawTaskAlertStore`의 task/alert 조회와 PENDING/RUNNING 행 보존을 확인한다.

90일 만료 조회는 workspace 전체에서 `kind`, `status`, `created_at` 범위로 실행된다. 기존 inbox 인덱스는 workspace로 시작해 이 조회를 지원하지 않으므로 migration `098_claw_task_alert_retention_index.sql`에서 `(kind, status, created_at)` 인덱스를 추가했다. 매 실행은 표당 최대 한 배치만 지우고, 표가 없으면 0으로 보고하며, 결과 줄에는 표 이름과 건수만 남긴다.
