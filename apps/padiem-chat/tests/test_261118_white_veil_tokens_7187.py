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

# #8060: shipped reads live in _support; assertions stay here.
from _support.token_veil_source import admin_models_css, index_html, read, read_static, tokens_css

import re
from collections import Counter
from pathlib import Path

from css_rules import parse_rules, declaration, rule_selector_list_contains

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = STATIC / "padiem-tokens.css"

#: 각 토큰의 :root 값 — 전수표 최다 값 그대로. 이 문자열이 계약이다.
PANEL_TOKENS = {
    "--surface-panel-deep": "rgba(8, 9, 11, .82)",
    "--surface-panel-solid": "rgba(8, 9, 11, .97)",
    "--surface-panel-dim": "rgba(8, 9, 11, .96)",
    "--surface-card-deep": "rgba(10, 11, 13, .48)",
    "--surface-card-solid": "rgba(13, 14, 16, .68)",
    "--surface-panel-veil": "rgba(9, 10, 12, .86)",
    "--surface-ink-deep": "rgba(1, 2, 4, .76)",
    "--surface-fade-deep": "rgba(6, 7, 9, .82)",
    "--surface-fade-solid": "#06080d",
}

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
    "--surface-veil-haze": "rgba(255, 255, 255, .78)",
    "--line-veil-haze": "rgba(255, 255, 255, .78)",
    "--text-veil-haze": "rgba(255, 255, 255, .78)",
    "--ws-form-wash": "rgba(255, 255, 255, .018)",
    "--ws-banner-shadow": "rgba(0, 0, 0, .12)",
}

#: #7811 C2 surfaces 1차가 이 시트에서 가져간 쓰임새 토큰 (되돌리기 검증용).
SURFACES_TOKENS = {
    "--surfaces-starter-hover-wash": "rgba(255, 255, 255, .105)",
    # 2차: 베일 그라디언트의 .018 꼬리도 전용 쓰임새 토큰이 소유한다.
    "--ws-form-wash": "rgba(255, 255, 255, .018)",
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
         "linear-gradient(145deg, rgba(255, 255, 255, .06), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97)",
         "linear-gradient(145deg, var(--surface-veil-soft), var(--ws-form-wash)), var(--surface-panel-solid)"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035) !important", "var(--surface-veil-ghost) !important"),
        ("background", "rgba(255, 255, 255, .035)", "var(--surface-veil-ghost)"),
        ("box-shadow",
         "inset 0 1px 0 rgba(255, 255, 255, .04), 0 14px 38px rgba(0, 0, 0, .12)",
         "inset 0 1px 0 var(--inset-veil-panel), 0 14px 38px var(--ws-banner-shadow)"),
        ("background", "rgba(255, 255, 255, .04)", "var(--surface-veil-panel)"),
        ("border-color", "rgba(255, 255, 255, .09) !important", "var(--line-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .09) !important", "var(--line-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("border-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("background", "rgba(255, 255, 255, .09) !important", "var(--surface-veil-dim) !important"),
        ("border-color", "rgba(255, 255, 255, .34)", "var(--line-veil-mist)"),
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
        # #8008 15차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
        ("border-color", "rgba(255, 255, 255, .22)", "var(--line-veil-faint)"),
        ("box-shadow",
         "0 20px 54px rgba(28, 36, 44, .16), inset 0 1px 0 rgba(255, 255, 255, .80), 0 0 0 1px rgba(255, 255, 255, .34)",
         "0 20px 54px rgba(28, 36, 44, .16), inset 0 1px 0 rgba(255, 255, 255, .80), 0 0 0 1px var(--inset-veil-mist)"),
    ],
    "padiem-glass-reading.css": [
        ("background",
         "linear-gradient(90deg, rgba(17, 24, 31, .06), transparent 28%, transparent 76%, rgba(17, 24, 31, .04)), linear-gradient(180deg, rgba(255, 255, 255, .05), transparent 44%, rgba(17, 24, 31, .05))",
         "linear-gradient(90deg, rgba(17, 24, 31, .06), transparent 28%, transparent 76%, rgba(17, 24, 31, .04)), linear-gradient(180deg, var(--surface-veil-faint), transparent 44%, rgba(17, 24, 31, .05))"),
        # #8008 10차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
        ("border-color", "rgba(255, 255, 255, .78)", "var(--line-veil-haze)"),
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
        # #8008 9차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
        ("border-color", "rgba(255, 255, 255, .52)", "var(--line-veil-soft)"),
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
         "linear-gradient(145deg, var(--rich-composer-bg-wash), rgba(255, 255, 255, .04)), var(--rich-composer-bg-end)",
         "linear-gradient(145deg, var(--rich-composer-bg-wash), var(--surface-veil-panel)), var(--rich-composer-bg-end)"),
        ("border-bottom-color", "rgba(255, 255, 255, .09)", "var(--line-veil-dim)"),
        ("background", "rgba(255, 255, 255, .09)", "var(--surface-veil-dim)"),
    ],
    "padiem-settings.css": [
        ("border-color", "rgba(255, 255, 255, .54)", "var(--line-veil-strong)"),
        # background mist 1선언(glass 닫기 단추)은 #8001(대표 11-18 08:38)로
        # 칸 바탕 var(--card-bg) 한 판 토큰이 되며 선언 자체가 사라졌다.
        ("border-color", "rgba(255, 255, 255, .34)", "var(--line-veil-mist)"),
        ("border-color", "rgba(255, 255, 255, .78)", "var(--line-veil-haze)"),
    ],
    "shared-tooltip.css": [
        ("border", "1px solid rgba(255, 255, 255, .34)", "1px solid var(--line-veil-mist)"),
    ],
    "padiem-surfaces.css": [
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .06), rgba(255, 255, 255, .018)), rgba(8, 9, 11, .97) !important",
         # #7811 C2 surfaces 2차: .018 꼬리는 전용 쓰임새 토큰으로 옮겼다.
         "linear-gradient(145deg, var(--surface-veil-soft), var(--ws-form-wash)), var(--surface-panel-solid) !important"),
        ("background", "rgba(255, 255, 255, .05)", "var(--surface-veil-faint)"),
        ("background", "rgba(255, 255, 255, .06)", "var(--surface-veil-soft)"),
        ("background", "rgba(255, 255, 255, .72)", "var(--surface-veil-strong)"),
        ("background",
         "linear-gradient(145deg, rgba(255, 255, 255, .105), rgba(255, 255, 255, .04)), rgba(13, 14, 16, .68)",
         # #7811 C2 surfaces 1차: .105는 전용 쓰임새 토큰으로 옮겼다.
         "linear-gradient(145deg, var(--surfaces-starter-hover-wash), var(--surface-veil-panel)), var(--surface-card-solid)"),
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
        # #7811 C3: cinematic 시작 카드 호버 배경(.04 꼬리) 한 줄은 이 시트를 떠났다.
        # 어느 상태에서도 칠하지 못하던 줄이라 계약에서 뺐다.
        ("background", "rgba(255, 255, 255, .78)", "var(--surface-veil-haze)"),
        ("background",
         "linear-gradient(180deg, rgba(255, 255, 255, .78), rgba(250,252,255,.58))",
         "linear-gradient(180deg, var(--surface-veil-haze), rgba(250,252,255,.58))"),
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
    rules = parse_rules(tokens_css())
    root = next(r for r in rules if r.media is None and ":root" in r.selectors)
    for name, literal in {**ROOT_TOKENS, **PANEL_TOKENS, **SURFACES_TOKENS}.items():
        assert root.declarations.get(name) == literal, name


def test_no_theme_block_overrides_the_veil_tokens() -> None:
    """베일은 테마 값이 아니라 역할 스케일이라 테마 블록에서 덮지 않는다."""
    for rule in parse_rules(tokens_css()):
        themed = rule.media is not None or any("data-theme" in s for s in rule.selectors)
        if themed:
            for name in ROOT_TOKENS:
                assert name not in rule.declarations, (rule.selectors, name)


def test_changed_declarations_consume_the_tokens() -> None:
    """바뀐 줄들은 토큰을 쓰고, 토큰을 원래 리터럴로 되돌리면 치환 전 값과 같다."""
    for sheet, items in CHANGED.items():
        rules = parse_rules(read_static(sheet))
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
            for name, literal in {**ROOT_TOKENS, **PANEL_TOKENS, **SURFACES_TOKENS}.items():
                swapped = swapped.replace(f"var({name})", literal)
            assert swapped == old, (sheet, prop, new)


def test_veil_tokens_keep_their_role_discipline() -> None:
    """구분선 토큰은 border 계열이, 표면 토큰은 background 계열이 쓴다."""
    for sheet in CHANGED:
        for rule in parse_rules(read_static(sheet)):
            for prop, value in rule.declarations.items():
                if "--line-veil-" in value:
                    assert prop.startswith("border"), (sheet, prop, value)
                if "--surface-veil-" in value:
                    assert prop.startswith("background"), (sheet, prop, value)


def test_excluded_sheets_stay_literal() -> None:
    """토큰을 로드하지 않는 페이지가 쓰는 시트는 리터럴을 유지한다."""
    for sheet in EXCLUDED_SHEETS:
        css = read_static(sheet)
        assert "--veil-" not in css, sheet
    admin = admin_models_css()
    for token in ADMIN_MODELS_VEIL_TOKENS:
        assert f"var({token})" in admin, token
    for token in ROOT_TOKENS:
        if token not in ADMIN_MODELS_VEIL_TOKENS:
            assert f"var({token})" not in admin, token


def _page_sheets(page: Path) -> set[str]:
    """한 페이지가 로드하는 시트: <link> + @import 체인 + 동적 로더."""
    html = read(page)
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
        css_text = read(p)
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
            html = read_static(page)
            assert "padiem-tokens.css" in html, f"{page} → {sheet}"


def test_this_round_replaced_exactly_44_declarations() -> None:
    """1차 44선언은 그대로이고, 3차 10·4차 11·5차 10·7차 11·8차 표면·테두리 4선언을 더했다.
    (7차 1선언은 #8001에서 --card-bg 한 판 토큰으로 바뀌며 계약에서 빠졌다.
    4차 1선언은 #7811 C3에서 칠하지 못하던 줄로 지워지며 계약에서 빠졌다.)"""
    assert sum(len(items) for items in CHANGED.values()) == 88
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
    assert panel == 10
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
    assert mist == 10


UTIL_MENU_CSS = (STATIC / "util-menu.css").read_bytes().decode("utf-8", errors="replace")
UTIL_APP_CSS = (STATIC / "util-app.css").read_bytes().decode("utf-8", errors="replace")
GLASS_PORTRAIT_CSS = (STATIC / "padiem-glass-portrait.css").read_bytes().decode("utf-8", errors="replace")
CARD_BG_PREFIX = "var(--card-bg"
GLASS_CARD_PREFIX = "var(--glass-card-surface"
BG_PROP = "background"
GLASS_SCOPE = 'data-theme="padiem-glass"'
GLASS_SCOPE_MSG = "--glass-card-surface left the glass scope"


def _one_rule(rules: list, selector: str, label: str):
    matched = [r for r in rules if r.media is None and rule_selector_list_contains(r, selector)]
    assert len(matched) == 1, f"{label}: expected one rule, got {len(matched)}"
    return matched[0]


def _decl(rule, prop: str) -> str:
    value = declaration(rule, prop)
    assert value is not None, prop
    return value


def test_pdfmd_inner_panels_follow_the_theme_tokens() -> None:
    shell = _one_rule(parse_rules(UTIL_MENU_CSS), ".pdfmd-shell", "PDF→MD shell")
    assert _decl(shell, BG_PROP).startswith(CARD_BG_PREFIX)
    cols = _one_rule(parse_rules(UTIL_APP_CSS), ".pdfmd-input-col", "PDF→MD inner panel")
    assert _decl(cols, BG_PROP).startswith(GLASS_CARD_PREFIX)
    for rule in parse_rules(GLASS_PORTRAIT_CSS):
        if declaration(rule, "--glass-card-surface") is not None:
            assert any(GLASS_SCOPE in s for s in rule.selectors), (
                GLASS_SCOPE_MSG
            )
