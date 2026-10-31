# #5972 한글 서체 A/B 비교 (결정 전 자료)

기존 레이아웃·기능은 그대로 두고 서체만 교체해 같은 화면에서 비교했다. **어느 안도 확정/배포하지 않았다.**
비교는 로컬 브라우저(Chrome, deviceScaleFactor 1)에서 HEAD `1de2abc3` 기준으로 수행했다.

---

## 1. 현재 상태 (실측)

| 항목 | 확인 결과 |
|---|---|
| CSS 선언 | 본문 `Pretendard, "Noto Sans KR", "Malgun Gothic", system-ui, sans-serif` / 제목 `"Noto Serif KR", "Nanum Myeongjo", serif` |
| 로딩된 웹폰트 | **없음** — `@font-face` 등록 0건, 폰트 요청 0건 |
| 제목 실제 렌더 | **Times New Roman + Malgun Gothic** (라틴/숫자 Times, 한글 Malgun) |
| 본문 실제 렌더 | **Noto Sans KR** (이 PC에 설치된 로컬 폰트, 웹폰트 아님) |
| 제목 크기/굵기 | 히어로 51.84px 700 · 섹션 34px 700 · 밴드 22px 700 |
| 본문 | 16px 400 · 리드 16px 400 · 버튼 14px 600 |

**원인:** CSS는 폰트 이름만 지정하고 실제로 로드하지 않았다. 그래서 `--font-serif`의 `Noto Serif KR`·`Nanum Myeongjo`가 없으면 브라우저 기본 `serif`로 떨어지고, 그 결과 제목의 라틴/숫자가 Times New Roman, 한글이 Malgun Gothic으로 섞여 렌더된다. 대표 피드백의 직접 원인이다.
본문도 로컬 설치 폰트에 의존하므로, Noto Sans KR이 없는 PC에서는 Malgun Gothic으로 떨어진다(현재 미리보기 캡처 환경은 Noto Sans KR 설치 PC).

## 2. 후보 서체와 라이선스

| 후보 | 라이선스 | 상업적 이용 | 배포 방식 | 자산 크기(실측) |
|---|---|---|---|---|
| **Pretendard** | SIL Open Font License 1.1 | 허용 | jsDelivr CDN, dynamic-subset | 11개 파일 **280KB** (필요 글리프만 로드) |
| **마루부리 (MaruBuri)** | 네이버 나눔글꼴 오픈 라이선스 (폰트 자체 판매만 금지) | 허용 | 네이버 공식 CDN `hangeul.pstatic.net` | 굵기별 **약 414–466KB** (전체 글리프, 서브셋 없음) |

- Pretendard: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css` (가변 45–920)
- 마루부리: `https://hangeul.pstatic.net/hangeul_static/css/maru-buri.css` — 굵기가 별도 패밀리로 제공됨(`MaruBuri`, `MaruBuriLight`, `MaruBuriSemiBold`, `MaruBuriBold`)

## 3. 비교안 정의

| 안 | 구성 |
|---|---|
| **CURRENT** | 현 상태(웹폰트 없음) |
| **A** | Pretendard 전체 적용 — 제목·본문·버튼 모두 Pretendard Variable |
| **B** | 마루부리 제목(`MaruBuriBold`) + Pretendard 본문 |

B안은 마루부리 굵기가 별도 패밀리이므로 제목 요소의 `font-weight`를 400으로 두고 `MaruBuriBold` 패밀리를 직접 지정해 가짜 볼드(synthetic bold)를 피했다.

## 4. 측정 결과 — 1440×900

| 측정 | CURRENT | A | B | 원본 reference_01 |
|---|---|---|---|---|
| 히어로 높이 | 361px | **361px** | **361px** | 364px |
| 문서 전체 높이 | 1478px | **1478px** | **1478px** | 1086px |
| 제목 줄 수 | 2줄 | **2줄** | **2줄** | 2줄 |
| 1행 폭 / 2행 폭 | 487 / 423px | **421 / 366px** | **476 / 412px** | (문구가 달라 절대값 비교 불가) |
| 제목 블록 높이 | 120px | 120px | 120px | — |
| 리드 줄 수 / 폭 | 2줄 380·316 | 2줄 415·236 | 2줄 415·236 | — |
| 섹션 제목 폭 | 210px | 182px | 205px | — |
| 카드 제목 줄 수 | 2줄 | 2줄 | 2줄 | — |
| 주 버튼 | 145×48 | **139×48** | **139×48** | — |
| 가로 오버플로 | 0 | **0** | **0** | — |
| 실제 렌더 | Times New Roman + Malgun Gothic | Pretendard Variable | 제목 MaruBuri / 본문 Pretendard Variable | — |
| 폰트 페이로드 | 0KB | **280KB** (11파일) | **721KB** (12파일) | — |

**핵심:** 세 안 모두 히어로 361px, 문서 1478px, 제목 2줄이 유지된다. 서체 교체가 원본 구도·레이아웃·기능을 바꾸지 않는다.

## 5. 측정 결과 — 390×844

| 측정 | CURRENT | A | B |
|---|---|---|---|
| 히어로 높이 | 431px | 431px | 431px |
| 문서 전체 높이 | 3455px | 3455px | 3455px |
| 제목 줄 수 | 2줄 | 2줄 | 2줄 |
| 1행 폭 / 2행 폭 | 254 / 220px | **220 / 191px** | **248 / 215px** |
| 주 버튼 | 145×48 | 139×48 | 139×48 |
| 가로 오버플로 | 0 | 0 | 0 |

390px에서도 3안 모두 줄바꿈이 동일(각 2줄)하고 버튼 폭 차이는 6px이다. 한글 줄바꿈이 깨지거나 넘치는 안은 없다.

## 6. 정성 비교

- **CURRENT**: 제목이 Malgun Gothic 볼드로 렌더되어 획 굵기가 균일하지 않고, 숫자·라틴이 Times New Roman으로 섞인다. 가장 완성도가 낮다.
- **A (Pretendard)**: 자소 폭이 고르고 자간이 안정적이며, 제목 폭이 13%가량 줄어(487→421) 여백이 살아난다. 제목·본문·버튼이 한 서체로 통일되어 일관성이 가장 높다. 토스형 현대적 UI에 해당한다.
- **B (마루부리)**: 명조 계열 획의 리듬과 삐침이 살아 있어 에디토리얼·프리미엄 인상이 가장 강하다. 제목 폭이 A보다 13% 넓지만(476) 620px 텍스트 열 안에서 2줄이 유지된다. 비용은 A의 2.6배(280KB → 721KB)이고, 네이버 CDN이 전체 글리프를 내려주므로 서브셋 이득이 없다.

## 7. 확인 필요 (결정 사항)

1. A안과 B안 중 선택 — 이 문서는 결정하지 않는다.
2. B안이 선택되면 자체 호스팅 여부(외부 CDN 의존)와 굵기 수를 정해야 한다. 제목 전용이면 Bold 1종(약 452KB)으로 한정할 수 있다.
3. 선택 후 적용 범위(제목만/전체, 독립 5개 페이지 동시 적용)를 확정해야 한다.

## 8. 자료

| 파일 | 내용 |
|---|---|
| `compare-headline-1440.jpg` | 1440 히어로 제목 3안 상하 비교 |
| `compare-headline-390.jpg` | 390 모바일 3안 좌우 비교 |
| `capture-current-1440x900.jpg` / `capture-A_pretendard-1440x900.jpg` / `capture-B_maruburi_pretendard-1440x900.jpg` | 각 안 1440×900 전체 캡처 |
| `capture-*-390x844.jpg` | 각 안 390×844 캡처 |
