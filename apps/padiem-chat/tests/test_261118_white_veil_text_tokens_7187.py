"""#7187 2차 — 반투명 흰색 글자색 의미 토큰(--text-veil).

1차의 표면/구분선 토큰과 같은 원칙을 글자색에 적용한다. 전수표에서
글자색으로 쓰인 반투명 흰색 중 단계 값과 문자 그대로 같은 선언만 바꾼다.

* --text-veil-faint = rgba(255, 255, 255, .42)
* --text-veil-strong = rgba(255, 255, 255, .92)

값이 다르거나 표기 형태가 다른 선언, var() fallback, 다른 역할의 단계 값은
바꾸지 않는다. 1차 계약(test_261118_white_veil_tokens_7187.py)과 분리해
이번 차수의 8개 선언만 검증한다.
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

#: 각 토큰의 :root 값 — 치환 전 리터럴과 문자 그대로 같다.
ROOT_TOKENS = {
    "--text-veil-faint": "rgba(255, 255, 255, .42)",
    "--text-veil-strong": "rgba(255, 255, 255, .92)",
    "--text-veil-mist": "rgba(255, 255, 255, .34)",
}

#: 2차에서 토큰으로 바꾼 선언: (속성, 치환 전 값, 치환 후 값). 공백 정규화 비교.
CHANGED = {
    "capability-nav.css": [
        ("color", "rgba(255, 255, 255, .92)", "var(--text-veil-strong)"),
    ],
    "padiem-cinematic-workspace.css": [
        ("color", "rgba(255, 255, 255, .42)", "var(--text-veil-faint)"),
        ("color", "rgba(255, 255, 255, .42)", "var(--text-veil-faint)"),
        ("color", "rgba(255, 255, 255, .34)", "var(--text-veil-mist)"),
        ("color", "rgba(255, 255, 255, .34)", "var(--text-veil-mist)"),
        ("color", "rgba(255, 255, 255, .92) !important", "var(--text-veil-strong) !important"),
    ],
    "padiem-foundation.css": [
        ("color", "rgba(255, 255, 255, .92)", "var(--text-veil-strong)"),
        ("color", "rgba(255, 255, 255, .42)", "var(--text-veil-faint)"),
        ("color", "rgba(255, 255, 255, .42)", "var(--text-veil-faint)"),
    ],
    "padiem-glass.css": [
        ("color", "rgba(255, 255, 255, .92)", "var(--text-veil-strong)"),
        ("color", "rgba(255, 255, 255, .92)", "var(--text-veil-strong)"),
    ],
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_root_tokens_hold_the_swept_values() -> None:
    rules = parse_rules(tokens_css())
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_text_veil_tokens() -> None:
    for rule in parse_rules(tokens_css()):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_changed_declarations_consume_the_text_tokens() -> None:
    for sheet, items in CHANGED.items():
        rules = parse_rules(read_static(sheet))
        actual: Counter = Counter()
        for rule in rules:
            for prop, value in rule.declarations.items():
                if "--text-veil-" in value:
                    actual[(prop, _norm(value))] += 1
        expected: Counter = Counter((prop, new) for prop, _old, new in items)
        assert actual == expected, f"{sheet}: {actual - expected} / missing {expected - actual}"
        for prop, old, new in set(items):
            swapped = new
            for name, literal in ROOT_TOKENS.items():
                swapped = swapped.replace(f"var({name})", literal)
            assert swapped == old, (sheet, prop, new)


def test_text_tokens_are_only_color_declarations() -> None:
    for sheet in CHANGED:
        for rule in parse_rules(read_static(sheet)):
            for prop, value in rule.declarations.items():
                if "--text-veil-" in value:
                    assert prop == "color", (sheet, prop, value)


def test_this_round_replaced_exactly_eight_declarations() -> None:
    """2차 8선언은 그대로이고, 7차가 글자 토큰 2선언을 더했다."""
    assert sum(len(items) for items in CHANGED.values()) == 11
