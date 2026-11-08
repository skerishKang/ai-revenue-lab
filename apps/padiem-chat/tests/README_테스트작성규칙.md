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
