# AI Development Workflow Status Model

상태: Canonical  
적용 범위: 저장소 공통 개발·검증 작업

이 문서는 작업 상태의 의미와 전이 조건을 고정한다. 상태 이름은 완료감이나 자신감을 표현하는 문구가 아니라, 요구된 증거가 존재하는지를 나타내는 운영 계약이다.

## 1. 상태 목록

| Status | 의미 | 진입 조건 | 다음 상태 |
|---|---|---|---|
| `PLANNING` | 제품 목표 또는 기술 범위가 아직 구현 계약으로 고정되지 않음 | 요구 접수 | `WORK_ORDER_READY` |
| `WORK_ORDER_READY` | CTO 작업계약이 exact base SHA와 범위를 포함해 확정됨 | CTO work order 완료 | `IMPLEMENTING` |
| `IMPLEMENTING` | Web Developer가 승인된 branch에서 작업 중 | branch와 scope 확인 | `CI_FAILED`, `CI_PASSED` |
| `CI_FAILED` | 필수 hosted/local automated check 중 하나 이상 실패 | 실패 로그 확보 | `IMPLEMENTING` |
| `CI_PASSED` | 정의된 automated checks가 해당 HEAD에서 통과 | exact HEAD와 결과 확보 | `LOCAL_VALIDATION_REQUIRED`, `CTO_REVIEW` |
| `LOCAL_VALIDATION_REQUIRED` | 실제 환경 검증이 필요하지만 완료되지 않음 | UI·외부 연동·배포 등 해당 | `LOCAL_FAILED`, `LOCAL_PASSED` |
| `LOCAL_FAILED` | exact HEAD의 실제 환경 검증 실패 | 재현 증거 확보 | `IMPLEMENTING` |
| `LOCAL_PASSED` | exact HEAD의 필수 실제 환경 검증 통과 | 원문 증거와 tested SHA 확보 | `CTO_REVIEW` |
| `CTO_REVIEW` | 구현·CI·로컬 증거에 대한 독립 최종 검토 중 | 필수 입력 확보 | `NOT_READY`, `CONDITIONALLY_READY`, `READY` |
| `NOT_READY` | acceptance criteria 또는 안전·회귀 기준을 충족하지 못함 | CTO 판정 | `IMPLEMENTING`, `PLANNING` |
| `CONDITIONALLY_READY` | 제한된 조건이 충족되면 승인 가능하나 현재 즉시 병합 기준은 아님 | CTO가 조건과 위험을 명시 | `CTO_REVIEW`, `READY`, `NOT_READY` |
| `READY` | 현재 exact HEAD가 정의된 병합 기준을 충족 | CTO 최종 판정 | 사용자 승인 후 `MERGED` |
| `MERGED` | 승인된 PR이 default branch에 병합됨 | merge SHA 확보 | `PRODUCTION_VERIFIED` 또는 종료 |
| `PRODUCTION_VERIFIED` | 실제 운영 환경이 승인된 merge/release SHA와 일치하고 핵심 검증을 통과 | 배포 revision과 운영 증거 확보 | 종료 |

## 2. 권한 규칙

### Web Developer가 부여할 수 있는 상태

- `IMPLEMENTING`
- `CI_FAILED`
- `CI_PASSED`
- `LOCAL_VALIDATION_REQUIRED`

Web Developer는 `READY`, `CONDITIONALLY_READY`, `NOT_READY`를 최종 판정으로 부여할 수 없다.

### Local Validator가 부여할 수 있는 상태

- `LOCAL_FAILED`
- `LOCAL_PASSED`

이는 검증 결과이지 병합 승인 판정이 아니다.

### Web CTO만 부여할 수 있는 상태

- `WORK_ORDER_READY`
- `CTO_REVIEW`
- `NOT_READY`
- `CONDITIONALLY_READY`
- `READY`

### User / Product Owner가 승인하는 행동

- 최종 제품 판단
- 병합
- 배포
- scope 또는 acceptance criteria의 제품적 변경

## 3. 상태 전이 규칙

### 3.1 `CI_PASSED`는 `READY`가 아니다

다음 중 하나라도 해당하면 Local Validation 또는 추가 CTO 검토가 필요하다.

- UI·UX 변경
- 브라우저 상호작용
- 외부 API
- 인증·권한·세션
- 데이터베이스
- 운영체제·GPU·장치 종속 기능
- 실제 배포
- CI가 커버하지 않는 회귀 위험

### 3.2 테스트 HEAD가 바뀌면 증거를 재사용하지 않는다

새 commit이 추가되면 이전 HEAD에서 수행한 CI 또는 Local Validation은 새 HEAD의 직접 증거가 아니다.

영향이 없다는 명시적 CTO 판단이 없는 한 관련 검증을 다시 수행한다.

### 3.3 `CONDITIONALLY_READY`는 조건을 구체적으로 기록한다

필수 항목:

- 미충족 또는 외부 의존 조건
- 허용 가능한 이유
- 병합 전 필요한지, 병합 후 필요한지
- 책임자
- 검증 방법
- 실패 시 rollback 또는 중단 조건

막연한 “나중에 확인”은 유효한 조건이 아니다.

### 3.4 `READY`는 사용자 승인과 병합을 대체하지 않는다

`READY`는 기술·제품 기준을 충족했다는 CTO 판정이다. 실제 병합 또는 배포는 별도 사용자 승인 이후 수행한다.

### 3.5 `MERGED`는 production 완료가 아니다

Production surface가 존재하는 작업은 다음을 별도로 확인한다.

- 배포된 revision
- 안정 URL
- 필수 환경변수와 binding
- 핵심 endpoint 또는 browser smoke
- rollback 방법

## 4. 실패 처리

실패 상태에서는 다음을 기록한다.

- failed command 또는 user action
- exact HEAD SHA
- exit code 또는 HTTP/status evidence
- 핵심 오류 원문
- 재현 절차
- 예상 결과와 실제 결과
- source modification 여부

실패를 숨기기 위해 테스트를 삭제·skip·완화하거나 acceptance criteria를 변경해서는 안 된다.

## 5. 권장 PR 상태 표시

PR 본문 또는 CTO 보고에는 다음 형식을 사용한다.

```text
Workflow status: LOCAL_VALIDATION_REQUIRED
Exact head: <40-character SHA>
Evidence owner: Local Validator
Blocking evidence: Desktop/Mobile browser run and external API isolation
```

최종 판정 예:

```text
CTO final status: READY
Reviewed head: <40-character SHA>
User merge approval: pending
```
