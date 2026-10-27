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

## v2 — 실제 사진 히어로 (Visual Fidelity 1차 개선)

1차(CSS/SVG로 그린 의사당 실루엣)는 CENTRAL 검토에서 **채택되지 않았습니다.** 피드백은
① 히어로 사진, ② 건축물 구도, ③ 네이비/골드, ④ 빛의 대비, ⑤ 큰 타이포그래피, ⑥ 3카드 배치가
우선순위였고, v2는 그 순서대로 다시 만들었습니다.

### 이미지 자산

| | 상태 |
| --- | --- |
| CENTRAL 시안 `04_korea_cinematic_home.png` 외 3종 | **없음.** 이 머신(Downloads·Documents·Pictures·E:·F:·G:)과 GitHub(#5967 본문·댓글)에서 확인 실패. 대체 그림을 만들어 완성 처리하지 않았다. |
| 한국 히어로 사진 | **실제 사진 확보·라이선스 확인.** `Dangsan Railway Bridge Night View.jpg` — 저작자 Tony, **CC BY 2.0**(ShareAlike 없음), Wikimedia Commons. 출처·사용 조건·표기 요건은 `assets/ATTRIBUTION.md`, 화면 하단에 저작 표기 노출. |
| 미국·프랑스·영국 히어로 | **미확보.** 각 국가 블록이 `--hero-photo: none`을 명시해 코드로 기록하고, 그때만 CSS/SVG 백스톱 장면이 렌더된다. |

사진 파일 자체는 리사이즈·재인코딩만 했고 크롭·색 보정을 하지 않았습니다. 건물 확대와 네이비/골드
톤은 렌더 단계(`--hero-photo-size`, `--hero-photo-position`, 국가 음계 토)에서 결정됩니다.

### 구성 요소별 구현 (1440 실측)

| 요구 | v1 | v2 | 측정값 |
| --- | --- | --- | --- |
| 히어로 사진 | CSS 그라디언트 + SVG | 실제 사진(2400/1200 image-set) | `background-size: 128%`, `position: 88% 66%`, 사진 요청 200 |
| 건축물 구도 | 임의 실루엣 | 여의도·국회 의사당 돔과 주랑이 우측 1/3에 통째로 보이도록 앵커 | 장면 638px, 사진 층 1295×637 |
| 네이비/골드 | 장미·호박 석양 | 딥 네이비 램프(`#060b18`→`#9db3d2`) + 골드 액센트(`#e8b45f`) | 국가 음계 8단 전부 교체, 스타일 축은 무변경 |
| 빛의 대비 | 단조 그라디언트 | 사진 하이라이트 + 좌측/하단 스크림 2중 | 제목 최악 대비 15.85:1 |
| 큰 타이포그래피 | 62px | 최대 82px 세리프, 자간 -0.035em | 실측 81.16px @1440 |
| 3카드 배치 | 장면 아래 별도 단 | 장면을 32px 덮어쓰는 숫자 매김 카드(01·02·03) | 카드-히어로 겹침 32px, CTA 이격 17px |

### v2 계측

```text
RESPONSIVE=PASS   1440/768/390 가로 오버플로 0 · 카드 3열@1440 · 390은 장면이 상단 배너(겹침 없음)
ACCESSIBILITY=PASS 픽셀 표본(문자 뒤 가장 밝은 화소) 최악 대비:
                  제목 15.85 · 리드 17.81 · 카드 제목 15.98 · 카드 설명 8.26 · gold 눈선 8.82 · CTA 9.92  → 전원 AA/AAA
                  사진 없는 백스톱 장면에서도 muted 6.19:1 유지(네이비 램프 교체로 4.33:1 미달이 자동 해소)
FUNCTION=PASS     카드→에디터 전환(home display none), 라벨-필드 8/8 연결, 첫 필드 포커스,
                  초안 뼈대 채움 102자, Esc 홈 복귀+CTA 포커스, #/meeting 새로고침 복원, pageerror 0
LOAD=PASS         요청 4건(문서·CSS·JS·사진), 외부 요청 0, 사진 2400px 326KB / 1200px 68KB(image-set)
NOT_MEASURED      FCP(백그라운드 탭에서 Paint Timing 미발생), 시안 원본과의 픽셀 비교(원본 부재)
```

### 검증 재현

```bash
python -m pytest reference/padiem-parliament-ai-design-v1/tests -q   # 21 passed
node --check reference/padiem-parliament-ai-design-v1/parliament-app.js
```

캡처: `docs/screenshots/5967/v2-*.png` — `v2-home-kr-dark-1440.png`, `v2-home-kr-dark-390.png`,
`v2-editor-speech-kr-dark-1440.png`, `v2-editor-meeting-kr-dark-390.png`.
v1 계열(`home-kr-dark-*.png`)은 검토 이력으로 남기고 채택 전 상태로 표시한다.

