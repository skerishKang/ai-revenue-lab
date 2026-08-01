# 04 — Copy and Trust-Label Inventory

검증 제품 화면의 핵심 문구 목록입니다. 이 문서에서 **제품 문구를 변경하지
않습니다.** 문구 수정이 필요한 경우 아래 "revalidation" 열에 따라 브라우저 검증을
다시 수행해야 합니다.

## 신뢰 라벨 9종

| 범주 | 한국어 표시 | 영문 표시 | 사용 상태 | 사용 목적 | 피해야 할 오해 | 수정 시 revalidation |
| --- | --- | --- | --- | --- | --- | --- |
| AI-ASSISTED STEP | AI 보조 단계 | AI-ASSISTED STEP | running / step-complete | AI가 보조하는 단계임을 표시 | AI가 사람 결정을 대신한다는 오해 | 예 |
| HUMAN ACTION | 사람 행동 | HUMAN ACTION | brief / running / bench | 사람이 수행하는 행동임을 표시 | 클릭만으로 자동 승인된다는 오해 | 예 |
| SOURCE EVIDENCE | 출처 증거 | SOURCE EVIDENCE | evidence drawer / evidence bottom | 비교 근거가 출처 증거임을 표시 | 증거가 실제 문서라는 오해 | 예 |
| MISSING EVIDENCE | 누락 증거 | MISSING EVIDENCE | missing-evidence | 누락 증거를 자동 추정하지 않음을 표시 | 누락이 자동으로 채워진다는 오해 | 예 |
| CONFLICTING EVIDENCE | 충돌 증거 | CONFLICTING EVIDENCE | conflicting-evidence | 충돌이 사람 판단 대상임을 표시 | 최저가가 자동 최선이라는 오해 | 예 |
| DRAFT RESULT | 초안 결과 | DRAFT RESULT | draft-result | 초안이 확정이 아님을 표시 | 초안이 실제 구매 추천이라는 오해 | 예 |
| NOT YET APPROVED | 아직 승인되지 않음 | NOT YET APPROVED | draft-result / review-requested / approval-pending | 승인 전임을 표시 | 보이는 결과가 승인된 것이라는 오해 | 예 |
| HUMAN-APPROVED | 사람 승인 완료 | HUMAN-APPROVED | approved | 사람 최종 승인을 표시 | AI가 승인했다는 오해 | 예 |
| VERIFIED ORGANIZATIONAL AI SKILL | 검증된 조직 AI 기술 | VERIFIED ORGANIZATIONAL AI SKILL | skill-saved / skill-card | 재사용 가능한 검증 스킬을 표시 | 실제 조직 연동이나 실데이터라는 오해 | 예 |

## 상태 표시 문구

| 문구 | 사용 상태 | 사용 목적 | 피해야 할 오해 | revalidation |
| --- | --- | --- | --- | --- |
| SYNTHETIC WORK TASK | bench / run | 모든 콘텐츠가 합성임을 표시 | 실제 업무라는 오해 | 예 |
| REQUIRED INPUT | task-selected / input-incomplete | 필수 입력 확인 | 입력이 자동 처리된다는 오해 | 예 |
| INPUT INCOMPLETE / READY | input-incomplete / ready | 입력 상태 표시 | — | 예 |
| STOPPED / RESUME | stopped / resume | 중단·재개 상태 표시 | 중단 시 기록 손실이라는 오해 | 예 |
| REVIEW CORRECTION | correction-required | 검토 수정 요청 표시 | 수정이 자동 반영된다는 오해 | 예 |
| REJECTED STEP | correction-required | 거부된 추천 표시 | — | 예 |
| REVISED | revised | 수정 반영 표시 | — | 예 |
| RETRY / SYSTEM-ERROR / VALIDATION-ERROR / CANCELLED | 해당 오류 상태 | 복구 경로 안내 | 오류가 데이터를 지운다는 오해 | 예 |
| EMPTY | empty bench | 빈 업무대 표시 | — | 예 |
| VERSION HISTORY · 버전 이력 | completed | 버전·담당자·다음 검토일 표시 | 서버 저장이라는 오해 | 예 |
| RETAINED EXCEPTIONS | skill-saved | 예외가 최종 카드에 유지됨을 표시 | 예외가 사라진다는 오해 | 예 |

## 안내·차단 메시지

| 메시지(한국어) | 발생 상황 | revalidation |
| --- | --- | --- |
| 업무 실행자는 자신의 결과를 검토하거나 승인할 수 없습니다. 합성 운영 책임자에게 인계하십시오. | operator가 검토/승인 action 시도 | 예 |
| 검토자는 업무 실행·수정·저장을 대신할 수 없습니다. 실행자에게 반환하십시오. | reviewer가 실행 action 시도 | 예 |
| 사람 승인 전에는 스킬을 저장할 수 없습니다. | 승인 전 save-skill 시도 | 예 |
| 브라우저 메모리에만 존재 · 저장되지 않음 | 저장 전 전 구간 | 예 |
| 이 초안은 DRAFT RESULT입니다. 확정이 아니며 실제 구매 추천이 아닙니다. | draft-result | 예 |
| 누락 증거를 자동 추정할 수 없습니다. / 최저가를 자동 최선으로 판정할 수 없습니다. | missing/conflicting | 예 |
| 최종 추천과 예외 수용 여부는 사람이 확인합니다. AI가 대신 승인하지 않습니다. | bench/brief | 예 |

## 금지 원칙 (문구·구현 공통)

```text
실제 구매 추천이라고 주장하지 않는다.
실제 파일 업로드·모델 호출·조직 연결을 하지 않는다.
누락 증거를 자동 추정하지 않는다.
최저가를 자동 최선으로 판정하지 않는다.
AI가 스스로 승인하지 않는다.
```
