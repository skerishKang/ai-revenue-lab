# B14 오버레이 적용 절차 — 2026-11-06

문서 전용입니다. 작성 시점에 운영 서버 접속·배포·재시작·파일 수정을 실행하지 않았습니다. 실행 권한은 컴2 운영 담당자에게 있습니다.

관련: #6838(추론 설정), #7004(콘솔 재저장 시 reasoning 블록 보존, `9a73bb3e`), #7005(오버레이 초안 도구, `b448d3e`)

이 문서는 컴2 호스트의 B14에만 적용합니다. Cloudflare Worker/D1 경로는 다루지 않습니다. 모든 명령은 **root**로 실행합니다.

---

## 0. 전제와 고정 값

| 항목 | 값 |
|---|---|
| 서비스 | `padiem-b14.service` (User/Group `padiem-b14`) |
| 앱 체크아웃 | `/opt/padiem/b14/app` |
| venv | `/opt/padiem/b14/venv` |
| 기준 레지스트리 | `B14_REGISTRY_PATH` (템플릿 값 `/var/lib/padiem-b14/b14-registry/b14_models.json`) |
| 오버레이 | `B14_REGISTRY_OVERLAY_PATH` 또는 기준 파일 옆 `b14_models.overrides.json` |
| 원장 | `B14_CALL_LEDGER_PATH` (템플릿 값 `/opt/padiem/b14/ledger/b14-call-ledger.db`) |
| 관리 콘솔 | `http://127.0.0.1:8781/login` (컴2 루프백 전용) |
| 헬스 | `python3 /opt/padiem/b14/deploy/host-com2/b14/health.py` |

`EnvironmentFile=-/opt/padiem/b14/env/b14.env`가 Unit의 `Environment=`보다 우선합니다. 따라서 파일이 아니라 **실행 중 프로세스의 환경**을 실제 값으로 읽습니다.

---

## 1. 사전 확인

### 1-1. 실행 중 실제 환경 값

```bash
PID=$(systemctl show padiem-b14.service -p MainPID --value)
tr '\0' '\n' < "/proc/$PID/environ" \
  | grep -E '^B14_(REGISTRY_PATH|REGISTRY_OVERLAY_PATH|CALL_LEDGER_PATH)='
```

기록할 값:

```text
BASE=<B14_REGISTRY_PATH 실제 값>
OVERLAY=<B14_REGISTRY_OVERLAY_PATH 실제 값, 없으면 $(dirname "$BASE")/b14_models.overrides.json>
LEDGER=<B14_CALL_LEDGER_PATH 실제 값>
```

`B14_REGISTRY_OVERLAY_PATH`가 출력에 없으면 미설정이며, 기본값은 기준 파일과 같은 디렉터리의 `b14_models.overrides.json`입니다.

**통과 증거:** `BASE`가 `/var/lib/padiem-b14/b14-registry/b14_models.json`이고 `OVERLAY`가 그 옆 경로로 확정됨.

### 1-2. 배포본 SHA와 도구 존재

```bash
git -C /opt/padiem/b14/app rev-parse HEAD
test -f /opt/padiem/b14/app/tools/b14_overlay_draft.py \
  && echo B14_OVERLAY_TOOL=present || echo B14_OVERLAY_TOOL=missing
```

- `9a73bb3e`(#7004) 미만이면 **멈춥니다.** 콘솔 재저장 시 블록 보존이 없습니다.
- 도구가 `missing`이면 **멈춥니다.** #7005(`b448d3e`) 이후 main SHA를 평소 B14 배포 절차로 먼저 반영해야 합니다. 이 문서는 배포 명령을 실행하지 않습니다.

**통과 증거:** SHA가 `9a73bb3e` 이상이고 `B14_OVERLAY_TOOL=present`.

### 1-3. 기준 파일 지문과 기존 오버레이

```bash
sha256sum "$BASE"
test -e "$OVERLAY" && sha256sum "$OVERLAY" || echo OVERLAY=absent
stat -c '%a %U:%G %n' "$(dirname "$BASE")" 2>/dev/null
```

**통과 증거:** 기준 SHA-256 기록됨, 기존 오버레이 유무(`absent` 또는 SHA) 기록됨, 디렉터리가 `700 padiem-b14:padiem-b14`.

### 1-4. 원장 백업

```bash
install -d -m 0700 /var/backups/padiem-b14
BACKUP=/var/backups/padiem-b14/b14-call-ledger-$(date -u +%Y%m%dT%H%M%SZ).db
sqlite3 "$LEDGER" "PRAGMA wal_checkpoint(TRUNCATE);"
cp -p "$LEDGER" "$BACKUP"
chmod 600 "$BACKUP"
stat -c '%s %a %U:%G %n' "$BACKUP"
```

**통과 증거:** 백업 크기 > 0, 권한 `600`, 경로 기록됨.

---

## 2. 초안 입력 만들기

어떤 모델에 어떤 reasoning 값을 줄지는 **비공개 등록부(#6838)** 를 따릅니다. 이 문서에는 가짜 id만 둡니다. 실제 값은 거버넌스 폴더의 지정 파일에서 가져옵니다.

```bash
GOVERNANCE_DIR="<거버넌스 폴더>"
DRAFT="$GOVERNANCE_DIR/b14_overlay_draft.json"
```

입력 형식(아래 id·값은 형식 예시일 뿐입니다):

```json
{
  "models": {
    "vendor-a/chat-1": {
      "supported": true,
      "values": ["low", "high"],
      "thought_summary": true
    }
  }
}
```

규칙:
- 키는 기준 레지스트리에 **실제로 존재하는** 모델 id여야 합니다.
- 블록은 `normalize_policy()`를 통과해야 합니다. `supported: true`면 `values`가 필수이고, 값은 `minimal|low|medium|high`만 됩니다.
- 행 전체를 쓰지 않습니다. 기준 행 복사는 도구가 담당합니다.

**통과 증거:** `python3 -m json.tool "$DRAFT" >/dev/null`이 exit 0이고, 실제 모델 id 목록이 거버넌스 파일과 일치함.

---

## 3. 적용 순서

### 3-1. 초안 생성

```bash
PY=/opt/padiem/b14/venv/bin/python
TOOL=/opt/padiem/b14/app/tools/b14_overlay_draft.py
STAGE=/root/b14-overlay-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$STAGE"

"$PY" "$TOOL" --base "$BASE" --draft "$DRAFT" \
  --out "$STAGE/b14_models.overrides.json"
```

도구는 기준 행을 통째로 복사하고 reasoning 블록만 붙인 뒤 기동과 같은 `merge_overlay()` + `validate_registry()`를 통과한 경우에만 파일을 씁니다. 실패하면 모델 id와 문제 키를 stderr에 출력하고 exit 1이며, 출력 파일을 만들지 않습니다.

**통과 증거:** `wrote ... models=<N> effective_models=<M>` 출력, exit 0.

### 3-2. 배포 전 검증

```bash
"$PY" "$TOOL" --base "$BASE" --check "$STAGE/b14_models.overrides.json"
```

**통과 증거:** `OK: ... models=<N> effective_models=<M>`, exit 0.

### 3-3. 설치 (백업 → 임시 파일 → 소유자·권한 → 교체)

기존 오버레이가 있으면 먼저 백업합니다.

```bash
test -e "$OVERLAY" && cp -p "$OVERLAY" "$STAGE/previous.overrides.json"
```

임시 파일에 쓰고 소유자·권한을 맞춘 뒤 한 번에 교체합니다.

```bash
cp "$STAGE/b14_models.overrides.json" "$OVERLAY.new"
chown padiem-b14:padiem-b14 "$OVERLAY.new"
chmod 600 "$OVERLAY.new"
mv "$OVERLAY.new" "$OVERLAY"
stat -c '%a %U:%G %n' "$OVERLAY"
sha256sum "$STAGE/b14_models.overrides.json" "$OVERLAY"
```

**통과 증거:** `600 padiem-b14:padiem-b14 <OVERLAY>`, 스테이징 파일과 설치 파일의 SHA-256 동일.

### 3-4. 재시작과 헬스

```bash
systemctl restart padiem-b14.service
systemctl is-active padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

기대: `active`, `{"healthy": true, "exit_code": 0, "issues": [], ...}`, `demo_mode`가 `true`가 아님.

**통과 증거:** `active` + `healthy: true` + `issues: []`.

### 3-5. 기동 로그 확인

```bash
journalctl -u padiem-b14.service --since "10 min ago" --no-pager \
  | grep -E "invalid B14 JSON|reasoning block rejected|unexpected/missing keys|Traceback"
```

기대: 출력 없음(오버레이가 잘못되면 B14는 기동을 중단하므로 3-4가 먼저 실패합니다).

**통과 증거:** 위 grep 결과 0줄.

### 3-6. 원장 스키마와 thought_summary 값

```bash
sqlite3 "$LEDGER" "PRAGMA table_info(b14_model_call_attempt);" | wc -l
sqlite3 "$LEDGER" "PRAGMA table_info(b14_model_call_attempt);" \
  | cut -d'|' -f2 | grep -c '^thought_summary_'
```

기대: 컬럼 수 **31**, `thought_summary_` 컬럼 **2**개(`thought_summary_count`, `thought_summary_chars`). 31이 아니면 이 런북을 멈추고 원장 마이그레이션 상태를 먼저 확인합니다. 수동 `ALTER TABLE`은 금지입니다.

대상 모델로 스트리밍 요청 1회 후:

```bash
sqlite3 "$LEDGER" \
  "SELECT started_at, thought_summary_count, thought_summary_chars
     FROM b14_model_call_attempt ORDER BY started_at DESC LIMIT 5;"
```

기대: 생각이 온 턴은 두 값 모두 > 0, 요청하지 않은 턴은 NULL.

**통과 증거:** `31` / `2` 출력, 그리고 최근 행 중 대상 턴의 `thought_summary_count`·`thought_summary_chars` > 0.

### 3-7. 콘솔 재저장 1회 후 블록 유지 확인

컴2 브라우저에서 `http://127.0.0.1:8781/login`에 접속해 같은 모델을 **한 번 재저장**합니다. 콘솔에는 reasoning 입력란이 없으므로 아무 값도 입력하지 않습니다.

재저장 전후에 같은 명령으로 오버레이의 블록 수와 지문을 비교합니다.

```bash
"$PY" - "$OVERLAY" <<'PY'
import hashlib, json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
rows = doc.get("models") or []
blocks = [row.get("reasoning") for row in rows if "reasoning" in row]
digest = hashlib.sha256(
    json.dumps(blocks, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()[:16]
print("MODELS", len(rows), "REASONING_ROWS", len(blocks), "REASONING_SHA", digest)
PY
```

**통과 증거:** 재저장 전후 `MODELS`·`REASONING_ROWS`·`REASONING_SHA`가 모두 동일.

---

## 4. 실패 시 되돌리기

코드 롤백은 필요 없습니다. 오버레이만 되돌리고 재시작합니다.

### 4-1. 오버레이 제거(비활성화)

```bash
mv "$OVERLAY" "$OVERLAY.disabled-$(date -u +%Y%m%dT%H%M%SZ)"
systemctl restart padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

### 4-2. 이전 오버레이 복원

3-3에서 백업을 만든 경우(적용 전 오버레이가 있었던 경우)에만 사용합니다.

```bash
install -o padiem-b14 -g padiem-b14 -m 600 \
  "$STAGE/previous.overrides.json" "$OVERLAY"
systemctl restart padiem-b14.service
python3 /opt/padiem/b14/deploy/host-com2/b14/health.py
```

**통과 증거:** `healthy: true`, `issues: []`.

기준 레지스트리 파일은 수정하지 않았으므로 되돌릴 대상이 아닙니다. 원장은 추가형이며 되돌리지 않습니다.

---

## 5. 금지

- 수동 `ALTER TABLE` / `DROP COLUMN` — 원장 스키마는 기동 시 `apply_migrations()`만 사용합니다.
- 부분 행 오버레이 — 행 전체 복사는 `tools/b14_overlay_draft.py`만 사용합니다.
- 콘솔로 reasoning 값 입력 — 콘솔은 해당 필드를 보내지 않으며, 보내도 `_clean_model()`이 거부합니다.
- 기준 레지스트리(`$BASE`) 직접 수정 — 변경은 오버레이에만 기록합니다.
- 문서·PR·로그에 실제 모델/프로바이더 이름, 비밀 값, 토큰 기록.

---

## 6. 이 문서가 하지 않은 것

- 운영 서버 접속, 배포, 재시작, 오버레이 파일 생성·설치를 실행하지 않았습니다.
- 실제 모델/프로바이더 이름과 reasoning 값을 쓰지 않았습니다.
- B14 코드·마이그레이션·배포 스크립트를 변경하지 않았습니다.
