"""#7187 6차 — 짙은 남 잉크 글자/선택 칸 토큰.

남은 색 리터럴 전수표에서 값 ``#1a2230`` 묶음(13선언·3시트)을 쓰임새별 두
토큰으로 옮긴다.

* ``--text-deep-ink`` — 글자 11선언(padiem-home 톱니·tooltip).
* ``--swatch-deep-ink`` — 선택된 테마 칸 배경·테두리 2선언.

값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다(모든 사용처가
같은 값). 이 값은 padiem-home의 ``--text``와 같지만 역할이 다르므로 별도
토큰으로 둔다(``--user-bubble-bg`` 선례). 사이드바 시트와 ``padiem-glass.css``는
건드리지 않는다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.token_foundation_source import foundation_css, index_html, read, read_static, tokens_css

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {
    "--text-deep-ink": "#1a2230",
    "--swatch-deep-ink": "#1a2230",
}

CHANGED = {
    "padiem-themes.css": {
        # #7811 C3: padiem-home 입력칸 글자색 두 줄이 이 시트를 떠났다. 대화 상태의
        # !important 줄은 기본 규칙과 값이 같은 중복이라 걷어 냈고(2 → 1), 기본
        # 규칙(.composer textarea)은 바탕 규칙이 읽는 --surfaces-composer-text의
        # padiem-home 값(var(--text-deep-ink))으로 옮겼다(8 → 7).
        ("color", "var(--text-deep-ink)"): 7,
        ("color", "var(--text-deep-ink) !important"): 1,
    },
    "padiem-settings.css": {
        ("background", "var(--swatch-deep-ink)"): 1,
        ("border-color", "var(--swatch-deep-ink)"): 1,
    },
    "shared-tooltip.css": {
        ("color", "var(--text-deep-ink)"): 1,
    },
}

LITERAL = "#1a2230"


def test_root_tokens_hold_the_pre_change_literal() -> None:
    rules = parse_rules(tokens_css())
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_tokens() -> None:
    for rule in parse_rules(tokens_css()):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_the_declarations_consume_the_right_role() -> None:
    total = 0
    for sheet, expected in CHANGED.items():
        actual: Counter = Counter()
        for rule in parse_rules(read_static(sheet)):
            for prop, value in rule.declarations.items():
                normalized = re.sub(r"\s+", " ", value).strip()
                if any(name in normalized for name in ROOT_TOKENS):
                    actual[(prop, normalized)] += 1
        assert actual == Counter(expected), sheet
        total += sum(actual.values())
    # 13선언으로 옮겼고(#7187 6차), #7811 C3에서 2선언이 이 시트들을 떠나 11선언이다.
    assert total == 11


def test_swapping_the_tokens_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert LITERAL in restored, (sheet, prop, value)


def test_no_deep_ink_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = read_static(sheet)
        assert LITERAL not in text, sheet


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules(read_static(sheet)):
            for prop, value in rule.declarations.items():
                if "--text-deep-ink" in value:
                    assert prop == "color", (sheet, prop)
                if "--swatch-deep-ink" in value:
                    assert prop in ("background", "border-color"), (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = index_html()
    for sheet in CHANGED:
        link = "./" + sheet
        assert link in index, sheet
        assert index.index("padiem-tokens.css") < index.index(link), sheet


def test_sidebar_sheets_and_glass_sheet_stay_out() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = read_static(sheet)
        for name in ROOT_TOKENS:
            assert name not in text, (sheet, name)
