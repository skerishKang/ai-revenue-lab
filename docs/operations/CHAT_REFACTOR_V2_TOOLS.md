# 리팩터링 v2 도구 (#7809 · #7810)

리팩터링 v2 트랙이 쓰는 가드·증거 도구의 실행 방법과 수치 정의.
제품 코드(`apps/padiem-chat/static`, `apps/padiem-chat/app`)는 이 문서의 도구들이
읽기만 하고 바꾸지 않는다.

---

## 1. 수치 감사 — `tools/chat_structure_audit.py`

저장소 파일만 읽어 구조 수치를 잰다. 표준 라이브러리만 쓴다(가상환경 불필요).

```bash
python tools/chat_structure_audit.py --json    # 기계용(래칫·문서 인용용)
python tools/chat_structure_audit.py --table   # 사람용 표
```

### 수치 정의

CSS 대상은 `apps/padiem-chat/static/*.css`. **주석을 제거한 뒤** 세고,
`@media`·`@supports` 안쪽 규칙도 포함한다.

| 키 | 정의 |
|---|---|
| `css_files` | 시트 수 |
| `css_rules` | 선택자 규칙 블록 수(중첩 포함). `@media`·`@supports`·`@layer` 등 컨테이너 안쪽 규칙도 센다. `@keyframes` 프레임(`from{}`·`0%{}`)은 선택자 규칙이 아니므로 세지 않는다 |
| `css_important` | `!important` 가 붙은 선언 수 |
| `css_important_by_file` | 위를 파일별로. 기준선 파일에는 `css_important_by_file/<시트 이름>` 키로 한 줄씩 펼쳐 들어간다 |
| `css_themed_rules` | 선택자에 `data-theme` 이 있는 규칙 수 |
| `css_themed_important` | 그 규칙 안의 `!important` 선언 수 |
| `css_color_literals` | 값에 색 숫자(`#hex`, `rgb()`, `rgba()`, `hsl()`, `hsla()`)가 든 선언 수. `--이름:` 사용자 속성 **정의는 세지 않는다** |
| `css_color_literals_unthemed` | 그중 `data-theme` 범위 밖 선언 수 |
| `css_local_imports` | 같은 폴더 시트를 부르는 `@import` 수(외부 글꼴 제외) |

JS 대상은 `static/app.js` 와 `static/index.html`.

| 키 | 정의 |
|---|---|
| `appjs_lines` | `app.js` 줄 수 |
| `appjs_forwarders` | 본문이 모듈 인스턴스 호출 한 줄뿐인 함수 수(`return 모듈().메서드(…);` 또는 `모듈().메서드(…);`) |
| `appjs_deps_total` | `window.PadiemChat…Module.create({ … })` 묶음의 최상위 항목 수 합. 공유 문맥 `PadiemChatAppContext.create` 묶음은 제외 |
| `appjs_function_decls` | `function 이름(…)` 선언 수 |
| `appjs_dom_lookups` | `getElementById`·`querySelector` 식별자 등장 수(`querySelectorAll` 은 `querySelector` 의 앞부분 일치로 함께 센다) |
| `appjs_listeners` | `addEventListener` 등장 수 |
| `index_script_tags` | `index.html` 의 `<script` 수 |

서버 대상은 `apps/padiem-chat/app/*.py`.

| 키 | 정의 |
|---|---|
| `history_py_lines` | `history.py` 줄 수 |
| `d1_history_store_lines` | `D1HistoryStore` 클래스 본문 줄 수(클래스 줄부터 다음 최상위 문장 직전까지) |
| `d1_history_store_methods` | 그 본문에 직접 정의된 `def`(·`async def`) 메서드 수 |
| `py_functions_over_300` | 300줄 이상 함수 수(`ast` 로 잰다). `--json` 은 이름·파일·줄 수 목록(`py_functions_over_300_names`)도 낸다 |

시험 대상은 `apps/padiem-chat/tests/test_*.py` (#8061).

| 키 | 정의 |
|---|---|
| `test_files_importing_test_files` | 다른 `test_` 모듈을 import하는 시험 파일 수 |
| `test_to_test_import_edges` | 그 import 문 전체 수(파일당 여러 건 센다) |

규칙: 새 공용 시험 헬퍼는 `apps/padiem-chat/tests/_support/` 에 두고 `test_` 파일끼리 import하지 않는다(#8061). 옛 import는 일괄 이동하지 않는다.

| 키 | 정의 |
|---|---|
| `test_files_asserting_raw_static_text` | static CSS·JS·HTML 원문을 읽어 문자열 단언을 둔 시험 파일 수 |
| `raw_static_text_assertions` | 그 단언 수(한글 사용자 문구 계약은 제외) |

규칙: 새 시험은 원문 글자 대신 파싱된 구조로 단언하고, 화면에 나와야 하는 한국어 문구 계약만 문자열로 둔다(#8060). 옛 시험 일괄 수정은 하지 않는다.

### 찾기 옵션(T1 이 사용)

```bash
# 한 시트에서 해당 선언 나열: 줄 · 선택자 · 속성 · 값
python tools/chat_structure_audit.py --file padiem-themes.css --list colors
python tools/chat_structure_audit.py --file padiem-themes.css --list important
python tools/chat_structure_audit.py --file padiem-themes.css --list themed

# 마지막 복합 선택자가 같고 속성이 같은 규칙을 "로드 순서대로" 나열
# (시트 · 줄 · !important 여부 · 테마 범위)
python tools/chat_structure_audit.py --overrides ".library-item-title" display
```

로드 순서는 `index.html` 의 `<link>` 순서를 따르고, 시트 안의 로컬 `@import` 는
그 시트보다 앞에서 펼친다(CSS 규칙상 `@import` 는 자기보다 앞에서 적용된다).
같은 시트가 여러 번 로드되면 첫 등장 순서를 쓴다.

---

## 2. 구조 래칫 — `apps/padiem-chat/tests/test_structure_ratchet.py`

기준선 JSON을 커밋하지 않는다(#8054). 매 실행마다 base 트리를 임시 체크아웃하고,
head와 **같은 감사 도구 코드**로 둘 다 잰 뒤 비교한다.

- 어떤 수치든 base(main) 실측보다 **크면 실패**. 메시지에 무엇이 얼마나 늘었는지와
  안내("덮지 말고 이기고 있는 규칙을 고친다 / 새 기능은 새 모듈에")를 출력한다.
- **줄어들면 실패하지 않는다.** 기준선 갱신 커밋이 없으므로, 수치를 줄이는 PR 두 개가
  같은 파일에서 충돌하지 않는다.
- `index_script_tags` 는 새 모듈 1개 = script 태그 +1이 정상이라 비교에서 뺀다(#7816).
  `css_important_by_file` 은 `css_important_by_file/<시트>` 키로 펼쳐 비교한다.
- 파일 줄 상한 같은 **절대 상한**은 이 래칫이 아니라 `test_r5_file_size_guard_7216.py`·
  `test_r6_history_file_size_guard_7790.py` 가 소유한다.

base 트리 선택 순서: `PADIEM_STRUCTURE_BASE_ROOT`(준비된 체크아웃) →
`PADIEM_STRUCTURE_BASE_SHA`(CI가 PR base 커밋을 넘김, 없으면 `git fetch --depth=1`) →
`PADIEM_STRUCTURE_BASE_REF` 또는 `origin/main`.

CI: `.github/workflows/b62-padiem-chat-ci.yml` 의 `b62-ui-contract-tests` 잡이
시험 소스에서 static 경로를 읽는 모듈을 자동 수집한다. Chat 정적 파일이 바뀌는
PR에서는 이 시험이 항상 돈다. app 코드가 바뀌는 PR은 전체 Chat 시험에서 함께
돈다. 기존 가드(`test_r5_file_size_guard_7216.py`,
`test_r6_history_file_size_guard_7790.py`)는 그대로 둔다.

로컬 실행:

```bash
cd apps/padiem-chat
uv run python -m pytest -q tests/test_structure_ratchet.py
```

base 실측을 직접 보려면(감사 도구 `--root`):

```bash
git worktree add --detach /tmp/padiem-base origin/main
python tools/chat_structure_audit.py --root /tmp/padiem-base --json
git worktree remove --force /tmp/padiem-base
```

---

## 3. 화면 픽셀 비교 — `tools/chat_pixel_compare.py`

CSS를 바꾼 PR이 "화면이 그대로"임을 보이는 유일한 증거(#7809 공통 규칙 3).
로컬 정적 서버 + 모의 API로 기준과 비교 대상을 각각 띄워 같은 조합의
스크린샷을 찍고 픽셀 차이를 센다. 실제 서버·로그인·고객 계정을 쓰지 않고,
외부 요청은 전부 abort 한다. playwright·Pillow·numpy 가 필요하다(로컬 증거용).

```bash
# 작업 트리 대 origin/main 전체 조합(기본)
python tools/chat_pixel_compare.py

# 일부만: --only theme=<이름> screen=<이름> viewport=<1440x950|390x844>
python tools/chat_pixel_compare.py --only theme=light screen=conversation

# PR: 바뀐 시트가 닿는 화면만(#8055) — 130조합을 다 돌리지 않는다
python tools/chat_pixel_compare.py --changed-sheets util-menu.css chat-feedback.css

# 다섯 테마에서 그 요소의 실제 계산 값(토큰 값을 정할 때)
python tools/chat_pixel_compare.py --computed ".project-drive-status" color
```

- 입력: `--before`(기본 `origin/main`)과 `--after`(기본 작업 트리, 리비전을
  주면 `git archive` 로 꺼낸다). 각각 별도 포트의 정적 서버로 띄운다.
- 조합: 테마 5(`light`·`dark`·`padiem-glass`·`cinematic`·`padiem-home`) ×
  폭 2(1440×950, 390×844) × 화면 13.
  화면: 홈(로그아웃), 홈(로그인), 대화, Claw, 유틸, 캘린더, 자동화, 라이브러리,
  설정 창, 프로필 메뉴 열림, 내 의견 창, 프로젝트 설정 창, 로그인 창.
- 모의 API: `/api/auth/status`(게스트·로그인 두 모드), `/api/projects`,
  `/api/conversations`, `/api/project-files`, `/api/calendar/*` 는 고정 응답,
  나머지 `/api/*` 는 즉시 같은 모양 404. 비동기 상태 문구가 응답 타이밍에 따라
  갈리지 않게 네트워크 경주를 제거한다. 클로 연결 카드 상태 문구는
  MutationObserver 로 게스트 단말 문구에 고정한다.
- 안정화 규칙: 움직임을 멈추는 CSS(애니메이션·전환·캐럿·`backdrop-filter`
  끔)는 `<style>` 요소로 넣는다 — 스크립트 문자열 주입은 매 페이지
  SyntaxError를 내고 CSS가 적용되지 않는다(#7187 r41 교훈). dialog 뒷배경
  흐림은 래스터화가 비결정적이라 양쪽 같은 규칙으로 끈다. 정적 서버 backlog
  128 이상. `Math.random`·`Date.now`·`new Date()` 고정. 화면 상태 서명·상태
  문구·픽셀이 3번 연속 같을 때 찍는다(2연속은 지연 생성 숨은 UI 덩어리를 못
  잡았다). 찍기 전 검증: 앱 초기화 표식, 페이지 오류 0, 스크립트 로드 실패
  0 — 불충분하면 최대 3회 다시 찍는다.
- 차이 판정: 채널별 ±1 색 반올림(안티에일리어싱·디더링)을 제외한 뒤 잔차
  8픽셀 이하는 페인트 디더링으로 무차이(#7187 r41 noise_pixels 선례). 그 위는
  실차이로 본다. 보고서(`compare_report.json`·`control_report.json`)에는
  원값(`pixel`)과 판정값(`noise`)을 함께 남긴다.
- 출력: 차이 JSON, 차이 난 조합의 before·after·diff 이미지,
  after 쪽 캡처 전수(`captures/`) — 각 화면이 의도한 상태로 찍혔는지 사람이
  직접 여는 용도. 차이가 하나도 없으면 종료 코드 0. `--out`으로 산출물 폴더를
  바꿀 수 있다(야간 실행은 러너 임시 폴더).
- 범위 좁히기(#8055): `--changed-sheets <시트…>`를 주면 `tools/chat_pixel_scope.py`
  가 시트 본문의 표식(`#calendarView`·`.util-`·`[data-claw-card]` 등)으로
  **그 시트가 닿는 화면만** 고른다. 화면 이름은 `SCREENS`와 같고
  (`apps/padiem-chat/tests/test_pixel_sheet_scope_8055.py`가 대조한다), 공용 시트
  (`padiem-tokens.css` 등)나 모르는 시트 이름은 전 화면으로 넓게 잡는다 —
  좁히지 못한 것을 “차이 없음”으로 통과시키지 않는다. 고른 화면·조합 수는
  로그 JSON과 `scope_report.json`에 남는다.
- 130조합 전체(main 대 main)는 PR이 아니라 야간 워크플로
  `.github/workflows/b62-chat-pixel-nightly.yml`(04:00 KST)이 돈다. 산출물은
  artifact `chat-pixel-nightly`, 실패하면 "화면 픽셀 야간 비교 실패" 이슈를 연다
  (이미 열려 있으면 새로 열지 않는다).

- 절차(증거 세션):
  1. 제어쌍 `--control`: 같은 대상을 두 번 찍어 비교 — 전 조합 0이어야 한다.
     0이 아니면 도구 문제다(종료 코드 2).
  2. main 대 main(기본 실행): 전 조합 0(종료 코드 0).
  3. 변조 시험 `--tamper`: `--radius-pill` 999px→0px 로 바꾼 사본으로 claw
     화면을 찍어 차이가 잡히는지 본다(잡히지 못하면 종료 코드 3). 참고:
     `--radius-sm` 10→13px 는 클로 화면에서 보이는 10px 요소가 brand-mark
     1개뿐이라 잡히지 않을 수 있다(#7187 관찰). `999px→40px` 는 높이 80px
     이하 요소에서 클램프로 무차이므로 쓰지 않는다.

한계: 채널 ±1과 잔차 8픽셀 이하는 무차이로 본다 — 작은 요소 하나의
반경·색 1단계 변경은 이 도구로 잡히지 않으므로 해당 변경은 숫자 시험으로
확인한다.

---

## 4. JS가 실행 중에 붙이는 시트 (#7811 C1 목록)

`index.html`의 `<link>`가 아닌, JS가 `document.head`에 `<link rel="stylesheet">`를
추가하는 시트 7종. 전부 중복 가드(`link[마커]`가 있으면 붙이지 않음)를 갖고,
C1에서는 손대지 않았다. 늦게 붙으므로 카운트 시점의 캐스케이드에서는
정적 `<link>`보다 뒤에 온다.

| 시트 | 붙이는 JS | 붙는 시점 | 정적 `<link>` |
|---|---|---|---|
| `padiem-glass.css` | `theme-init.js`, `theme.js`의 `ensureGlassStyles()` | head 동기 실행(theme-init, 테마가 glass일 때) / 테마를 glass로 적용·초기화할 때(theme) | 있음(`data-padiem-glass-theme`) — 보통 미동작 |
| `padiem-glass-portrait.css` | `theme-init.js`, `theme.js`의 `ensureGlassStyles()` | 위와 같음 | 있음(`data-padiem-glass-portrait`) — 보통 미동작 |
| `padiem-glass-reading.css` | `theme.js`의 `ensureGlassStyles()` | 테마를 glass로 적용·초기화할 때 | 없음(유일한 로더) |
| `interaction-polish.css` | `interaction-polish.js`의 `ensureStyles()` | 모듈 초기화 즉시 | 있음(`data-interaction-polish-styles`) — 보통 미동작. `a11y.js`는 이 JS를 주입한다(시트 아님) |
| `capability-presentation.css` | `message-lifecycle.js`의 `ensureCapabilityStyles()` | 작업 카드(`renderTaskCard`) 첫 렌더 | 없음(유일한 로더) |
| `mode-presentation.css` | `product-capabilities.js`의 `ensureModeStyles()` | 모드 표시 설치(`installModePresentation`) | 없음(유일한 로더) |
| `pc-file-exchange.css` | `b66-quote-runtime.js`·`claw-web-xlsx-sources.js`·`util-pdfmd.js`·`util-tools.js`의 `loadPcExchange()`(네 곳이 같은 시트를 공유, 가드는 `link[href]` 조회) | PC 파일 교환 부품 첫 사용 | 없음(유일한 로더) |
