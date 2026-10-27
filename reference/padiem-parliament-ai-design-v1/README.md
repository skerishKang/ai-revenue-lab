# PADIEM Parliament AI — 시네마틱 디자인 프로토타입 (#5967)

운영 의원3종(`/apps/council/`)을 **건드리지 않는** 독립 시각·동작 프로토타입입니다.
대표가 선택한 "한국 국회의사당 + 석양" 콘셉트를 실제 브라우저에서 확인 가능한 화면으로
만들고, 국가별 디자인을 앱 복제 없이 **테마 축**으로 통합할 수 있는 구조인지 증명합니다.

```text
PRODUCTION_CHANGED=NO   이 디렉터리는 운영 자산 번들에 스테이징되지 않습니다
NETWORK_USED=NO         fetch·XHR·WebSocket 호출 0 (테스트가 고정)
```

## 여는 법

```bash
cd reference/padiem-parliament-ai-design-v1
python -m http.server 8765     # http://127.0.0.1:8765/index.html
```

`file://`에서도 열리지만, 히어로 시차와 스크롤 동작은 http 서빙에서 확인합니다.

## 화면 구성 (지시대로 3가지만)

1. **상단 최소 메뉴** — 브랜드 표시, `프로토타입` 태그, 국가/스타일 선택 2개. 그 외 항목 없음.
2. **웅장한 히어로** — 석양 하늘·태양 글로우·실루엣·그레인. 실제 기관의 표장·로고는 쓰지
   않은 추상 의회 실루엣(기둥렬 + 얕은 지붕 + 중앙 등대)입니다.
3. **업무 카드 3개** — 축사·인사말 / SNS 홍보 / 회의정리·활동집. 문구는 운영 화면과 동일.

카드를 고르면 히어로는 물러나고 **간결한 문서 작업실**(좌: 업무 정보, 우: 본문)로 전환됩니다.
`Esc` 또는 "시네마틱 홈으로"로 돌아옵니다. URL 해시(`#/speech`)로 재진입 시 선택이 유지됩니다.

## 테마 구조 — 국가와 스타일은 독립 축

| 축 | HTML 속성 | 정의하는 것 | 정의하지 않는 것 |
| --- | --- | --- | --- |
| 국가 | `html[data-country="kr\|us\|fr\|uk"]` | 8단계 음계(`--tone-1..8`) + 하늘/태양/실루엣 재료(`--sky-*`, `--sun`, `--skyline`, `--reflection`, `--haze`, `--vignette`) + 강조색·글꼴 | 배경/패널/본문 같은 **역할** |
| 스타일 | `html[data-style="classic\|modern\|dark\|light\|minimal"]` | 역할(`--bg`, `--panel`, `--text`, `--paper`, `--ink`, `--glass`, `--hero-*`)을 국가 음계의 몇 번째 칸에 붙일지와 모서리·글꼴·글로우 강도 | 새로운 색 재료 |

그래서 4×5 = 20 조합을 20개 블록으로 복제하지 않습니다. `tests/test_parliament_prototype.py`가
① 네 국가의 토큰 **키 집합이 완전히 동일한지**, ② 어떤 스타일도 `--tone-*`/`--sky-*`를 새로
정의하지 않는지, ③ 토큰 자리 밖(CSS 레이아웃 계층)에 **색 리터럴이 하나도 없는지**로 고정합니다.
운영 통합 시 이 파일은 별도 앱이 아니라 공용 시스템(`apps/padiem-chat/static/padiem-themes.css`)과
동일한 토큰 이름을 쓰므로 그 안의 테마 블록으로 흡수됩니다.

## 이미지에 관해 — 사실대로 기록

- CENTRAL이 제공한 디자인 패키지 `PADIEM Parliament AI Design Concepts 20261027`의
  `04_korea_cinematic_home.png` **원본은 이 머신과 GitHub 어디에도 존재하지 않습니다.**
  v2에서 재확인한 범위: `C:\Users\limone\{Downloads,Documents,Pictures}`, `E:\`, `F:\`(DriveFS),
  `G:\Ddrive\BatangD\task\workdiary`, 최근 4일 수신 파일 목록, #5967 본문·댓글 — 모두 없음.
  확인 위치: `C:\Users\limone\{Downloads,Documents,Pictures}`, `E:\`, `F:\`(DriveFS),
  `G:\Ddrive\BatangD\task\workdiary`, 그리고 #5967 본문·댓글(이미지 첨부 없음).
- #5967 본문 자체가 "현재 GitHub 연결에서는 바이너리 이미지 업로드를 지원하지 않아
  이미지를 이슈에 실제 첨부한 상태는 아니"라고 기록합니다.
- 따라서 히어로는 **그 PNG를 재현한 것이 아니라**, 이슈에 적힌 시안 설명
  (한국 국회의사당·석양, 상단 최소 메뉴, 웅장한 히어로, 간결한 3업무 카드)을 기준으로
  CSS 그라디언트 + 인라인 SVG로 새로 그린 것입니다. 사진 원본을 확보한 것이 아니며,
  원본 확보 후에는 이 화면 위에 얹는 것이 아니라 토큰(`--sky-*`)만 교체해 비교합니다.

## 운영 제품과의 관계

- 인증·AI 생성·파일 저장·사진 업로드·활동집 복원 계약은 **재사용 대상**이며 이 프로토타입은
  하나도 호출하지 않습니다. 연결은 시안 승인 후 별도 단계입니다.
- 축사·SNS·회의록·활동집의 기존 기능과 운영 CSS/HTML/JS는 수정되지 않았습니다.
- 국가별 디자인을 별도 앱으로 복제하지 않습니다. 이 디렉터리는 1차 시안 검토용입니다.

## v5 — 2차 원본 해석표 기준 구현 (COM1 3단계 절차의 3차)

COM1 `운영방침/21_시안_분석_구현_3단계_운영절차_20261028.md`에 따라 **원본 PNG를 먼저 계측하고
해석표를 만든 뒤** 그 수치로 배치를 다시 잡았다. 해석표 전문은 PR #5974에 기록돼 있고,
여기에는 그 표가 지시한 값과 실제 재현 결과만 남긴다.

### 원본 계측값 → 구현 실측 (1440×810 앵커, innerWidth 1440, dpr 1)

| 구역 | 04 시안 계측 | 구현 실측 | 차이 |
| --- | --- | --- | --- |
| 헤더 | 사진 위 투명, 1줄, y 0..78 | `position:absolute` 1줄, y 0..69 | −9px |
| 히어로 | y 0..424 = 52.20%H, 전폭 사진 | y 0..423 = 52.20%H, `.pa-scene` inset:0 | **0px** |
| 카피 열 | x 82..740 (51.4%W) | x 81..740 (51.4%W) | 1px |
| h1 | 2줄 블록 114px (44px/1.30 환산) | 2줄 114px | **0px** |
| CTA | w 245 · h 46 · y 332 | w 249 · h 51 · y 330 | +4 / +5px |
| 업무 밴드 시작 | y 424 (52.28%H) | y 423 | 1px |
| 업무 제목 밴드 | h 85 | h 88 | +3px |
| 카드 3열 | x 276..1394 · h 200 · 폭 350/354/390 | x 272..1392 · h 204 · 폭 366×3 | +4px / 등폭 |
| 스트립 | h 101 · 흰 카드 · 구분선 · 라인 아이콘 | h 97 · `--strip-bg` · `border-left` · SVG | −4px |
| 페이지 전체 | 810 (1.00화면) | 959 (1.18화면) | +149px |

이전 상태는 1,489px(1.84화면)였고 카드 행이 y 101.1%로 첫 화면 밖에 있었다. 지금은 카드가
y 511..715로 **첫 화면 안에 전부 들어오고**, 스트립 하단만 810 경계를 14px 넘는다.

### 고의로 원본과 다르게 둔 것 (대표/CTO 결정)

| 항목 | 원본 | 이 구현 | 근거 |
| --- | --- | --- | --- |
| 헤더 우측 | bell + 아바타 + "김민주 의원실" + chevron | **표시하지 않음** | CTO 결정 4 — 로그인·계정 데이터 연결 전에는 허구 목업을 띄우지 않는다 |
| 국가·스타일 전환 | 없음 | 우상단 아이콘 1개 → 팝오버 | CTO 결정 3 — 4×5 전환은 필요하되 헤더를 2줄로 만들지 않는다 |
| 메뉴 라벨 | 업무 도구/활용 사례/가이드/공지사항 | 동일. 실제 화면이 있는 것만 눌리고 나머지는 `aria-disabled` + "준비 중" | CTO 결정 2 — 미구현 화면에 임의 링크를 만들지 않는다 |
| 카드 폭 | 350/354/390 (등폭 아님) | 3열 등폭 | 생성 시안의 오차로 판단. 등폭이 그리드 계약과 맞는다 |
| 카드 2의 반응 칩 | 사진에 하트·좋아요 오버레이 | 없음 | 제공된 `sns-card.jpg`에 칩이 없다. 임의로 그리지 않았다 |

### 히어로·카드 사진

대표가 AI 생성으로 전달한 4장을 **실제로 열어 내용을 확인한 뒤** 역할에 맞췄다.
`parliament-hero.jpg`(의사당 석양) · `speech-card.jpg`(본회의장 연단) ·
`sns-card.jpg`(스마트폰 사진 격자) · `meeting-card.jpg`(회의 문서).
출처·변형·명도 계측은 `assets/ATTRIBUTION.md`, 교체 절차는 `assets/IMAGE-SLOTS.md`.

제공된 사진 2장(히어로·카드3)은 **왼쪽이 밝다**(히어로 좌/우 평균 122/98, 카드3 x 3분위 88/63/56) —
원본은 반대다. 그래서 파일을 자르거나 뒤집지 않고 렌더 층으로 해결했다: 히어로는
`--hero-scrim-strong`(.92)의 좌측 그라데이션, 카드는 `--work-scrim`이 왼쪽 40%를 카드 색으로 덮는다.

### 텍스트 대비 (캡처 픽셀 실측, 글자마다 바로 뒤 배경과 견줌)

```text
hero h1 1행 7.96 · 2행(골드) 4.06 · lead 10.03 · eyebrow 4.69 · 인용 5.98
헤더 워드마크 9.05 · 메뉴 5.64 · 검색 placeholder 6.68 · CTA 9.09
업무 h2 14.36 · 소개 6.03
카드 제목 10.26 / 12.34 / 4.57 · 설명 4.71 / 6.22 / 6.79 · 링크 14.77 / 12.78 / 12.90
스트립 제목 13.32..15.96 · 설명 6.74..6.80
→ WCAG 2.1 AA: 본문·라벨(13~15px)은 4.5 이상, 대형·볼드(20px+·44px)는 3.0 이상을 전 구간 충족
```

### 좌우 비교

`docs/screenshots/5967/compare-kr-1440.png` — 왼쪽은 **원본 PNG를 재사용하지 않고** 2차 해석표의
계측값만으로 다시 그린 배치도, 오른쪽은 실제 웹 캡처다. 원본 라스터와 오버레이 원판은
`reference/design-assets/`, `reference/generated-assets/`에 두며 `.gitignore`로 추적에서 제외했다.

### v5 계측 (Playwright Chromium 140 · 로컬 서버 8801 · 운영 주소 미사용)

```text
BROWSER        headless Chromium, viewport 1440×810 / 390×844, devicePixelRatio 1, innerWidth 실측 병기
RESPONSIVE     1440: 카드 3열 · 가로 오버플로 0 · 390: 카드 1열, 접힘 순서 헤더→히어로→소개→카드→스트립, 오버플로 0
FUNCTION       카드 3장→에디터(kicker·필드 30/18/12·본문·home display:none) · Esc 에디터 종료 → 팝오버 먼저 닫기 ·
               팝오버 열면 포커스가 체크된 라디오로, 닫으면 트리거로 복귀 · Enter/방향키로 국가 전환 ·
               검색 "sns"→1건, "zzz"→빈 안내, 해제→3건 · CTA·업무 도구 스크롤+포커스 ·
               비활성 메뉴는 클릭 불가(조작성 검사도 거부) + "준비 중" announce · 새로고침 후 #/meeting·테마 복원
TOUCH_TARGETS  1440·390 모두 44px 미만 타깃 0건
THEME_AXIS     20조합 페인트 서명 16종 고유 — 페이지 배경 8종·카드색 4종·스트립 8종·글꼴 2종·모서리 반지름 3종·사진 층 2종
LOAD           요청 호스트 1곳(자신) · pageerror 0 · HTTP>=400 0 · 외부 요청 0
```

### v6 — 타이포그래피 (B2 확정: 마루부리 제목 + Pretendard 본문)

3차 배치 구현 후에도 **선언한 폰트와 실제 렌더가 달랐다.** 이 프로토타입은 웹폰트 파일을
하나도 싣지 않았기 때문에, `--font-body: Pretendard…`는 `Noto Sans KR`로,
`--font-display: NanumMyeongjo…`는 `Batang`으로 해결됐다. `document.fonts.check()`는
fallback을 허용하면 참을 주므로 판별력이 없고, 존재하지 않는 패밀리와 캔버스 폭을 견주는
차등법으로만 알 수 있었다.

| 슬롯 | 확정 | 배포 파일 | 근거 |
|---|---|---|---|
| `--font-display` | MaruBuri 400·700 | `assets/fonts/MaruBuri-{Regular,Bold}.woff2` | 원본 04의 히어로 제목이 명조 계열이라 그 결을 보존 |
| `--font-body` / `--font-label` | Pretendard 400·500·600·700 | `assets/fonts/Pretendard-{Regular,Medium,SemiBold,Bold}.woff2` | 메뉴·본문·카드·에디터 가독성 통일 |

- 마루부리는 공식 TTF를 **WOFF2 컨테이너로만** 변환했다(fontTools). 변환 전후
  `glyph 12466 / cmap 12398 / family·style·unitsPerEm` 동일을 대조 확인했고,
  Regular 3.12→0.41 MB, Bold 3.20→0.43 MB가 됐다. 글자 모양·전진폭은 그대로이므로 이름을 바꾸지 않았다.
- Pretendard는 공식 subset 빌드를 그대로 사용(가중치당 ≈261 KB). 6종 합계 **≈1.87 MB**, 원격 CDN 요청 0.
- `@font-face`는 `font-display: swap`, `src`는 상대 경로만 쓴다.
- **면이 없는 가중치는 쓰지 않는다.** 기존 CSS의 650·750을 600·700으로 정규화해,
  선언한 가중치가 곧 실재하는 파일이 되도록 맞췄다(테스트가 강제).
- 라이선스: Pretendard = SIL OFL 1.1(Reserved Font Name 'Pretendard'),
  마루부리 = 네이버 글꼴. 고지문 두 종을 `assets/fonts/`에 글꼴과 함께 둔다.
  OFL의 RFN 조항에 따라 **직접 서브셋을 추가 생성하면 'Pretendard' 이름을 쓸 수 없다.**

### 타이포 적용 후 실측 (1440×810 / 390×844, innerWidth·dpr 병기)

```text
DECLARED==RENDERED  10/10  (h1·업무 h2·인용·편집기 kicker = MaruBuri / body·nav·카드 제목·설명·스트립·eyebrow = Pretendard)
FACES LOADED        6/6    MaruBuri 400·700, Pretendard 400·500·600·700   원격 폰트 요청 0
HEADLINE @1440      2줄 · 블록 114px · 2행 ink 517px   (원본 목표: 2줄 · 114px · 542px)
TOPBAR              1줄 · h 69px                      카드 3열 · 첫 화면 안(511..715)
HEADLINE @390       2줄 · 블록 73px  ← 마루부리는 30px에서 3줄(실측 한계 28px), 그래서 28px로 고정
OVERFLOW_X          0 (1440 · 390)                    44px 미만 타깃 0건
CONTRAST            26개 요소 전부 AA 통과 — 글자 화소마다 '잉크를 메운 뒤 국소 중간값'으로 추정한
                    그 자리 배경과 견운 값. 1행 19.0 · 2행(골드) 10.5 · lead 19.0 · 인용 17.9 ·
                    카드 제목 18.5+ · 카드 설명 18.5+ · 스트립 설명 6.03 · 업무 소개 4.60
```

대비 지표는 세 번 고쳤다. ①영역 전체의 brightest-2%는 텍스트 없는 밝은 배경을 끌어들여 과소평가를,
②글자마다 22px 고리는 마루부리처럼 획이 빽빽한 서체에서 **이웃 획**을 배경으로 오인해 허위 실패를,
③스크림을 진하게 하면 꼬리 표본이 줄어 오히려 수치가 나빠지는 역설을 냈다.
잉크 화소를 영역 중간값으로 메운 뒤 국소 중간값 필터로 배경제를 만드는 방식으로 최종 확정했고,
그때 단색 카드 위 텍스트는 worst==median(6.03)이 되어 지표가 물리에 맞는다.

### v7 — 해외 3개 국가의 fallback 차이 제거 (배포된 두 면으로 확정)

v6 직후 남은 유일한 불일치였다. 4개국 × 5스타일 20조합에서 선언 첫 패밀리와 실제로 그린 면을
폭 차등으로 대조한 결과:

```text
kr      h1 선언 MaruBuri          -> 렌더 MaruBuri          일치
us      h1 선언 Playfair Display  -> 렌더 Georgia           불일치
fr / uk h1 선언 NanumMyeongjo     -> 렌더 Georgia           불일치
본문    us/fr/uk 1순위 Inter      -> 이 머신에서만 일치      Inter 도 배포하지 않은 면이었다
```

`Georgia`·`Inter` 모두 이 검사 장비에 설치돼 있어 우연히 맞아떨어졌을 뿐, 다른 운영체제에서는
다른 면으로 렌더되는 상태였다.

**조치:** 새 폰트를 받지 않고 이미 배포한 두 면으로 4개국을 통일했다. 각 국가 블록의
`--font-display` 1순위를 `MaruBuri`, `--font-body`·`--font-label` 1순위를 `Pretendard`로 두고,
`Playfair Display`·`NanumMyeongjo`는 웹폰트 로드 실패 때의 의도된 대체로 스택 뒤쪽에 남긴다.

```text
SLOT CHECKS        140/140  선언 == 렌더, fallback 0   (20조합 × 7슬롯)
DISPLAY / BODY     MaruBuri / Pretendard — 4개국 공통
LAYOUT @1440x810   h1 2줄·114px, h2 1줄, 헤더 1줄, 카드 3열(y 511..715), ovfX 0 — 20조합 동일
LAYOUT @390x844    h1 2줄·73px, 카드 1열, ovfX 0 — 20조합 동일
THEME_AXIS         20조합 고유 페인트 서명 16종 유지 (페이지 배경 8·카드색 4·스트립 8·반지름 3·사진층 2)
```

**대가:** 국가 축의 '제목 서체' 변별력이 사라졌다(서명 3종 → 1종). 이 저장소가 배포하는 세리프는
마루부리 한 종이다. 원본 매트릭스 03은 미국·영국·프랑스 제목을 고대비 라틴 세리프
(`A STRONGER COMMUNITY`, `Des idées pour des citoyens plus forts`)로 보여주지만, 그 서체를 싣는
결정은 '재사용' 범위 밖이므로 하지 않았다. 라틴 디스플레이 서체 배포가 승인되면 복원한다.
국가는 이제 팔레트·사진·반지름으로 구분된다.

### 재현

```bash
python -m pytest reference/padiem-parliament-ai-design-v1/tests -q   # 36 passed
node --check reference/padiem-parliament-ai-design-v1/parliament-app.js
python -m http.server 8801 --directory reference/padiem-parliament-ai-design-v1
```

캡처: `docs/screenshots/5967/final-home-kr-1440.png`(전체 959px),
`final-home-kr-1440-fold.png`(1440×810 앵커), `final-home-kr-390.png`,
`final-editor-sns-kr-light-1440.png`, `compare-kr-1440.png`.
v1(CSS/SVG 렌더)·v2(단일 사진 히어로)·v3(46/54 분할) 계열 캡처는 채택되지 않은 상태이므로
추적에서 제외했다 — 리뷰가 낡은 배치를 근거로 읽지 않도록.
