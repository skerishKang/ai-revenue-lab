"""Phase 2 work-view unification (#5028): five screens, one expression.

Additive scoped mirrors of the finished Chat/Claw design live in
standalone-views.css only. This pins their presence and the hard boundaries:
no index.html/locale/JS/DB/server-contract changes, no per-view feature or
permission edits, no new design system.
"""

from pathlib import Path

# #8060: shipped reads live in _support; assertions stay here.
from _support.first_screen_work_views_source import locale_source, read as _source_read


STATIC = Path(__file__).resolve().parents[1] / "static"


def _read(name: str) -> str:
    return _source_read(name)


FRAME = _read("standalone-views.css")


def test_work_view_titles_share_one_expression():
    # #7476 H1: the advanced-settings page joined the same title rule (settings
    # was the last page missing from this list).
    assert ".app-shell:is([data-state=\"meeting\"],[data-state=\"automation\"],[data-state=\"connectors\"],[data-state=\"util\"],[data-state=\"settings\"]) .standalone-view-title," in FRAME
    assert ".app-shell[data-state=\"calendar\"] .calendar-view-title," in FRAME
    assert ".app-shell[data-state=\"library\"] .library-view h2 {" in FRAME
    assert "font-size: clamp(26px, 4vw, 34px);" in FRAME
    assert "font-weight: 770;" in FRAME


def test_work_view_kickers_share_one_expression():
    assert ":is(.standalone-view-kicker,.calendar-view-kicker,.library-kicker) {" in FRAME
    assert "letter-spacing: .13em;" in FRAME
    assert "color: var(--accent);" in FRAME


def test_work_view_cards_use_shared_tokens():
    # #7187 R3 2차: the fallback went away — the token sheet always defines --line.
    assert ".library-item {\n  border-color: var(--line);" in FRAME
    assert ":is(.calendar-item,.calendar-record,.capability-card) {" in FRAME
    assert ".app-shell[data-state=\"automation\"] #clawAutomation {\n  border-color: var(--line);" in FRAME
    # #7187 반경 스케일(261115): the sheet names the token and the token file
    # pins 16px, so the painted panel radius is unchanged.
    assert '.app-shell[data-state="meeting"] .meeting-panel {\n  border-radius: var(--radius-md);' in FRAME
    assert "--radius-md: 16px;" in _read("padiem-tokens.css")


def test_work_view_primary_actions_are_solid_accent():
    assert ".app-shell[data-state=\"calendar\"] .calendar-record-submit," in FRAME
    assert ".app-shell[data-state=\"meeting\"] .meeting-controls #meetingStart {" in FRAME
    assert "color: var(--accent-contrast);" in FRAME


def test_work_view_state_text_uses_muted_token():
    assert ".app-shell[data-state=\"calendar\"] :is(.calendar-loading,.calendar-empty) {" in FRAME
    assert "color: var(--muted);" in FRAME
