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

감사 도구를 불러 `apps/padiem-chat/tests/structure_baseline.json` 기준선과 비교한다.

- 어떤 수치든 기준선보다 **크면 실패**. 메시지에 무엇이 얼마나 늘었는지와
  안내("덮지 말고 이기고 있는 규칙을 고친다 / 새 기능은 새 모듈에")를 출력한다.
- 기준선보다 **작으면 실패**. 새 값을 보여 주고 기준선을 내리라고 한다.
  수치를 줄인 PR은 그 PR에서 `structure_baseline.json` 을 실측으로 갱신한다
  (#7809 공통 규칙 5 — 가드 숫자는 내리기만 한다).
- 기준선 파일은 **한 줄에 키 하나**. 트랙끼리 서로 다른 키를 고치므로 병합
  충돌이 나지 않는다. `css_important_by_file` 은 `css_important_by_file/<시트>` 
  키로 펼쳐 둔다.

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

기준선 갱신(수치를 줄인 PR에서만):

```bash
python tools/chat_structure_audit.py --json > /tmp/now.json
# /tmp/now.json 의 css_important_by_file 를 css_important_by_file/<시트> 키로
# 펼쳐 한 줄에 키 하나로 structure_baseline.json 에 반영한다.
```

