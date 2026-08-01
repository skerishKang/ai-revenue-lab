# 05 — Backend Integration UX Contract (UX 관점)

backend 구현 없이, 검증된 UX가 backend에 연결될 때 기대되는 **UX 관점 연결
계약**입니다. 이 문서는 backend 구현 계약이 아니라, backend 연결 시 UI가 어떻게
동작해야 하는지를 정의합니다.

## 원칙 (변경 금지)

```text
optimistic approval 금지          — 서버 승인 확인 전 HUMAN-APPROVED 표시 금지
optimistic publication 금지       — 서버 게시 확인 전 공개 표시 금지
optimistic skill save 금지        — 서버 저장 성공 전 VERIFIED 스킬 저장 표시 금지
role authority는 server response 기준 — UI 역할 라벨이 서버 응답을 덮어쓰지 않음
error 후 사용자가 입력한 수정 내용 보존  — 오류 후 재시도에도 수정 내용 유지
```

## 상황별 계약

| 상황 | UI state | message | primary action | secondary action | focus target | aria-live priority | retry behavior | data preservation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| initial loading | loading | 업무 실습대 불러오는 중 | (자동) | — | view-heading | polite | 자동 | — |
| empty bench | empty | 업무대가 비어 있습니다 | 합성 업무 불러오기 | — | view-heading | polite | 수동 재시도 | — |
| task load failure | system-error | 합성 업무대를 불러오지 못했습니다 | 재시도 | — | error-summary | assertive | 재시도 → 동일 상태 복귀 | 상태 보존 |
| draft autosave pending | draft-result + pending 표시 | 초안 저장 대기 중 | 저장 대기 상태 표시 | 계속 편집 | view-heading | polite | 자동 재시도 | 초안 보존 |
| draft save success | draft-result | 초안 저장 완료(브라우저 메모리) | 다음 단계 | — | view-heading | polite | — | 저장본 보존 |
| draft save failure | validation-error | 초안 저장 실패 | 오류 확인 후 복귀 | 재시도 | error-summary | assertive | 재시도 | 사용자 입력 보존 |
| role handoff pending | review-requested + 인계 대기 | 인계 처리 중 | 대기 | — | role-banner | polite | 자동 | 역할·기록 보존 |
| role handoff conflict | validation-error | 역할 충돌 | 오류 확인 | 실행자에게 반환 | error-summary | assertive | 재시도 | 역할 이력 보존 |
| stale version | validation-error | 최신 버전이 아닙니다 | 새 버전 불러오기 | — | error-summary | assertive | 새 버전으로 동기화 | 기존 편집 임시 보존 |
| review already completed | validation-error | 검토가 이미 완료되었습니다 | 결과 새로고침 | — | error-summary | assertive | 상태 동기화 | 결과 보존 |
| approval conflict | validation-error | 승인 상태가 충돌합니다 | 상태 새로고침 | — | error-summary | assertive | 상태 동기화 | 승인 기록 보존 |
| idempotent retry | retry | 같은 요청을 다시 시도합니다 | 재시도 확인 | — | error-summary | assertive | 멱등 재시도 | 상태 보존 |
| session expired | validation-error | 세션이 만료되었습니다 | 다시 연결 | — | error-summary | assertive | 재인증 후 복귀 | 로컬 초안 보존 |
| permission denied | validation-error | 권한이 없습니다 | 접근 요청 | 실습대로 복귀 | error-summary | assertive | — | 데이터 미노출 |
| network offline | system-error | 네트워크 연결 없음 | 재시도 | 오프라인 계속 | error-summary | assertive | 연결 복구 후 재시도 | 로컬 상태 보존 |
| backend unavailable | system-error | 서버를 사용할 수 없습니다 | 재시도 | 나중에 다시 | error-summary | assertive | 백오프 재시도 | 로컬 상태 보존 |
| partial evidence load | evidence drawer + 부분 로드 | 증거 일부만 불러옴 | 나머지 불러오기 | — | drawer-heading | polite | 수동 재시도 | 로드된 증거 유지 |
| audit event delayed | skill-saved + 지연 표시 | 감사 기록 반영 대기 | 상태 확인 | — | view-heading | polite | 자동 동기화 | 감사 로컬 보류 |

## 권한·저장 계약

```text
승인·저장·공개 상태는 서버 응답이 최종 권위.
UI의 role banner는 서버 승인 역할과 일치해야 하며, 불일치 시 validation-error.
스킬 저장 성공 전에는 VERIFIED ORGANIZATIONAL AI SKILL 표시 금지.
어떤 오류 상황에서도 사용자가 입력한 수정·보완 내용을 버리지 않는다.
```

## 검증 제품 경계

현재 검증 제품은 backend 0 / persistent storage 0입니다. 위 계약은 미래 backend
연결 시 검증 대상으로, 이 문서만으로 backend 구현이 승인되지는 않습니다.
