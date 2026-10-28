"""#5799 — the speech page becomes the shared util template.

Meeting-header parity (brand-dot kicker through the shared glass list), a
per-tool kicker/tagline, grouped form sections, readable control outlines and
the light PADIEM blue primary — all scoped so the other three tools keep their
current presentation until their own pass.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
STANDALONE_CSS = (ROOT / "static" / "standalone-views.css").read_text(encoding="utf-8")
UTIL_CSS = (ROOT / "static" / "util-menu.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "util-menu.js").read_text(encoding="utf-8")


def test_the_util_header_joins_the_glass_brand_eyebrow():
    """The glass dot+eyebrow list is what every destination shares; the util
    page must be in it or its kicker stays a plain gray line."""
    for needle in ("standalone-view-kicker", "::before"):
        pass
    start = STANDALONE_CSS.index('html[data-theme="padiem-glass"] body .app-shell:is(')
    first_block = STANDALONE_CSS[start : STANDALONE_CSS.index(") :is(", start)]
    assert '[data-state="util"]' in first_block, "glass kicker list missing the util state"
    before_block = STANDALONE_CSS[STANDALONE_CSS.index("::before", start) - 400 : STANDALONE_CSS.index("::before", start)]
    assert '[data-state="util"]' in before_block, "glass kicker dot list missing the util state"


def test_the_speech_header_carries_the_tool_kicker_and_tagline():
    assert 'id="utilKicker"' in HTML and 'id="utilTagline"' in HTML
    assert 'data-kicker="Padiem Speech"' in HTML
    assert "행사에 맞는 축사·인사말 초안을 준비합니다" in HTML
    # The sync keeps the shared defaults for tools without their own pass.
    assert 'tab.dataset.kicker || "Padiem Util"' in APP_JS
    assert 'tab.dataset.tagline || "AI 홍보·기록 비서"' in APP_JS


def test_the_speech_form_groups_into_sections():
    form = HTML[HTML.index('id="utilSpeechForm"') : HTML.index("</form>", HTML.index("id=\"utilSpeechForm\""))]
    # #6100: the reference lane leads the form first (the SNS tool's #6098
    # language), then the #5799 sections: 기본 정보, 내용, 분량·말투·참고.
    assert form.count('class="util-fieldset"') == 4
    for legend in ("참고 글", "기본 정보", "내용", "분량·말투·참고"):
        assert f"<legend>{legend}</legend>" in form
    # The PC reference lane is the form's own first section, mount inside it.
    ref_at = form.index('id="utilSpeechRef"')
    assert ref_at < form.index('id="utilSpeechPcRef"') < form.index("<legend>기본 정보</legend>")
    # Field names are the API surface — grouping must not rename anything.
    for name in ("event", "date", "place", "nature", "audience", "author", "message", "emphasis", "length", "tone", "style"):
        assert f'name="{name}"' in form


def test_the_speech_controls_draw_readable_outlines():
    scoped = "#utilSpeechPanel .util-form input"
    assert scoped in UTIL_CSS
    assert "border: 1px solid rgba(51, 74, 91, .34); background: #ffffff;" in UTIL_CSS
    assert "#utilSpeechPanel .util-form input:hover" in UTIL_CSS
    assert "#utilSpeechPanel .util-form label" in UTIL_CSS and "font-weight: 600" in UTIL_CSS


def test_the_speech_primary_is_the_light_blue_and_stays_speech_scoped():
    override = "html[data-theme=\"padiem-glass\"] #utilSpeechPanel .util-generate"
    assert override in UTIL_CSS
    # Light PADIEM blue with dark ink, not the old navy.
    block = UTIL_CSS[UTIL_CSS.index(override) :]
    assert "var(--accent, #79bce7)" in block[: block.index("}")]
    # The composer-matched navy stays for the tools that have not had their pass.
    assert "html[data-theme=\"padiem-glass\"] .util-generate," in UTIL_CSS
    # The speech override must not leak to SNS/meeting buttons: every new
    # generate rule carries the speech panel scope.
    for chunk in UTIL_CSS.split("util-generate"):
        pass
    speech_block_start = UTIL_CSS.index("#5799")
    speech_block = UTIL_CSS[speech_block_start:]
    for line in speech_block.splitlines():
        if ".util-generate" in line and "{" in line:
            assert "#utilSpeechPanel" in line, f"unscoped generate rule in the #5799 block: {line.strip()}"
