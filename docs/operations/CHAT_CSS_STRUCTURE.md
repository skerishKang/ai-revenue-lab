# Chat CSS 구조 — 초안

- 범위: `apps/padiem-chat/static/*.css`
- 기준: 2026-11-18, #8018·#8014·#8030 병합 뒤 main
- 상태: **초안**. C3~C6가 끝날 때 허용 목록과 가드 최종값을 확정한다.

## 1. 세 층

1. **토큰** — `padiem-tokens.css` 한 파일. 테마별 색 값은 여기에만 있다.
2. **구성요소 시트** — 부품마다 하나. 색은 `var(--이름)`만 쓰고 `data-theme` 선택자와 `!important`를 두지 않는다.
3. **테마 전용 배치 시트** — 허용 목록에 있는 것만. 모든 선택자가 그 테마로 시작하고 `!important`를 두지 않는다.

예외는 하나다. 어떤 테마에서든 지켜야 하는 접근성 하한(최소 글자 크기·터치 크기·초점 표시)은 `accessibility-floor.css`에 모으고, 그 시트에서만 사유 주석과 함께 `!important`를 쓴다. 이 시트는 아직 없다.

## 2. 로드 순서

`index.html`이 부르는 시트는 72개다. 정확한 순서는 아래와 같다.

```text
 1 padiem-glass.css
 2 padiem-glass-portrait.css
 3 styles.css
 4 padiem-tokens.css
 5 attachments.css
 6 history.css
 7 projects.css
 8 documents.css
 9 outputs.css
10 rich-response.css
11 search-sources.css
12 chat-pc-session.css
13 chat-feedback.css
14 chat-news.css
15 padiem-foundation.css
16 padiem-surfaces.css
17 padiem-editorial.css
18 padiem-rich.css
19 padiem-first-use.css
20 padiem-bright-readability.css
21 padiem-glass-brand-polish.css
22 padiem-glass-gutter-alignment.css
23 padiem-cinematic-chat.css
24 padiem-cinematic-workspace.css
25 padiem-themes.css
26 accessibility-polish.css
27 sidebar-utility.css
28 capability-nav.css
29 pc-pairing-card.css
30 pc-connect-flow.css
31 pc-delegation-settings.css
32 mcp-gateway-settings.css
33 claw-manual-intake.css
34 claw-workspace.css
35 util-menu.css
36 util-app.css
37 util-tools.css
38 util-chat-mode.css
39 util-quote.css
40 util-excel.css
41 util-slash.css
42 claw-quote-compare.css
43 b66-quote-runtime.css
44 claw-local-handoff.css
45 claw-device-manager.css
46 claw-composer-connection-status.css
47 claw-device-guidance.css
48 claw-pc-enrollment-consent.css
49 padiem-chat-ui-polish.css
50 calendar.css
51 library.css
52 claw-task-hub.css
53 padiem-shared-ui.css
54 claw-connection-guide.css
55 answer-actions.css
56 shared-tooltip.css
57 standalone-views.css
58 connector-pages.css
59 meeting-capture.css
60 claw-focus-layout.css
61 voice-composer.css
62 voice-ui.css
63 shared-six-panel-frame.css
64 sidebar-unified.css
65 padiem-dark-contrast.css
66 sidebar-section-polish.css
67 sidebar-history-scroll.css
68 interaction-polish.css
69 mobile-header-collapse.css
70 chat-screen-polish.css
71 mobile-target-legibility.css
72 padiem-settings.css
```

`padiem-tokens.css`는 `styles.css` 바로 뒤, 모든 구성요소 시트 앞이다. `styles.css`는 바이트 고정 참조 미러라 수정하지 않는다.

### JS가 실행 중에 붙이는 시트 7종

정적 `<link>`가 아닌 시트도 있다. 전부 중복 가드를 갖고, 정적 `<link>`보다 늦게 붙으므로 카운트 시점의 캐스케이드에서는 뒤에 온다.

| 시트 | 붙이는 곳 | 붙는 시점 | 정적 `<link>` |
|---|---|---|---|
| `padiem-glass.css` | `theme-init.js`, `theme.js` | glass 테마 적용·초기화 | 있음 — 보통 미동작 |
| `padiem-glass-portrait.css` | `theme-init.js`, `theme.js` | glass 테마 적용·초기화 | 있음 — 보통 미동작 |
| `padiem-glass-reading.css` | `theme.js` | glass 테마 적용·초기화 | 없음 |
| `interaction-polish.css` | `interaction-polish.js` | 모듈 초기화 즉시 | 있음 — 보통 미동작 |
| `capability-presentation.css` | `message-lifecycle.js` | 작업 카드 첫 렌더 | 없음 |
| `mode-presentation.css` | `product-capabilities.js` | 모드 표시 설치 | 없음 |
| `pc-file-exchange.css` | `b66-quote-runtime.js`, `claw-web-xlsx-sources.js`, `util-pdfmd.js`, `util-tools.js` | PC 파일 교환 첫 사용 | 없음 |

정적 72개 + JS 전용 4개 = Chat 5테마 시트 76개. 나머지 8개는 단독 페이지 시트다: `admin.css`, `admin-models.css`, `admin-model-ext.css`, `credential-slots.css`, `mcp-oauth-consent.css`, `padiem-home.css`, `help.css`, `legal-pages.css`. 합계 84개.

## 3. 토큰 규칙

### 정의 위치

- 기본값은 `padiem-tokens.css`의 `:root`에 둔다.
- 테마별 값은 같은 파일의 `html[data-theme="light|dark|cinematic|padiem-home|padiem-glass"]` 블록에만 둔다.
- 시스템 다크 분기는 `@media (prefers-color-scheme: dark)` 안의 `:root`에만 둔다. `html[data-theme]` 블록(특이성 0,1,1)이 `:root`(0,1,0)를 이기므로, 테마 블록이 있는 테마는 시스템 설정에 끌려가지 않는다.
- 구성요소 시트에는 색 리터럴과 `data-theme` 선택자를 두지 않는다. 색은 `var(--이름)`으로만 읽는다.

### 이름

`--<부품>-<역할>` 형태를 쓴다. 예: `--auth-panel-bg`, `--composer-home-shadow`, `--sidebar-footer-border`. 테마 이름이나 색 이름(`--light-blue`)을 쓰지 않는다. 같은 값을 쓰는 곳이 다섯 테마 모두 같으면 기존 토큰을 재사용하고, 테마마다 다르면 새 토큰을 만든다.

### 선언 하나를 푸는 절차

1. `python tools/chat_structure_audit.py --file <시트> --list colors`로 대상 선언을 뽑는다.
2. `python tools/chat_structure_audit.py --overrides "<선택자>" <속성>`으로 같은 대상을 다시 정하는 규칙을 찾는다.
3. `python tools/chat_pixel_compare.py --computed "<선택자>" <속성>`으로 다섯 테마의 실제 값을 적는다.
4. 기존 토큰 가운데 다섯 값이 모두 같은 것이 있으면 그것을 쓴다. 없으면 `padiem-tokens.css`에 새 토큰을 만들고, 기본값은 치환 전 바탕 값, 테마 블록은 3번의 실측값을 쓴다.
5. 소비 선언을 `var(--토큰)`으로 바꾸고, 같은 대상을 정하는 뒤 시트의 덮어쓰기를 지운다. 그 선언만 지우고, 규칙이 비면 규칙도 지운다. `!important`를 다시 붙여 맞추지 않는다.
6. `python tools/chat_pixel_compare.py`로 5테마 × 1440·390을 비교하고, 제어쌍과 변조 시험을 함께 낸다. 차이가 나면 이기는 규칙을 찾아 중복 선언을 같은 토큰으로 바꾸거나 지운다.
7. 새 토큰의 값·테마 덮개·소비 선언을 고정하는 계약 시험을 만들고, `structure_baseline.json`의 실측 숫자를 내린다.

### 증거

- 5테마 × 1440·390 픽셀 비교: `nonzero: []`, 제어쌍 0.
- 변조: 이번에 만든 토큰 하나를 바꾸면 화면이 달라진다.
- 캡처와 `manifest.json`: `padiem-reports/<날짜>/7811-<묶음>/`.
- 수치 전 → 후: `css_color_literals`, `css_color_literals_unthemed`, `css_important`, `css_themed_important`, 시트 수.
- CSS 글자를 읽는 시험이 깨지면 읽는 대상을 새 위치로 옮기거나 계산된 값 검사로 바꾼다. 검사를 약하게 만들지 않는다.

## 4. 허용 목록 (초안)

영구 허용:

- `styles.css` — 바이트 고정 참조 미러. 이 파일의 색 숫자는 옮기지 않는다.
- `padiem-foundation.css`의 외부 글꼴 `@import` 3줄 — 색이 아니다.
- `padiem-foundation.css` `body::after`의 SVG 노이즈 data URI — 색이 아닌 텍스처 페이로드다. 격자선 색은 토큰이다.
- 단독 페이지 8개 시트 — Chat 5테마 밖이다. 별도 트랙에서 다룬다.

C3~C6에서 정리할 때까지의 임시 소유(영구 허용 아님):

- 테마 덮어쓰기: `padiem-themes.css`, `padiem-dark-contrast.css`, `padiem-bright-readability.css`, `padiem-glass-brand-polish.css`, `padiem-glass-reading.css`, `padiem-glass-gutter-alignment.css`.
- Glass 배치: `padiem-glass-portrait.css`, `shared-six-panel-frame.css`, `claw-focus-layout.css`.
- C3~C6에서 정리할 부품: `padiem-surfaces.css`, `padiem-cinematic-workspace.css`, `padiem-rich.css`, `padiem-editorial.css`, `projects.css`, `padiem-settings.css`, `mode-presentation.css`, `calendar.css`.
- `padiem-foundation.css`의 나머지 색 선언 28개 — 뒤 시트가 전부 덮는다. 소유 시트와 함께 C3/C6에서 지운다.

`!important`의 영구 허용은 아직 없다. 목표는 `accessibility-floor.css` 것만 남기는 것이다. 현재 값은 아래 가드에 있다.

## 5. 가드 숫자 (2026-11-18, #8018·#8014·#8030 기준)

| 키 | 값 |
|---|---:|
| `css_files` | 84 |
| `css_rules` | 4,207 |
| `css_important` | 952 |
| `css_themed_rules` | 743 |
| `css_themed_important` | 532 |
| `css_color_literals` | 1,871 |
| `css_color_literals_unthemed` | 1,193 |
| `css_local_imports` | 0 |

기준선 파일은 `apps/padiem-chat/tests/structure_baseline.json`이다. 한 줄에 키 하나를 두고, 시트별 `!important`는 `css_important_by_file/<시트>` 키로 펼친다. 수치는 내리기만 한다.

## 6. 지금까지 (C2)

- `history.css` 기본 배경·로그인 창: #7963, #7998.
- `padiem-first-use.css` 첫 화면 입력창 그림자: #8007.
- `padiem-foundation.css` 바탕·크롬 9개 선언: #8018. 나머지 28개는 뒤 시트가 덮어 이번에 토큰화하지 않았다.
- `padiem-surfaces.css`는 다섯 테마 공통값이 없어 #7954에서 닫혔다.
- `padiem-glass` 세로 화면의 `!important` 37개를 걷어 냈다: #8014. `css_important` 989 → 952, `css_themed_important` 569 → 532.
- Claw 요청 말풍선 home·cinematic 대비를 토큰으로 고쳤다: #8020/#8030. `css_color_literals` 1,873 → 1,871, 비테마 1,194 → 1,193.
- `padiem-cinematic-workspace.css`·`padiem-rich.css`·`padiem-editorial.css`는 #7187 진행 중이다.

## 7. 새 화면을 만들 때

1. 부품 시트를 하나 만든다. `index.html`에서는 `padiem-tokens.css` 뒤, 기존 부품 시트와 같은 층에 `<link>`를 넣는다.
2. 색은 `var(--토큰)`만 쓴다. 새 색이 필요하면 토큰 파일에 `:root` 기본값과 필요한 테마 값만 추가한다.
3. 테마 전용 배치가 필요하면 허용 목록에 시트를 추가하고, 모든 선택자를 그 테마로 시작하게 한다. `!important`는 쓰지 않는다.
4. 감사 도구로 수치를 재고, 기준선을 내린다. 픽셀 5테마 × 1440·390, 제어쌍, 변조, 캡처를 PR에 낸다.
5. CSS 글자를 읽는 시험이 있으면 새 위치를 읽게 한다. 검사를 약하게 만들지 않는다.
