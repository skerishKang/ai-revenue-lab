# 06 — Analytics Event Spec (UX 측정용, 구현 아님)

실제 analytics는 구현하지 않았습니다. 아래는 UX 측정을 위한 **event
specification**이며, 구현 시 필수/금지 속성을 지켜야 합니다.

## 공통 금지 속성 (모든 event)

```text
실제 문서 내용 (견적 원문·메모 본문)
개인 이름
이메일 주소
전화번호
자유입력 전체 text (supplement note 등)
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
| skill_save_completed | 스킬 저장 | state, version, exceptionCount | — | 없음 | 저장 완료율 |
| recovery_attempted | 오류 후 재시도 | fromState, action, attempt | — | 없음 | 복구가 성공하는가 |

## 구현 원칙

```text
event에 문서·견적·메모 내용을 넣지 않는다.
event에 개인 식별자를 넣지 않는다.
분석 질문은 funnel/완료율 관점으로만 정의한다.
구현 전 이 스펙과 별도로 수집 정책 승인이 필요하다.
```
