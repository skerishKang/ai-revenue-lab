# padiem-auth 상태 저장소 이전 설계 (#8772 단계 1~3)

## 범위와 기준

- 기준 리비전: `1231983a1b7fc689257ed2991bf8ef45689c50f4`
- 이 문서가 다루는 범위: 설계·인벤토리, `apps/padiem-auth-state` 서비스, Worker의 저장소 전환 스위치.
- 비목표: 운영 전환, 데이터 이전, Worker 배포, 비밀 변경, 실제 서버 설치, 로그인 화면·문구·동작 변경.
- 기본 저장소는 기존 Durable Object다. 컴2 저장소를 선택했을 때 그 저장소가 실패하면 DO로 재시도하지 않는다.

## 현재 상태 호출 경로

`apps/padiem-auth/worker.mjs:377`의 `stateBindingFor(env)`가 유일한 상태 RPC 어댑터다. 각 호출은 아래 형태를 사용한다.

```js
env.AUTH_STATE.get(env.AUTH_STATE.idFromName(name))
  .fetch(`https://internal/${method}`, { method: 'POST', body: JSON.stringify(args) })
```

성공 응답의 `{ value }`만 반환하고, 실패하면 `state failed` 예외를 던진다. Worker 진입점은 `worker.mjs:1487`에서 이 어댑터를 `createApp`에 주입한다. `AuthStateObject.fetch`는 `worker.mjs:1189`의 메서드 허용 목록, `state.mjs`의 SQL, 일부 계정·복구·삭제 오버라이드를 실행한다.

## `idFromName` 이름 종류

| 이름 종류 | 실제 이름 | 격리 단위 | 용도 |
|---|---|---|---|
| 전역 계정 레지스트리 | `google-account-registry` | 서비스 전체 1개 | 계정, 차단, 연결, 삭제, 복구, 이메일 확인, 세션 색인 |
| 전역 연령 확인 | `google-age-confirmation` | 서비스 전체 1개 | 연령 확인 기록과 중복 제출 결과 |
| 전역 비밀번호 로그인 게이트 | `password-login-gate` | 서비스 전체 1개 | IP·시간대 예산, 로그인 실패 일일 예산 |
| 전역 클라이언트 assertion 재생 방지 | `client-assertion-replay` | 서비스 전체 1개 | 클라이언트 assertion JTI 1회 사용 |
| 로그인·코드·세션 객체 | 로그인 시작 때 만든 43문자 난수 | 로그인 흐름 1개 | 로그인 요청, 1회용 코드, 프로필, 세션, 갱신 토큰 |
| 세션 폐기 대상 객체 | `auth_session_index.object_id` | 기존 로그인 객체 1개 | 계정 차단·삭제·비밀번호 변경 시 세션 폐기 |

계정 이름으로 Durable Object를 만들지는 않는다. 계정별 격리는 전역 레지스트리 표의 `account_id`, `fingerprint`, `product_user_id`와 테이블 제약조건으로 수행한다.

## 노출 RPC 메서드

`worker.mjs:1189`의 허용 목록 44개다.

```text
createLogin, consumeLogin, beginPasswordAttempt,
claimAssertion, loginFailureBudget, resetLoginFailureBudget,
createCode, exchangeCode, inspectRefresh, rotate, revoke,
forceRevokeForAccountDeletion, indexAccountSession,
beginAccountDeletion, indexedAccountSessions, releaseAccountDeletion,
finalizeAccountDeletion, pruneAccountDeletionAudit, nextAccountDeletionAuditExpiry,
resolveAccount, accountById, accountCreatedAt, ageConfirmedAt, putAccount,
createAgeConfirmation, readAgeConfirmation, consumeAgeConfirmation,
claimAgeConfirmation, recordAgeConfirmationResult, readAgeConfirmationResult,
setAccountStatus, identityIsDeleted, clearIdentityDeletion,
recordAccountChatUsers, accountIdsForChatUser,
pendingChatAccountDeletions, completeChatAccountDeletion,
passwordBindingRefused, emailRecoveryCandidate, completeEmailRecovery,
passwordEmailConfirmed, reserveEmailConfirmation,
recordEmailConfirmationToken, completeEmailConfirmation
```

`state.mjs` 자체에는 위 목록 외에 `passwordCredentialEpoch`, `passwordRecoveryAccount`, `recordPasswordCredentialEpoch`, `accountByFingerprint`, `clearExpiredProfiles`, `createSession`, `consumeCode`가 있다. 이들은 Worker RPC로 직접 노출하지 않고 상위 메서드 내부에서 사용한다. 컴2 서비스도 `state.mjs`를 그대로 import하므로 SQL과 이러한 내부 메서드를 복제하지 않는다.

## 표별 쓰기 시점과 보존 기간

빈도는 운영 측정값이 아니라 현재 코드의 호출 경로에서 도출한 상대 빈도다.

| 표 | 주요 쓰기 시점 | 현재 보존·정리 |
|---|---|---|
| `blocked_accounts` | 계정 차단 시 1행 | 해제 미구현, 계정 삭제 시에도 명시 삭제 없음 |
| `google_accounts` | 최초 계정 생성, 최초 생성 시각·연령 확인 보완 | 계정 삭제까지 |
| `client_assertions` | 허용된 assertion JTI마다 1행 | 만료 시각은 창 끝 또는 최대 600초, 다음 claim 때 만료 행 삭제 |
| `login_requests` | 로그인 시작 시 1행, 소비·시도 초과 시 갱신 | 만료 600초, 명시 만료 정리 없음 |
| `age_confirmations` | 연령 게이트 생성·claim·결과 기록 | 게이트 600초, 결과 60초, 생성/소비 시 만료 행 정리 |
| `password_attempts` | 이메일 폼 시도마다 갱신 | 만료 600초, 다음 시도 때 정리 |
| `codes` | 로그인 완료 코드 발급, 교환 시 소비 | 만료 60초, 명시 삭제 없음 |
| `code_profiles` | 프로필이 있는 코드 발급 | 만료 60초, 교환 또는 alarm 때 정리 |
| `sessions` | 코드 교환 시 1행, 폐기 시 갱신 | 세션 30일, 명시 만료 삭제 없음 |
| `refresh_tokens` | 세션 생성 1행, 갱신마다 선행 갱신+후행 삽입 | 세션 수명과 함께 DO 퇴거에 의존, token 자체 만료 열 없음 |
| `auth_session_index` | 코드 교환 후 계정당 1행 | 만료 30일, 계정 삭제 외 정리 없음 |
| `account_deletion_locks` | 삭제 시작·재시도 | 임대 300초, 시작/해제/완료 시 정리 |
| `account_deletion_audit` | 계정 삭제 완료 | 365일, 완료 또는 alarm 때 정리 |
| `identity_deletion_tombstone` | 계정 삭제 | 명시적 재가입 전까지 유지 |
| `account_chat_users` | 계정↔Chat 사용자 연결 | 계정 삭제까지 |
| `pending_chat_account_deletions` | 마지막 연결 삭제 | Chat 삭제 완료까지 재시도 |
| `password_credential_epochs` | 비밀번호 자격 연결 | 계정 삭제까지 |
| `email_confirmation_tokens` | 확인 메일 발급 | 만료 7일, 재발급·완료 시 정리 |
| `email_confirmations` | 이메일 확인 완료 | credential epoch과 함께 계정 삭제까지 |
| `email_confirmation_budget` | 확인 메일 허용 시 원천·전체 버킷 갱신 | 원천은 시간, 전체는 일 단위, 다음 예약 때 만료 행 정리 |
| `login_failure_budget` | 로그인 실패 시 원천·일별 갱신 | 일 단위, 다음 조회/충전 때 만료 행 정리 |
| `auth_state_nonces` (신규) | 인증된 RPC마다 nonce 1행 | 시각 허용 오차 300초, 만료 행 정리 |

## 쓰기 낭비와 축소 방법

1. **매 호출 만료 정리 DELETE**: `claimAssertion`, `loginFailureBudget`, `beginPasswordAttempt`, `createAgeConfirmation`, `beginAccountDeletion`, `reserveEmailConfirmation`, `recordEmailConfirmationToken`가 호출마다 만료 행을 삭제한다. 만료 조건은 모든 조회·쓰기에 그대로 두고, 삭제는 주기적 maintenance로 모은다. 단, nonce 재생 방지는 만료 행 정리와 새 nonce 삽입을 원자적으로 수행한다.
2. **DO 퇴거에만 의존하는 장기 보존**: `login_requests`, `codes`, `sessions`, `refresh_tokens`, `auth_session_index`는 단일 SQLite 서비스로 옮기면 DO의 자동 퇴거가 사라진다. 만료된 코드·로그인·시도·세션·토큰·세션 색인을 같은 만료 기준으로 주기적으로 제거해야 한다. 만료 세션은 모든 조회·갱신·폐기 경로에서 이미 거부된다.
3. **갱신마다 2행 이상**: `rotate`는 선행 토큰 갱신과 후행 토큰 삽입을 원자적으로 수행한다. 30초 재시도 창을 유지하되, 세션 만료·폐기 이후 후행 토큰과 오래된 체인을 함께 정리한다.
4. **계정 행의 다중 쓰기**: `putAccount`는 삽입, 생성 시각 보완, 연령 확인 보완을 나눠 수행한다. 첫 값만 보존하는 의미는 유지하면서 하나의 조건부 UPSERT로 묶을 수 있다. 이번 단계에서는 계약 동일성을 우선해 기존 SQL을 그대로 둔다.
5. **코드 교환의 중복 정리**: `exchangeCode`는 프로필 삭제 후 같은 digest를 한 번 더 삭제한다. 현재 두 번째 DELETE는 일반적으로 0행이지만, 단일 조건부 DELETE로 줄일 여지가 있다.
6. **세션 색인 쓰기와 stale 행**: 코드 교환마다 `sessions`와 별개로 `auth_session_index` 1행이 추가된다. 계정 차단·삭제·비밀번호 변경의 세션 폐기에 필요하므로 유지하되, 만료된 색인이 불필요한 폐기 RPC를 만들지 않도록 만료 세션과 같은 maintenance 주기로 제거한다.
7. **재시도성 연결 기록**: `recordAccountChatUsers`와 삭제 준비의 선택적 연결 스냅샷은 이미 있는 행에도 `ON CONFLICT DO NOTHING`을 호출한다. 실제 변경이 없는 행은 쓰지 않지만 호출 수가 늘 수 있으므로, 연결 스냅샷은 변경이 있을 때만 갱신한다.

## 컴2 서비스 설계

- Node HTTP 서비스 뒤에 기존 터널을 두고, Worker는 HTTPS로만 호출한다.
- SQLite는 WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout`을 사용한다. 각 상태 메서드의 `transactionSync`는 `BEGIN IMMEDIATE`로 직렬화한다.
- `state.mjs`를 그대로 import하고 `this.sql.exec`/`this.storage.transactionSync`를 Node SQLite 어댑터로 제공한다. 계정·복구·삭제 오버라이드도 가능한 한 기존 `AuthStateObject`를 재사용한다.
- 객체 이름별 인스턴스와 직렬화 큐를 유지한다. 전역 레지스트리의 비동기 account 작업은 기존 DO의 `blockConcurrencyWhile`와 같은 이름 단위 직렬화를 제공하고, 세션 객체의 SQL 트랜잭션은 SQLite가 원자적으로 보호한다.
- Worker 인증은 요청 본문 원문·메서드·경로·시각·nonce를 HMAC-SHA256으로 서명한다. 시각 허용 오차는 ±300초, nonce는 1회만 허용하며, 본문 크기와 JSON 형식을 검증한다. 비밀 값은 코드·시험·로그·문서에 넣지 않는다.
- 응답은 DO와 같이 성공 시 `{ value }`, 상태 실패 시 `{ error: 'state_failure' }`를 반환한다. 서명·시각·nonce 오류는 각각 거절하고 본문·헤더·비밀을 로그에 남기지 않는다.

## 전용 identity·삭제 기록 브리지

기존 공유 identity HTTPS ingress와 삭제 기록 서비스 바인딩을 컴2에 그대로 노출하지 않는다. 대신 identity Worker에 default-off인 auth-state 전용 문을 둔다.

- identity 전용 문: `/internal/auth-state/identity/<method>`, 비밀 `PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET`, v2 서명, 허용 메서드는 `resolve_or_create_identity_subject`, `resolve_or_create_product_link`, `list_active_product_links_for_subject` 3개뿐이다.
- 삭제 기록 전용 문: `/internal/auth-state/deletion-record/<method>`, 비밀 `PADIEM_AUTH_STATE_DELETION_RECORD_RPC_SECRET`, v2 서명, 허용 메서드는 `resolve_subject_removed_by_account_deletion` 1개뿐이다.
- 두 문은 기존 공유 ingress 비밀로 열리지 않으며, 비secret 설정 시 404를 유지한다. 재전송 ID는 기존 identity Durable Object의 replay 표를 사용한다.
- 컴2에는 Worker↔상태 서비스·identity·삭제 기록 전용 비밀만 둔다. 기존 Chat 비밀번호 RPC 비밀과 identity HMAC 키는 Worker에만 남긴다.
- `completeEmailRecovery`는 기존 Chat 비밀과 identity HMAC 키를 필요로 하므로 Worker에서 오케스트레이션을 유지하고, 상태 메서드만 컴2를 호출한다. 삭제 복구의 로컬 tombstone은 컴2가 커밋한 뒤 Chat 정리는 Worker가 이어서 수행한다. 이 내부 handoff는 Worker가 제거하고 공개 응답은 기존 `{ state: 'deleted' }`를 유지한다.

## Worker 전환 스위치

- `AUTH_STATE_BACKEND`: `do` 또는 `com2`, 미설정은 기본 DO로 동작한다. 알 수 없는 명시 값은 fail-closed다.
- `AUTH_STATE_URL`: 컴2 서비스의 HTTPS origin.
- `AUTH_STATE_SECRET`: Worker와 컴2가 공유하는 HMAC 비밀.
- `do`는 기존 `AUTH_STATE` 바인딩이 반드시 필요하다. `com2`는 URL과 비밀이 반드시 필요하고 DO 바인딩을 사용하지 않는다.
- 컴2 호출의 네트워크 오류·비성공 응답·잘못된 JSON은 즉시 예외로 끝낸다. DO 재호출은 어떤 경우에도 없다.
- 공개 로그인 응답과 화면·문구는 기존 오류 경로를 유지한다. 내부 로그에는 저장소 종류와 실패 단계만 남긴다.

## 수용 기준

- 기존 `apps/padiem-auth/test/*.test.mjs`가 변경 없이 통과한다.
- 컴2 서비스의 동일 입력 결과가 DO 구현과 같다.
- 같은 1회용 코드의 동시 교환은 하나만 성공하고, 같은 갱신 토큰의 동시 회전은 기존 30초 재시도 계약을 지킨다.
- 만료, 재전송, 잘못된 서명, 시각 오차, 본문 변조가 거절된다.
- 기본 DO 경로와 명시적 컴2 경로가 모두 시험되고, 컴2 실패 시 DO 호출이 발생하지 않는다.
