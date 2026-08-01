# SOURCE_MAPPING — 고객용 산출물 ↔ 원본 소스 매핑

모든 고객용 산출물은 검증된 상업 설계(PR #363)와 검증된 UX(PR #354), 핸드오프
(PR #358)에서 파생됩니다. 실제 데이터는 사용하지 않습니다.

| 고객용 산출물 | 원본 소스 | 주요 내용 |
| --- | --- | --- |
| Business32_Master_Proposal_10p.pptx/.pdf | commercial `01`, `02`, `07`, `09`, `10` | 10페이지 제안 구조, Offer A/B/C, 가격 가설, 위험 경계 |
| Business32_OnePage_Offer_Source.pptx / Business32_OnePage_Offer.pdf | commercial `02`, `07` | 10초 원페이지: 대상·문제·스킬·Offer·첫 행동·가설·사람 검토 |
| Business32_Skill_Discovery_Worksheet.docx/.pdf | commercial `06`, `09` | 업무 1개 선정용 13문항 작성형 워크시트 |
| Business32_Verified_Skill_Card_Sample.pptx/.pdf | commercial `06` | 20개 스킬 필드 + 합성 샘플(교육 프로그램 안내문) |
| Business32_Pilot_Quote_Template.xlsx | commercial `02`, `07` | Offer 선택·공급가액·VAT·총액·착수금·잔금 계산 |
| Business32_Customer_Meeting_Script.md | commercial `09` | 30분 상담 대본 |
| Business32_Followup_Email_Templates.md | commercial `09` | 후속 이메일 템플릿 |
| rendered/ | 위 모든 PDF | PDF 페이지별 PNG 렌더 |

## 스킬 카드 필드 정합 (PR #363 06-deliverable-spec)

PR #363의 필수 필드와 고객용 카드 표시 매핑:

| PR #363 필드 | 스킬 카드 표시 |
| --- | --- |
| skill name | 스킬 이름 |
| business purpose | 업무 목적 |
| owner | 소유자 |
| active operator | 실행자 |
| reviewer | 검토자 |
| allowed use | 허용 사용 |
| prohibited use | 금지 사용 |
| required inputs | 입력자료 |
| execution steps | 실행 단계 |
| AI-assisted steps | AI 보조 단계 |
| human actions | 사람 판단 단계 |
| evidence requirements | 필수 증거 |
| missing-evidence behavior | 누락 처리 |
| conflicting-evidence behavior | 충돌 처리 |
| review checks | 검토 기준 |
| known exceptions | 예외 |
| approval record | 승인 기준 |
| version | 버전 |
| next review date | 다음 검토일 |
| rollback condition | 재실행 조건 |

## 합성 샘플 업무

```text
교육 프로그램 안내문 작성 및 검토 (SAMPLE · SYNTHETIC)
가상 기관명 · 가상 프로그램 · 가상 일정 · 가상 대상자 · 가상 승인자
```

실제 기관명·내부문서·견적서·개인정보는 사용하지 않습니다.

## 비원본

- 가격은 PR #363의 가설 그대로(`PRICE_HYPOTHESIS_ONLY`).
- 제공자 정체성은 중립 유지(`FINAL_IDENTITY_REQUIRED`).
