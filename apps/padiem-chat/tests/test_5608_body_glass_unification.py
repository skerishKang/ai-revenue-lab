"""#5608/#5028: the util and meeting bodies read as one PADIEM surface.

2026-11-01: the 의원3종 panels moved to their own app, so the util page keeps
only the PDF → Markdown surface. What still belongs here is the shared frame
membership, the single glass shell (no double inset) and the shared page-title
contract.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME = (ROOT / "static/shared-six-panel-frame.css").read_text(encoding="utf-8")
UTIL_CSS = (ROOT / "static/util-menu.css").read_text(encoding="utf-8")
MEETING_CSS = (ROOT / "static/meeting-capture.css").read_text(encoding="utf-8")


def _selector_group(selector: str) -> str:
    start = selector.index(":is(") + len(":is(")
    depth = 1
    for index in range(start, len(selector)):
        if selector[index] == "(":
            depth += 1
        elif selector[index] == ")":
            depth -= 1
            if depth == 0:
                return " ".join(selector[start:index].split())
    raise AssertionError("unterminated :is() selector")


def _shared_primary_rules(css: str) -> list[tuple[str, str]]:
    rules = []
    position = 0
    while True:
        position = css.find("html body :is(", position)
        if position < 0:
            return rules
        brace = css.index("{", position)
        close = css.index("}", brace)
        rules.append((css[position:brace].strip(), css[brace + 1:close]))
        position = close


def test_util_view_joins_every_six_panel_frame_lane() -> None:
    frame_lists = [segment for segment in FRAME.split(":is(") if ".meeting-view" in segment]
    assert len(frame_lists) >= 4, "expected the frame, ultrawide, eyebrow and collapse lanes"
    for segment in frame_lists:
        assert ".util-view" in segment, "a six-panel lane is missing .util-view"


def test_the_pdf_shell_flattens_inside_the_glass_frame() -> None:
    block = UTIL_CSS[UTIL_CSS.index("#5028/#5608: inside the shared six-panel frame"):]
    assert "@media (min-width: 921px)" in block
    assert 'html[data-theme="padiem-glass"] body .app-shell[data-state="util"]' in block
    assert ".pdfmd-shell" in block
    assert "padding: 0" in block and "box-shadow: none" in block
    assert "backdrop-filter: none" in block


def test_meeting_transcript_height_is_capped_for_the_first_screen() -> None:
    # #5028: the idle transcript no longer over-expands the bright panel.
    assert "min-height: clamp(180px, 24vh, 260px)" in MEETING_CSS
    assert "min-height: clamp(200px, 30vh, 330px)" not in MEETING_CSS


def test_util_header_joins_the_shared_page_title_contract() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    header = html[html.index('class="util-header"') : html.index("</header>", html.index('class="util-header"'))]
    # #7172: the page heading is the UTIL first screen; the one tool's name
    # (PDF → Markdown) belongs to its card below, and comes back when the
    # tool itself is open.
    assert 'class="standalone-view-kicker" id="utilKicker"' in header and "Padiem Util" in header
    assert "PDF → Markdown" not in header
    assert 'class="standalone-view-title"' in header
    assert 'data-locale-key="util-title"' in header and ">유틸</h2>" in header
    assert 'class="standalone-view-tagline" id="utilTagline"' in header
    assert "자주 쓰는 문서·홍보 도구 모음" in header
    STANDALONE_CSS = (ROOT / "static/standalone-views.css").read_text(encoding="utf-8")
    title_list = STANDALONE_CSS[STANDALONE_CSS.index(".app-shell:is([data-state=\"meeting\"],") : STANDALONE_CSS.index("font-weight: 770")]
    assert '[data-state="util"]' in title_list
    kicker_list = STANDALONE_CSS[STANDALONE_CSS.index(":is(.standalone-view-kicker,.calendar-view-kicker") - 200 : STANDALONE_CSS.index(":is(.standalone-view-kicker,.calendar-view-kicker") + 60]
    assert '[data-state="util"]' in kicker_list
    stack_list = STANDALONE_CSS[STANDALONE_CSS.index(".util-header > div") - 400 : STANDALONE_CSS.index(".util-header > div")]
    assert '[data-state="util"]' in stack_list


def test_the_primary_action_matches_the_chat_claw_send_color() -> None:
    # #7162 absorbed #5608's glass-only navy into the app-wide shared primary
    # rule ? the same #355977 send-button colors, now in every theme. #7172
    # adds the util toolbox buttons to every block of that rule; assert the
    # membership of each block's selector list, not one formatted line.
    polish = (ROOT / "static/padiem-chat-ui-polish.css").read_text(encoding="utf-8")
    rules = _shared_primary_rules(polish)
    assert len(rules) == 3, "base, hover and focus-visible share one selector list"
    groups = [_selector_group(selector) for selector, _ in rules]
    assert groups[0] == groups[1] == groups[2], groups
    members = {part.strip() for part in groups[0].split(",")}
    assert ".util-tool-open" in members
    assert ".pdfmd-btn-primary" in members
    base, hover, focus = rules
    assert base[0].endswith(")") and hover[0].endswith(":not(:disabled):hover")
    assert focus[0].endswith(":focus-visible")
    assert "background: #355977;" in base[1]
    assert "color: #fff;" in base[1]
    assert "background: #2e4d67;" in hover[1]
    assert "outline: 3px solid #6a9abc;" in focus[1]
    # The glass-only copy is gone; one rule carries the decision.
    assert "html[data-theme=\"padiem-glass\"] .pdfmd-btn-primary {" not in UTIL_CSS
    h2_rule = UTIL_CSS[UTIL_CSS.index(".util-header h2") : UTIL_CSS.index(".util-header .standalone-view-tagline")]
    assert "font-size" not in h2_rule
