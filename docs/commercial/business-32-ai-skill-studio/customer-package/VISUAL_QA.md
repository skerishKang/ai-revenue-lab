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
워크시트 페이지 수:  3 이하
스킬 카드 페이지 수: 2~3
렌더 PNG:           PDF 모든 페이지와 일치 (파일 존재 검증)
외부 런타임:         0
실제 고객·기관 데이터: 0
backend·SaaS·자동승인 주장: 0
가격 가설 표시 누락: 0
사람 검토 문구 누락:  0
```

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
