# VISUAL_QA — 시각 검토 기록

현재 작업 모델은 이미지를 직접 볼 수 없으므로 픽셀 단위 시각 검토는 수행하지
않았습니다.

```text
PIXEL_VISUAL_QA_PASS: NOT DECLARED (PENDING)
CUSTOMER_SEND_READY:  NOT DECLARED
BLOCKER_ZERO:         NOT DECLARED
MAJOR_ZERO:           NOT DECLARED
```

## 구조 검증 (수행됨)

```text
제안서 페이지 수:   10
원페이지 페이지 수:  1
워크시트 페이지 수:  2 (1페이지 Q1~Q7, 2페이지 Q8~Q13)
스킬 카드 페이지 수: 2~3
렌더 PNG:           PDF 모든 페이지와 일치 (파일 존재 검증)
외부 런타임:         0
실제 고객·기관 데이터: 0
backend·SaaS·자동승인 주장: 0
가격 가설 표시 누락: 0
사람 검토 문구 누락:  0
```

## 좌표 검증 (수행됨)

Web CTO 픽셀 검토 결과(`PIXEL_VISUAL_QA_FAILED / BLOCKER_FOUND`)에 따라
생성 스크립트를 수정하고, PPTX 객체 좌표를 검증하는 validator를 추가했습니다.

```text
모든 PPTX shape:
  left >= 0, top >= 0
  left + width  <= 슬라이드 폭
  top + height  <= 슬라이드 높이

footer와 본문 객체 겹침 검사:
  Slide 5 page-boundary overflow: 0
  Slide 5 footer overlap:         0
  One-page page-boundary overflow: 0
  One-page footer overlap:        0

Worksheet:
  페이지 수:           2
  반복 헤더:           2/2 페이지
  문항 분배:           1페이지 Q1~Q7, 2페이지 Q8~Q13
  체크박스:            체크형 문항(Q12 빈도)만 사용
  과도한 빈 페이지:     0
```

Slide 5는 3열×4행 카드의 세로 간격·높이를 축소해 전체 12개 카드가
슬라이드 안전영역 안에 들어가며, footer와 겹치지 않습니다. One-page는
footer를 파란 하단선과 분리하고 마지막 박스와의 간격을 확보했습니다.

## 렌더 목록

`rendered/` 아래 PDF 페이지별 PNG와 매니페스트(`rendered/manifest.md`)가
생성됩니다. 시각 검토자는 다음을 확인합니다.

```text
1. 10초 원페이지 가독성
2. 스킬 카드의 SAMPLE/SYNTHETIC/HUMAN REVIEW REQUIRED/NOT AUTOMATICALLY
   APPROVED 표시
3. 푸터 문구(표지/내부/마지막)
4. Offer A/B/C 가격 가설 표현
5. 사람 검토 필수 문구
6. 업무 스킬 설계 도면 시각 문법(일반 SaaS/챗봇/강의/프롬프트/IDE/자동화/평가표
   표현 없음)
```

시각 검토가 완료되기 전에는 `PIXEL_VISUAL_QA_PASS`를 선언하지 않습니다.
