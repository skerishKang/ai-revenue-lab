"""#6065 S4: the sign-in gate and the record lists take the design's surfaces.

Measured in Chromium against the bytes `origin/main` serves, before and after.

  auth panel      radius 16 -> 14 with the field panel's padding
                  `clamp(14px, 1.8vw, 20px)`; its heading moved from a fixed 17px to
                  the card-title scale (measured 20px / -0.4px at 1440).
  lists           `.council-saved-list` and `.council-archive` had no surface at all
                  (border-radius 0px, no border, no padding — a bare <ul>). They are
                  now panels (14px radius, 20px padding, hairline border at 1440)
                  whose rows are separated by a hairline instead of each row being its
                  own bordered box: row 1 border-top 0px, row 2 1px.
  row buttons     were a 1px bordered grey chip; now borderless, transparent, weight
                  600, padding 8px 0, and still 44px tall through the shared floor.
  google link     hairline pill (999px, weight 600), 45.6px tall.

Fail-closed and the session contract are untouched and re-proven: signed out the
panel is shown with exactly one `.council-form` (the login form) and no tool
builder attached; submitting credentials reaches `POST /api/auth/password/login`
and, when the server does not confirm a session, the panel stays open with the
failure status and still zero builders. The Google link keeps
`/auth/google/start?return_to=%2Fapps%2Fcouncil%2F`.
"""
from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
CSS = (APP_ROOT / "static" / "council-app.css").read_text(encoding="utf-8")
HTML = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (APP_ROOT / "static" / "council-app.js").read_text(encoding="utf-8")


def block(selector: str) -> str:
    found = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.S)
    assert found, f"missing rule: {selector}"
    return found.group(1)


PANEL = ("border-radius: 14px", "padding: clamp(14px, 1.8vw, 20px)",
         "border: 1px solid var(--council-border)", "background: var(--council-surface)")


def test_the_sign_in_panel_uses_the_field_panel_surface():
    auth = block(".council-auth")
    for prop in PANEL:
        assert prop in auth, f"{prop} missing: {auth}"
    heading = block(".council-auth > h2")
    assert "font-size: clamp(17px, 1.39vw, 20px)" in heading, heading
    assert "letter-spacing: -0.02em" in heading, heading
    for sel in (".council-auth-lead", ".council-auth-status"):
        assert "word-break: keep-all" in block(sel), f"{sel} may break a Korean word"


def test_the_record_lists_are_panels_with_hairline_rows_not_stacks_of_boxes():
    for panel_sel, row_sel in ((".council-saved-list", ".council-saved-item"),
                               (".council-archive", ".council-archive-item")):
        panel = block(panel_sel)
        for prop in PANEL:
            assert prop in panel, f"{panel_sel}: {prop} missing: {panel}"
        assert "gap: 0" in block(panel_sel + " ul"), f"{panel_sel} rows must not be spaced boxes"
        assert "padding: 6px 0" in block(row_sel), row_sel
        sep = block(row_sel + " + " + row_sel)
        assert "border-top: 1px solid var(--council-border)" in sep, row_sel


def test_the_row_action_is_a_bare_line_and_keeps_the_shared_touch_floor():
    for sel in (".council-archive-item button", ".council-saved-item .council-saved-open"):
        row = block(sel)
        assert "border: 0" in row and "background: transparent" in row, sel
        assert "font-weight: 600" in row and "padding: 8px 0" in row, sel
        assert "border-radius" not in row, f"{sel} must not fight the floor block on radius"
    floor = re.search(r"\.council-archive-item button,[^{]*\{[^}]*min-height:\s*44px;[^}]*\}", CSS, re.S)
    assert floor, "the single 44px floor block (#6075) must still cover the row buttons"
    assert ".council-saved-item .council-saved-open" in floor.group(0)


def test_the_secondary_links_are_the_designs_hairline_pills():
    google = block(".council-google")
    assert "border-radius: 999px" in google, google
    assert "min-height: 44px" in google and "font-weight: 600" in google, google
    assert ".council-google" in CSS and ".council-badge-action" in CSS, "pinned selector names"


def test_the_gate_and_the_session_contract_are_still_the_ones_the_app_shipped():
    assert 'data.authenticated === true' in JS and "fail-closed" in JS
    assert 'href="/auth/google/start?return_to=%2Fapps%2Fcouncil%2F"' in HTML
    assert 'autocomplete="current-password"' in HTML, "the credential form must stay a credential form"
    assert "showAuthPanel" in JS and "hideAuthPanel" in JS
    for endpoint in ('"/api/auth/status"', '"/api/auth/password/login"', '"/api/chat"', '"/api/projects"'):
        assert endpoint in JS, endpoint
    assert not re.search(r'fetch\("/api/(?!chat|projects|auth/)', JS), "no new endpoint may appear"


def test_s4_added_no_asset_no_font_and_no_style_axis():
    assert "@font-face" not in CSS and "url(" not in CSS and "@import" not in CSS
    assert "data-style" not in CSS and "padiem-parliament-theme" not in CSS
    assert CSS.count("min-height: 44px") >= 6, CSS.count("min-height: 44px")
    code = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    code = "\n".join(l for l in code.splitlines() if "--focus-ring" not in l)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", code), "the surfaces stay on shared tokens"
