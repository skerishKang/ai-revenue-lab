"""#7187 3차 — 아주 옅은 칸 바탕 씻김/상단 하이라이트 토큰.

남은 색 리터럴 전수표에서 값 ``rgba(255, 255, 255, .035)`` 묶음(10선언·3시트,
다섯 테마 computed 동일)을 골라 쓰임새별 두 토큰으로 옮긴다.

* ``--surface-veil-ghost`` — 배경 9선언(칸 바탕 씻김).
* ``--inset-veil-ghost`` — ``inset 0 1px 0`` 상단 하이라이트 1선언.

값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다(다섯 테마에서
같은 값이 칠해진다). 사이드바 시트(로컬2 #7961)는 건드리지 않는다.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {
    "--surface-veil-ghost": "rgba(255, 255, 255, .035)",
    "--inset-veil-ghost": "rgba(255, 255, 255, .035)",
}

CHANGED = {
    "padiem-cinematic-workspace.css": {
        ("background", "var(--surface-veil-ghost) !important"): 4,
    },
    "padiem-editorial.css": {
        ("background", "var(--surface-veil-ghost)"): 1,
    },
    "padiem-rich.css": {
        ("background", "var(--surface-veil-ghost)"): 4,
        ("box-shadow", "inset 0 1px 0 var(--inset-veil-ghost)"): 1,
    },
}

ORIGINAL = "rgba(255, 255, 255, .035)"


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


def test_the_ten_declarations_consume_the_right_role() -> None:
    total = 0
    for sheet, expected in CHANGED.items():
        actual: Counter = Counter()
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--surface-veil-ghost" in value or "--inset-veil-ghost" in value:
                    actual[(prop, value)] += 1
        assert actual == Counter(expected), sheet
        total += sum(actual.values())
    assert total == 10


def test_swapping_the_tokens_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert ORIGINAL in restored, (sheet, prop, value)


def test_no_ghost_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = (STATIC / sheet).read_text(encoding="utf-8")
        assert ORIGINAL not in text, sheet


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--surface-veil-ghost" in value:
                    assert prop.startswith("background"), (sheet, prop)
                if "--inset-veil-ghost" in value:
                    assert prop.startswith("box-shadow"), (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for sheet in CHANGED:
        assert index.index("padiem-tokens.css") < index.index("./" + sheet), sheet


def test_sidebar_sheets_stay_out_of_this_change() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        assert "--surface-veil-ghost" not in text, sheet
        assert "--inset-veil-ghost" not in text, sheet
