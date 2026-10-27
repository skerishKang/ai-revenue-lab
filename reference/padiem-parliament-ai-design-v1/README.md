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

## v3 — 원본 시안과 대조한 최종 배치 (#5967 자산 전달 후)

CENTRAL이 `reference/design-assets/`에 시안 4종 + ZIP을 전달했고, SHA-256 6/6을 이 머신에서
다시 계산해 확인했다. `04_korea_cinematic_home.png`를 한국 기본 시안으로 삼아 배치를 다시 잡았다.

### 시안이 요구한 구조와 실제 구현

| 시안 요소 | 구현 | 1440 CSS px 실측 |
| --- | --- | --- |
| 상단 수평 내비(브랜드 · 메뉴 · 검색 · 계정) | `.pa-topbar` 안에 브랜드 · 6개 메뉴 · 검색 · 상태 칩 · 테마 전환 | 내비 한 줄 높이 64px, 메뉴 4개 활성 + 2개 `aria-disabled` |
| 왼쪽 텍스트 / 오른쪽 사진 히어로 | `.pa-hero` 46% / 54% 분할, 왼쪽은 `--hero-panel`(그라파이트) | 히어로 469px, h1 48px, 골드 CTA 255×52 |
| 사진 위 우측 인용 | `.pa-hero-quote`를 사진 층 위에 절대 배치 | 768 이하에서는 사진에 가려 숨김 |
| AI WORK TOOLS 밴드(밝은 배경) | 기본 `data-style="light"` → 페이지는 밝고 히어로 패널만 어둡게 | 본문 배경 `rgb(247,244,238)` |
| 카드 3장(사진 + 색 오버레이 + 번호 + 원형 화살표) | `--work-1/2/3`(남·초록·보라) 위에 같은 사진을 자른 위치로 얹음, opacity .58 | 카드 431×285, 3열, 겹침 없음 |
| 기능 스트립 4항 | `.pa-strip` | 4열 @1440 · 2열 @1100 · 1열 @767 |

### 좌우 비교

`docs/screenshots/5967/compare-kr-1440.png` — 위쪽 히어로 밴드, 아래쪽 카드 밴드를 같은 폭으로
맞춰 왼쪽은 원본 시안, 오른쪽은 실제 웹 캡처다.

### 남아 있는 차이 (원인을 명시)

1. **석양 톤.** 시안은 주황 석양, 보유 자산은 같은 건물의 **밤** 사진(CC BY 2.0)이다. 파일에 손을 대지
   않고 `--pa-grade-op`(0.42)의 `mix-blend-mode: color`로 색만 입혔다. 완전히 맞추려면 석양 사진
   자산이 필요하다 — 임의로 생성한 배경으로 대체하지 않는다.
2. **카드 사진.** 시안은 카드마다 서로 다른 소재(연단·스마트폰·보고서)를 쓴다. 지금은 같은 라이선스
   사진을 위치만 바꿔 깔았다. 소재별 사진 3장이 추가 자산으로 필요하다.
3. **상단 바 2행.** 시안에는 없는 국가/스타일 전환기와 `API 미연결` 배지를 프로토타입이 갖고 있어
   1426px에서 한 줄로 정리되지 않는다. 전환기를 설정 팝업으로 옮길지는 대표 판단이다.
4. **건물 크기.** 사진 안에서 의사당이 차지하는 비중이 시안보다 작다. `--hero-photo-zoom`(1.34)과
   `--hero-photo-position`(88% 60%)으로 조정 가능한 값으로 노출해 뒀다.

### v3 계측 (Tabbit 실제 Chromium · 로컬 서버 · 운영 주소 미사용)

```text
BROWSER_NOTE     이 브라우저는 dpr 1.1(Windows 110% 배율)이라 뷰포트 1440 지정 시 CSS 폭이 1295였다.
                 최종 캡처는 1584×990 디바이스 px로 잡아 innerWidth 1440 / clientWidth 1426을 확인하고 촬영했다.
RESPONSIVE=PASS  1440: 카드 3열·가로 오버플로 0 · 390: 카드 1열·가로 오버플로 0 (pageerror 0)
FUNCTION=PASS    카드→에디터(home display none) · 라벨-필드 8/8 · 첫 필드 포커스 · Esc 복귀+CTA 포커스 ·
                 사이드 상단 메뉴로 업무 직접 열기(SNS) · 미구현 메뉴는 "준비 중" 안내 ·
                 검색 필터: "회의"→카드 1건, "zzz"→빈 안내, 해제→3건 복원
THEME_AXIS=PASS  국가 4×스타일 5를 같은 마크업에서 전환, 사진 없는 국가는 --hero-photo: none + CSS 백스톱
LOAD=PASS        요청 4종(문서·CSS·JS·사진), 외부 요청 0, 사진 image-set 1200(68KB)/2400(326KB)
NOT_MEASURED     FCP(백그라운드 탭에서 Paint Timing 미발생)
```

### 재현

```bash
python -m pytest reference/padiem-parliament-ai-design-v1/tests -q   # 21 passed
node --check reference/padiem-parliament-ai-design-v1/parliament-app.js
```

캡처: `docs/screenshots/5967/final-home-kr-1440.png`, `final-home-kr-390.png`,
`final-editor-sns-kr-light-1440.png`, `compare-kr-1440.png`.
v1(CSS/SVG 렌더)·v2(단일 사진 히어로) 계열 캡처는 검토 이력에서 제치고 저장소 추적에서 제외했다
(채택되지 않은 상태의 이미지가 리뷰를 어지럽히지 않도록).
