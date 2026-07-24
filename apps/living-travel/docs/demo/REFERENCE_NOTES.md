# Reference Benchmarks — Living Travel Interactive Concept Demo

Observed 2026-07-24. Analysis of information architecture and interaction
patterns, not visual cloning.

## 1. Norang (Travel Planning)

| Field | Note |
|---|---|
| Type | 여행 계획형 |
| Screen | 코스 선택, 일정 편집 |
| Adopted | 일자별 타임라인 구성, 정보 밀도 조절 |
| Rejected | 가격 중심 카드, 가로 스크롤 일정 |

## 2. Recordue (Travel Journal)

| Field | Note |
|---|---|
| Type | 여행 기록형 |
| Screen | 데이별 노트, 사진 일기 |
| Adopted | 날짜 구분 + 짧은 에세이 형식, 이미지-텍스트 비율 |
| Rejected | 개인 사진 중심 구조, 감정 태그 |

## 3. Travy (Travel Magazine Curation)

| Field | Note |
|---|---|
| Type | 편집 매거진형 |
| Screen | 큐레이션된 장소 리스트 |
| Adopted | 장소 설명의 편집적 톤, 분류별 카테고리 |
| Rejected | 광고성 추천, 리뷰 점수 |

## 4. Medium / Substack (Editorial Publication)

| Field | Note |
|---|---|
| Type | 편집 저널형 |
| Screen | 아티클 본문, 시리즈 |
| Adopted | 여백이 많은 본문 레이아웃, 읽기 리듬, 챕터 구분 |
| Rejected | 댓글/좋아요, 구독 중심 CTA |

## 5. Lonely Planet Guide (Premium Curation)

| Field | Note |
|---|---|
| Type | 고급 큐레이션형 |
| Screen | 도시 가이드, 지역별 추천 |
| Adopted | 동네 중심 구성, "하루 일정" 프레임, 조용한 장소 우선 |
| Rejected | 가격 등급 표시, 예약 링크, 평점 |

## Design decisions derived

- 개인 여행 매거진 감각 — editorially curated, not algorithmically generated.
- 각 day를 챕터로 구성 — 여행의 시간적 흐름을 존중.
- 장소 수를 제한 — 하루 3~5곳으로 정보 과부하 방지.
- 이미지는 분위기 전달용 — factual 증거가 아님을 명시.
- Before/After 비교 화면 — 차이를 시각적/서술적으로 전달.
- 선택형 feedback — 빠른 의사 결정 유도, 자유 텍스트는 보조.
- 가격·예약·별점 없음 — 편집적 가치 중심.
