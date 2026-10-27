"""#5967 Parliament AI 디자인 프로토타입의 정적 계약.

이 레인이 실행하는 것: 프로토타입이 (1) 어떤 네트워크도 쓰지 않는 시각·동작 시안인지,
(2) 국가=음계 / 스타일=역할 두 축이 토큰으로만 분리돼 레이아웃에 색 리터럴이 없는지,
(3) 운영 의원3종 화면·자산 경로부터 독립 디렉터리인지.
실제 브라우저 렌더·반응형·접근성·성능 수치는 이 테스트가 아니라 PR에 첨부한 계측
보고서와 캡처의 증거다.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "parliament-theme.css").read_text(encoding="utf-8")
JS = (ROOT / "parliament-app.js").read_text(encoding="utf-8")
CHAT_BUILDER = (REPO_ROOT / "apps" / "padiem-chat" / "scripts" / "build_b66_worker_dependencies.py").read_text(encoding="utf-8")

COUNTRIES = ("kr", "us", "fr", "uk")
STYLES = ("classic", "modern", "dark", "light", "minimal")

RAMP = frozenset(f"--tone-{n}" for n in range(1, 9))
SCENE = frozenset({"--sky-1", "--sky-2", "--sky-3", "--sky-4", "--sun", "--sun-glow", "--skyline", "--skyline-back", "--reflection", "--haze", "--lit", "--vignette"})
# 사진 층은 국가가 재료를 정한다. 없는 국가는 `none`을 명시해 미확보 상태를 코드에 남긴다.
PHOTO = frozenset({"--hero-photo", "--hero-photo-position", "--hero-photo-zoom", "--pa-grade-op", "--skyline-display"})
# 밤 사진에 시안 톤을 입히는 층: 국가마다 강도를 정한다(0이면 무보정).
# 시안의 3카드 분할 색: 국가마다 자기 음계에서 3개를 배정한다.
WORK = frozenset({"--work-1", "--work-2", "--work-3"})
IDENTITY = frozenset({"--accent", "--accent-contrast", "--accent-soft", "--gold", "--gold-soft", "--danger", "--success", "--font-display", "--font-body", "--font-label"})
ROLES = frozenset({"--bg", "--page-bg", "--panel", "--text", "--muted", "--line", "--paper", "--ink", "--ink-muted", "--glass", "--shadow", "--focus-ring", "--hero-scrim", "--hero-text", "--pa-scene-op"})

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
COMMENT = re.compile(r"/\*.*?\*/", re.S)
VARREF = re.compile(r"var\(--[a-z0-9-]+\)")
COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![-\w])(?:red|blue|green|white|black|navy|silver|cream|gold)(?![-\w])")
NETWORK = re.compile(r"fetch\s*\(|XMLHttpRequest|new\s+WebSocket|EventSource|sendBeacon|navigator\.clipboard")
EXTERNAL_ASSET = re.compile(
    r"""(?:src|href)\s*=\s*["'](?:https?:)?//[^"']*|url\(\s*["']?(?:https?:)?//|@import"""
)
# <a href>는 자산을 읽지 않는다. 링크는 저작 표기 2건만 허용하고, 그 밖의 외부 링크는 실패시킨다.
ANCHOR_HREF = re.compile(r"""<a\s[^>]*href="((?:https?:)?//[^"]+)"""  )
ALLOWED_LINK_HOSTS = ("commons.wikimedia.org", "creativecommons.org")


def rules(text: str) -> list[tuple[str, str]]:
    return [(re.sub(r"\s+", " ", sel).strip(), body) for sel, body in RULE.findall(COMMENT.sub("", text))]


def blocks_for(role: str, value: str) -> list[str]:
    token = f'[data-{role}="{value}"]'
    return [body for sel, body in rules(CSS) if token in sel]


def props_of(*bodies: str) -> set[str]:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", " ".join(bodies)))


TOKEN_SITE = re.compile(
    r"^\s*(?:html\[data-(?:country|style)=\"[a-z]+\"\]|:root)"
    r"(?:\s*,\s*(?:html\[data-(?:country|style)=\"[a-z]+\"\]|:root))*\s*$"
)


def layout_source() -> str:
    """색 재료를 정의하는 토큰 자리만 걷어낸 CSS — 레이아웃이 실제로 읽는 부분."""
    keep = [sel + "{" + body + "}" for sel, body in rules(CSS) if not TOKEN_SITE.match(sel)]
    assert len(rules(CSS)) - len(keep) >= 9, "the token axis blocks themselves must be present"
    return COMMENT.sub("", "\n".join(keep))


def layout_text() -> str:
    """거기서 토큰 참조까지 지운 것 — 색 리터럴이 숨을 수 있는 유일한 영역."""
    return VARREF.sub("", layout_source())


# ── 프로토타입 = 네트워크 제로, 원격 자산 제로 ───────────────────────────────
def test_prototype_calls_no_api_and_loads_no_remote_asset() -> None:
    assert not NETWORK.search(JS), f"the prototype must not touch the network: {NETWORK.findall(JS)[:3]}"
    for name, text in (("index.html", HTML), ("parliament-theme.css", CSS), ("parliament-app.js", JS)):
        offenders = [o for o in EXTERNAL_ASSET.findall(text) if not o.startswith("<a")]
        assert not offenders, f"{name} must load no remote asset: {offenders[:3]}"
    assert "@import" not in CSS


def test_the_only_outbound_links_are_the_licence_record() -> None:
    links = ANCHOR_HREF.findall(HTML)
    assert links, "the attribution link must exist for CC BY"
    for href in links:
        host = href.split("/")[2] if "//" in href else ""
        assert host in ALLOWED_LINK_HOSTS, f"unexpected outbound link: {host or href}"
    assert any("creativecommons.org" in h for h in links), "the licence itself must be linked"


def test_binaries_are_limited_to_licensed_assets_and_captures() -> None:
    """바이너리는 (1) 출처가 기록된 히어로 자산, (2) 검토 캡처 두 자리만 허용한다."""
    shipped = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    code = [p for p in shipped if not p.startswith(("assets/", "docs/screenshots/"))]
    assert code, "the prototype must ship its own source files"
    assert all(Path(p).suffix in {".html", ".css", ".js", ".md", ".py"} for p in code), code
    images = [p for p in shipped if p.startswith("assets/") and Path(p).suffix in {".jpg", ".jpeg", ".png", ".webp"}]
    assert images, "the hero asset must actually be present once a photo is adopted"
    attribution = (ROOT / "assets" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    for image in images:
        assert Path(image).name in attribution, f"{image} ships without a recorded source"
    for probe in ("CC BY", "creativecommons.org", "upload.wikimedia.org", "저작자"):
        assert probe in attribution, f"the licence record is missing {probe}"


# ── 축 1 · 국가 = 음계만 정의하고 역할은 배정하지 않는다 ─────────────────────
def test_each_country_declares_exactly_one_ramp_block() -> None:
    for country in COUNTRIES:
        declaring = [b for b in blocks_for("country", country) if re.search(r"--[a-z0-9-]+\s*:", b)]
        assert len(declaring) == 1, f"{country} declares its ramp in {len(declaring)} places"
        assert props_of(*declaring) == RAMP | SCENE | PHOTO | WORK | IDENTITY, country


def test_countries_share_the_identical_token_contract() -> None:
    keys = {country: props_of(*blocks_for("country", country)) for country in COUNTRIES}
    assert len({frozenset(v) for v in keys.values()}) == 1, "a new country must add the same key set, nothing else"
    for country, value in keys.items():
        assert not value & ROLES, f"{country} assigns roles that belong to the style axis: {sorted(value & ROLES)}"


def test_country_blocks_never_reuse_another_country_value() -> None:
    hexes = {country: re.findall(r"#[0-9a-fA-F]{6}", " ".join(blocks_for("country", country))) for country in COUNTRIES}
    assert all(len(v) >= 8 for v in hexes.values()), hexes
    assert len(set(hexes["kr"]) & set(hexes["us"])) == 0, "the ramps must be genuinely different palettes"


# ── 축 2 · 스타일 = 역할 할당 + 성격, 색 재료는 만들지 않는다 ────────────────
def test_every_style_assigns_the_full_role_set() -> None:
    for style in STYLES:
        assigned = props_of(*blocks_for("style", style))
        assert ROLES <= assigned, f'{style} leaves roles unassigned: {sorted(ROLES - assigned)}'


def test_no_style_invents_colour_material() -> None:
    for style in STYLES:
        assigned = props_of(*blocks_for("style", style))
        material = sorted(k for k in assigned if k.startswith(("--tone-", "--sky-")) or k in SCENE)
        assert not material, f"{style} must pick from the country ramp, not repaint it: {material}"


def test_styles_differ_only_in_which_ramp_step_a_role_uses() -> None:
    for style in STYLES:
        body = " ".join(blocks_for("style", style))
        tone_refs = len(re.findall(r"var\(--tone-\d\)", body))
        assert tone_refs >= 8, f"{style} maps only {tone_refs} roles onto the country ramp"
        assert "var(--accent" in body, f"{style} does not take the country accent"


# ── 레이아웃 계층은 토큰만 읽는다 ───────────────────────────────────────────
def test_layout_layer_has_no_color_literal() -> None:
    offenders = COLOR_LITERAL.findall(layout_text())
    assert offenders == [], f"colour literals escaped the token blocks: {offenders[:8]}"


def test_every_token_the_layout_reads_is_declared_somewhere() -> None:
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", COMMENT.sub("", CSS)))
    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", layout_source()))
    assert used - declared == set(), f"tokens read without any definition: {sorted(used - declared)}"
    assert declared >= RAMP | SCENE | ROLES


# ── 화면 구성: 최소 메뉴 · 히어로 · 카드 3개 · 문서 작업실 ───────────────────
def test_screen_composition_is_limited_as_ordered() -> None:
    assert HTML.count("<h1") == 1
    assert HTML.count('class="pa-work"') == 3, "exactly three work cards"
    assert HTML.count('class="pa-work-select"') == 3
    # 시안은 영구 사이드바 메뉴와 업무 카드 목록이라는 서로 다른 두 개의 탐색을 쓴다.
    assert HTML.count("<nav") == 2, "rail menu + work list, and nothing more"
    assert HTML.count('class="pa-nav-item"') + HTML.count('class="pa-nav-item is-current"') == 6
    assert HTML.count('aria-disabled="true"') == 2, "미구현 메뉴는 죽은 통제처럼 보여선 안 된다"
    assert HTML.count("<footer") == 1
    for fragment in ('class="pa-topbar"', 'class="pa-hero"', 'class="pa-scene"', 'class="pa-editor"'):
        assert fragment in HTML, fragment
    assert "활동집" in HTML, "the meeting card must keep the activity-book framing"


def test_heading_hierarchy_and_labels_are_complete() -> None:
    assert 'aria-labelledby="paEditorTitle"' in HTML and 'id="paEditorTitle"' in HTML
    assert re.search(r'<h2 class="pa-editor-kicker" id="paEditorTitle">', HTML)
    assert "paEditorKicker" not in HTML + JS, "the editor title id must be the one JS writes"
    for target in set(re.findall(r'aria-(?:labelledby|controls|describedby)="([^"]+)"', HTML)):
        assert f'id="{target}"' in HTML, f"aria reference hangs: {target}"


# ── 접근성: 정적 마크업에서 확인되는 불변조건 ────────────────────────────────
def test_accessibility_invariants_in_markup() -> None:
    assert '<html lang="ko"' in HTML
    assert 'class="pa-skip" href="#paMain"' in HTML and 'id="paMain"' in HTML
    for button in re.findall(r"<button[^>]*class=\"pa-work-select[^\"]*\"[^>]*>", HTML):
        assert 'aria-controls="paEditor"' in button and 'aria-expanded="false"' in button
    assert 'role="status"' in HTML and 'aria-live="polite"' in HTML
    assert re.search(r'<label[^>]*for="paDocument"', HTML)
    assert re.search(r'<select name="country" id="paCountry"', HTML)
    assert re.search(r'<label>국가\s*<select', HTML), "each select needs its wrapping label"
    assert 'aria-hidden="true"' in HTML


def test_view_toggles_survive_the_class_display_rule() -> None:
    """JS가 #paHome을실행 중에 숨기지만 클래스의 `display: grid`가 UA [hidden]을 이긴다.

    실제 브라우저에서 두 화면이 동시에 뜨는 것을 계측으로 확인했기 때문에,
    `[hidden] { display: none !important }` 오버라이드가 이 화면 전환의 load-bearing 규칙이다.
    """
    assert "home.hidden = true;" in JS and "editor.hidden = true;" in JS
    home_grid = [body for sel, body in rules(CSS) if ".pa-home" in sel and re.search(r"display:\s*(grid|flex)", body)]
    assert home_grid, "#pa-home must still carry a class-level display for this guard to mean anything"
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", CSS), (
        "a class `display` beats the UA [hidden] rule, so the view toggle needs an !important override")


def test_target_size_focus_and_reduced_motion_are_tokenised() -> None:
    assert "--pa-target: 44px;" in CSS
    assert CSS.count("min-height: var(--pa-target)") >= 5
    assert ":focus-visible" in layout_text()
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "@media (prefers-contrast: more)" in CSS


def test_three_viewports_are_declared() -> None:
    widths = {int(value) for _, value in re.findall(r"@media[^{]*\((max-width|min-width): (\d+)px\)", CSS)}
    assert {390, 767, 1200} <= widths, f"measured breakpoints: {sorted(widths)}"


# ── 운영 제품과 완전히 분리 ─────────────────────────────────────────────────
def test_prototype_never_links_to_the_production_entry() -> None:
    assert not re.search(r'(?:href|src)="[^"]*apps/council', HTML), "no link or asset request into production"
    assert not re.search(r"(?:location|window\.open|fetch)\s*[=(]\s*[\"'`][^\"'`]*apps/council", JS)
    assert "council-app." not in HTML + CSS + JS
    assert '"/api/' not in HTML + JS and "'/api/" not in HTML + JS


def test_chat_asset_stager_does_not_learn_this_directory() -> None:
    assert "padiem-parliament" not in CHAT_BUILDER
    assert '"prefix": "apps/council"' in CHAT_BUILDER, "the shipped entry staging must stay exactly as it is"


def test_countries_without_a_photo_say_so_explicitly() -> None:
    """대체 그림을 지어 완성을 주장하지 않도록, 사진 없는 국가는 none을 코드로 선언해야 한다."""
    for country in ("us", "fr", "uk"):
        body = " ".join(blocks_for("country", country))
        assert re.search(r"--hero-photo:\s*none", body), f"{country} must declare --hero-photo: none until its asset arrives"
    kr = " ".join(blocks_for("country", "kr"))
    assert re.search(r"--hero-photo:\s*(?:url|image-set)\(", kr), "kr is the country that actually has a licensed photo"
    assert re.search(r"--skyline-display:\s*none", kr), "the CSS skyline is a fallback, not decoration on top of a photo"
    referenced = set(re.findall(r'url\("\./assets/([^"]+)"\)', CSS))
    on_disk = {p.name for p in (ROOT / "assets").iterdir() if p.is_file()}
    assert referenced and referenced <= on_disk, f"CSS references assets that are not shipped: {sorted(referenced - on_disk)}"


def test_prototype_directory_shape_is_independent() -> None:
    assert ROOT.parent.name == "reference"
    assert ROOT.name == "padiem-parliament-ai-design-v1"
    assert (ROOT / "README.md").is_file()
    for forbidden in ("wrangler.toml", "package.json", "requirements.txt"):
        assert not (ROOT / forbidden).exists(), forbidden
