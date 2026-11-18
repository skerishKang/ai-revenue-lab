"""#7187 1차 — 반투명 백색 역할+강도 토큰(--surface-veil·--line-veil).

대표 결정(261117 23:44): 반투명 백색은 숫자만 줄이지 말고 쓰임새별 의미 토큰으로.
이름(CTO 확정): 역할 --surface-veil·--line-veil, 강도 단계 -faint/-soft/-strong.
각 단계 값은 전수표(599건/46파일)에서 그 역할이 가장 많이 쓰던 값 그대로다 —
반올림하거나 합치지 않는다:

* 표면(카드/표면 배경): .72 10회, .06 9회, .05 8회
  → --surface-veil-strong=.72, -soft=.06, -faint=.05
* 구분선(구분선/테두리): .22 11회, .52 10회, .54 9회
  → --line-veil-faint=.22, -soft=.52, -strong=.54

1차 범위: 현재 값이 단계 값과 문자 그대로 같은 사용처만 var()로 바꿨다.
같은 알파라도 표기 형태가 다른 곳(예: rgba(255,255,255,.72)), 그 역할의 단계에
없는 값(구분선 .72 등 — 역할 토큰으로 치환하면 이름이 쓰임새와 어긋난다),
var() fallback 안의 리터럴, 불투명 #ffffff, 그리고 padiem-tokens.css 를 로드하지
않는 페이지가 쓰는 시트(admin-models.css — admin/b14·b66·chat·claw 페이지,
help.css — help-tutorials 7페이지)는 원시 리터럴로 남는다 → 다음 라운드 목록.

판정은 "브라우저가 하는 일"(README_테스트작성규칙)이다. 선언 단위로 토큰 소비와
"토큰을 원래 리터럴로 되돌리면 치환 전 값과 같다"를 보고, 바이트 비교를 하지
않는다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

#: 각 토큰의 :root 값 — 전수표 최다 값 그대로. 이 문자열이 계약이다.
ROOT_TOKENS = {
    "--surface-veil-faint": "rgba(255, 255, 255, .05)",
    "--surface-veil-soft": "rgba(255, 255, 255, .06)",
    "--surface-veil-strong": "rgba(255, 255, 255, .72)",
    "--line-veil-faint": "rgba(255, 255, 255, .22)",
    "--line-veil-soft": "rgba(255, 255, 255, .52)",
    "--line-veil-strong": "rgba(255, 255, 255, .54)",
    "--surface-veil-ghost": "rgba(255, 255, 255, .035)",
    "--inset-veil-ghost": "rgba(255, 255, 255, .035)",
    "--surface-veil-panel": "rgba(255, 255, 255, .04)",
    "--inset-veil-panel": "rgba(255, 255, 255, .04)",
    "--line-veil-dim": "rgba(255, 255, 255, .09)",
    "--surface-veil-dim": "rgba(255, 255, 255, .09)",
    "--inset-veil-dim": "rgba(255, 255, 255, .09)",
    "--surface-veil-mist": "rgba(255, 255, 255, .34)",
    "--text-veil-mist": "rgba(255, 255, 255, .34)",
    "--line-veil-mist": "rgba(255, 255, 255, .34)",
    "--inset-veil-mist": "rgba(255, 255, 255, .34)",
}

#: 1차에서 토큰으로 바꾼 선언: (속성, 치환 전 값, 치환 후 값). 공백 정규화 비교.
CHANGED = {
    "admin-models.css": [
        ("box-shadow", "inset -1px 0 rgba(255, 255, 255, .09)", "inset -1px 0 var(--inset-veil-dim)"),
    ],
    "claw-focus-layout.css": [
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border", "1px solid rgba(255, 255, 255, .54)", "1px solid var(--line-veil-strong)"),
        ("border", "1px solid rgba(255, 255, 255, .54)", "1px solid var(--line-veil-strong)"),
        ("border", "1px solid rgba(255, 255, 255, .54)", "1px solid var(--line-veil-strong)"),
        ("border", "1px solid rgba(255, 255, 255, .54)", "1px solid var(--line-veil-strong)"),
        ("border", "1px solid rgba(255, 255, 255, .54)", "1px solid var(--line-veil-strong)"),
        ("border-bottom", "1px solid rgba(255, 255, 255, .22)", "1px solid var(--line-veil-faint)"),
        ("border-color", "rgba(255, 255, 255, .54)", "var(--line-veil-strong)"),
        ("border-color", "rgba(255, 255, 255, .54)", "var(--line-veil-strong)"),
        ("border-color", "rgba(255, 255, 255, .54)", "var(--line-veil-strong)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
    ],
    "mode-presentation.css": [
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .72)", "var(--surface-veil-strong)"),
        ("background", "rgba(255, 255, 255, .72)", "var(--surface-veil-strong)"),
        ("background", "rgba(255, 255, 255, .04)", "var(--surface-veil-panel)"),
    ],
    "padiem-cinematic-workspace.css": [
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .06), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97) !important",
         "linear-gradient(145deg, var(--surface-veil-soft), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97) !important"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("box-shadow",
         "inset 0 1px 0 rgba(255, 255, 255, .04) !important, 0 14px 38px rgba(0, 0, 0, .12)",
         "inset 0 1px 0 var(--inset-veil-panel) !important, 0 14px 38px rgba(0, 0, 0, .12)"),
        ("background", "rgba(255, 255, 255, .04)", "var(--surface-veil-panel)"),
        ("border-color", "rgba(255, 255, 255, .09) !important", "var(--line-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .09) !important", "var(--line-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("background", "rgba(255, 255, 255, .09) !important", "var(--surface-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .34) !important", "var(--line-veil-mist) !important"),
    ],
    "padiem-dark-contrast.css": [
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
    ],
    "padiem-editorial.css": [
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
    ],
    "padiem-first-use.css": [
        ("border-color", "rgba(255, 255, 255, .22)", "var(--line-veil-faint)"),
    ],
    "padiem-foundation.css": [
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
    ],
    "padiem-glass-brand-polish.css": [
        ("border-color", "rgba(255, 255, 255, .22) !important", "var(--line-veil-faint) !important"),
        ("box-shadow",
         "0 20px 54px rgba(28, 36, 44, .16), inset 0 1px 0 rgba(255, 255, 255, .80), 0 0 0 1px rgba(255, 255, 255, .34) !important",
         "0 20px 54px rgba(28, 36, 44, .16), inset 0 1px 0 rgba(255, 255, 255, .80), 0 0 0 1px var(--inset-veil-mist) !important"),
    ],
    "padiem-glass-reading.css": [
        ("background",
         "linear-gradient(90deg, rgba(17, 24, 31, .06), transparent 28%, transparent 76%, rgba(17, 24, 31, .04)), linear-gradient(180deg, rgba(255, 255, 255, .05), transparent 44%, rgba(17, 24, 31, .05))",
         "linear-gradient(90deg, rgba(17, 24, 31, .06), transparent 28%, transparent 76%, rgba(17, 24, 31, .04)), linear-gradient(180deg, var(--surface-veil-faint), transparent 44%, rgba(17, 24, 31, .05))"),
    ],
    "padiem-glass.css": [
        ("background",
         "linear-gradient(90deg, rgba(121, 188, 231, .82), rgba(255, 255, 255, .72), rgba(199, 167, 107, .66))",
         "linear-gradient(90deg, rgba(121, 188, 231, .82), var(--surface-veil-strong), rgba(199, 167, 107, .66))"),
        ("background-image",
         "linear-gradient(180deg, rgba(26, 34, 42, .20), rgba(255, 255, 255, .05) 38%, rgba(29, 38, 47, .20)), radial-gradient(circle at 18% 22%, rgba(255, 255, 255, .38), transparent 34%), radial-gradient(circle at 76% 62%, rgba(105, 156, 189, .24), transparent 38%), linear-gradient(135deg, #88939d 0%, #b8c1c8 36%, #d5d9dc 58%, #909aa4 100%), var(--padiem-glass-background-image)",
         "linear-gradient(180deg, rgba(26, 34, 42, .20), var(--surface-veil-faint) 38%, rgba(29, 38, 47, .20)), radial-gradient(circle at 18% 22%, rgba(255, 255, 255, .38), transparent 34%), radial-gradient(circle at 76% 62%, rgba(105, 156, 189, .24), transparent 38%), linear-gradient(135deg, #88939d 0%, #b8c1c8 36%, #d5d9dc 58%, #909aa4 100%), var(--padiem-glass-background-image)"),
        ("background-image",
         "linear-gradient(rgba(255, 255, 255, .08) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, .05) 1px, transparent 1px)",
         "linear-gradient(rgba(255, 255, 255, .08) 1px, transparent 1px), linear-gradient(90deg, var(--surface-veil-faint) 1px, transparent 1px)"),
        ("border", "1px solid rgba(255, 255, 255, .52)", "1px solid var(--line-veil-soft)"),
        ("border-bottom", "1px solid rgba(255, 255, 255, .22)", "1px solid var(--line-veil-faint)"),
        ("border-color", "rgba(255, 255, 255, .52)", "var(--line-veil-soft)"),
        ("border-color", "rgba(255, 255, 255, .52) !important", "var(--line-veil-soft) !important"),
    ],
    "padiem-rich.css": [
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
        ("background", "rgba(255, 255, 255, .06) !important", "var(--surface-veil-soft) !important"),
        ("border-color", "rgba(255, 255, 255, .22)", "var(--line-veil-faint)"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
        ("box-shadow", "inset 0 1px 0 rgba(255, 255, 255, .035)", "inset 0 1px 0 var(--inset-veil-ghost)"),
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .08), rgba(255, 255, 255, .04)), rgba(8, 9, 11, .90)",
         "linear-gradient(145deg, rgba(255, 255, 255, .08), var(--surface-veil-panel)), rgba(8, 9, 11, .90)"),
        ("border-bottom-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("background", "rgba(255, 255, 255, .09)", "var(--surface-veil-dim)"),
    ],
    "padiem-settings.css": [
        ("border-color", "rgba(255, 255, 255, .54)", "var(--line-veil-strong)"),
        ("background", "rgba(255, 255, 255, .34)", "var(--surface-veil-mist)"),
        ("border-color", "rgba(255, 255, 255, .34)", "var(--line-veil-mist)"),
    ],
    "shared-tooltip.css": [
        ("border", "1px solid rgba(255, 255, 255, .34)", "1px solid var(--line-veil-mist)"),
    ],
    "padiem-surfaces.css": [
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .06), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97) !important",
         "linear-gradient(145deg, var(--surface-veil-soft), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97) !important"),
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .72)", "var(--surface-veil-strong)"),
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .105), rgba(255, 255, 255, .04)), rgba(13, 14, 16, .68)",
         "linear-gradient(145deg, rgba(255, 255, 255, .105), var(--surface-veil-panel)), rgba(13, 14, 16, .68)"),
        ("box-shadow", "inset 0 1px 0 rgba(255, 255, 255, .04)", "inset 0 1px 0 var(--inset-veil-panel)"),
        ("box-shadow", "inset 0 1px 0 rgba(255, 255, 255, .04)", "inset 0 1px 0 var(--inset-veil-panel)"),
        ("box-shadow", "inset 0 1px 0 rgba(255, 255, 255, .04) !important", "inset 0 1px 0 var(--inset-veil-panel) !important"),
        ("background", "rgba(255, 255, 255, .09) !important", "var(--surface-veil-dim) !important"),
    ],
    "padiem-themes.css": [
        ("background",
         "linear-gradient(145deg, rgba(210,235,255,.14), rgba(255, 255, 255, .04)), rgba(8,12,20,.78)",
         "linear-gradient(145deg, rgba(210,235,255,.14), var(--surface-veil-panel)), rgba(8,12,20,.78)"),
        ("background",
         "linear-gradient(145deg, rgba(200,230,255,.10), rgba(255, 255, 255, .04)), rgba(8,12,20,.7)",
         "linear-gradient(145deg, rgba(200,230,255,.10), var(--surface-veil-panel)), rgba(8,12,20,.7)"),
        ("background",
         "linear-gradient(145deg, rgba(255,240,214,.10), rgba(255, 255, 255, .04)), rgba(11,14,22,.7)",
         "linear-gradient(145deg, rgba(255,240,214,.10), var(--surface-veil-panel)), rgba(11,14,22,.7)"),
    ],
    "util-menu.css": [
        ("background", "rgba(255, 255, 255, .72)", "var(--surface-veil-strong)"),
    ],
}

#: 토큰을 로드하지 않는 페이지가 쓰는 시트(리터럴 유지).
EXCLUDED_SHEETS = ("help.css",)
#: admin-models.css는 이제 모든 소비 페이지가 토큰을 로드하므로 5차 토큰만 쓴다.
ADMIN_MODELS_VEIL_TOKENS = ("--inset-veil-dim",)

#: 동적으로 주입되는 시트와 그 로더 스크립트.
DYNAMIC_SHEETS = {
    "padiem-glass-reading.css": "theme.js",
    "mode-presentation.css": "product-capabilities.js",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_root_tokens_hold_the_swept_values() -> None:
    """토큰의 :root 값은 바꾸기 전 리터럴과 문자 그대로 같다."""
    rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in ROOT_TOKENS.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_veil_tokens() -> None:
    """베일은 테마 값이 아니라 역할 스케일이라 테마 블록에서 덮지 않는다."""
    for rule in parse_rules(TOKENS.read_text(encoding="utf-8")):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_changed_declarations_consume_the_tokens() -> None:
    """바뀐 줄들은 토큰을 쓰고, 토큰을 원래 리터럴로 되돌리면 치환 전 값과 같다."""
    for sheet, items in CHANGED.items():
        rules = parse_rules((STATIC / sheet).read_text(encoding="utf-8"))
        actual: Counter = Counter()
        for rule in rules:
            for prop, value in rule.declarations.items():
                # 2차의 글자색 토큰은 별도 계약
                # (test_261118_white_veil_text_tokens_7187.py)이 검증한다.
                if "veil-" in value and "--text-veil-" not in value:
                    actual[(prop, _norm(value))] += 1
        expected: Counter = Counter((prop, new) for prop, _old, new in items)
        assert actual == expected, f"{sheet}: {actual - expected} / missing {expected - actual}"
        for prop, old, new in set(items):
            swapped = new
            for name, literal in ROOT_TOKENS.items():
                swapped = swapped.replace(f"var({name})", literal)
            assert swapped == old, (sheet, prop, new)


def test_veil_tokens_keep_their_role_discipline() -> None:
    """구분선 토큰은 border 계열이, 표면 토큰은 background 계열이 쓴다."""
    for sheet in CHANGED:
        for rule in parse_rules((STATIC / sheet).read_text(encoding="utf-8")):
            for prop, value in rule.declarations.items():
                if "--line-veil-" in value:
                    assert prop.startswith("border"), (sheet, prop, value)
                if "--surface-veil-" in value:
                    assert prop.startswith("background"), (sheet, prop, value)


def test_excluded_sheets_stay_literal() -> None:
    """토큰을 로드하지 않는 페이지가 쓰는 시트는 리터럴을 유지한다."""
    for sheet in EXCLUDED_SHEETS:
        css = (STATIC / sheet).read_text(encoding="utf-8")
        assert "--veil-" not in css, sheet
    admin = (STATIC / "admin-models.css").read_text(encoding="utf-8")
    for token in ADMIN_MODELS_VEIL_TOKENS:
        assert f"var({token})" in admin, token
    for token in ROOT_TOKENS:
        if token not in ADMIN_MODELS_VEIL_TOKENS:
            assert f"var({token})" not in admin, token


def _page_sheets(page: Path) -> set[str]:
    """한 페이지가 로드하는 시트: <link> + @import 체인 + 동적 로더."""
    html = page.read_text(encoding="utf-8")
    stack: list[Path] = []
    for href in re.findall(r"<link[^>]*?href=[\"']([^\"']+\.css)[^\"']*[\"']", html):
        cand = page.parent / href.split("?")[0]
        if cand.is_file():
            stack.append(cand)
    sheets: set[str] = set()
    for script in re.findall(r"<script[^>]*src=[\"']\./([^\"']+\.js)[\"']", html):
        for sheet, loader in DYNAMIC_SHEETS.items():
            if script == loader:
                sheets.add(sheet)
    seen: set[Path] = set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        sheets.add(p.name)
        css_text = p.read_text(encoding="utf-8")
        for href in re.findall(r"@import\s+(?:url\()?['\"]([^'\")]+\.css)['\"]\)?", css_text):
            cand = p.parent / href.split("?")[0]
            if cand.is_file():
                stack.append(cand)
    return sheets


def test_changed_sheets_are_only_consumed_by_pages_that_load_tokens() -> None:
    """바뀐 시트를 소비하는 모든 페이지는 padiem-tokens.css 를 로드한다."""
    consumers: dict[str, set[str]] = {}
    for page in STATIC.rglob("*.html"):
        for sheet in _page_sheets(page):
            consumers.setdefault(sheet, set()).add(page.relative_to(STATIC).as_posix())
    for sheet in CHANGED:
        pages = consumers.get(sheet, set())
        assert pages, f"{sheet}: 소비하는 페이지를 찾지 못했다"
        for page in pages:
            html = (STATIC / page).read_text(encoding="utf-8")
            assert "padiem-tokens.css" in html, f"{page} → {sheet}"


def test_this_round_replaced_exactly_44_declarations() -> None:
    """1차 44선언은 그대로이고, 3차 10·4차 11·5차 10·7차 11선언을 더했다."""
    assert sum(len(items) for items in CHANGED.values()) == 86
    ghost = sum(
        1
        for items in CHANGED.values()
        for _prop, _old, new in items
        if "veil-ghost" in new
    )
    assert ghost == 10
    panel = sum(
        1
        for items in CHANGED.values()
        for _prop, _old, new in items
        if "veil-panel" in new
    )
    assert panel == 11
    dim = sum(
        1
        for items in CHANGED.values()
        for _prop, _old, new in items
        if "veil-dim" in new
    )
    assert dim == 10
    mist = sum(
        1
        for items in CHANGED.values()
        for _prop, _old, new in items
        if "veil-mist" in new
    )
    assert mist == 11
