"""#7187 8차 — 흰 안개(.78) 칠하기·테두리·글자 토큰.

남은 색 리터럴 전수표에서 값 ``rgba(255, 255, 255, .78)`` 묶음(12선언·11시트) 중
칠하는 10선언을 쓰임새별 세 토큰으로 옮긴다.

* ``--surface-veil-haze`` — 배경 3선언(그라디언트 첫 정지 포함).
* ``--line-veil-haze`` — 테두리 4선언(``!important`` 하나는 원래 자리 그대로).
* ``--text-veil-haze`` — 글자 4선언.

``styles.css``는 바이트 고정(참조 미러)이라 손대지 않는다.
값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다(5테마 실측에서
칠하는 곳마다 같은 값). 사이드바 시트와 ``padiem-glass.css``는
건드리지 않는다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {
    "--surface-veil-haze": "rgba(255, 255, 255, .78)",
    "--line-veil-haze": "rgba(255, 255, 255, .78)",
    "--text-veil-haze": "rgba(255, 255, 255, .78)",
}

CHANGED = {
    "accessibility-polish.css": {
        ("border-color", "var(--line-veil-haze)"): 1,
    },
    "chat-feedback.css": {
        ("border-color", "var(--line-veil-haze)"): 1,
    },
    "interaction-polish.css": {
        ("background", "var(--surface-veil-haze)"): 1,
    },
    "padiem-editorial.css": {
        ("color", "var(--text-veil-haze)"): 1,
    },
    "padiem-glass-reading.css": {
        # #8008 10차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
        ("border-color", "var(--line-veil-haze)"): 1,
    },
    "padiem-rich.css": {
        ("color", "var(--text-veil-haze)"): 1,
    },
    "padiem-surfaces.css": {
        ("color", "var(--text-veil-haze)"): 1,
    },
    "padiem-settings.css": {
        ("border-color", "var(--line-veil-haze)"): 1,
    },
    "padiem-themes.css": {
        ("background", "var(--surface-veil-haze)"): 1,
        ("background", "linear-gradient(180deg, var(--surface-veil-haze), rgba(250,252,255,.58))"): 1,
    },
    "util-menu.css": {
        ("color", "var(--text-veil-haze)"): 1,
    },
}

LITERALS = ("rgba(255, 255, 255, .78)", "rgba(255,255,255,.78)")


def test_root_tokens_hold_the_pre_change_literal() -> None:
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_tokens() -> None:
    for rule in parse_rules(TOKENS.read_text(encoding="utf-8")):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_the_eleven_declarations_consume_the_right_role() -> None:
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


def test_swapping_the_tokens_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert any(literal in restored for literal in LITERALS), (sheet, prop, value)


def test_no_haze_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = (STATIC / sheet).read_text(encoding="utf-8")
        for literal in LITERALS:
            assert literal not in text, (sheet, literal)


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--surface-veil-haze" in value and "inset" not in value:
                    assert prop.startswith("background"), (sheet, prop)
                if "--line-veil-haze" in value:
                    assert prop.startswith("border"), (sheet, prop)
                if "--text-veil-haze" in value:
                    assert prop == "color", (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for sheet in CHANGED:
        link = "./" + sheet
        if link in index:
            assert index.index("padiem-tokens.css") < index.index(link), sheet
        else:
            assert sheet == "padiem-glass-reading.css", sheet
            assert "theme.js" in index
            assert "padiem-tokens.css" in index


def test_sidebar_sheets_and_glass_sheet_stay_out() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        for name in ROOT_TOKENS:
            assert name not in text, (sheet, name)
