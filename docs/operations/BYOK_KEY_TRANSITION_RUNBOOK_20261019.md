# #5121 BYOK 전용 키 운영 전환 Runbook (2026-10-19)

관련: #5121 (BYOK 구현), PR #5131·#5137·#5143 (병합 구현 재사용), #5002 (모델 경로 분리), #4317/#3936/#4316 (제품 원장).

이 문서는 **전환 준비** 문서다. 2026-10-19 기준 운영 D1·Worker Secret·Worker 코드·DNS·Tunnel은 변경하지 않았다. 실행 명령은 승인된 운영 창에서만 사용한다.

## 1. 확인된 현재 상태

2026-10-19 읽기 전용 재확인 결과다. 이 작업은 운영 Worker·D1·Secret·DNS를 변경하지 않았다.

`scripts/ops/byok_key_transition.py preflight`:

```text
DPAPI_CUSTOM_KEY_SECRET=MISSING
WORKER_CUSTOM_KEY_SECRET=MISSING
D1_MIGRATION_053=MISSING
CUSTOM_CREDENTIAL_ROWS=TABLE_MISSING
DEPLOYED_BYOK_ROUTE=PRESENT
BYOK_TRANSITION_READY=NO
SECRET_VALUES_PRINTED=0
```

`apps/padiem-chat/scripts/byok_predeploy_readiness.py check` (bounded evidence):

```text
BYOK_PREDEPLOY_STATE=BLOCKED_BY_SECRET
SECRET_READY=NO
SECRET_STRENGTH=NOT_INSPECTED
MIGRATION_053=MISSING
D1_OWNERSHIP=UNKNOWN
BYOK_BLOCKERS=SECRET_MISSING,MIGRATION_053_MISSING
SECRET_VALUES_OUTPUT=0
ROW_VALUES_OUTPUT=0
PRODUCTION_MUTATION=0
```

확인 내용:

- **코드 배포 단계 완료:** `GET https://chat.padiem.net/api/chat/custom/credential`은 JSON 401 `authentication_required`를 반환한다. 같은 상위 경로의 미존재 경로(`/api/chat/custom/nonexistent-probe`)는 404이므로 라우트별 401을 배포 증거로 판정한다. 기존 B62 코드 배포 gate 실행(2026-10-19T12:50:54Z, `d953eadd`)이 main 코드를 배포했으며 이 작업이 실행한 변경이 아니다.
- **Secret 단계 미완료:** COM2 DPAPI 저장소와 Cloudflare Worker `padiem-chat` 양쪽에 `PADIEM_CHAT_CUSTOM_KEY_SECRET`이 없다. `PADIEM_CHAT_SESSION_SECRET`은 양쪽에 존재한다. 두 저장소의 존재 여부는 독립 신호다.
- **Migration 단계 미완료:** 운영 D1 `padiem-chat-db`에 `chat_custom_provider_credentials` 테이블이 없다. 기존 고객 BYOK 행은 0건이다.
- **고객 키 복호화 단계 해당 없음:** 등록 행이 없으므로 재봉인·복호화 실패 대상도 0건이다.
- 2026-10-19 확인 시 Governance 로컬 경로 `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance`는 이 호스트에서 접근할 수 없었다. 상태 표기: `GOVERNANCE=NOT_READ`.

## 2. 도구 역할과 전환 전제

- `scripts/ops/byok_key_transition.py`는 전환 상태 요약(`preflight`), 단계 계획(`print_plan`)과 승인된 변경 명령(`register-local`, `upload-worker`, `apply-migration`)을 담당한다.
- `apps/padiem-chat/scripts/byok_predeploy_readiness.py`(#5149)는 읽기 전용 증거로 053 스키마 정확성, FK·소유 무결성, Secret 이름과 강도를 분류한다. 변경 명령이 없다. 같은 분류기를 새로 만들지 않는다.
- 두 도구는 같은 `PADIEM_CHAT_CUSTOM_KEY_SECRET`, 최소 32자, `chat_custom_provider_credentials` 계약을 공유한다. 집중 테스트가 이 일치를 고정한다.

- 전환 대상 main SHA는 40자 전체 SHA로 고정한다. PR merge commit을 사용한다.
- **하나의 전용 키 값을 COM2 DPAPI와 Cloudflare Worker에 동일하게 공급한다.** 두 런타임이 같은 D1의 봉인 행을 읽으므로 값이 다르면 한쪽은 503으로 fail-closed 된다.
- 전용 키는 최소 32자이며 앞뒤 공백이 없어야 한다. 스크립트가 생성·검증한다.
- Secret 원문은 argv, 로그, PR, 화면, 셸 기록에 남기지 않는다. 업로드는 stdin으로만 전달한다.
- Cloudflare 인증은 기존 OAuth 자식 프로세스를 사용하고 `CLOUDFLARE_API_TOKEN` 계열 환경변수는 제거한다. 계정 ID는 공개 보고서에 기록하지 않는다.
- 운영 배포는 기존 `B62 Production Code Deploy Gate`만 사용한다. 수동 `wrangler deploy` 경로를 새로 만들지 않는다.
- DNS, Tunnel, 라우트, D1 데이터, R2 객체는 이 절차에서 변경하지 않는다.

## 3. 실행 순서

### Step 0 — 읽기 전용 기준선

전환 상태와 준비도 증거를 먼저 기록한다. 두 명령 모두 운영 값을 변경하지 않는다.

```powershell
py -3 scripts/ops/byok_key_transition.py preflight --account-id <ACCOUNT_ID>
```

```powershell
$w = "D:\cli\wrangler.cmd"
$db = "padiem-chat-db"
$env:CLOUDFLARE_ACCOUNT_ID = "<ACCOUNT_ID>"

& $w d1 execute $db --remote --json `
  --command "SELECT name,type,sql FROM sqlite_master WHERE name='chat_custom_provider_credentials'" `
  | Set-Content -Encoding ascii byok-meta-1.json
& $w d1 execute $db --remote --json `
  --command "PRAGMA table_info(chat_custom_provider_credentials)" `
  | Set-Content -Encoding ascii byok-meta-2.json
& $w d1 execute $db --remote --json `
  --command "PRAGMA foreign_key_list(chat_custom_provider_credentials)" `
  | Set-Content -Encoding ascii byok-meta-3.json

py -3 -c "import json; parts=[json.load(open(f'byok-meta-{i}.json',encoding='utf-8')) for i in (1,2,3)]; json.dump([p[0] for p in parts], open('byok-d1-evidence.json','w',encoding='utf-8'))"

& $w secret list --name padiem-chat --format json | Set-Content -Encoding ascii byok-secrets.json

py -3 apps/padiem-chat/scripts/byok_predeploy_readiness.py check-d1 byok-d1-evidence.json
py -3 apps/padiem-chat/scripts/byok_predeploy_readiness.py check --secrets byok-secrets.json --d1 byok-d1-evidence.json
```

- `check-d1`: `EXACT`(종료 0), `MISSING`(종료 2), `DRIFT`/`INVALID_EVIDENCE`(종료 1)
- `check`: `READY`(0), `BLOCKED_BY_SECRET`/`BLOCKED_BY_MIGRATION`(2), `FAILED`(1)
- 증거 파일은 이름·스키마·집계만 담는다. Secret 값, 봉인 값, 행 값은 출력되지 않는다.

`BYOK_TRANSITION_READY=NO`여도 나머지 점검은 계속된다. 각 실패 코드는 독립적으로 표시된다.

### Step 1 — 정확한 main의 BYOK 코드 배포

기존 배포 gate를 사용한다. `target_sha`는 현재 main과 정확히 같아야 한다.

```powershell
gh workflow run b62-production-code-deploy-gate.yml `
  -f mode=deploy_production_code `
  -f target_sha=<EXACT_MAIN_SHA> `
  -f confirmation=DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN
```

배포 후 확인:

```powershell
curl.exe -sS -o NUL -w "%{http_code}`n" https://chat.padiem.net/api/chat/custom/credential
```

- 미인증 JSON 401/403: 라우트 배포됨 (`PRESENT`)
- 404: 미배포 (`ABSENT`)
- HTML 403: Cloudflare WAF 응답이며 라우트 존재 증거가 아니다 (`UNKNOWN`)

### Step 2 — Migration 053 적용

정확한 main 체크아웃에서만 실행한다. 스크립트는 `git rev-parse HEAD`가 `--expected-main`과 같은지 확인한 뒤 additive 테이블을 생성하고 존재를 재확인한다. 테이블을 먼저 만들어 두면 Secret 공급 직후 첫 등록 요청이 테이블 부재로 실패하지 않는다.

```powershell
py -3 scripts/ops/byok_key_transition.py apply-migration `
  --expected-main <EXACT_MAIN_SHA> `
  --account-id <ACCOUNT_ID> `
  --confirm-apply APPLY_BYOK_053_FROM_EXACT_MAIN
```

Migration 내용은 `CREATE TABLE IF NOT EXISTS` 하나이며 기존 테이블을 변경·삭제하지 않는다. 현재 기존 행이 0건이므로 legacy 재봉인 대상도 0건이다.

### Step 3 — COM2 DPAPI에 전용 키 등록

`register-local`은 값을 생성해 DPAPI에만 저장하고 원문을 출력하지 않는다. 기존 값이 있으면 `--replace` 없이는 거부한다.

```powershell
py -3 scripts/ops/byok_key_transition.py register-local --confirm-register
```

출력 계약:

```text
DPAPI_SECRET_STORED=YES
SECRET_LENGTH_OK=YES
SECRET_VALUES_PRINTED=0
```

### Step 4 — 동일 값을 Worker에 공급

반드시 기존 hidden-input store를 통해 실행한다. `store.py run`이 DPAPI 값을 자식 환경으로 주입하며 값은 argv에 없다.

```powershell
py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py run `
  py -3 scripts/ops/byok_key_transition.py upload-worker `
  --account-id <ACCOUNT_ID> --confirm-upload
```

`--account-id`는 DPAPI/환경에 이미 있으면 생략할 수 있다. 스크립트는 `wrangler secret put`에 stdin으로 값을 전달하고, 출력에서 값을 `[REDACTED]`로 치환한 뒤 `secret list`로 이름만 재확인한다.

### Step 5 — 준비 완료 확인

상태 요약과 준비도 분류를 모두 통과해야 한다.

```powershell
py -3 scripts/ops/byok_key_transition.py preflight --account-id <ACCOUNT_ID> --require-ready
```

기대값:

```text
DPAPI_CUSTOM_KEY_SECRET=PRESENT
WORKER_CUSTOM_KEY_SECRET=PRESENT
D1_MIGRATION_053=APPLIED
CUSTOM_CREDENTIAL_ROWS=0
DEPLOYED_BYOK_ROUTE=PRESENT
BYOK_TRANSITION_READY=YES
```

`--require-ready`는 미충족 시 종료 코드 1을 반환한다.

이어서 #5149 분류기로 스키마 정확성·무결성·Secret 강도를 확인한다. Step 0과 같은 PowerShell 세션에서 실행한다(`$w`, `$db` 사용). `--inspect-local-key`는 `store.py run`이 주입한 DPAPI 값을 길이만 검사하며 값을 출력하지 않는다.

```powershell
py -3 apps/padiem-chat/scripts/byok_predeploy_readiness.py write-integrity-query byok-integrity.json
$sql = (Get-Content byok-integrity.json -Raw | ConvertFrom-Json).sql
& $w d1 execute $db --remote --json --command $sql | Set-Content -Encoding ascii byok-integrity-evidence.json

# 스키마·Secret 증거는 Step 2~4 완료 후 Step 0의 세 D1 명령과 `secret list`를 다시 실행해 갱신한다.
py -3 apps/padiem-chat/scripts/byok_predeploy_readiness.py check-d1 byok-d1-evidence.json
py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py run `
  py -3 apps/padiem-chat/scripts/byok_predeploy_readiness.py check `
  --secrets byok-secrets.json --d1 byok-d1-evidence.json `
  --integrity byok-integrity-evidence.json --inspect-local-key
```

기대값:

```text
BYOK_PREDEPLOY_STATE=READY
SECRET_READY=YES
SECRET_STRENGTH=OK
MIGRATION_053=EXACT
D1_OWNERSHIP=EMPTY
BYOK_BLOCKERS=NONE
```

종료 코드 0과 `BYOK_BLOCKERS=NONE`을 동시에 확인한다. 기존 행이 있으면 `D1_OWNERSHIP=OK`이 정상이며, `VIOLATION`은 전환 중단 사유다.

### Step 6 — Owner 범위 실제 검증

1. Owner 세션으로 `PUT /api/chat/custom/credential`에 공급사 API 키를 등록한다.
2. `GET /api/chat/custom/credential` 응답의 `key_last4`만 확인한다. 원문 키가 응답에 없는지 확인한다.
3. Chat, Claw(`/api/claw/general`), B66(`/api/b66/ai/chat`, `/api/b66/quote/interpret`)에서 각각 1회씩 `custom` 선택 요청을 실행한다.
4. 각 요청의 응답 계약과 제품 결과를 확인한다. B14 router/registry/default 경로가 호출되지 않아야 한다.
5. D1 행은 `SELECT key_last4, length(sealed_credential), created_at, updated_at`만 조회한다. `sealed_credential` 원문과 고객 키는 보고서에 넣지 않는다.

이 검증은 BYOK_DIRECT 증거다. B14_MANAGED 또는 FULL_PLATFORM 통과 증거로 기록하지 않는다.

## 4. 단계별 실패 판정

각 상태는 서로 다른 원인이므로 하나의 503/404로 합쳐 판정하지 않는다. 인증(401)은 BYOK 저장소 접근보다 먼저 수행되므로 404는 코드 단계, 401/503은 코드 배포 이후 단계의 신호다.

| 관측 신호 | 판정 | 다음 조치 |
| --- | --- | --- |
| `preflight`의 `DEPLOYED_BYOK_ROUTE=ABSENT`, 라우트 404, 같은 상위 경로도 404 | 코드 미배포 | Step 1 exact-main 배포 gate |
| `DEPLOYED_BYOK_ROUTE=UNKNOWN` (HTML 403) | WAF 응답, 배포 여부 미판정 | JSON 401/404가 나오는 경로로 재확인 |
| `DPAPI_CUSTOM_KEY_SECRET=MISSING`, `WORKER_CUSTOM_KEY_SECRET=PRESENT` | COM2 DPAPI에만 전용 키 없음 | Step 3 `register-local`만 실행 |
| `DPAPI_CUSTOM_KEY_SECRET=PRESENT`, `WORKER_CUSTOM_KEY_SECRET=MISSING`, `SECRET_READY=NO`, `BYOK_BLOCKERS=SECRET_MISSING` | Worker에만 전용 키 없음 | Step 4 `store.py run` + `upload-worker`만 실행 |
| 두 Secret 모두 `MISSING` | 전용 키 미공급 | Step 3 → Step 4 순서로 실행 |
| `D1_MIGRATION_053=MISSING`, `CUSTOM_CREDENTIAL_ROWS=TABLE_MISSING`, `check-d1=MISSING`, `MIGRATION_053_MISSING` | 053 미적용 | Step 2 exact-main `apply-migration` |
| `check-d1=DRIFT` 또는 `BYOK_PREDEPLOY_STATE=FAILED` + `MIGRATION_053_DRIFT` | 053 스키마 불일치 | 중단. 테이블 삭제·변경 금지, Owner 결정 후 교정 migration |
| `D1_OWNERSHIP=VIOLATION` (`orphan_users`, `invalid_owner`, `invalid_last4`, `invalid_envelope`, `invalid_timestamps` 중 1 이상) | 행 무결성 위반 | 중단. 값이 아닌 집계만 보고하고 Owner 결정 |
| 인증된 `GET /api/chat/custom/credential` → 503 `custom_provider_unavailable` | Worker 저장소 미구성(전용 키 누락) | Step 4 |
| 인증된 `PUT /api/chat/custom/credential` → 503 `custom_credential_save_failed` | D1 테이블 부재/쓰기 실패 | Step 2, D1 상태 재확인 |
| 인증된 `GET`/제품 요청 → 503 `custom_credential_unavailable` | 고객 키 복호화 실패(키 ring 불일치·변조) | §6 복구 절차. 행 삭제 금지 |
| 인증된 제품 요청 → 409 `custom_credential_required` | 등록된 고객 키 없음 | 전환 실패가 아니다. Step 6의 Owner 키 등록 필요 |
| 라우트 401 `authentication_required` | 인증 전 단계 | 코드 배포는 정상. Owner 세션으로 재확인 |

고객 키 복호화 실패는 읽기 전용 분류기로 판정할 수 없다. 분류기는 봉인 값·행 값을 투영하지 않으며, 이 경로는 `tests/test_5121_byok_key_separation.py`의 실제 AES-GCM 계약과 인증된 런타임 응답으로만 확인한다.

제품별 확인은 기존 #5138·#5145 증거를 재사용한다. 각 제품에서 `custom` 선택 요청 1회의 응답 계약만 확인하고, 실패 시 같은 요청을 반복하지 않고 위 표의 코드로 원인을 판정한다.

중단 조건:

- Step 1~5 중 하나라도 `PENDING`·`BLOCKED`·`FAILED`이면 다음 단계로 진행하지 않는다.
- `MIGRATION_053_DRIFT`, `D1_OWNERSHIP_VIOLATION`, `EVIDENCE_INVALID`는 중단 사유다. 테이블·행·Secret 값을 임의로 수정해 우회하지 않는다.
- 런타임 503은 코드별로 1회만 재현 확인한다. 원인이 판정되면 해당 단계만 복구하고 전체 제품 요청을 반복하지 않는다.
- 복구는 §6 롤백 절차를 사용하며, 행 삭제·덮어쓰기와 D1 데이터 변경은 하지 않는다.

## 5. Legacy v1 → v2 재봉인 검증 절차

현재 운영 행은 0건이므로 이 절차는 `STEP_7_LEGACY_RESEAL_HASH_CHECK=NOT_APPLICABLE`이다. 향후 v1 행이 존재하는 상태에서 전환할 때 사용한다.

사전 조건: `PADIEM_CHAT_SESSION_SECRET`의 현재 값 또는 `PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS`에 과거 세션 Secret이 설정되어 있어야 한다.

1. 읽기 전용으로 대상 행의 `sealed_credential` SHA-256, `key_last4`, `created_at`, `updated_at`을 기록한다.
2. Owner 읽기 1회를 실행한다. 읽기 경로가 v1으로 복호화한 뒤 v2로 재봉인한다.
3. 같은 행을 다시 읽어 다음을 확인한다.
   - `sealed_credential` SHA-256이 1회 변경됨
   - `key_last4`, `created_at`, `updated_at`이 그대로임
   - 두 번째 읽기에서는 봉인 값이 더 이상 변하지 않음
4. legacy ring을 제거한 구성으로 읽어도 성공하는지 확인한다.

집중 테스트는 실제 AES-GCM으로 같은 계약을 검증한다.

```powershell
py -3 -m pytest apps/padiem-chat/tests/test_5121_byok_key_separation.py -q
```

포함 항목:

- v1 봉인 → v2 재봉인 및 legacy 키로의 복호화 거부
- legacy ring 제거 후 v2 단독 읽기
- 변조된 ciphertext의 fail-closed 및 행 미변경
- 잘못된 전용 키의 503 매핑과 공급사 미호출

## 6. 롤백

- 코드: 기존 `rollback_production_code` 모드와 기록된 `previous_version_id`를 사용한다.
- 기능 비활성화: Worker의 `PADIEM_CHAT_CUSTOM_KEY_SECRET`을 제거하면 BYOK 경로만 503이 되고 B14 관리 경로는 유지된다. D1 테이블은 additive이므로 삭제하지 않는다.
- 키 불일치: 이전 전용 키 값을 다시 공급하고 `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS`에 해당 값을 넣어 읽기를 복구한다. v2 행을 삭제하거나 덮어쓰지 않는다.
- Migration: 되돌릴 필요가 없다. 빈 테이블은 관리 경로에 영향을 주지 않는다.

## 7. 향후 전용 키 회전

1. 현재 키를 `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS`에 먼저 등록한다(Worker와 COM2 양쪽).
2. 새 키로 교체한다.
3. Owner 읽기가 발생할 때 각 행이 새 키로 재봉인된다.
4. 재봉인 완료를 확인한 뒤 previous ring을 제거한다.

`register-local --replace`는 1단계 이전에 실행하지 않는다. previous ring 없이 교체하면 기존 v2 행을 읽을 수 없다.

## 8. 금지·경계

- Secret 원문 출력, argv 전달, PR/로그/스크린샷 게시 금지
- preflight 외 명령의 무단 실행 금지. 모든 변경 명령은 `--confirm-*`과 exact-main 검증을 요구한다.
- 운영 D1 데이터·R2 객체·DNS·Tunnel·라우트 변경 금지
- LOCAL A 데이터/Secret/백업, LOCAL D UI 파일, 다른 모델 작업 디렉터리 수정 금지
- 활성 모델 정책 변경 금지. BYOK 검증은 명시적 `custom` 선택 요청에만 적용한다.
