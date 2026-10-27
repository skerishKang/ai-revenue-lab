# 이미지 슬롯 계약 (IMAGE-SLOTS)

히어로 1장 + 업무 카드 3장은 **CSS 변수 4개만 바꿔서** 교체한다. HTML 구조는 손대지 않는다.
대표가 제공한 생성 이미지 4장은 2026-10-28에 수신·적용 완료했다(출처·내용·계측은 `ATTRIBUTION.md`).

## 슬롯

| 변수 | 화면 요소 | 현재 파일 | fit / position |
|---|---|---|---|
| `--hero-photo` | `.pa-photo` (`.pa-scene` 안, 히어로 전폭) | `assets/parliament-hero.jpg` | `cover` · `74% 44%` · `--hero-photo-zoom: 1.06` |
| `--card-image-1` | `.pa-work[data-work="speech"]::before` | `assets/speech-card.jpg` | `--card-fit` · `--card-position-1: 64% 52%` |
| `--card-image-2` | `.pa-work[data-work="sns"]::before` | `assets/sns-card.jpg` | `--card-fit` · `--card-position-2: 56% 50%` |
| `--card-image-3` | `.pa-work[data-work="meeting"]::before` | `assets/meeting-card.jpg` | `--card-fit` · `--card-position-3: 42% 58%` |

카드 사진의 강도는 `--card-photo-op`, 왼쪽으로 무거워지는 색 오버레이는 `--work-scrim`이 정한다.
히어로의 읽기 오버레이 강도는 스타일 축의 `--hero-scrim` / `--hero-scrim-strong`이 정한다.

## 교체 절차

1. 새 파일을 `assets/`에 넣는다(원본 해상도보다 크게 늘리지 않는다 — 업스케일은 저해상도로 드러난다).
2. `assets/ATTRIBUTION.md`에 파일명·출처·변형·실제 내용을 기록한다. 기록이 없으면 CI가 실패한다.
3. `parliament-theme.css`의 `html[data-country="kr"]` 블록에서 해당 변수 한 줄만 바꾼다.
4. 1440×810과 390×844에서 캡처해 원본과 다시 비교한다. 크롭으로 잘리는 요소가 없는지 확인한다.

## 사진이 없는 국가

`us` / `fr` / `uk` 블록은 `--hero-photo: none`과 `--card-image-1..3: none`, `--card-photo-op: 0`을
명시적으로 선언한다. 그때만 `.pa-sky` / `.pa-sun` / `.pa-haze` / `.pa-skyline`으로 만든 CSS 백스톱 장면이
렌더된다(`--skyline-display: block`). 없는 사진을 있는 것처럼 보여주지 않기 위한 규칙이다.

## 수신 원본 보관 위치 (비공개)

`E:\wt-5967-design-261027\reference\generated-assets\` 의 PNG 4장(각 1672×941).
시안 PNG 4종이 있는 `reference/design-assets/`와 함께 **공개 커밋하지 않는다**.
