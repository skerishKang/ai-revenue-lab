"""#7811 C3 후속(261127 결정) — 시네마틱 폰 폭 Claw 첫 카드도 다른 테마처럼 숨김.

#8767이 `.starter`의 `!important` 3개를 남긴 이유는 폰 폭 Claw 일반 화면에서
`connector-pages.css`의 카드 지움 규칙(배경 투명·테두리 0·그림자 없음)을
시네마틱만 이기고 있었기 때문이다. CTO 결정: 시네마틱도 다른 네 테마처럼 그
규칙이 이기게 한다 — `padiem-bright-readability.css` 시네마틱 `.starter`
규칙에서 `!important` 3개를 뗀다.

이 시험은 그 계약을 잠근다:

* bright-readability의 시네마틱 `.starter` 규칙은 `!important` 없이 같은 값을
  유지한다(넓은 폭에서는 그 규칙이 (0,2,1)로 claw-focus-layout.css의 지움
  규칙 (0,2,0)을 이기므로 넓은 폭 화면은 그대로다).
* connector-pages.css의 지움 규칙은 폰 폭(`@media (max-width: 720px)`) Claw
  일반 화면에서 세 선언을 그대로 갖고, 특이도가 시네마틱 규칙보다 높아서
  (`!important`가 없으니) 카드를 지운다.
* 어떤 시트도 시네마틱 `.starter`에 새 `!important`를 돌려놓지 않는다.
"""
from __future__ import annotations

import re

from _support import theme_sheets as sheets

BRIGHT = "padiem-bright-readability.css"
CONNECTOR = "connector-pages.css"
CIN_STARTER = 'html[data-theme="cinematic"] .starter'
STRIP_SELECTOR = (
    '.app-shell[data-state="claw"] .claw-workspace[data-view="general"]'
    " ~ .conversation .claw-home-card > .claw-workspace-starter"
)
NARROW_MEDIA = "@media (max-width: 720px)"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _specificity(selector: str) -> tuple[int, int, int]:
    """(id, 클래스·속성·의사클래스, 타입) 근사 특이도. :not()은 인자만 센다."""
    classes = len(re.findall(r"\.[A-Za-z_-][\w-]*|\[[^\]]+\]|:[A-Za-z-]+(?!\()", selector))
    inner = re.findall(r":not\(([^)]*)\)", selector)
    for part in inner:
        classes += len(re.findall(r"\.[A-Za-z_-][\w-]*|\[[^\]]+\]|:[A-Za-z-]+", part))
    types = len(re.findall(r"(?:^|[\s>~+])([a-z]+)(?![\w-])", selector))
    return (0, classes, types)


def _declared(sheet_name: str, selector: str) -> dict[str, str]:
    # 같은 선택자의 규칙이 여러 개면 뒤 규칙이 이긴다(같은 시트 안 로드 순서).
    found: dict[str, str] = {}
    hits = 0
    for rule in sheets.rules(sheet_name):
        if selector in [re.sub(r"\s+", " ", part).strip()
                        for part in rule.selector.split(",")]:
            hits += 1
            found.update({decl.prop: _norm(decl.value) for decl in rule.decls})
    assert hits, (sheet_name, selector)
    return found


def test_the_cinematic_starter_rule_keeps_its_values_without_flags():
    box = _declared(BRIGHT, CIN_STARTER)
    assert box["background"] == (
        "linear-gradient(145deg, rgba(224,242,255,.10), rgba(255,255,255,.024)),"
        " rgba(7,11,18,.62)")
    assert box["border-color"] == "rgba(136,201,255,.24)"
    assert box["box-shadow"] == (
        "0 0 26px rgba(96,178,242,.10), inset 0 1px 0 rgba(255,255,255,.08)")
    for prop, value in box.items():
        assert "!important" not in value, (prop, value)


def test_the_phone_claw_strip_rule_wins_over_the_cinematic_rule():
    strip = _declared(CONNECTOR, STRIP_SELECTOR)
    assert strip["background"] == "transparent"
    assert strip["border"] == "0"
    assert strip["box-shadow"] == "none"
    # 지움 규칙은 폰 폭 조건 안에 있다(넓은 폭에서는 적용되지 않는다).
    raw = sheets.sheet(CONNECTOR)
    block = None
    start = 0
    while True:
        start = raw.find(NARROW_MEDIA, start)
        if start < 0:
            break
        depth = 0
        for i in range(raw.index("{", start), len(raw)):
            depth += (1 if raw[i] == "{" else 0) - (1 if raw[i] == "}" else 0)
            if depth == 0:
                candidate = raw[start:i + 1]
                if STRIP_SELECTOR in candidate:
                    block = candidate
                break
        start += len(NARROW_MEDIA)
    assert block is not None, "지움 규칙이 폰 폭 조건 안에 없다"
    # 특이도: 지움 규칙이 시네마틱 규칙보다 높다 — !important가 없으니 이긴다.
    assert _specificity(STRIP_SELECTOR) > _specificity(CIN_STARTER)


def test_the_wide_width_paint_survives_above_the_claw_focus_strip():
    # 넓은 폭에서는 connector-pages의 지움 규칙이 적용되지 않고, bright의
    # 시네마틱 규칙 (0,2,1)이 claw-focus-layout의 지움 규칙 (0,2,0)을 이기므로
    # 넓은 폭 화면은 그대로다. 이 우위가 깨지면 1440 화면이 바뀐다.
    focus_strip = ".claw-home-card > .claw-workspace-starter"
    assert _specificity(CIN_STARTER) > _specificity(focus_strip)
    focus = _declared("claw-focus-layout.css", focus_strip)
    assert focus["background"] == "transparent"
    assert focus["box-shadow"] == "none"


def test_no_sheet_re_flags_the_cinematic_starter():
    for sheet_name in sheets.shipped_sheet_names():
        for rule in sheets.rules(sheet_name):
            if CIN_STARTER not in [re.sub(r"\s+", " ", part).strip()
                                   for part in rule.selector.split(",")]:
                continue
            for decl in rule.decls:
                assert "!important" not in decl.value, (sheet_name, decl.prop)
