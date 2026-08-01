# 05 — Backend Integration UX Contract (UX 관점)

backend 구현 없이, 검증된 UX가 backend에 연결될 때 기대되는 **UX 관점 연결
계약**입니다. 이 문서는 backend 구현 계약이 아니라, backend 연결 시 UI가 어떻게
동작해야 하는지를 정의합니다.

## 원칙 (변경 금지)

```text
optimistic approval 금지                  — 서버 승인 확인 전 HUMAN-APPROVED 표시 금지
optimistic role handoff completion 금지   — 서버 인계 확인 전 인계 완료 표시 금지
optimistic skill save 금지                — 서버 저장 성공 전 VERIFIED 스킬 저장 표시 금지
optimistic version confirmation 금지      — 서버 버전 확정 전 version 표시 금지
role authority는 server response 기준     — UI 역할 라벨이 서버 응답을 덮어쓰지 않음
error 후 사용자가 입력한 수정 내용 보존     — 오류 후 재시도에도 수정 내용 유지
```

> 참고: Business 32는 공개 게시 제품이 아니라 조직 스킬 저장 제품입니다.
> `optimistic publication`(공개 게시) 개념은 Business 29의 domain으로, B32
> 계약에는 포함하지 않습니다.

## 1. 저장 상태 계약

backend 연결 시 저장 상태를 명확히 분리합니다. (현재 합성 frontend의 상태는
섹션 6의 경계 문장을 사용합니다.)

| 상태 | 의미 | UI 표현 | VERIFIED/저장완료 표시 |
| --- | --- | --- | --- |
| local-draft | 사용자가 작성한 내용이 현재 브라우저에만 존재 | 초안 · 로컬만 존재 | 금지 |
| sync-pending | 서버 응답 대기, 사용자 입력 보존, 중복 제출 방지 | 저장·동기화 중 | 금지 (승인·최종 저장 완료 표시 금지) |
| server-saved | 서버가 저장 성공을 명시적으로 확인, server version·저장 시각 포함 | 초안이 서버에 저장되었습니다. | 허용 |
| save-failed | 서버 저장 실패 | 저장 실패 · 재시도 가능 | 금지 |
| conflict | 서버 version과 로컬 base version 불일치 | 버전 충돌 · 확인 필요 | 금지 |

- `server-saved`가 되기 전에는 `브라우저 메모리`라는 표현을 저장 완료 문구로
  사용하지 않습니다.
- 서버 저장 성공 문구: **"초안이 서버에 저장되었습니다."**
- 현재 합성 frontend만 설명할 때는 별도 경계 문장을 사용합니다:
  **"현재 데모는 브라우저 메모리만 사용합니다."**

## 2. Verified skill atomic confirmation

다음 항목은 **하나의 서버 transaction 또는 동등한 atomic confirmation**으로
처리됩니다.

```text
skill record 저장
version 생성
approval provenance 저장
audit event 생성
server confirmation 반환
```

- 위 전체가 성공하기 전에는 `skill-saved`, `VERIFIED ORGANIZATIONAL AI SKILL`,
  `저장 완료`를 표시하지 않습니다.
- 중간 상태: `skill-save-pending` — **"저장·버전 기록 확인 중"**
- 실패 상태: `skill-save-failed` — **"저장 완료 아님 · 사용자 수정 내용 유지 ·
  재시도 가능"**

> 폐기: `audit event delayed` + UI state `skill-saved` 조합. 감사기록이
> 실패하거나 확인되지 않은 경우 상태는 `skill-save-pending` 또는
> `skill-save-failed`이어야 하며 `skill-saved`가 아닙니다.

## 3. Offline boundary

오프라인 상태에서 허용되는 행동:

```text
이미 불러온 초안 읽기
로컬 초안 수정
로컬 임시 보존
증거의 이미 로드된 부분 열람
```

오프라인 상태에서 차단되는 행동:

```text
role handoff 완료
review submission
review approval
final approval
skill save 완료
version 확정
audit 확정
```

오프라인 UI 표시:

```text
OFFLINE · NOT SYNCED
로컬 변경사항은 서버에 저장되지 않았습니다.
```

온라인 복구 시 순서:

```text
서버 최신 version 확인
충돌 검사
사용자 선택 후 재동기화
```

로컬 변경으로 서버 상태를 자동 덮어쓰지 않습니다.

## 4. Stale-version conflict

서버 version과 로컬 base version이 다르면:

```text
자동 승인 금지
자동 저장 덮어쓰기 금지
최신 버전 확인
내 변경사항 비교
재적용 또는 폐기 선택
```

필수 표시:

```text
local base version
server current version
충돌한 변경 범주
```

실제 문서 내용 전체를 analytics나 error log에 보내지 않습니다.

## 5. 상황별 계약

| 상황 | UI state | message | primary action | secondary action | focus target | aria-live priority | retry behavior | data preservation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| initial loading | loading | 업무 실습대 불러오는 중 | (자동) | — | view-heading | polite | 자동 | — |
| empty bench | empty | 업무대가 비어 있습니다 | 합성 업무 불러오기 | — | view-heading | polite | 수동 재시도 | — |
| task load failure | system-error | 합성 업무대를 불러오지 못했습니다 | 재시도 | — | error-summary | assertive | 재시도 → 동일 상태 복귀 | 상태 보존 |
| draft autosave pending | draft-result + sync-pending | 초안 저장 대기 중 | 저장 대기 상태 표시 | 계속 편집 | view-heading | polite | 자동 재시도, 중복 제출 방지 | 초안 보존 |
| draft save success | draft-result + server-saved | 초안이 서버에 저장되었습니다. | 다음 단계 | — | view-heading | polite | — | 저장본 보존 |
| draft save failure | validation-error + save-failed | 초안 저장 실패 | 오류 확인 후 복귀 | 재시도 | error-summary | assertive | 재시도 | 사용자 입력 보존 |
| role handoff pending | review-requested + sync-pending | 인계 처리 중 | 대기 | — | role-banner | polite | 자동 | 역할·기록 보존 |
| role handoff conflict | validation-error + conflict | 역할 충돌 | 오류 확인 | 실행자에게 반환 | error-summary | assertive | 재시도 | 역할 이력 보존 |
| stale version | validation-error + conflict | 최신 버전이 아닙니다 | 최신 버전 확인 | 내 변경사항 비교 | error-summary | assertive | 재적용/폐기 선택 후 동기화 | 기존 편집 임시 보존, 자동 덮어쓰기 금지 |
| review already completed | validation-error | 검토가 이미 완료되었습니다 | 결과 새로고침 | — | error-summary | assertive | 상태 동기화 | 결과 보존 |
| approval conflict | validation-error + conflict | 승인 상태가 충돌합니다 | 상태 새로고침 | — | error-summary | assertive | 상태 동기화 | 승인 기록 보존 |
| idempotent retry | retry | 같은 요청을 다시 시도합니다 | 재시도 확인 | — | error-summary | assertive | 멱등 재시도 | 상태 보존 |
| session expired | validation-error | 세션이 만료되었습니다 | 다시 연결 | — | error-summary | assertive | 재인증 후 복귀 | 로컬 초안 보존 |
| permission denied | validation-error | 권한이 없습니다 | 접근 요청 | 실습대로 복귀 | error-summary | assertive | — | 데이터 미노출 |
| network offline | system-error + offline | OFFLINE · NOT SYNCED · 로컬 변경사항은 서버에 저장되지 않았습니다. | 오프라인 계속 | 재시도 | error-summary | assertive | 연결 복구 후 서버 version 확인 → 충돌 검사 → 사용자 선택 재동기화 | 로컬 임시 보존, 자동 덮어쓰기 금지 |
| backend unavailable | system-error | 서버를 사용할 수 없습니다 | 재시도 | 나중에 다시 | error-summary | assertive | 백오프 재시도 | 로컬 상태 보존 |
| partial evidence load | evidence drawer + 부분 로드 | 증거 일부만 불러옴 | 나머지 불러오기 | — | drawer-heading | polite | 수동 재시도 | 로드된 증거 유지 |
| audit event delayed | skill-save-pending | 감사 기록 확인 대기 · 저장 완료 아님 | 상태 확인 | — | view-heading | polite | 자동 동기화 | 감사 로컬 보류 (skill-saved 아님) |
| skill save pending | skill-save-pending | 저장·버전 기록 확인 중 | 대기 | — | view-heading | polite | 자동 | 사용자 입력 보존 |
| skill save failed | skill-save-failed | 저장 완료 아님 · 사용자 수정 내용 유지 · 재시도 가능 | 재시도 | 오류 확인 | error-summary | assertive | 재시도 | 사용자 수정 내용 유지 |

## 6. 권한·저장 계약

```text
승인·인계·저장·버전 상태는 서버 응답이 최종 권위.
UI의 role banner는 서버 승인 역할과 일치해야 하며, 불일치 시 validation-error.
스킬 저장 atomic confirmation 전에는 VERIFIED ORGANIZATIONAL AI SKILL 표시 금지.
어떤 오류 상황에서도 사용자가 입력한 수정·보완 내용을 버리지 않는다.
오프라인/충돌 상황에서 로컬 변경으로 서버 상태를 자동 덮어쓰지 않는다.
```

## 7. 검증 제품 경계

현재 검증 제품은 backend 0 / persistent storage 0입니다. 위 계약은 미래 backend
연결 시 검증 대상으로, 이 문서만으로 backend 구현이 승인되지는 않습니다.

```text
현재 데모는 브라우저 메모리만 사용합니다.
```
