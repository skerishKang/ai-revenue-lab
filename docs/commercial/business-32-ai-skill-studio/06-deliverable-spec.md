# 06 — Deliverable Specification

검증된 조직 AI 스킬 패키지(`VERIFIED ORGANIZATIONAL AI SKILL PACKAGE`)는
최소 다음 필드를 포함합니다.

| 필드 | 설명 |
| --- | --- |
| skill name | 스킬 이름 |
| business purpose | 업무 목적 |
| owner | 스킬 소유자 |
| active operator | 실행자 역할 |
| reviewer | 검토자 역할 |
| allowed use | 허용 사용 |
| prohibited use | 금지 사용 |
| required inputs | 필수 입력자료 |
| execution steps | 실행 단계 |
| AI-assisted steps | AI 보조 단계 |
| human actions | 사람 행동 |
| evidence requirements | 증거 요구사항 |
| missing-evidence behavior | 누락 증거 처리 |
| conflicting-evidence behavior | 충돌 증거 처리 |
| review checks | 검토 기준 |
| known exceptions | 알려진 예외 |
| approval record | 승인 기록 |
| version | 버전 |
| next review date | 다음 검토일 |
| rollback condition | rollback 조건 |

## 예시 필드 값 (합성)

```text
skill name:      공급업체 견적 비교 및 구매 추천 메모 작성 (합성)
business purpose: 세 개의 합성 견적서를 비교해 검토용 추천 메모를 만든다
owner:           합성 운영 책임자
active operator: 업무 실행자
reviewer:        합성 운영 책임자 · 사람 검토자
allowed use:     합성 업무 실습에만 사용
prohibited use:  실제 구매 추천·실제 조직 연결에 사용 금지
required inputs: 합성 견적 A/B/C, 비교 기준
execution steps: 범위 정규화 → 필드 추출 → 근거 연결 → 초안 작성 → 검토·기술화
AI-assisted steps: 필드 추출, 근거 연결, 초안 작성
human actions:   범위 확인, 충돌 판단, 검토, 승인
evidence requirements: 출처 증거 연결
missing-evidence behavior: 보완 요청 또는 중단 (자동 추정 금지)
conflicting-evidence behavior: 사람 판단 (자동 최선 금지)
review checks:   근거·예외·미확인 항목 포함 여부
known exceptions: 긴급 납기 시 규칙 재검토
approval record: 사람 검토자 최종 승인
version:         1.0
next review date: 2026-11-01 (합성)
rollback condition: 이전 버전 스킬로 복귀
```

## 원칙

- 모든 예시는 합성입니다. 실제 고객 데이터를 필드에 넣지 않습니다.
- 스킬 패키지는 사람 검토·승인 기록을 포함해야 합니다.
- 누락·충돌·예외·금지 기준은 납품 카드에 명시됩니다.
