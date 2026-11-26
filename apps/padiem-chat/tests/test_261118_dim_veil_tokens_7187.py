"""#7187 5차 — 엷은 구분선·칸 바탕·인셋 하이라이트 토큰.

남은 색 리터럴 전수표에서 값 ``rgba(255, 255, 255, .09)`` 묶음(10선언·4시트,
모두 비테마 단일 색)을 쓰임새별 세 토큰으로 옮긴다.

* ``--line-veil-dim`` — 테두리 6선언.
* ``--surface-veil-dim`` — 배경 3선언.
* ``--inset-veil-dim`` — ``inset -1px 0`` 하이라이트 1선언.

값은 치환 전 리터럴 그대로고 테마 블록에서는 덮지 않는다. 사이드바 시트와
``padiem-glass.css``는 건드리지 않는다.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.token_veil_source import admin_models_css, index_html, read, read_static, tokens_css

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

ROOT_TOKENS = {
    "--line-veil-dim": "rgba(255, 255, 255, .09)",
    "--surface-veil-dim": "rgba(255, 255, 255, .09)",
    "--inset-veil-dim": "rgba(255, 255, 255, .09)",
}

CHANGED = {
    "admin-models.css": {
        ("box-shadow", "inset -1px 0 var(--inset-veil-dim)"): 1,
    },
    "padiem-cinematic-workspace.css": {
        # 7811 C5: 이 시트의 우선 표시를 걷어 내 다섯 선언 모두 토큰만 소비한다.
        ("border-color", "var(--line-veil-dim)"): 5,
        ("background", "var(--surface-veil-dim)"): 1,
    },
    "padiem-rich.css": {
        ("border-bottom-color", "var(--line-veil-dim)"): 1,
        ("background", "var(--surface-veil-dim)"): 1,
    },
    "padiem-surfaces.css": {
        # #8340: 캡 제거로 !important 없이 토큰만 소비한다.
        ("background", "var(--surface-veil-dim)"): 1,
    },
}

LITERALS = ("rgba(255, 255, 255, .09)", "rgba(255,255,255,.09)")


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


def test_the_ten_declarations_consume_the_right_role() -> None:
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
    assert total == 10


def test_swapping_the_tokens_back_returns_the_original_literal() -> None:
    for sheet, expected in CHANGED.items():
        for (prop, value) in expected:
            restored = value
            for name, literal in ROOT_TOKENS.items():
                restored = restored.replace(f"var({name})", literal)
            assert any(literal in restored for literal in LITERALS), (sheet, prop, value)


def test_no_dim_literal_remains_in_the_changed_sheets() -> None:
    for sheet in CHANGED:
        text = read_static(sheet)
        for literal in LITERALS:
            assert literal not in text, (sheet, literal)


def test_each_token_stays_in_its_own_property_family() -> None:
    for sheet in CHANGED:
        for rule in parse_rules(read_static(sheet)):
            for prop, value in rule.declarations.items():
                if "--line-veil-dim" in value:
                    assert prop.startswith("border"), (sheet, prop)
                if "--surface-veil-dim" in value:
                    assert prop.startswith("background"), (sheet, prop)
                if "--inset-veil-dim" in value:
                    assert prop.startswith("box-shadow"), (sheet, prop)


def test_consumers_load_tokens_first() -> None:
    for sheet in CHANGED:
        link = "./" + sheet
        consumers = [p for p in STATIC.glob("*.html") if link in read(p)]
        assert consumers, sheet
        for page in consumers:
            html = read(page)
            assert html.index("padiem-tokens.css") < html.index(link), (sheet, page.name)


def test_sidebar_sheets_and_glass_sheet_stay_out() -> None:
    for sheet in ("padiem-glass.css", "sidebar-unified.css", "sidebar-utility.css"):
        text = read_static(sheet)
        for name in ROOT_TOKENS:
            assert name not in text, (sheet, name)
