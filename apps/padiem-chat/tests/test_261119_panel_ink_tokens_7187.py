"""#7187 9차 — 패널 짙은 잉크(#17212a) 쓰임새 토큰.

남은 색 리터럴 전수표(감사 도구 실측)에서 값 ``#17212a`` 묶음 중 화면에 실제로
칠해지는 11선언을 ``--text-panel-ink`` 하나로 모은다. 유리 패널·대화상자·설정
머리·연결 재시도 글자가 모두 같은 값이라 역할 이름은 "패널 위 짙은 글자"다.

값은 치환 전 리터럴 그대로이고, 선언마다 테마와 무관하게 같은 값을 박아 두었으므로
``:root`` 기본값만 둔다(테마 블록 덮어쓰기 없음). 6차의 ``--text-deep-ink``
(#1a2230)와 값이 달라 병합하지 않는다.

사이드바 시트(``sidebar-utility.css``)·``padiem-glass.css``·``claw-focus-layout.css``·
``help.css``의 같은 값 선언은 이번 묶음 밖이라 그대로 둔다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {"--text-panel-ink": "#17212a"}

CHANGED = {
    "accessibility-polish.css": {
        ("color", "var(--text-panel-ink)"): 1,
    },
    "capability-nav.css": {
        ("color", "var(--text-panel-ink)"): 2,
    },
    "mode-presentation.css": {
        ("color", "var(--text-panel-ink)"): 5,
    },
    "padiem-settings.css": {
        ("color", "var(--text-panel-ink)"): 2,
    },
    "standalone-views.css": {
        ("color", "var(--text-panel-ink)"): 1,
    },
}

LITERAL = "#17212a"
TOKEN_NAME = "--text-panel-ink"
TOKENS_SHEET = "padiem-tokens.css"
JS_ONLY_SHEET = "mode-presentation.css"
JS_ONLY_ENTRY = "product-capabilities.js"
TEXT_COLOR_PROP = "color"


def test_root_token_holds_the_pre_change_literal() -> None:
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_token() -> None:
    for rule in parse_rules(TOKENS.read_text(encoding="utf-8")):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_the_eleven_declarations_consume_the_token() -> None:
    total = 0
    for sheet, expected in CHANGED.items():
        actual: Counter = Counter()
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                normalized = re.sub(r"\s+", " ", value).strip()
                if any(name in normalized for name in ROOT_TOKENS):
                    actual[(prop, normalized)] += 1
        assert actual == Counter(expected), sheet
        total += sum(actual.values())
    assert total == 11


def test_swapping_the_token_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert LITERAL in restored, (sheet, prop, value)


def test_no_panel_ink_literal_remains_in_the_changed_sheets() -> None:
    # capability-nav.css:57의 ``#17212a``는 이번 묶음에서 뺀 Claw 대화상자
    # (Claw 패널 소유) 글자라 그대로 둔다 — 한 시트에 남는 유일한 예외다.
    for sheet in CHANGED:
        text = (STATIC / sheet).read_text(encoding="utf-8")
        if sheet == "capability-nav.css":
            assert text.count(LITERAL) == 1, sheet
        else:
            assert LITERAL not in text, sheet


def test_the_token_is_only_used_for_text_color() -> None:
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if TOKEN_NAME in value:
                    assert prop == TEXT_COLOR_PROP, (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert TOKENS_SHEET in index
    for sheet in CHANGED:
        link = "./" + sheet
        if link in index:
            assert index.index(TOKENS_SHEET) < index.index(link), sheet
        else:
            # mode-presentation.css는 product-capabilities.js가 실행 중에 붙인다
            # (docs/operations/CHAT_CSS_STRUCTURE.md 2절의 JS 전용 시트).
            assert sheet == JS_ONLY_SHEET, sheet
            assert JS_ONLY_ENTRY in index


def test_the_excluded_sheets_keep_their_local_literals() -> None:
    # 이번 묶음에서 뺀 시트는 손대지 않았음을 고정한다(다음 라운드 후보).
    for sheet in ("padiem-glass.css", "claw-focus-layout.css",
                  "sidebar-utility.css", "help.css"):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        assert TOKEN_NAME not in text, sheet
