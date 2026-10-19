# PADIEM BYOK / B14 독립 검증 분류 원칙 (2026-10-19)

관련: #5121 (BYOK 구현), #4317 (Chat), #3936 (Claw), #4316 (B66), #4318 (플랫폼/B14), #5108 (관리자), #5002 (테스트 정합화).

## 대표 지시와 목적

현재 B14의 모델·Secret·라우팅 오류가 각 제품의 업무 로직 테스트를 불필요하게 중복 차단한다. **제품 기능의 실제 모델 사용 검증과 B14 경유 통합 검증을 분리**하고, 고장 난 경계의 소유자를 식별하여 동일 장애에 대해 Chat/Claw/B66의 검사를 반복하지 않는다.

PADIEM Custom(BYOK)이 구현·검증되면 **고객 소유 자격증명으로 공급사를 직접 호출하는 B14 비경유 실행**을 제품 기능 수용 증거로 인정할 수 있다. BYOK 성공만으로 B14의 모델 선택·등급·폴백 또는 전체 플랫폼 경로 완료를 주장하지 않는다. **미구현·미실증 경로에서 PASS를 선기록하지 않는다.**

## 필수 시험 구분

| 분류 코드 | 시험 경계 | BYOK 단독 증거로 통과 가능? | 책임 이슈 |
|---|---|---|---|
| PRODUCT_ONLY | Chat 대화 생성·저장·복원·프로젝트·파일, AI 후처리 UI | YES: 제품 기능의 BYOK 종단 실제 실행이 확인된 경우 | #4317 |
| PRODUCT_ONLY | Claw AI 업무 계획·후속 대화·도구 선택·작업 결과 반환 | YES: BYOK + 실제 도구/승인 경로를 통과한 해당 시나리오 | #3936 |
| PRODUCT_ONLY | B66 단계별 견적 대화·필드 확인·생성·PDF·후속 수정 | YES: BYOK 모델 결과에서 실제 견적/PDF 업무 완료한 해당 시나리오 | #4316 |
| SHARED_NONMODEL | 공통 로그인·세션·고객 격리, 파일 저장·조회, P01 승인/취소·상태 복원, 데이터 무결성 | 모델과 독립된 테스트는 모델 호출 불필요. AI 연계 시 BYOK 사용 가능하나 독립된 서버/권한 증거 필요 | #4317/#3936/#4316 |
| B14_ONLY | B14 Registry, provider credential, 모델별 readiness, default, tier entitlement, Beam·LongCat 순서, fallback, router SSE, B14 오류/회복 | **NO** — 반드시 실제 B14 경유 테스트 | #4318 및 해당 B14 구현 이슈 |
| FULL_PLATFORM | 실제 PADIEM 기본 모델 선택 → B14 → 공급사 → 제품 기능 반환, B14와 제품 사이 권한·SSE·복구 | **NO** — 실제 B14 경유 증거 필요 | #4318 + 제품별 원장 |
| BYOK_PATH | 고객 키 보관·철회·tenant 격리, 직접 공급사 호출, 키 비노출, 응답 계약 | YES — 실제 BYOK 경로의 독립 테스트 | #5121 |

## 결과 기록 계약

테스트 증거마다 아래를 기록한다.

```text
ISSUE / SCENARIO / SURFACE=CHAT|CLAW|B66|P01|B14
PATH=BYOK_DIRECT|B14_MANAGED|NO_MODEL|MOCK
PROVIDER_MODEL=명시적 모델 ID 또는 NA
ENV=UNIT|LOCAL|STAGING|PRODUCTION
BUILD_SHA / SERVED_VERSION(운영 테스트일 때)
AUTH_SCOPE=인증/테넌트 증거
RESULT=PASS|FAIL|BLOCKED|NOT_RUN
FAILURE_OWNER=B14|BYOK|PRODUCT|AUTH|DATA|TOOL|INFRA|UNKNOWN
EVIDENCE=테스트/로그/PR/실행 식별자(비밀 제외)
```

- `PATH=MOCK`인 테스트는 로직 계약만 증명하며 실제 모델 종단 E2E가 아니다.
- `PRODUCT_E2E_BYOK=PASS`는 해당 제품·시나리오의 통과를 뜻한다.
- `B14_E2E=PASS`와 `PLATFORM_FULL_E2E=PASS`는 별도 증거가 있을 때만 기록한다.
- 모델 공급사 장애/인증 실패를 특정하려면 **첫 실패 지점과 반환 오류 코드**를 저장한다. 동일 코드·버전·공통 B14 경로로 재현된 장애는 #4318에 대표 증거 1건을 기록하고 각 제품 원장에는 링크만 남긴다.
- B14 오류가 확인된 뒤 동일 조건의 Chat/Claw/B66 공급사 호출을 반복하지 않는다. 모델 이후 제품 로직의 확인은 BYOK_DIRECT 또는 기존 모의 응답 계약 테스트로 진행한다.
- BYOK가 실패해도 B14가 원인이라고 분류하지 않는다. `FAILURE_OWNER=UNKNOWN`이면 경계별 분리 진단 후 확정한다.
- 제품 전용 오류가 발생한 경우 해당 제품 원장만 재검증하고, 공유 B14 전체 회귀를 임의로 재실행하지 않는다.
- 변경 영향이 있는 경계만 집중 재검증한다. 신규 포괄 테스트와 공급사 유료 호출을 자동 선행조건으로 만들지 않는다.

## 적용 우선순위

1. #5121에서 실제 BYOK_DIRECT 최소 호출 구현/검증, 요청에 명시한 경우만 선택.
2. #4317/#3936/#4316 원장에 제품 기능의 PATH별 수용 상태를 분리 기록.
3. #4318은 B14_MANAGED 필수 경로만 수집·검증. 각 제품은 같은 B14 장애 원장 링크 재사용.
4. #5002 테스트 갱신 시 비활성 `b14/auto`를 다시 사용하거나 잘못된 모델 정책을 테스트 기대값에 고정하지 않는다.
5. #5108에서 관리자 B14 상태 및 BYOK 연결 상태를 혼동하지 않도록 구분.

이 원칙은 테스트 증거의 귀속과 중복 검사 감소를 위한 기술 절차이며, 새로운 고객 요금/이용 제한 정책을 설정하지 않는다.

## #5002 구현 반영 (2026-10-19)

- `apps/padiem-chat/tests/model_path_manifest.json`이 각 모델 경계 테스트 모듈을
  `BYOK_DIRECT` / `B14_MANAGED` / `NO_MODEL` / `MOCK`으로 분류하고, conftest가
  모듈당 정확히 하나의 pytest marker를 부여한다. `test_5002_model_path_classification.py`는
  `app.b14_client`를 새로 import한 테스트가 분류 없이 `NO_MODEL`로 빠지면 실패한다.
- `.github/workflows/b62-padiem-chat-ci.yml`의 FULL 제품 회귀는 B14 계약 job을
  계속 실행하되 그 실패로 `b62-test`를 연쇄 실패시키지 않는다. B14 job의 실패는
  자체 check로 표시되고, 최초 실패 증거는 #4318에 1회 기록한 뒤 제품 원장은 링크만
  남긴다. `b14_only`(B14 소스)와 `b14_tests_only`(B14 테스트) 범위는 검토 대상
  자체가 B14이므로 계속 B14 계약 성공을 요구한다.
- CI summary는 `PRODUCT_E2E_BYOK`, `PRODUCT_E2E_BYOK_LIVE`, `B14_E2E`를 별도로 출력한다.
  `PRODUCT_E2E_BYOK=INTEGRATION_MOCK`은 실제 ASGI·D1 저장소를 쓰되 공급사 전송을
  `MockTransport`로 대체한 통합 증거이며, LIVE 공급사 호출 증거가 아니다.
  `PRODUCT_E2E_BYOK_LIVE`와 `B14_E2E`는 별도 승인·실행 전까지 `NOT_RUN`이다.
- 기본 모델 기대값은 `product_tier_routes`의 활성 route에서 파생한다. Free/Plus/Pro/Max의
  현재 승인 설정은 변경하지 않고, `b14/auto`는 계속 executable 집합 밖이다.

## #5002 제품별 BYOK E2E 자동화 (2026-10-19)

`apps/padiem-chat/tests/test_5002_byok_product_e2e.py`(marker `byok_direct`,
`PATH=BYOK_DIRECT`)가 실제 ASGI 앱, 실제 `D1HistoryStore`(SQLite + migration
001/002/042/053), 실제 `D1CustomProviderCredentialStore`를 사용하고 공급사 전송만
`httpx.MockTransport`로 대체해 다음을 검증한다.

- Chat 일반/스트림 요청의 공급사 호출, 대화 저장, 다음 턴의 서버 저장 이력 복원
- 테넌트별 키·세션·대화 격리와 타 고객 대화 이어쓰기 거부(공급사 호출 0회)
- 키 교체·삭제의 즉시 반영과 삭제 후 `custom_credential_required` 거부
- 공급사 429/5xx 오류 시 오류 코드 매핑, vendor 본문 비노출, 대화 미저장
- B14 클라이언트·라우터·카탈로그·정책 저장소 실패 주입에서 BYOK 통과(`B14_CALL_COUNT=0`)
- 같은 주입에서 관리 경로는 502 `b14_injected_failure`로 실제 실패(음성 대조)

| SURFACE | RESULT | 비고 |
|---|---|---|
| CHAT | `PRODUCT_E2E_BYOK=INTEGRATION_MOCK` | 공급사는 MockTransport. LIVE 아님 |
| CLAW | `NOT_RUN` | 구현·테스트는 미병합 PR #5137에 있음. 중복 개발하지 않음 |
| B66 | `NOT_RUN` | 동일 |
| B14 | `B14_E2E=NOT_RUN` | BYOK 경로의 B14 호출 0회만 검증 |

`LIVE_VERIFIED=NO`: 승인되지 않은 유료/실제 공급사 호출은 수행하지 않았다.

## #5121 BYOK 암호화 키 독립화 (2026-10-19)

`apps/padiem-chat/app/byok_credentials.py`는 이제 고객 공급사 키를
`PADIEM_CHAT_CUSTOM_KEY_SECRET`에서 파생한 전용 AES-GCM 키(v2 purpose)로
봉인한다. 세션 쿠키 Secret은 새 암호문의 키가 아니다.

| Secret/설정 | 역할 |
|---|---|
| `PADIEM_CHAT_CUSTOM_KEY_SECRET` | 현재 쓰기·읽기 키. 32자 이상 |
| `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS` | 교체된 전용 Secret의 쉼표 목록. v2 복호화 전용 |
| `PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS` | 분리 이전 session_secret의 쉼표 목록. v1 복호화 전용 |

- 현재 `PADIEM_CHAT_SESSION_SECRET`도 v1 복호화 후보에 자동 포함된다.
- 읽기 시 현재 키 → 이전 전용 키 → legacy session 키 순서로 시도하고, 이전 키로
  열린 행은 `sealed_credential`만 현재 키로 재봉인한다. `key_last4`/`created_at`/
  `updated_at`은 유지한다.
- AAD는 `padiem-custom:{user_id}:{provider_id}`로 유지된다.
- 전용 Secret이 없거나 32자 미만이면 저장소를 구성하지 않아
  `/api/chat/custom/*`와 BYOK 채팅이 503으로 fail-closed 된다.
- 모든 키로 복호화할 수 없으면 `CustomCredentialDecryptionError`로 503 처리하며
  원문·키·봉인문은 응답/로그에 포함하지 않는다.

단계적 전환 순서(운영 Secret 등록·배포는 별도 승인 작업):

1. `PADIEM_CHAT_CUSTOM_KEY_SECRET`을 등록한다.
2. 현재 세션 Secret이 그대로인 상태에서 배포하면 기존 v1 행이 자동으로 읽히고
   v2로 재봉인된다.
3. 세션 Secret을 먼저 교체한 경우 이전 값을
   `PADIEM_CHAT_CUSTOM_KEY_LEGACY_SESSION_SECRETS`에 넣어 배포한다.
4. 재봉인이 끝난 것을 확인한 뒤 legacy 목록을 제거한다.
5. 전용 Secret 교체 시 이전 값을 `PADIEM_CHAT_CUSTOM_KEY_PREVIOUS_SECRETS`에 둔 채
   새 값을 배포하고, 이후 이전 값 목록을 제거한다.

검증: `apps/padiem-chat/tests/test_5121_byok_key_separation.py` (`byok_direct`).
이 문서는 소스·테스트 기준이며, 운영 Secret 등록과 배포 완료를 뜻하지 않는다.
