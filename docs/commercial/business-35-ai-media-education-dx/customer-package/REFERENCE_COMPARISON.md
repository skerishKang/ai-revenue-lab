# REFERENCE_COMPARISON — Business 35 Customer Package

```
FINAL_IDENTITY_DECIDED
PROVIDER: 파디엠
CONTRACTING_ENTITY: 파디엠
BUSINESS_DETAILS_VERIFICATION_PENDING
LEGAL_REVIEW_REQUIRED
PRICE_HYPOTHESIS_ONLY
DO_NOT_SEND
```

## Source

```text
현재 PR 산출물: feat/business-35-customer-facing-package (PR #359), head 22b1b824...
G드라이브 후보안: /mnt/g/downloads/
  Business35_Master_Proposal_10p_reviewed.pptx
  Business35_Master_Proposal_10p_reviewed.pdf
  Business35_OnePage_Offer_reviewed.pdf
비교 사본: tmp/business35-reviewed-reference/ (repository 밖 임시 폴더)
```

## 비교 항목 (텍스트·구조 수준)

```text
슬라이드 구조        후보안: slide당 23–36 shape, 번호 배지(01–10), 카드 구조
                     현재: slide당 5–18 shape, 단순 텍스트 상자 → 후보안 구조 채택
정보 계층           후보안: 제목 + 핵심 메시지 헤드라인 + 카드 본문 (3단계)
                     현재: 제목 + 텍스트 상자 (2단계) → 헤드라인 도입
페이지별 텍스트 양   후보안: slide당 40–70 단어, 카드로 분산
                     현재: slide당 30–50 단어 → 유지
제목·본문 크기       후보안: 제목 28–30pt, 본문 12–17pt
                     현재: 제목 30pt, 본문 14–17pt → 유지 (후보안과 동등)
footer 처리          후보안: 전 페이지 "DRAFT MASTER · LEGAL REVIEW REQUIRED ·
                     NOT YET SENT · 제안 제공자 정보는 발송 전 최종 확정" 반복
                     현재: cover(full)/inner(short)/last(provider) 구분 → 현재 유지
                     (후보안의 전 페이지 반복은 하단 지배 우려로 미채택)
상품 A/B 구분        후보안: 기간/가격 카드 + 산출물 카드 (2열)
                     현재: 텍스트 상자 → 후보안 카드 구조 채택
6주 timeline         후보안: Week 0–6 로우 + 설명 박스
                     현재: Week 0–6 로우 + 설명 박스 → 동등 (유지)
가격 page            후보안: 상품 A/B/B/C 4-카드 ladder
                     현재: 4-로우 텍스트 → 후보안 카드 ladder 채택
마지막 CTA           후보안: 4단계 + 단계별 설명
                     현재: 4단계 카드 (설명 없음) → 후보안 설명 추가
one-page 정보 밀도   후보안: 2열 구조 (문제/방식 · 상품 A/B), B 표준 가격 포함
                     현재: 단일 열 → 후보안 2열 구조 채택 + B 표준 가격 추가
```

## 채택할 요소

```text
1. Slide 번호 배지 (01–10) — 페이지 식별 명확
2. 핵심 메시지 헤드라인 (각 slide 상단 한 줄 요약)
3. Slide 1의 A/B/C 카드 분리 (수작업/개인별 AI/기준 부재)
4. Slide 5/6 상품 카드 (기간·가격 카드 + 산출물/흐름 카드)
5. Slide 9 가격 4-카드 ladder (A/B/B/C)
6. Slide 10 단계별 설명 (다음 단계 각 카드에 보조 설명)
7. One-page 2열 구조 (왼쪽: 문제/방식, 오른쪽: 상품 A/B/C)
8. One-page에 B 표준 파일럿 가격(1,500만–2,500만원) 포함
```

## 채택하지 않을 요소

```text
1. 후보안의 전 페이지 동일 footer 반복
   — 현재 cover/inner/last 구분이 화면 하단 지배를 피하는 데 더 나음
2. 후보안의 픽셀 수준 디자인 (컬러·간격·정렬 미세 조정)
   — 이미지 입력 불가 모델로는 판단 불가
3. 후보안 one-page의 배경 장식 요소 (이미지 입력 불가로 판단 불가)
```

## 채택 이유

```text
- 번호 배지·헤드라인·카드 구조는 텍스트·구조 수준에서 명확히 정보 계층을 개선
- 상품 A/B 카드와 가격 ladder는 비교·판단을 돕는 명확한 시각 구분 제공
- one-page 2열은 10초 이해 목표에 부합 (무엇/누구/진입/후속/다음 행동)
- B 표준 가격 추가는 원문(01-one-page-offer.md)과 일치 (새 claim 아님)
```

## 시각 확인이 필요한 항목

```text
- 픽셀 단위 텍스트 잘림·겹침·한글 글리프 (이미지 지원 모델 필요)
- 카드 내 여백·텍스트 정렬 (렌더 이미지 직접 검토 필요)
- 색상 대비·흑백 인쇄 구분 (렌더 이미지 직접 검토 필요)
- 페이지별 시각 리듬 (10장 연속 검토 필요)
```

## 참고

```text
후보안이 "더 우수함"이라는 픽셀 수준 판정은 하지 않는다.
채택된 요소는 텍스트·구조 수준에서 명확히 개선되는 것만 반영했다.
픽셀 시각 검토·겹침 없음·잘림 없음·최종 디자인 승인은 선언하지 않는다.
```
