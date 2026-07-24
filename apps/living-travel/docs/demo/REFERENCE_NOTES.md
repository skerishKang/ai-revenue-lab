# Reference Benchmarks — Living Travel Interactive Concept Demo

Observed 2026-07-24. Analysis of information architecture and interaction
patterns from live public services. No visual cloning.

## 1. Norang (Travel Planning)

| Field | Detail |
|---|---|
| Type | 여행 계획형 |
| Source URL | https://norang.page/ |
| Observation date | 2026-07-04 |
| Observed screen/pattern | Day-by-day itinerary builder, category selector with visual chips, destination card grid |
| Adopted | 일자별 타임라인 구성, 정보 밀도 조절, chip-style category selector |
| Rejected | 가격 중심 카드, 가로 스크롤 일정, 예약 연결 CTA |

## 2. Recordue (Travel Journal)

| Field | Detail |
|---|---|
| Type | 여행 기록형 |
| Source URL | https://www.recordue.com/ |
| Observation date | 2026-07-02 |
| Observed screen/pattern | Day-based journal entries, photo+text layout, mood tags |
| Adopted | 날짜 구분 + 짧은 에세이 형식, 이미지-텍스트 비율 유지 |
| Rejected | 개인 사진 중심 구조 (Demo uses synthetic images), 감정 태그 UI |

## 3. Travy (Travel Magazine Curation)

| Field | Detail |
|---|---|
| Type | 편집 매거진형 |
| Source URL | https://travy.co.kr/ |
| Observation date | 2026-07-10 |
| Observed screen/pattern | Curated place lists by category, editorial tone in place descriptions, neighborhood-based grouping |
| Adopted | 장소 설명의 편집적 톤 (editorial voice), 분류별 카테고리 구성 |
| Rejected | 광고성 추천 표시, 리뷰 점수/평점 시스템 |

## 4. Medium (Editorial Publication)

| Field | Detail |
|---|---|
| Type | 편집 저널형 |
| Source URL | https://medium.com/ |
| Observation date | 2026-07-05 |
| Observed screen/pattern | Article body with generous whitespace, series/episode navigation, focus on reading rhythm |
| Adopted | 여백이 많은 본문 레이아웃, 읽기 리듬을 위한 단락 구분, 챕터/에피소드 구조 |
| Rejected | 댓글/좋아요/클랩 시스템, 구독 중심 CTA, 추천 알고리즘 배지 |

## 5. Lonely Planet (Premium Travel Curation)

| Field | Detail |
|---|---|
| Type | 고급 큐레이션형 |
| Source URL | https://www.lonelyplanet.com/south-korea/busan |
| Observation date | 2026-07-08 |
| Observed screen/pattern | City guide with neighborhood breakdown, "day itinerary" frames, quiet vs touristy place distinction |
| Adopted | 동네 중심 구성, "하루 일정" 프레임, 조용한 장소 우선 분류 |
| Rejected | 가격 등급/예산 표시, 예약 링크, 사용자 평점, 호텔/식당 가격 정보 |

## Design decisions derived

- 개인 여행 매거진 감각 — editorially curated, not algorithmically generated.
- 각 day를 챕터로 구성 — 여행의 시간적 흐름을 존중.
- 장소 수를 제한 — 하루 3~5곳으로 정보 과부하 방지.
- 이미지는 분위기 전달용 — factual 증거가 아님을 명시.
- Before/After 비교 화면 — 차이를 시각적/서술적으로 전달.
- 선택형 feedback — 빠른 의사 결정 유도, 자유 텍스트는 보조.
- 가격·예약·별점 없음 — 편집적 가치 중심.
