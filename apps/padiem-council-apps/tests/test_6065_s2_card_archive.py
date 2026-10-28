"""#6065 S2: the card frame and the archive tap affordance.

Measured in Chromium against the bytes `origin/main` serves, and A/B'd against
`main` itself so the AI lanes are proven unchanged:

  card frame      design `.pa-work` at 1440: icon slot 30x30 holding a 26x26
                  stroke svg, a 22x2 rule under it, title clamp(17px,1.39vw,20px)
                  /700/-0.02em. Production before S2 had no icon slot at all and a
                  fixed 17px title with normal tracking. After S2: icon 30x30 at
                  x=277 with a 26x26 svg, rule 22x2, title 20px/-0.4px at 1440 and
                  17px at <=768 — the same two numbers the design produces.
  archive         `input.council-book-check` is 24x24 (#6075). It is now wrapped in
                  `label.council-archive-check`, measured 44x44 at 320/390/768/1440.
                  Pressing the label 5px inside its left edge toggled the box in all
                  four widths (checked=False -> True), and the 활동집 path still read
                  `.council-book-check:checked`.
  skip link       92.8x25.6 before (the only sub-44 control left in the app);
                  min-height 44px on :focus after.

The five flow cases (speech/sns/meeting at kr, speech at fr, meeting at us) sent
byte-identical POST bodies and rendered identical results before and after:
`/api/chat` and `/api/projects/p1/files` carry no `country` for kr and the chosen
code otherwise, and the SNS photo composition file still posts as JSON.
"""
from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
CSS = (APP_ROOT / "static" / "council-app.css").read_text(encoding="utf-8")
HTML = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (APP_ROOT / "static" / "council-app.js").read_text(encoding="utf-8")


def block(selector: str) -> str:
    found = re.search(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.S | re.M)
    assert found, f"missing rule: {selector}"
    return found.group(1)


def test_the_card_is_the_two_column_frame_with_an_icon_slot():
    card = block(".council-card")
    assert "grid-template-columns: 30px minmax(0, 1fr)" in card, card
    assert "display: grid" in card, card
    icon = block(".council-card-icon")
    assert "width: 30px" in icon and "height: 30px" in icon, icon
    assert "grid-column: 1" in icon and "grid-row: 1 / span 3" in icon, icon
    svg = block(".council-card-icon svg")
    for prop in ("width: 26px", "height: 26px", "fill: none", "stroke: var(--council-text)", "stroke-width: 1.5"):
        assert prop in svg, f"{prop} missing: {svg}"
    rule = block(".council-card-icon::after")
    assert "width: 22px" in rule and "height: 2px" in rule, rule
    assert "var(--council-border)" in rule, "the rule must come from the shared token, not a literal"
    # the text children move to column two, and the editor keeps the whole card width
    assert "grid-column: 2" in CSS[CSS.index(".council-card > h2"):CSS.index(".council-card.active")]
    assert "grid-column: 1 / -1" in block(".council-card-body")


def test_every_tool_carries_its_own_inline_icon_and_none_of_them_is_an_asset():
    cards = dict(re.findall(r'<section class="council-card" id="council-(\w+)"(.*?)</section>', HTML, re.S))
    assert set(cards) == {"speech", "sns", "meeting"}, sorted(cards)
    for tool, card in cards.items():
        assert 'class="council-card-icon" aria-hidden="true"' in card, tool
        assert card.count('viewBox="0 0 32 32"') == 1, tool
        assert card.count("<svg") == 1, tool
    assert HTML.count('class="council-card-icon"') == 3
    assert "url(" not in CSS and "@import" not in CSS and "@font-face" not in CSS


def test_the_card_title_uses_the_design_fluid_scale():
    title = block(".council-card > h2")
    assert "font-size: clamp(17px, 1.39vw, 20px)" in title, title
    assert "letter-spacing: -0.02em" in title, title
    assert "word-break: keep-all" in title, "Korean titles must not break mid-word"


def test_the_narrower_text_column_still_breaks_korean_at_word_ends():
    # The icon column takes 42px away from the text. At 390 the description broke in
    # the middle of the last word until both card strings kept whole words.
    title = block(".council-card > h2")
    desc = block(".council-card > p")
    assert "word-break: keep-all" in title, title
    assert "word-break: keep-all" in desc, desc
    assert "overflow-wrap: anywhere" in desc, "a single long token must still be able to break"


def test_the_archive_checkbox_is_pressed_through_a_44px_label():
    label = block(".council-archive-check")
    assert "min-width: 44px" in label and "min-height: 44px" in label, label
    assert "display: inline-flex" in label, label
    # the box keeps #6075's 24px size; only the affordance grows
    box = block(".council-book-check")
    assert "width: 24px" in box and "height: 24px" in box, box
    # the JS must wrap, not replace: the :checked query the book path relies on is unchanged
    assert 'check.className = "council-archive-check"' in JS
    assert "check.appendChild(cb)" in JS and "li.appendChild(check)" in JS
    assert 'querySelectorAll(".council-book-check:checked")' in JS


def test_the_skip_link_reaches_the_touch_floor_when_focused():
    focus = block(".council-skip:focus")
    assert "min-height: 44px" in focus, focus
    assert "display: inline-flex" in focus, focus


def test_no_style_axis_or_asset_leaked_in_with_the_card_frame():
    for text, name in ((HTML, "index.html"), (JS, "council-app.js"), (CSS, "council-app.css")):
        assert "padiem-parliament-theme" not in text, name
        assert "data-style" not in text, name
