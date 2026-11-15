"""#7817 — 첫 화면(게스트)의 카드 글자와 제목 둘째 줄이 읽히는가.

읽히는지는 사람이 보지 않고 숫자로 확인한다: 테마 토큰과 그 테마가 실제로 칠하는
표면 사이의 WCAG 대비를 계산한다. 기준은 카드 제목 4.5, 카드 설명 3.0, 제목 둘째
줄 4.5다.

규칙도 함께 잠근다(#7809 기능·수리 PR 규칙): 테마별 차이는 토큰 값으로만 내고,
`!important`나 새 `[data-theme=…]` 덮어쓰기 규칙으로 내지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
THEMES = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
GLASS = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
SURFACES = (STATIC / "padiem-surfaces.css").read_text(encoding="utf-8")

THEME_NAMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
# Surfaces each theme paints the first screen on, measured from the running app
# (`?theme=<name>`) at 1440 and 390. The darker of the pair is used for title
# text and the lighter one for the second headline line, i.e. the worst case for
# each. They are the same surfaces the browser QA script samples.
PAGE_SURFACE = {
    "light": (253, 253, 254),
    "dark": (16, 21, 28),
    "cinematic": (5, 10, 17),
    "padiem-home": (233, 237, 242),
    "padiem-glass": (227, 231, 233),
}


def _block(name: str) -> str:
    return TOKENS.split(f'html[data-theme="{name}"] {{', 1)[1].split("}", 1)[0]


def _value(sheet: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*([^;]+);", sheet)
    assert match, name
    return match.group(1).strip()


def _rgb(value: str) -> tuple[tuple[int, int, int], float] | None:
    value = value.strip()
    if value.startswith("#") and len(value) == 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)), 1.0
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if match:
        parts = [p.strip() for p in match.group(1).replace(",", " ").replace("/", " ").split()]
        rgb = tuple(int(float(p)) for p in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
        return rgb, alpha
    return None


def _token(name: str, theme: str) -> tuple[tuple[int, int, int], float]:
    """Resolve a colour token, following one alias step (`var(--muted)`)."""
    for sheet in (_block(theme), TOKENS.split(":root {", 1)[1].split("}", 1)[0]):
        try:
            value = _value(sheet, name)
        except AssertionError:
            continue
        alias = re.fullmatch(r"var\((--[a-z0-9-]+)\)", value)
        if alias:
            return _token(alias.group(1), theme)
        rgb = _rgb(value)
        if rgb is not None:
            return rgb
    raise AssertionError(f"{name} not resolved for {theme}")


def _over(fg: tuple[tuple[int, int, int], float], bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Composite a translucent ink over the surface it is painted on."""
    (r, g, b), alpha = fg
    return (
        round(r * alpha + bg[0] * (1 - alpha)),
        round(g * alpha + bg[1] * (1 - alpha)),
        round(b * alpha + bg[2] * (1 - alpha)),
    )


def _contrast(fg: tuple[tuple[int, int, int], float], bg: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    def lum(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])

    ink = _over(fg, bg)
    hi, lo = max(lum(ink), lum(bg)), min(lum(ink), lum(bg))
    return (hi + 0.05) / (lo + 0.05)


def test_second_headline_line_reads_one_token_and_no_theme_overrides_it() -> None:
    assert ".empty-state h1 br + * {" in SURFACES
    rule = SURFACES.split(".empty-state h1 br + * {", 1)[1].split("}", 1)[0]
    assert "color: var(--hero-sub-color);" in rule
    # #7809: 테마별 차이는 토큰 값으로. 테마 시트가 이 줄의 색을 따로 덮지 않는다.
    for sheet, name in ((THEMES, "padiem-themes.css"), (GLASS, "padiem-glass.css")):
        assert not re.search(r'\[data-theme="[a-z-]+"\] \.empty-state h1 br \+ span', sheet), name


def test_every_theme_defines_the_second_headline_token() -> None:
    for theme in THEME_NAMES:
        assert "--hero-sub-color" in _block(theme), theme


def test_second_headline_line_meets_4_5_in_every_theme() -> None:
    failures = []
    for theme in THEME_NAMES:
        ratio = _contrast(_token("--hero-sub-color", theme), PAGE_SURFACE[theme])
        if ratio < 4.5:
            failures.append(f"{theme}: {ratio:.2f}")
    assert not failures, "제목 둘째 줄 대비 4.5 미만: " + ", ".join(failures)


def test_card_title_and_description_meet_their_minimums_in_every_theme() -> None:
    failures = []
    for theme in THEME_NAMES:
        title = _contrast(_token("--text", theme), PAGE_SURFACE[theme])
        description = _contrast(_token("--muted", theme), PAGE_SURFACE[theme])
        if title < 4.5:
            failures.append(f"{theme} 제목 {title:.2f}")
        if description < 3.0:
            failures.append(f"{theme} 설명 {description:.2f}")
    assert not failures, "카드 글자 대비 기준 미달: " + ", ".join(failures)


def test_guest_cards_keep_their_press_behaviour() -> None:
    """게스트라도 카드는 눌린다 — 흐리게 만들려고 잠그지 않는다."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    starters = re.findall(r'<button type="button" class="starter[^"]*"[^>]*>', html)
    assert len(starters) >= 4
    for tag in starters:
        assert "disabled" not in tag
    for sheet in (THEMES, GLASS, SURFACES):
        assert not re.search(r'\[data-account-state="?guest"?\][^{]*\.starter', sheet)
