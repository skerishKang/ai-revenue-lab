# 06 — Analytics Event Spec (UX 측정용, 구현 아님)

실제 analytics는 구현하지 않았습니다. 아래는 UX 측정을 위한 **event
specification**이며, 구현 시 필수/금지 속성을 지켜야 합니다.

## 공통 금지 속성 (모든 event)

```text
draft full text           — 초안 전체 text 금지
evidence full text        — 증거 전체 text 금지
quotation full text       — 견적 원문 금지
person name               — 개인 이름 금지
email                     — 이메일 금지
phone                     — 전화번호 금지
document contents         — 문서 내용 전체 금지
자유입력 전체 text (supplement note 등) — 자유입력 전체 text 금지
```

모든 event는 합성 데이터만 사용하며, event 수집 전 별도 승인이 필요합니다.

## Event 표

| event | trigger | required properties | forbidden properties | PII risk | business question |
| --- | --- | --- | --- | --- | --- |
| task_selected | 업무 시작 | taskId, state | — | 없음 | 어떤 업무가 가장 선택되는가 |
| input_missing_seen | input-incomplete 노출 | inputId, state | — | 없음 | 어느 입력이 가장 누락되는가 |
| input_supplemented | 입력 보완 | inputId, state | — | 없음 | 보완이 성공하는가 |
| evidence_drawer_opened | 증거 열기 | state, fromAction | — | 없음 | 증거를 여는 시점은 어디인가 |
| evidence_conflict_seen | 충돌 증거 노출 | state, conflictId | — | 없음 | 충돌이 어디서 발견되는가 |
| run_stopped | 실행 중단 | state, reason | — | 없음 | 중단이 흔한가 |
| run_resumed | 재개 | state, resumeFrom | — | 없음 | 중단 후 재개율은 얼마인가 |
| review_requested | 검토 요청 | state, reviewerRole | — | 없음 | 검토 요청 빈도 |
| role_handoff_requested | 인계 버튼 | fromRole, toRole, state | — | 없음 | 역할 전환 필요성 |
| role_handoff_completed | 인계 완료 | fromRole, toRole, state | — | 없음 | 인계가 성공하는가 |
| review_rejected | 수정 요청 | state, reviewerRole | 수정 사유 자유입력 전체 text | 낮음 | 수정 요청이 잦은가 |
| correction_applied | 수정 반영 | state, correctionCount | — | 없음 | 수정 반영 소요 |
| approval_completed | 사람 최종 승인 | state, approvedBy | — | 없음 | 승인 완료율 |
| skill_save_completed | 스킬 저장 atomic confirmation 성공 | state, version, exceptionCount | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 저장 완료율 |
| skill_save_pending | 저장·버전 기록 확인 중 시작 | state, retryCount | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | pending에서 실패율 |
| skill_save_failed | 스킬 저장 실패 | state, failureKind, retryCount | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 저장 실패 원인 분포 |
| draft_sync_pending | 초안 동기화 시작 | state, baseVersion | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 동기화가 흔한가 |
| draft_sync_completed | 초안 서버 저장 확인 | state, serverVersion | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 동기화 성공률 |
| draft_sync_failed | 초안 동기화 실패 | state, failureKind | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 동기화 실패율 |
| version_conflict_seen | stale version 충돌 노출 | localBaseVersion, serverCurrentVersion, conflictCategory | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 충돌 빈도와 범주 |
| offline_mode_entered | 오프라인 진입 | state | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 오프라인 사용 빈도 |
| offline_sync_attempted | 온라인 복구 재동기화 시도 | state, attempt | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 오프라인 복구 성공률 |
| recovery_attempted | 오류 후 재시도 | fromState, action, attempt | draft full text, evidence full text, quotation full text, person name, email, phone, document contents | 없음 | 복구가 성공하는가 |

## 구현 원칙

```text
event에 문서·견적·메모 내용을 넣지 않는다.
event에 개인 식별자를 넣지 않는다.
분석 질문은 funnel/완료율 관점으로만 정의한다.
구현 전 이 스펙과 별도로 수집 정책 승인이 필요하다.
```
