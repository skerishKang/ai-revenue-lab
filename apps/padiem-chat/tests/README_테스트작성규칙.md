# Chat 테스트 작성 규칙 (#7186)

판정 기준은 "브라우저가 하는 일이 그대로인가"이다. 파일 바이트가 아니다.
같은 동작인데 선택자 순서·줄바꿈·주석·문구만 바뀌어 실패하는 계약을 만들지 않는다.

상위 계획: #7189 · 도구: `tests/css_rules.py` · 도구 자체 시험: `tests/test_css_rules_helper.py`

## 1. CSS

| 하지 않는다 | 한다 |
| --- | --- |
| `".a, .b { color: #fff; }" in css` | `rule_selector_list_contains(rule, ".a", ".b")` |
| `"background: #355977" in css` | `declaration(rule, "background") == "#355977"` |

- 규칙 블록은 `parse_rules()`로 찾고, 선택자 포함 여부는 그 블록의 선택자
  목록(과 `:is()`/`:where()` 안 목록)으로 판정한다. 선택자 순서·줄바꿈·주석은
  결과에 영향을 주지 않는다.
- 속성 값은 `declaration()`으로 읽는다. 그 값 자체가 계약일 때만 쓴다.
- 시각 결과(색 대비, 겹침, 크기)가 판정 대상이면 브라우저의 computed style을
  읽는다. CSS 텍스트 검사로 대신하지 않는다.
- `@media` 안의 규칙은 `rule.media`로 구분한다. 같은 선택자가 여러 번 나오는
  것은 정상이다. 미디어 범위가 다르면 다른 규칙이다.
- `rule_selector_list_contains()`는 정확 일치다. `.a`로 `.a:hover` 규칙을 찾지
  않는다. 상태 목록은 `:is(...)` 안에 두고 `is_list_items()`로 펼친다.

좋은 예:

```python
rules = parse_rules(POLISH_CSS.read_text(encoding="utf-8"))
base = [
    rule
    for rule in find_rules_with_selector(rules, ".claw-generate-button")
    if not any(s.endswith((":hover", ":focus-visible")) for s in rule.selectors)
][0]
assert rule_selector_list_contains(base, "#meetingStart")
assert declaration(base, "background") == "#355977"
```

```python
rules = parse_rules(POLISH_CSS.read_text(encoding="utf-8"))
mobile = [
    rule
    for rule in find_rules_with_selector(rules, ".settings-done")
    if rule.media == "(max-width: 640px)"
]
assert len(mobile) == 1
assert declaration(mobile[0], "width") == "100%"
```

나쁜 예:

```python
assert ".claw-inbox-primary, .util-tool-open, .pdfmd-btn-primary, #meetingStart) {" in css
```

```python
assert "background: #355977;" in css  # 첫 일치가 다른 규칙일 수 있고, 중복 선언도 통과한다.
```

## 2. 문구

- 고정 문장을 붙잡지 않는다. `data-locale-key`가 `locale.js`의 `ko`·`en` 양쪽에
  선언되어 있는지, HTML이 그 키를 실제로 참조하는지 검사한다.
- 문구 자체는 대표 결정 사항이고 locale 파일에서만 바뀐다. 특정 문장이 계약이어야
  한다면 그 문장을 소유한 locale 키를 검사한다.
- 문구가 화면에 실제로 적용되는지 봐야 한다면 브라우저에서 렌더된 텍스트를 읽는다.

좋은 예:

```python
keys = locale_keys(read("locale.js"), "ko: {", "en: {")
assert 'data-locale-key="nav-claw"' in read("index.html")
assert "nav-claw" in keys
```

나쁜 예:

```python
assert "PDF → Markdown" in index_html
```

## 2-1. JS 동작

| 하지 않는다 | 한다 |
| --- | --- |
| `"googleCalendarReadState = \"active\"" in app` | 모듈을 실행하고 함수를 직접 불러 반환값·DOM·부수효과를 확인 |
| 포워더의 정확한 한 줄 문자열 찾기 | 포워더를 실행해 모듈 메서드 위임과 인자 전달을 확인 |
| 소스 블록을 잘라 `eval`하기 | 공개된 `create(deps)`로 인스턴스를 만들어 실제 deps 계약으로 실행 |

- 모듈 소스는 **실행**해도 된다. 계약은 그 실행의 반환값·DOM 변화·deps
  getter/setter 읽기·쓰기에 둔다.
- 앱 클로저 값을 흉내 낼 때는 얇은 가짜 DOM/`fetch`로 경계를 만들고, 원문
  줄·순서·공백은 고정하지 않는다.
- 브라우저 동작이 판정 대상이면 Chromium에서 직접 호출한다.

## 3. 금지 계약은 유지한다

- "app.js에서 `MutationObserver` 금지", "이 경로로 `fetch` 금지" 같은 부정 계약은
  지금도 유효한 안전·구조 결정이다. 지우지 않는다.
- 금지 대상의 존재 자체를 검사하는 형태로 유지한다. 검사 강도를 낮추지 않는다.
- 왜 금지인지 테스트 docstring에 적는다. 이유가 사라졌다면 계약을 지우는 PR에서
  이유도 함께 지운다.

```python
def test_app_js_does_not_observe_dom_mutations() -> None:
    """재렌더 루프가 입력 커서를 되돌리던 원인이었다. 그 동작이 돌아오면 안 된다."""
```

## 4. 기존 계약을 옮기는 방법

- 일괄 변환하지 않는다. 그 파일을 건드리는 PR에서 하나씩 옮긴다.
- 옮기기 전에 기존 계약이 실제로 무엇을 보장했는지 읽는다. 새 계약이 같은 보장을
  하지 못하면 옮기지 않는다.
- 검사 강도는 같거나 더 강해야 한다. 약해지는 순간 그 PR은 실패다.
- 삭제·`skip`·`xfail`·완화 금지. 실패를 통과로 바꾸는 어떤 변경도 계약 이전이 아니다.

### 이전 사례

- #7186 2단계(PR #7194): `test_5608_body_glass_unification.py`·
  `test_util_first_screen_7172.py`·`test_5908_quick_tool_grid.py`의 공용 주요 버튼
  3블록과 `.util-tool-card` 테두리를 문자열 슬라이스에서 `parse_rules`·
  `find_rules_with_selector`·`rule_selector_list_contains`·`declaration`으로 옮겼다.
  로컬 헬퍼 `_selector_group`·`_shared_primary_rules`는 css_rules가 대신한다.
- #7186 R2 3단계(자동화 구역): `test_claw_automation_create_ui.py`·
  `test_claw_automation_edit_ui.py`·`test_claw_automation_enable_toggle_ui.py`·
  `test_b62_3237_web_automation_readonly_ui.py`·`test_r5_a1_automation_module_7216.py`의
  모듈 소스 블록 자르기·payload 글자 추출·CSS 문자열·script 위치 검사를 실제
  POST/PATCH 본문, 행 렌더 결과, `parse_rules`, `HTMLParser` 로드 순서로 옮겼다.
  금지 계약(HTML sink, 실행 활성화 주장 문구, 변경 도우미 부재)은 이유를 적어 유지했다.
- #7186 R2 4단계(최근 대화 메뉴): `test_r5_step3_history_module_7216.py`의 이동 본문·
  script 위치·모듈 함수 문자열 검사를 모듈 인스턴스 실행(행·버튼·aria·locale 키,
  PATCH/DELETE method·경로·본문)과 `HTMLParser` 로드 순서로 옮겼다. 이중 소유·팩토리
  경계는 소유 구조 계약이라 이유를 적어 유지했다.
- #7186 R2 5단계(로그인 세션 구역): `test_r5_step4_auth_module_7216.py`·
  `test_4416`·`test_5424`·`test_5474`·`test_5479`·`test_5559`·`test_5664`의 인증 상태
  매핑·로그인/로그아웃 요청·재시도 정책·아바타/계정 표시 문자열 검사를 공용 하네스
  `_r5_auth_module_harness.py`의 실행 관찰(선박 표 주입 상태별 보임/숨김·문구·aria,
  POST method·경로·본문, 재시도 횟수, 세션 발행)로 옮겼다. HTML sink·전달 함수·이동
  본문 위치·capabilities 공유 규칙 같은 경계·구조 계약은 이유를 적어 유지했다.
- #7186 R2 6단계(대화 구역): `test_r5_step5_conversation_module_7216.py`·
  `test_claw_disclosure_chat_isolation_261016.py`·`test_continuous_first_turn_layout_261015.py`·
  `test_4488_answer_copy_wiring_261019.py`의 한 줄 전달 함수 문자열·deps 정규식
  카운트·본문 슬라이스 검사를 전달 함수 실행 위임, app.js deps 블록 실행
  (getter/setter 라이브 읽기·쓰기), 로드 시점 DOM 접촉 0회, showConversation·
  addUserMessage·renderAnswer·renderStreamError·resetConversation의 렌더 요소·
  aria·locale 키·첨부 페이로드 본문 실행으로 옮겼다. 이동 본문 소유·정의 1개·
  미이동 와이어링 호출점은 소유 구조 계약으로 이유를 적어 유지했다.
- #7186 R2 설정·사이드바 1단계: `test_r5_step1_settings_sidebar_module_7216.py`·
  `test_4416`·`test_7476_settings_dialog_contract.py`·`test_7365`의 설정 창 열기/닫기·
  고급 설정 전환·접기/펴기·알림 스위치·계정 구역 문자열 검사를 공용 하네스
  `_r5_settings_sidebar_module_harness.py`와 `claw-push.js`·`chat-auth-module.js` 실행
  관찰(hidden·aria-expanded·포커스·locale 키 보존·메뉴 키·이벤트)로 옮겼다. 팩토리·
  이중 소유·전달 함수·script 로드 순서(HTMLParser)는 구조 계약이라 이유를 적어 유지했다.
- #7186 R2 첨부·Claw 실행 해제: `test_b54_claw_execute_retry_ui.py`·
  `test_b54_claw_execute_progress_ui.py`·`test_5881_file_lane.py`·
  `test_b62_1727_attachment_unification.py`·`test_chat_multi_attachment_261102.py`·
  `test_2505_chat_claw_attachment_parity.py`의 첨부 페이로드·칩 흐름·이미지 라우팅과
  clearClawRecovery/clearClawWait 해제 배선 문자열 검사를 공용 하네스
  `_r5_attachment_module_harness.py`의 실행 관찰(chat-conversation-module.js의
  attachmentPayload 4분지·addAttachmentFiles 흡수와 칩별 거부·칩 렌더·제거 연결·
  resetConversationView 해제, claw-session.js의 인증 소실 해제)과 실 app.js 행동
  하네스 결과로 옮겼다. 이중 소유·단일 정의·app.js deps 공급 와이어링·"해제는 타이머를
  만들지 않는다" 금지·클라이언트 이미지 거부 문구 부재는 구조·금지 계약이라 이유를
  적어 유지했다.

## 5. 도구

`tests/css_rules.py` — 표준 라이브러리만 사용한다.

| 함수 | 쓰임 |
| --- | --- |
| `parse_rules(css_text)` | `Rule(selectors, declarations, media)` 목록 |
| `find_rules_with_selector(rules, selector)` | 선택자 목록에 `selector`가 든 규칙 |
| `rule_selector_list_contains(rule, *selectors)` | 목록 포함 여부(정확 일치) |
| `declaration(rule, prop)` | 속성 값(블록 안 마지막 선언) |
| `is_list_items(selector)` | `:is()`/`:where()` 안 목록 |

파서가 읽는 모양과 읽지 않는 모양은 `css_rules.py` 모듈 docstring에 있다.

전송 구역(tus 업로드·파일 레인·첨부 역량)은 소스 문자열이 아니라 `_r5_transport_upload_harness.py`의 실행 관찰로 검사한다 — 남기는 문자열 검사는 "그 문자열이 없다" 자체가 계약인 경우뿐이고, 이유를 시험 docstring에 적는다.

스트리밍 배선(file-lane 칩 업로드·취소 신호)도 소스 문자열이 아니라 `_r5_streaming_harness.py`의 실행 관찰로 검사한다(#7186 R2 2차).

제품 표면·BYOK(product-capabilities.js)도 소스 문자열이 아니라 `_r5_product_capabilities_harness.py`의 실행 관찰로 검사한다(#7186 R2 마무리 1단계).
