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


# #4488: a broad `:is(.standalone-view-body)` selector is defeated by the older
# per-view overrides and never reaches Meeting/Calendar, whose gap lives on the
# view root. Each view therefore needs an explicit selector that is at least as
# specific as the legacy rule and appears later in the cascade.
_BODY_GAP_BLOCK = """\
.app-shell[data-state="meeting"] .meeting-view,
.app-shell[data-state="automation"] .automation-view .standalone-view-body,
.app-shell[data-state="connectors"] .connectors-view .standalone-view-body,
.app-shell[data-state="calendar"] .calendar-view,
.app-shell[data-state="library"] .library-view {
  gap: 12px;
}"""


def test_five_views_body_gap_wins_the_cascade():
    assert _BODY_GAP_BLOCK in FRAME
    # Equal-specificity legacy overrides must come earlier so the shared rule wins.
    block_at = FRAME.index(_BODY_GAP_BLOCK)
    for legacy in (
        '.app-shell[data-state="automation"] .automation-view .standalone-view-body { gap: 0; }',
        '.app-shell[data-state="connectors"] .connectors-view .standalone-view-body {',
    ):
        assert FRAME.index(legacy) < block_at


def test_five_views_share_error_ink():
    assert ".app-shell[data-state=\"calendar\"] .calendar-error," in FRAME
    # 작업함 제거(#7109)로 clawInboxError 선택자는 삭제 —
    # calendar·connectors의 에러 잉크 공유 계약은 그대로 유지된다.
    assert ".app-shell[data-state=\"connectors\"] #connectorsError {" in FRAME
    # #7187 R3 9차: 다섯 테마 모두 --danger를 정의하므로 fallback은 지웠다.
    assert "color: var(--danger);" in FRAME
