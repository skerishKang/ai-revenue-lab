# B14 생각 요약 활성화 순서 — 운영(컴2 호스트) 기준 — 2026-11-05

문서 전용입니다. 이 문서의 어떤 명령도 작성 시점에 실행하지 않았습니다. 실행 권한은 Web CTO/대표에게 있습니다.

관련: #6907(B14 스트림), #6917(Chat 표시), #6903·#6913(Chat 선행), #6838(추론 설정), #6812(첫 글자 지연)

---

## 0. 운영 형태 — 확정

**운영 B14는 컴2 호스트입니다.** Chat의 `B14_UPSTREAM_MODE`가 컴2 B14를 가리킵니다.

| 항목 | 확정 값 |
|---|---|
| 실행 형태 | 컴2 systemd `padiem-b14.service` (`/opt/padiem/b14/app`) |
| 원장 | 로컬 SQLite — `B14_CALL_LEDGER_PATH` (예: `/opt/padiem/b14/ledger/b14-call-ledger.db`) |
| 레지스트리 | `B14_REGISTRY_PATH` (예: `/var/lib/padiem-b14/b14-registry/b14_models.json`) |
| 오버레이 | 기준 레지스트리 옆 `b14_models.overrides.json` (또는 `B14_REGISTRY_OVERLAY_PATH`) |
| 관리 콘솔 | `http://127.0.0.1:8781` (컴2 로컬 전용) |

**Cloudflare Worker/D1 B14 경로는 지금 쓰지 않습니다.** 이 문서는 컴2 호스트 경로만 다룹니다.

D1 ledger provision gate에는 현재 별도 결함이 기록되어 있습니다(기대 컬럼 27 vs 실제 31). 이 문서는 그 gate를 사용하지 않으며, 수정도 하지 않습니다. 재사용 계획이 생기면 이슈 #6928을 먼저 처리합니다.

---

## 1. 사전 조건

| # | 조건 | 확인 |
|---|---|---|
| P1 | #6917 main 머지 | PR checks fail·pending 0, 머지 SHA 기록 |
| P2 | 되돌릴 B14 이전 체크아웃 SHA·디렉터리 기록 | 2단계 첫 줄 |
| P3 | 원장 백업 경로·크기 기록 | 1단계 첫 줄 |
| P4 | 되돌릴 Chat 버전 ID 기록 | 4단계 배포 로그의 `PREVIOUS_VERSION_ID` |
| P5 | 검증용 로그인 사용자 + 스트리밍 허용 상태 | 4단계 전제 |

기록할 값:
```
PRE_CHANGE_B14_SHA =
PRE_CHANGE_B14_DIR =
B14_LEDGER_BACKUP =
PRE_CHANGE_CHAT_VERSION_ID =
TARGET_CHAT_SHA =
```

---

## 2. 1단계 — migration 0006 적용 (컴2 SQLite)

0006은 `b14_model_call_attempt`에 nullable 컬럼 2개를 더합니다. 컴2 B14는 시작 시 `SqliteLedger.apply_migrations()`가 `migrations/*.sql` 중 미적용 파일을 파일명 순서로 적용하고 `b14_local_migration`에 기록합니다. 즉 **0006 파일이 배포본에 있고 서비스가 재시작되면, 요청을 받기 전에 0006이 적용됩니다.**

### 2-1. 백업 (필수)

B14를 멈추지 않고 일관된 백업을 만들려면 WAL 체크포인트 후 파일을 복사하거나 sqlite backup API를 사용합니다. 백업 경로와 크기만 기록하고, 원장 행 내용은 복사하지 않습니다.

```
sqlite3 /opt/padiem/b14/ledger/b14-call-ledger.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp /opt/padiem/b14/ledger/b14-call-ledger.db <BACKUP_PATH>
stat -c '%s %n' <BACKUP_PATH>
```

### 2-2. 현재 적용 상태 확인

```
sqlite3 /opt/padiem/b14/ledger/b14-call-ledger.db \
  "SELECT name FROM b14_local_migration ORDER BY name;"
```

0006이 아직 없으면 pending입니다. 0004·0005도 pending일 수 있으므로 함께 확인합니다.

### 2-3. 적용

별도 수동 `ALTER`를 직접 실행하지 않습니다. `b14_local_migration`에 기록되지 않아 다음 기동에서 재적용을 시도하고 `duplicate column name`으로 실패합니다.

정상 경로는 **2단계 재시작**입니다. 새 배포본이 staging된 뒤 서비스가 다시 뜨면서 요청 수용 전에 pending migration을 적용합니다. 1단계를 코드 배포와 분리해 먼저 끝내야 한다면, 같은 앱의 `apply_migrations()`를 한 번 호출하는 방법만 허용합니다(수동 SQL 금지).

### 2-4. 확인

```
sqlite3 /opt/padiem/b14/ledger/b14-call-ledger.db \
  "SELECT name FROM b14_local_migration ORDER BY name;"
sqlite3 /opt/padiem/b14/ledger/b14-call-ledger.db \
  "PRAGMA table_info(b14_model_call_attempt);"
```

기대:
- `b14_local_migration`에 `0006_b14_attempt_thought_summary.sql` 존재
- `thought_summary_count`, `thought_summary_chars` 존재
- `b14_model_call_attempt` 컬럼 수 **31**

### 되돌리기

- 기본: 컬럼을 남깁니다(추가형, 이전 코드는 무시).
- 복원이 필요하면 2-1 백업으로 되돌립니다. 백업 이후 원장 행은 사라집니다.
- `ALTER TABLE ... DROP COLUMN`은 이 문서에서 금지합니다.

---

## 3. 2단계 — B14 배포 (#6907, 컴2 호스트)

### 3-1. 이전 상태 기록

```
readlink -f /opt/padiem/b14/app
git -C /opt/padiem/b14/app rev-parse HEAD
```

결과를 `PRE_CHANGE_B14_SHA`, `PRE_CHANGE_B14_DIR`에 기록합니다. 컴2 호스트 경로에는 게이트가 기록하는 버전 ID가 없으므로 이 수동 기록이 유일한 롤백 근거입니다.

### 3-2. 배포

```
bash /opt/padiem/b14/deploy/host-com2/b14/install.sh --dry-run
bash /opt/padiem/b14/deploy/host-com2/b14/install.sh --reload
```

기대 마커: `B14_COM2_INSTALL=staged:unit`, `already_current:*`, `NO_SERVICE_STARTED=YES`, `NO_CREDENTIAL_WRITTEN=YES`

거부 마커가 나오면 멈추고 CENTRAL에 보고합니다: `foreign_target`, `asgi_entry_missing`, `venv_python_missing`, `root_required`, `linux_required`

### 3-3. 재시작과 헬스

권한 소유자가 실행합니다.

```
systemctl restart padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

기대: `healthy: true`, `demo_mode` 아님, `issues: []`

이 재시작에서 1단계의 pending migration이 적용됩니다. 2-4로 스키마를 확인합니다.

### 되돌리기

1. 기록한 이전 SHA/디렉터리의 배포본으로 `install.sh --reload`
2. `systemctl restart padiem-b14.service`
3. `health.py`로 확인
4. 스키마는 되돌리지 않습니다(추가형)

---

## 4. 3단계 — 오버레이에 `thought_summary` 블록

오버레이는 컴2 호스트에만 적용됩니다. Cloudflare Worker 배포본에는 사람이 쓸 수 있는 오버레이 파일이 없습니다.

### 4-1. 쓰는 방법

1. **B14 관리 콘솔**(`http://127.0.0.1:8781`, 컴2 로컬)로 등록 — 검증·원자적 쓰기를 콘솔이 담당합니다. 우선 사용합니다.
2. 콘솔을 쓸 수 없으면 오버레이 파일을 직접 편집합니다. 편집 전 백업, JSON 파싱 확인, 재시작이 필요합니다.

### 4-2. 블록 형태

모델 이름은 공개 문서에 쓰지 않습니다. 대표가 지정한 Free 주 모델에만 붙입니다.

```json
{
  "models": [
    {
      "id": "<대표가 지정한 Free 주 모델>",
      "reasoning": {
        "supported": true,
        "values": ["medium", "high"],
        "default": "high",
        "thought_summary": true
      }
    }
  ]
}
```

### 4-3. 규칙

- `thought_summary`는 bool, 기본 꺼짐.
- `supported: false` 모델이 선언하면 **B14 기동이 중단**됩니다(실패 닫힘).
- 오버레이 JSON이 잘못되면 B14가 기동하지 않습니다. 재시작 전에 콘솔 검증 또는 `python -m json.tool`로 확인합니다.
- 이 플래그는 Google 업스트림 호출에 `extra_body.google.thinking_config.include_thoughts`를 붙입니다. 대상 모델의 업스트림이 Google인지 확인합니다. Google이 아니면 효과가 없거나 400 후 재시도로 무시될 수 있습니다.

### 4-4. 재시작과 확인

```
systemctl restart padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

기대:
- B14 로그에 `thought_summary_rejected`가 없음(있으면 해당 모델이 옵션을 거부한 것 — 그 모델에서는 꺼진 상태로 동작)
- 스트림 응답에 `delta.reasoning_content` 프레임이 보임
- 원장에 `thought_summary_count`, `thought_summary_chars`가 채워짐(5-3)

### 되돌리기 (가장 빠른 스위치)

- 콘솔에서 `thought_summary`를 `false`로 바꾸거나 키를 제거하고 재시작합니다.
- 코드 배포 없이 B14만 끄면 Chat #6917이 그대로여도 생각 이벤트가 오지 않으므로 화면에 "생각 중" 칸이 생기지 않습니다.
- 파일을 직접 고쳤다면 백업본으로 되돌리고 재시작합니다.

---

## 5. 4단계 — Chat 배포 (#6917)

전제: #6917 main 머지 완료.

워크플로: `b62-production-code-deploy-gate.yml`
- `mode` = `deploy_production_code`
- `target_sha` = #6917이 포함된 exact main SHA
- `confirmation` = `DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN`

배포 전후로 게이트 로그의 **`PREVIOUS_VERSION_ID`**를 기록합니다. 롤백 입력입니다.

스트리밍 전제:
- `PADIEM_CHAT_ORCHESTRATION_STREAM` 전체 켜짐 또는
- `PADIEM_CHAT_ORCHESTRATION_STREAM_USERS`에 검증 사용자 id 포함(#6899)
- #6913 이후 게스트는 AI를 쓸 수 없으므로 **로그인 사용자**로 검증합니다.

### 되돌리기

- `b62-production-code-deploy-gate.yml` 재디스패치
  - `mode` = `rollback_production_code`
  - `confirmation` = `ROLLBACK_B62_PRODUCTION_CODE_TO_RECORDED_VERSION`
  - `previous_version_id` = 기록한 값

### 비상 스위치 (배포 없이 생각 이벤트 끊기)

- `PADIEM_CHAT_ORCHESTRATION_STREAM`을 끄거나 allowlist에서 사용자를 제거합니다.
- Chat은 기존 JSON 경로로 돌아가고 생각 이벤트가 발생하지 않습니다. 단, 스트리밍 자체가 꺼지므로 답변 표시 방식도 기존으로 돌아갑니다.

---

## 6. 5단계 — 확인

### 6-1. 화면

로그인 사용자, 스트리밍 허용 상태에서 질문 1회.

| 항목 | 기대 |
|---|---|
| 첫 표시 | 답보다 먼저 "생각 중" 칸이 열리고 조각이 쌓임 |
| 답 시작 | 칸이 자동으로 접힘, 라벨이 "생각"으로 바뀜 |
| 다시 펼치기 | 클릭하면 생각 본문이 보임 |
| 답 본문 | 생각 텍스트가 섞이지 않음 |
| 390 / 1440 | 두 폭 모두 콘솔 오류 0, 레이아웃 깨짐 없음 |
| 화면 낭독기 | 접힌 요약("생각")과 답 문단이 서로 다른 노드로 읽힘 |
| #6812 | 첫 글자(생각 조각) 도착이 답변 지연으로 보이지 않음 |

### 6-2. 저장되지 않음

1. 스트리밍 중 "생각 중" 칸의 문장 일부를 복사해 둡니다.
2. 새로고침 후 같은 대화를 다시 엽니다 → 생각 칸이 없어야 합니다.
3. 대화 내보내기(TXT)·복사·공유 결과에 1의 문장이 없어야 합니다.
4. 서버 저장 답변과 화면 답 본문이 같고, 생각 문장이 포함되지 않아야 합니다.

### 6-3. 원장

```
sqlite3 /opt/padiem/b14/ledger/b14-call-ledger.db \
  "SELECT thought_summary_count, thought_summary_chars FROM b14_model_call_attempt ORDER BY started_at DESC LIMIT 5;"
```

기대:
- 생각이 실제로 온 턴: `thought_summary_count` > 0, `thought_summary_chars` > 0
- 생각을 요청하지 않은 턴/모델: 둘 다 NULL
- `b14_model_call_attempt`에 생각 **원문** 컬럼이 없음
- 0006 적용 후 컬럼 수 31

### 6-4. 경계

- #6913 게스트 차단 유지: 비로그인 요청은 401 `login_required`.
- 모델·프로바이더 이름이 화면·오류 문구에 나오지 않음.

---

## 7. 실패 시 판정표

| 증상 | 계층 | 먼저 할 일 |
|---|---|---|
| 화면에 생각 칸 없음, 답은 정상 | Chat 이벤트/스트림 게이트 | 스트리밍 스위치·allowlist 확인 → Chat 버전 확인 |
| 스트림에 `reasoning_content` 없음 | B14 오버레이/모델 | 오버레이 `thought_summary`, 모델 `supported`, 업스트림 확인, `thought_summary_rejected` 로그 확인 |
| 원장 INSERT 실패·`storage_unavailable` | 스키마 | 0006 적용 여부와 컬럼 수 31 확인 |
| 답 본문에 생각이 섞임 | 회귀 | 즉시 Chat 롤백, #6917 재검토 |
| 대화 기록/내보내기에 생각이 남음 | 회귀 | 즉시 Chat 롤백, #6917 재검토 |
| B14 기동 실패 | 오버레이 JSON | 백업으로 복원, JSON·정책 검증, 재시작 |
| 첫 글자 지연이 그대로 | B14 스트림/TTFT | B14 버전·모델, `b14.stream.first_delta` 계측 확인 |

원칙: 한 번에 한 계층만 되돌립니다. 되돌린 뒤 같은 확인을 다시 하고, 원인을 특정하기 전에 두 계층을 동시에 바꾸지 않습니다.

---

## 8. 전체 롤백 순서 (빠른 것부터)

1. **오버레이 끄기** (4-4 되돌리기) — 코드 배포 없음. 새 생각 조각이 즉시 멈춤.
2. **Chat 롤백** (5단계 되돌리기) — 기록된 `PREVIOUS_VERSION_ID`로.
3. **B14 롤백** (3단계 되돌리기) — 기록된 이전 SHA/디렉터리로.
4. **스키마** — 기본은 유지. 복원은 대표 승인 + 백업, 원장 행 손실을 감수할 때만.

호환성:
- B14가 켜져 있고 Chat이 롤백되어도 안전합니다(Chat이 모르는 필드를 무시).
- Chat이 #6917이고 B14 오버레이가 꺼져 있어도 안전합니다(생각 이벤트가 없음 → 칸 없음).
- 따라서 1→2→3 순서로 내려도 중간 상태가 사용자에게 오류를 만들지 않습니다.

---

## 9. 이 문서가 하지 않은 것

- 마이그레이션·배포·재시작·오버레이 수정을 실행하지 않았습니다.
- 모델·프로바이더 이름을 쓰지 않았습니다.
- Cloudflare/D1/시크릿/바인딩을 변경하지 않았습니다.
- #6917 머지·배포를 하지 않았습니다.
- D1 gate 27→31은 이슈 #6928에만 기록하고, 이 PR에서 고치지 않았습니다.
