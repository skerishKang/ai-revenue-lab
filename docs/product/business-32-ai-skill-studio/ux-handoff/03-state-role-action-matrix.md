# 03 — State / Role / Action Matrix

검증된 상태 머신(`scripts/machine.js`) 기준의 24개 상태 전체 행렬입니다.
권한은 `machine.context.activeRole` 기준이며 UI disabled 상태로 대체하지
않습니다.

## 권한 요약

| 역할 | 표시명 | 전용 action |
| --- | --- | --- |
| `operator` | 업무 실행자 | select-task, check-inputs, supplement, begin-run, complete-step, next-step, request-supplement, resolve-conflict, stop-run, resume-run, resume-confirm, request-review, apply-correction, re-run, save-skill, complete |
| `reviewer` | 합성 운영 책임자 · 사람 검토자 | approve-review, reject-review, approve |
| 공통 | — | handoff-to-reviewer (operator만), handoff-to-operator (reviewer만), load-ok/load-error/load-tasks/list-tasks/cancel/ack/retry/retry-confirm |

## 행렬 표기

- **back persistence**: 검증 제품은 backend 0 / persistent storage 0입니다.
  모든 값은 미래 backend 연결 시 기대 의미이며, 현재는 브라우저 메모리입니다.
- `—` = 해당 없음.

| state | active role | visible primary action | allowed actions | blocked actions | required evidence | trust label | success feedback | failure feedback | focus target | backend persistence expectation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| loading | operator | (자동) | load-ok, load-error | 사용자 action 전부 | — | — | 업무 실습대 준비 | load-error → system-error | view-heading | — |
| initial | operator | 업무 시작 | select-task | 실행·검토 action | — | SYNTHETIC WORK TASK | 업무 선택 | — | view-heading | 선택된 task id |
| empty | operator | 합성 업무 불러오기 | load-tasks | select-task | — | EMPTY | 업무대 채움 | — | view-heading | — |
| task-selected | operator | 필수 입력자료 확인 | check-inputs, list-tasks | begin-run(입력 전), 검토 action | — | REQUIRED INPUT | 입력 확인 | input-incomplete | view-heading | 업무 브리프 선택 |
| input-incomplete | operator | 확인으로 보완 | check-inputs, supplement | begin-run | 누락 입력자료 목록 | REQUIRED INPUT / INPUT INCOMPLETE | 입력 완료 | 보완 오류 → validation-error | view-heading | 입력 확인 상태 |
| ready | operator | 단계별 실행 시작 | begin-run | 검토 action | 입력 완료 | READY | 실행 시작 | — | view-heading | 준비 상태 |
| running | operator | 단계 완료 | complete-step, stop-run | 검토 action, save-skill | 단계 결과 | AI-ASSISTED STEP / HUMAN ACTION | 단계 완료 | 누락·충돌 발견 | view-heading | 단계 진행 |
| step-complete | operator | 다음 단계로 | next-step, stop-run | 검토 action | 단계 완료 기록 | AI-ASSISTED STEP / HUMAN ACTION | 다음 단계 | — | view-heading | 단계 기록 |
| missing-evidence | operator | 보완 요청 기록 | request-supplement, stop-run | complete-step(자동 추정 금지) | 누락 증거 플래그 | MISSING EVIDENCE | 보완 요청 | — | view-heading | 누락 목록 |
| conflicting-evidence | operator | 사람 판단 | resolve-conflict, stop-run | 자동 최저가 판정 | 충돌 증거 비교 | CONFLICTING EVIDENCE | 사람 판단 | 판단 누락 → validation-error | view-heading | 충돌 판단 |
| stopped | operator | 재개 | resume-run, cancel | complete-step | 중단 지점 | STOPPED | 재개/취소 | — | view-heading | 진행 상황 |
| resume | operator | 재개 확인 | resume-confirm | 취소(재개만) | 중단 지점 | RESUME | 재개 | — | view-heading | 진행 상황 |
| draft-result | operator →(인계)→ reviewer | 사람 검토 요청 / 검토자에게 인계 | request-review, handoff-to-reviewer(op), handoff-to-operator(rv) | approve, save-skill | 초안 + 미확인 항목 | DRAFT RESULT / NOT YET APPROVED | 검토 요청 | — | view-heading | 초안(autosave 후보) |
| review-requested | reviewer(인계 후) / operator(인계 전) | 검토 승인 / 수정 요청 | approve-review, reject-review, handoff-to-operator(rv), handoff-to-reviewer(op) | operator의 검토 action | 초안 | NOT YET APPROVED | 검토 결정 | role 위반 → validation-error | role-banner / view-heading | 검토 상태 |
| correction-required | reviewer(직후) → operator(반환 후) | 실행자에게 반환 / 수정 사항 반영 | apply-correction(op), handoff-to-operator(rv) | approve | 수정 요청 | REVIEW CORRECTION | 수정 반영 | role 위반 → validation-error | role-banner | 수정 요청 |
| revised | operator(또는 reviewer) | 수정된 절차 재실행 / 다시 검토 요청 | re-run, request-review, handoff-to-reviewer(op), handoff-to-operator(rv) | save-skill, approve | 수정된 초안 | REVISED | 재실행/재요청 | role 위반 → validation-error | view-heading | 수정본 |
| approval-pending | reviewer(승인 의사 후) | 사람 최종 승인 | approve, handoff-to-operator(rv), handoff-to-reviewer(op) | save-skill(차단), operator approve | 검토 승인 의사 | NOT YET APPROVED | 최종 승인 | pre-approval save-skill / role 위반 → validation-error | view-heading | 승인 상태 |
| approved | reviewer(직후) → operator(반환 후) | 실행자에게 반환 / 스킬 카드 저장 | save-skill(op only), handoff-to-operator(rv) | reviewer save-skill | 승인 기록 | HUMAN-APPROVED | 스킬 저장 | reviewer save-skill → validation-error | view-heading | 승인 기록 |
| skill-saved | operator | 버전·담당자·다음 검토일 확인 | complete, list-tasks | 재승인 | 스킬 카드 + 예외 | VERIFIED ORGANIZATIONAL AI SKILL | 완료 | — | view-heading | 스킬 카드 |
| completed | operator | 새 업무 시작 | list-tasks | 재승인 | 버전 이력 | VERSION HISTORY | 새 업무 | — | view-heading | 버전 이력 |
| validation-error | 이전 역할 유지 | 오류 확인 후 복귀 | ack | 다른 action | 오류 요약 | VALIDATION-ERROR | 이전 상태 복귀 | — | error-summary | 사용자 입력 보존 |
| system-error | operator | 재시도 | retry | 다른 action | — | SYSTEM-ERROR | retry 준비 | — | error-summary | 상태 보존 |
| retry | operator | 재시도 확인 | retry-confirm | 다른 action | — | RETRY | 이전 상태 복귀 | — | error-summary | 상태 보존 |
| cancelled | operator | 업무 다시 선택 | select-task, list-tasks | 검토 action | 취소 결과 | CANCELLED | 재선택 | — | error-summary | 진행 기록 보존 |

## 안전 불변식

```text
AI는 승인할 수 없다.
누락 증거는 자동 추정되지 않는다.
최저가는 자동 최선으로 판정되지 않는다.
사람 승인 전 스킬 저장은 차단된다.
미해결 예외는 최종 스킬 카드에 유지된다.
실제 구매 추천이라고 주장하지 않는다.
```
