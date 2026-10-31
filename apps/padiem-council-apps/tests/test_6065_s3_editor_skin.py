"""#6065 S3: the three editors take the design's field panel and paper surface.

Measured in Chromium against the bytes `origin/main` serves (S2) and against this
branch, and the five AI/storage cases were A/B'd for payload and output equality.

  1440px  editor body becomes two columns `340px 532px`: the form on the left and
          the result / saved list / archive on the right at x=631. Before S3 the
          form was one 886px column and the result stacked under it.
  768/390/320  the body stays one column (`grid-template-columns: none`), form
          706 / 332 / 262 wide — the design's own <=900 behaviour.
  controls  generate is a filled pill (radius 999px, weight 700, 48px tall at
          1440), save and the document actions are hairline pills, fields are
          15px on a 14px radius with 10px 12px padding, and the result textarea is
          a borderless sheet at 16.5px/1.85 inside a padded paper panel.

Horizontal overflow stayed 0 and occlusion stayed 0 across 32 cells (2 auth
states x 4 widths x 4 views).
"""
from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
CSS = (APP_ROOT / "static" / "council-app.css").read_text(encoding="utf-8")


def block(selector: str) -> str:
    found = re.search(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.S | re.M)
    assert found, f"missing rule: {selector}"
    return found.group(1)


def media(query: str) -> str:
    found = re.search(rf"@media \({re.escape(query)}\)\s*\{{(.*?)\n\}}", CSS, re.S)
    assert found, f"the {query} block must exist"
    body = found.group(1)
    assert "@media" not in body
    return body


def test_the_field_group_is_the_designs_meta_panel():
    meta = block(".council-fieldset")
    assert "border-radius: 14px" in meta, meta
    assert "padding: clamp(14px, 1.8vw, 20px)" in meta, meta
    assert "gap: 12px" in meta, meta
    label = block(".council-form label")
    assert "font-size: 12px" in label and "letter-spacing: .04em" in label, label
    assert "var(--council-muted)" in label, label


def test_the_fields_keep_the_touch_floor_at_the_design_size():
    fields = block(".council-form input,\n.council-form textarea,\n.council-form select")
    for prop in ("min-height: 44px", "padding: 10px 12px", "border-radius: 14px", "font-size: 15px"):
        assert prop in fields, f"{prop} missing: {fields}"
    area = block(".council-form textarea")
    assert "min-height: 92px" in area and "resize: vertical" in area, area


def test_the_primary_and_secondary_actions_are_the_designs_pills():
    primary = block(".council-generate,\n.council-login")
    assert "border-radius: 999px" in primary, primary
    assert "font-weight: 700" in primary and "padding: 10px 20px" in primary, primary
    assert "min-height: 44px" in primary, primary
    for sel in (".council-save", ".council-actions button"):
        assert "border-radius: 999px" in block(sel), sel


def test_the_result_is_a_paper_surface_not_an_input_box():
    paper = block(".council-result")
    assert "padding: clamp(16px, 2.4vw, 30px)" in paper, paper
    assert "border-radius: 18px" in paper, paper
    sheet = block(".council-result textarea")
    for prop in ("border: 0", "padding: 0", "font-size: 16.5px", "line-height: 1.85",
                 "min-height: clamp(320px, 54svh, 620px)"):
        assert prop in sheet, f"{prop} missing: {sheet}"


def test_the_sheet_keeps_a_visible_focus_signal_after_losing_its_outline():
    # The design drops the textarea outline and lights the panel border instead.
    assert "outline: 0" in block(".council-result textarea:focus-visible"), "the sheet must not keep a double ring"
    focus = block(".council-result:focus-within")
    assert "var(--council-accent)" in focus, "the paper border is the focus signal"
    assert ":focus-visible" in CSS, "the global keyboard ring stays"


def test_the_two_column_editor_only_opens_when_the_right_side_has_content():
    wide = media("min-width: 900px")
    assert "grid-template-columns: minmax(0, 340px) minmax(0, 1fr)" in wide, wide
    # Comments are stripped first: a note that merely mentions :has() must not pass
    # the gate check for a rule that is not actually gated.
    code = re.sub(r"/\*.*?\*/", "", wide, flags=re.S)
    selectors = [part.split("{")[0] for part in code.split("}") if "{" in part]
    assert selectors, "the wide block must hold rules"
    for sel in selectors:
        assert ":has(" in sel, f"an ungated editor rule would leave an empty column: {sel.strip()[:60]}"
    assert "min-width: 900px" in CSS and "max-width: 900px" in CSS, "the design switches columns at 900"


def test_the_editor_skin_still_borrows_nothing_from_outside_the_bundle():
    assert "@import" not in CSS, "the sheet may not reach another sheet"
    assert CSS.count("min-height: 44px") >= 6, CSS.count("min-height: 44px")
    assert "padiem-parliament-theme" not in CSS, "the prototype keeps its own key"
    # Comments carry issue numbers like #6046 and the keyboard ring keeps Chat's own
    # --focus-ring fallback, so neither is a colour the editor skin invented.
    outside = CSS.split("/* ══ cinematic token layer", 1)
    code = outside[0] + (outside[1].split("/* ══ end of the ported token layer", 1)[-1]
                         if len(outside) > 1 else "")
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = "\n".join(l for l in code.splitlines() if "--focus-ring" not in l)
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", code)
    assert not literals, f"the editor skin must stay on the shared tokens: {literals}"
