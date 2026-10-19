# #5121 BYOK 전용 키 운영 전환 Runbook (2026-10-19)

관련: #5121 (BYOK 구현), PR #5131·#5137·#5143 (병합 구현 재사용), #5002 (모델 경로 분리), #4317/#3936/#4316 (제품 원장).

이 문서는 **전환 준비** 문서다. 2026-10-19 기준 운영 D1·Worker Secret·Worker 코드·DNS·Tunnel은 변경하지 않았다. 실행 명령은 승인된 운영 창에서만 사용한다.

## 1. 확인된 현재 상태

`scripts/ops/byok_key_transition.py preflight` 읽기 전용 실행 결과:

```text
DPAPI_CUSTOM_KEY_SECRET=MISSING
WORKER_CUSTOM_KEY_SECRET=MISSING
D1_MIGRATION_053=MISSING
CUSTOM_CREDENTIAL_ROWS=TABLE_MISSING
DEPLOYED_BYOK_ROUTE=ABSENT
BYOK_TRANSITION_READY=NO
SECRET_VALUES_PRINTED=0
```

확인 내용:

- COM2 DPAPI 저장소에 `PADIEM_CHAT_CUSTOM_KEY_SECRET`이 없다. `PADIEM_CHAT_SESSION_SECRET`은 존재한다.
- Cloudflare Worker `padiem-chat`의 Secret 이름 목록에 `PADIEM_CHAT_CUSTOM_KEY_SECRET`이 없다.
- 운영 D1 `padiem-chat-db`에 `chat_custom_provider_credentials` 테이블이 없다. 기존 고객 BYOK 행은 0건이다.
- `GET https://chat.padiem.net/api/chat/custom/credential`은 404다. BYOK 코드가 운영 Worker에 배포되지 않았다.
- COM2 로컬 런타임의 고정 릴리스 디렉터리에는 `app/byok_credentials.py`가 없다. 로컬 런타임도 BYOK 코드 이전 상태다.
- 2026-10-19 확인 시 Governance 로컬 경로 `G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-governance`는 이 호스트에서 접근할 수 없었다. 상태 표기: `GOVERNANCE=NOT_READ`.

## 2. 전환 전제

- 전환 대상 main SHA는 40자 전체 SHA로 고정한다. PR merge commit을 사용한다.
- **하나의 전용 키 값을 COM2 DPAPI와 Cloudflare Worker에 동일하게 공급한다.** 두 런타임이 같은 D1의 봉인 행을 읽으므로 값이 다르면 한쪽은 503으로 fail-closed 된다.
- 전용 키는 최소 32자이며 앞뒤 공백이 없어야 한다. 스크립트가 생성·검증한다.
- Secret 원문은 argv, 로그, PR, 화면, 셸 기록에 남기지 않는다. 업로드는 stdin으로만 전달한다.
- Cloudflare 인증은 기존 OAuth 자식 프로세스를 사용하고 `CLOUDFLARE_API_TOKEN` 계열 환경변수는 제거한다. 계정 ID는 공개 보고서에 기록하지 않는다.
- 운영 배포는 기존 `B62 Production Code Deploy Gate`만 사용한다. 수동 `wrangler deploy` 경로를 새로 만들지 않는다.
- DNS, Tunnel, 라우트, D1 데이터, R2 객체는 이 절차에서 변경하지 않는다.

## 3. 실행 순서

### Step 0 — 읽기 전용 preflight

```powershell
py -3 scripts/ops/byok_key_transition.py preflight --account-id <ACCOUNT_ID>
```

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

### Step 2 — COM2 DPAPI에 전용 키 등록

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

### Step 3 — 동일 값을 Worker에 공급

반드시 기존 hidden-input store를 통해 실행한다. `store.py run`이 DPAPI 값을 자식 환경으로 주입하며 값은 argv에 없다.

```powershell
py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py run `
  py -3 scripts/ops/byok_key_transition.py upload-worker `
  --account-id <ACCOUNT_ID> --confirm-upload
```

`--account-id`는 DPAPI/환경에 이미 있으면 생략할 수 있다. 스크립트는 `wrangler secret put`에 stdin으로 값을 전달하고, 출력에서 값을 `[REDACTED]`로 치환한 뒤 `secret list`로 이름만 재확인한다.

### Step 4 — Migration 053 적용

정확한 main 체크아웃에서만 실행한다. 스크립트는 `git rev-parse HEAD`가 `--expected-main`과 같은지 확인한 뒤 additive 테이블을 생성하고 존재를 재확인한다.

```powershell
py -3 scripts/ops/byok_key_transition.py apply-migration `
  --expected-main <EXACT_MAIN_SHA> `
  --account-id <ACCOUNT_ID> `
  --confirm-apply APPLY_BYOK_053_FROM_EXACT_MAIN
```

Migration 내용은 `CREATE TABLE IF NOT EXISTS` 하나이며 기존 테이블을 변경·삭제하지 않는다. 현재 기존 행이 0건이므로 legacy 재봉인 대상도 0건이다.

### Step 5 — 준비 완료 확인

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

### Step 6 — Owner 범위 실제 검증

1. Owner 세션으로 `PUT /api/chat/custom/credential`에 공급사 API 키를 등록한다.
2. `GET /api/chat/custom/credential` 응답의 `key_last4`만 확인한다. 원문 키가 응답에 없는지 확인한다.
3. Chat, Claw(`/api/claw/general`), B66(`/api/b66/ai/chat`, `/api/b66/quote/interpret`)에서 각각 1회씩 `custom` 선택 요청을 실행한다.
4. 각 요청의 응답 계약과 제품 결과를 확인한다. B14 router/registry/default 경로가 호출되지 않아야 한다.
5. D1 행은 `SELECT key_last4, length(sealed_credential), created_at, updated_at`만 조회한다. `sealed_credential` 원문과 고객 키는 보고서에 넣지 않는다.

이 검증은 BYOK_DIRECT 증거다. B14_MANAGED 또는 FULL_PLATFORM 통과 증거로 기록하지 않는다.

## 4. Legacy v1 → v2 재봉인 검증 절차

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

## 5. 롤백

- 코드: 기존 `rollback_production_code` 모드와 기록된 `previous_version_id`를 사용한다.
- 기능 비활성화: Worker의 `PADIEM_CHAT_CUSTOM_KEY_SECRET`을 제거하면 BYOK 경로만 503이 되고 B14 관리 경로는 유지된다. D1 테이블은 additive이므로 삭제하지 않는다.
- 키 불일치: 이전 전용 키 값을 다시 공급하고 `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS`에 해당 값을 넣어 읽기를 복구한다. v2 행을 삭제하거나 덮어쓰지 않는다.
- Migration: 되돌릴 필요가 없다. 빈 테이블은 관리 경로에 영향을 주지 않는다.

## 6. 향후 전용 키 회전

1. 현재 키를 `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS`에 먼저 등록한다(Worker와 COM2 양쪽).
2. 새 키로 교체한다.
3. Owner 읽기가 발생할 때 각 행이 새 키로 재봉인된다.
4. 재봉인 완료를 확인한 뒤 previous ring을 제거한다.

`register-local --replace`는 1단계 이전에 실행하지 않는다. previous ring 없이 교체하면 기존 v2 행을 읽을 수 없다.

## 7. 금지·경계

- Secret 원문 출력, argv 전달, PR/로그/스크린샷 게시 금지
- preflight 외 명령의 무단 실행 금지. 모든 변경 명령은 `--confirm-*`과 exact-main 검증을 요구한다.
- 운영 D1 데이터·R2 객체·DNS·Tunnel·라우트 변경 금지
- LOCAL A 데이터/Secret/백업, LOCAL D UI 파일, 다른 모델 작업 디렉터리 수정 금지
- 활성 모델 정책 변경 금지. BYOK 검증은 명시적 `custom` 선택 요청에만 적용한다.
