"""#7187 4차 — 패널면 씻김/상단 하이라이트 토큰.

남은 색 리터럴 전수표에서 값 ``rgba(255, 255, 255, .04)`` 묶음(11선언·5시트)을
골라 쓰임새별 두 토큰으로 옮긴다.

* ``--surface-veil-panel`` — 배경 7선언(그라디언트 안쪽 포함).
* ``--inset-veil-panel`` — ``inset 0 1px 0`` 상단 하이라이트 4선언.

값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다. 사이드바 시트와
``padiem-glass.css``는 건드리지 않는다.
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
    "--surface-veil-panel": "rgba(255, 255, 255, .04)",
    "--inset-veil-panel": "rgba(255, 255, 255, .04)",
}

CHANGED = {
    "mode-presentation.css": {
        ("background", "var(--surface-veil-panel)"): 1,
    },
    "padiem-cinematic-workspace.css": {
        ("box-shadow", "inset 0 1px 0 var(--inset-veil-panel) !important, 0 14px 38px var(--ws-banner-shadow)"): 1,
        ("background", "var(--surface-veil-panel)"): 1,
    },
    "padiem-rich.css": {
        ("background", "linear-gradient(145deg, rgba(255, 255, 255, .08), var(--surface-veil-panel)), rgba(8, 9, 11, .90)"): 1,
    },
    "padiem-surfaces.css": {
        ("background", "linear-gradient(145deg, rgba(255, 255, 255, .105), var(--surface-veil-panel)), var(--surface-card-solid)"): 1,
        ("box-shadow", "inset 0 1px 0 var(--inset-veil-panel)"): 2,
        ("box-shadow", "inset 0 1px 0 var(--inset-veil-panel) !important"): 1,
    },
    "padiem-themes.css": {
        ("background", "linear-gradient(145deg, rgba(210,235,255,.14), var(--surface-veil-panel)), rgba(8,12,20,.78)"): 1,
        ("background", "linear-gradient(145deg, rgba(200,230,255,.10), var(--surface-veil-panel)), rgba(8,12,20,.7)"): 1,
        ("background", "linear-gradient(145deg, rgba(255,240,214,.10), var(--surface-veil-panel)), rgba(11,14,22,.7)"): 1,
    },
}

LITERALS = ("rgba(255, 255, 255, .04)", "rgba(255,255,255,.04)")


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
                if "--surface-veil-panel" in normalized or "--inset-veil-panel" in normalized:
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


def test_no_panel_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = (STATIC / sheet).read_text(encoding="utf-8")
        for literal in LITERALS:
            assert literal not in text, (sheet, literal)


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--surface-veil-panel" in value:
                    assert prop.startswith("background"), (sheet, prop)
                if "--inset-veil-panel" in value:
                    assert prop.startswith("box-shadow"), (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for sheet in CHANGED:
        link = "./" + sheet
        if link in index:
            assert index.index("padiem-tokens.css") < index.index(link), sheet
        else:
            assert sheet == "mode-presentation.css", sheet
            assert "product-capabilities.js" in index
            assert "padiem-tokens.css" in index


def test_sidebar_sheets_and_glass_sheet_stay_out() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        assert "--surface-veil-panel" not in text, sheet
        assert "--inset-veil-panel" not in text, sheet
