"""#6065: the cinematic design must be the 정본's, on the production surface.

The order that lifted this work said it plainly: changing a card colour and some padding is
not completion. So this module checks three things that a "close enough" restyle would pass
and a real port would not:

  * the token layer is the design file's own text, byte for byte, not a re-reading of it;
  * the two axes stay orthogonal the way the design defines them - the country supplies
    material, the style decides where it is used, and neither invents the other's values;
  * the surfaces the design has (hero, work tiles with their own photographs, the strip, the
    popover) exist in the shipped markup, and the surfaces it only pretends at (nav items
    with no screen behind them, a search box, a fake account chip) were deliberately left
    behind rather than ported as dead controls.

The behaviour - twenty combinations reachable, the pills mirroring the country authority,
the 작업실 opening and closing - is executed through the shipped module on the harness
document, not asserted from strings.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from _council_module import run

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
DESIGN = APP_ROOT.parent.parent / "reference" / "padiem-parliament-ai-design-v1"
TOKEN_START, TOKEN_END = 14, 562          # the design file's own token layer, inclusive

CSS = (STATIC / "council-app.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")

COUNTRIES = ("kr", "us", "uk", "fr")
STYLES = ("classic", "modern", "dark", "light", "minimal")
ROLES = ("--bg", "--page-bg", "--panel", "--text", "--muted", "--line", "--paper", "--ink",
         "--glass", "--shadow", "--focus-ring", "--hero-text", "--hero-scrim", "--works-bg",
         "--strip-bg")


@lru_cache(maxsize=None)
def rule(selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"missing rule for {selector}"
    return match.group(1)


def layer_rule(selector: str) -> str:
    """The same rule, read from the cinematic layer.

    Several production selectors are restated by the port - `.council-card` keeps its S2
    frame above and gains the design's face below - and the browser applies the later one,
    so a fidelity check has to read the same one the user sees.
    """
    tail = CSS.split("/* ══ end of the ported token layer", 1)[-1]
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", tail)
    assert match, f"the cinematic layer has no rule for {selector}"
    return match.group(1)


def country_block(country: str) -> str:
    match = re.search(r'(?m)^html\[data-country="' + country + r'"\]\s*\{(.*?)\n\}', CSS, re.S)
    assert match, f"no ramp block for {country}"
    return match.group(1)


def ported_layer() -> str:
    start = CSS.index("/* ══ cinematic token layer")
    end = CSS.index("/* ══ end of the ported token layer")
    return CSS[start:end]


# ── the port is the design's own text ────────────────────────────────────────

def declarations(block: str) -> set[tuple[str, str]]:
    """Every `--name: value;` pair in a CSS text, comments removed.

    Containment would let a re-invented value slip through beside the ported one: the
    mutation that adds `--tone-1: #000102` to the kr ramp keeps every design line present
    and passes a "is it in there" check. So this compares the whole set.
    """
    stripped = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    return {(name, value.strip()) for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", stripped)}


def test_the_token_layer_is_the_design_files_own_declarations() -> None:
    """The cheapest way to fail this order quietly is to write something that looks like the
    시안. So the ramp/photography/role declarations are compared against the reference file
    itself: same declarations, same values, nothing added and nothing replaced."""
    reference = DESIGN.joinpath("parliament-theme.css").read_text(encoding="utf-8").splitlines()
    wanted = declarations("\n".join(reference[TOKEN_START - 1:TOKEN_END]))
    shipped = declarations(ported_layer())
    assert wanted, "the reference file no longer carries the token layer this port names"
    assert shipped - wanted == set(), f"invented values: {sorted(shipped - wanted)[:6]}"
    assert wanted - shipped == set(), f"design values went missing: {sorted(wanted - shipped)[:6]}"
    assert len(wanted) >= 150, len(wanted)
    assert 'html[data-country="kr"]' in ported_layer() and 'html[data-style="dark"]' in ported_layer()


def test_the_axes_stay_orthogonal() -> None:
    """The design's whole claim is 4 + 5 blocks instead of 20. A country that starts
    assigning roles, or a style that starts inventing material, breaks that immediately."""
    for country in COUNTRIES:
        block = country_block(country)
        for role in ROLES:
            assert not re.search(r"(?m)^\s*" + re.escape(role) + r"\s*:", block), \
                f"{country} assigns {role}: the axes stopped being independent"
    style_blocks = re.findall(r'(?m)^html\[data-style="[^"]+"\][^{]*\{(.*?)\n\}', CSS, re.S)
    assert len(style_blocks) >= 5, len(style_blocks)
    for block in style_blocks:
        # a style may spend the country's material (--bg: var(--tone-8)); it may not mint any
        assert not re.search(r"(?m)^\s*--(?:tone|sky|sun|haze|vignette|work|gold|accent)[0-9-]*\s*:", block), \
            "a style invented ramp material"
        assert "--hero-photo" not in block, "a style chose the photography"


def test_every_country_declares_the_same_material_contract() -> None:
    keys = {country: set(re.findall(r"(?m)^\s*(--[a-z0-9-]+)\s*:", country_block(country)))
            for country in COUNTRIES}
    base = keys["kr"]
    assert base >= {"--tone-1", "--tone-8", "--accent", "--gold", "--hero-photo",
                    "--work-1", "--work-2", "--work-3", "--font-display", "--works-lift"}
    for country, found in keys.items():
        missing = base - found
        extra = found - base
        assert not missing and not extra, f"{country} differs from kr: -{missing} +{extra}"


# ── the surfaces the design has ──────────────────────────────────────────────

def test_the_first_screen_carries_the_cinematic_composition() -> None:
    for part in ('class="council-hero"', 'class="council-scene"', 'class="council-photo-layer"',
                 'class="council-grain"', 'class="council-hero-copy"', 'class="council-eyebrow"',
                 'class="council-title"', "<em>", 'class="council-hero-lead"',
                 'class="council-cta"', 'class="council-hero-quote"', 'class="council-works"',
                 'class="council-works-head"', 'class="council-strip"', 'id="councilHome"'):
        assert part in HTML, f"the first screen lost {part}"
    assert HTML.count("<h1") == 1, "the design keeps exactly one h1"
    assert rule(".council-hero").strip().startswith("position: relative")
    assert "min-height: clamp(400px, 52.2svh, 640px)" in rule(".council-hero")
    assert "align-content: center" in rule(".council-hero")
    assert "background-image: var(--hero-image)" in rule(".council-photo-layer")
    assert "linear-gradient(90deg, var(--hero-scrim-strong)" in CSS, "the left-weighted press went missing"


def test_each_tool_keeps_its_own_photograph_and_its_own_face() -> None:
    faces = re.findall(r'--work-(\d):\s*([^;]+);', CSS)
    assert len(faces) >= 12, "every country must give all three cards a face"
    card = layer_rule(".council-card")
    assert "background: var(--work-face)" in card
    assert "--work-scrim: linear-gradient(96deg, var(--work-face)" in card, \
        "the scrim has to be declared where the face is, or it never re-resolves"
    assert "z-index: -2" in layer_rule(".council-card::before")
    assert "z-index: -1" in layer_rule(".council-card::after")


def test_presence_is_decided_by_tokens_not_by_country_forks() -> None:
    """The design splits per country (the quote exists only on 04, the badge only on 01, the
    index only on 02). That has to stay a token decision, or the next country added will
    forget one of these rules."""
    for selector, token in ((".council-hero-quote", "--hero-quote-display"),
                            (".council-hero-actions", "--hero-actions-display"),
                            (".council-works-head", "--works-head-display"),
                            (".council-works-note", "--works-note-display"),
                            (".council-card-badge", "--work-badge-display"),
                            (".council-card-index", "--work-index-display")):
        assert f"display: var({token})" in rule(selector), f"{selector} stopped honouring {token}"
    assert "display: var(--hero-eyebrow-display)" in CSS, "the hero eyebrow is a per-country decision"


def test_the_us_uk_frame_keeps_the_two_column_shape_and_the_lift() -> None:
    for country in ("us", "uk"):
        block = country_block(country)
        assert "--work-display: grid" in block and "--work-cols: 76px minmax(0, 1fr)" in block
        assert "--works-lift: 250px" in block
    hero = CSS.split("html[data-country=\"us\"] .council-hero", 1)[-1]
    assert "min-height: 526px" in hero.split("\n\n")[0], "the taller 01/02 hero was flattened"
    areas = CSS.split('html[data-country="us"] .council-card', 1)[-1]
    assert 'grid-template-areas: "icon title" "icon body" "icon foot"' in areas, \
        "the flat production children need explicit cells to keep the design's shape"


# ── what was deliberately left in the prototype ──────────────────────────────

def test_no_dead_control_came_over_from_the_prototype() -> None:
    """The design's nav row and rail point at screens this app does not have. A control that
    leads nowhere is worse than no control.

    2026-11-01 order: the header now carries the design's nav row and a search field —
    allowed only because each is wired to a screen this app actually has. The nav items
    may only target home, the tools section or the three tools (checked against the
    harness-verified data-nav set), and the search field is the wired tool finder
    (#councilSearchForm → wireSearch), not the prototype's decorative global search.
    The decorative screens the design only pretends at stay banned, as does any
    second, unwired search surface (the old council-search class name)."""
    for dead in ("활용 사례", "공지사항", "내 서랍", "템플릿 라이브러리", "전체 도구 보기",
                 "council-search", "council-rail", "pa-nav", "pa-rail"):
        assert dead not in HTML, f"{dead} arrived without a screen behind it"
    header = HTML.split("</header>")[0].replace('name="identifier"', "")
    if "<input" in header:
        # A header search field exists — it must be the wired one, nothing else.
        assert 'id="councilSearchForm"' in header, "an unwired header input showed up"
        assert 'role="search"' in header, "the search field lost its search role"
        assert "wireSearch" in JS and "bestToolFor" in JS, "the search field has no logic"


def test_the_app_still_owns_no_account_state_of_its_own() -> None:
    for fake in ("김민주", "pa-avatar", "pa-bell", "제22대", "council-session-chip"):
        assert fake not in HTML + JS, f"{fake} is invented account chrome"
    assert 'autocomplete="current-password"' in HTML
    assert "POST /api/auth/password/login" in HTML or 'fetch("/api/auth/password/login"' in JS


def test_the_photography_credit_is_text_and_the_files_are_the_designs() -> None:
    credit = re.search(r'<p class="council-footer-photo"[^>]*>(.*?)</p>', HTML, re.S)
    assert credit and "Farruk Ahmed Bhuiyan" in credit.group(1) and "CC BY-SA" in credit.group(1)
    assert "<a" not in credit.group(1), "the credit stays text; a link is a different promise"
    attribution = (DESIGN / "assets" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "Farruk Ahmed Bhuiyan" in attribution and "commons.wikimedia.org" in attribution
    heroes = re.findall(r'--hero-photo:\s*url\("\./assets/([^"]+)"\)', CSS)
    assert sorted(heroes) == ["parliament-fr-hero.jpg", "parliament-hero.jpg",
                              "parliament-uk-hero.jpg", "parliament-us-hero.jpg"], heroes
    for name in heroes + ["speech-card.jpg", "sns-card.jpg", "meeting-card.jpg"]:
        assert (STATIC / "assets" / name).is_file(), f"{name} is referenced but not staged"


def test_a_closed_surface_stays_closed_under_the_component_rules() -> None:
    """A component rule that says display:grid beats the UA's [hidden]; the popover and the
    workspace bar both proved it. State has to win over presentation."""
    assert re.search(r"(?m)^\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}", CSS)


# ── executed behaviour ───────────────────────────────────────────────────────

def test_twenty_combinations_are_reachable_and_both_axes_move_the_page() -> None:
    seen = run("cinematic")
    signed_in = seen["signedIn"]
    assert signed_in["initialCountry"] == "kr" and signed_in["initialStyle"] == "light"
    after = signed_in["afterPills"]
    assert (after["country"], after["style"]) == ("uk", "classic")
    assert after["checkedCountry"] == ["uk"] and after["checkedStyle"] == ["classic"]
    assert after["storedStyle"] == "classic", "the style has to survive a reload"
    assert "영국" in after["triggerValue"] and "클래식" in after["triggerValue"]
    combos = signed_in["combos"]
    assert combos["reached"] == 20 and combos["distinct"] == 20, combos


def test_the_country_pills_mirror_the_existing_authority() -> None:
    """The <select> is still the only country authority: #6046's payload, filtering and
    padiem-council-country key all read it. A pill that set its own parallel state would
    split the app in two."""
    seen = run("cinematic")
    assert seen["signedIn"]["afterPills"]["selectValue"] == "uk"
    assert seen["signedOut"]["selectValue"] == "fr"


def test_the_workspace_opens_and_closes_without_losing_the_selection_contract() -> None:
    seen = run("cinematic")
    workspace = seen["signedIn"]["workspace"]
    assert workspace["on"] is True and workspace["barHidden"] is False
    assert workspace["title"] == "축사·인사말"
    assert workspace["openBodies"] == ["councilSpeechBody"], "exactly one panel, as before"
    assert workspace["selected"] == "speech"
    back = seen["signedIn"]["afterBack"]
    assert back["on"] is False and back["barHidden"] is True and back["openBodies"] == []
    assert back["selected"] is None and back["title"] == ""


def test_the_design_still_works_signed_out_and_the_gate_stays_closed() -> None:
    seen = run("cinematic")
    off = seen["signedOut"]
    assert (off["country"], off["style"]) == ("fr", "dark"), "the axes belong to the page"
    assert off["panelVisible"] is True and off["badge"] == "로그인 필요"
    assert off["forms"] == 1, "only the login form may exist while signed out"
    assert off["openBodies"] == [] and off["workspaceOn"] is False


def test_the_workspace_bar_stays_in_the_flow() -> None:
    """A sticky or floating bar paints over the first field of the very form it is the way
    out of - measured at 390, where input[name=nature] sat under #councilBack and the hit
    test returned the button. The design makes the same call for the same reason, and the
    script brings the reader to the bar instead."""
    tail = CSS.split("/* ══ end of the ported token layer", 1)[-1]
    bar = re.search(r"(?m)^html\.council-in-workspace \.council-workspace-bar\s*\{([^}]*)\}", tail)
    assert bar, "the workspace bar has no rule of its own any more"
    for floating in ("position: sticky", "position: fixed"):
        assert floating not in bar.group(1), f"{floating} would cover the form again"
    assert 'bar.scrollIntoView({ block: "start" })' in JS, "nothing brings the reader to the bar"


def test_the_workspace_state_is_painted_from_the_selection_itself() -> None:
    """One call site, inside applySelection: the screen a visitor is on must never disagree
    with which panel is open."""
    assert JS.count("paintWorkspace(") == 2, JS.count("paintWorkspace(")
    selection = JS[JS.index("function applySelection("):JS.index("function openLoginHere(")]
    assert "paintWorkspace(tool || null);" in selection
    assert 'classList[tool ? "add" : "remove"]("council-in-workspace")' in JS
    assert 'host("councilBack")' in JS and "leaveWorkspace" in JS
