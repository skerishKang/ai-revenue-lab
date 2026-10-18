"""COM1 LOCAL #4488 follow-up: one header/spacing/state contract for five views.

CSS-only change in standalone-views.css. No index.html, locale, JS, DB or
server-contract edits. Real selectors only: existing error/status IDs and
page bodies.
"""

from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


FRAME = _read("standalone-views.css")


def test_five_views_share_header_contract():
    assert ".standalone-view-header {\n  align-items: center;\n  min-height: 44px;" in FRAME


def test_five_views_share_body_spacing():
    assert ".app-shell[data-state=\"library\"] .library-view {\n  gap: 12px;" in FRAME


def test_five_views_share_error_ink():
    assert ".app-shell[data-state=\"calendar\"] .calendar-error," in FRAME
    assert ".app-shell[data-state=\"automation\"] #clawInboxError," in FRAME
    assert ".app-shell[data-state=\"connectors\"] #connectorsError {" in FRAME
    assert "color: var(--danger, #b42318);" in FRAME
