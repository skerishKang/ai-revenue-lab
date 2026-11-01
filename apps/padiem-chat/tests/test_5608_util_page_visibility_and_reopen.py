"""#5608: the util page must render, and reopened drafts must keep their body.

Two production defects were confirmed on chat.padiem.net before this change:

1. VISIBILITY -- ``#utilView`` was nested inside ``#clawWorkspace``, and
   ``showUtil()`` set ``hidden = true`` on every ``.claw-workspace`` except
   ``#utilView``. Because the ancestor itself is the one element that owns the
   panel, the util page measured 0x0 and Speech/SNS/Meeting were unreachable.
   The panel is now a top-level main-panel view owned by its own
   ``data-state="util"``, exactly like Calendar/Connectors/Automation/Meeting.

2026-11-01: the 의원3종 editors and their draft-reopen contract moved to
/apps/council/ with their own tests. What stays here is the util page shell:
it must be a top-level view owned by its own state.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"
APP_JS = ROOT / "static/app.js"



# --------------------------------------------------------------------------
# static structural contracts
# --------------------------------------------------------------------------


class _AncestorTracker(HTMLParser):
    """Records the open-tag chain that surrounds id="utilView"."""

    VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.util_view_parents: list[tuple[str, str | None]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if data.get("id") == "utilView" and self.util_view_parents is None:
            self.util_view_parents = [(t, a.get("id")) for t, a in self.stack]
        if tag not in self.VOID:
            self.stack.append((tag, data))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index]
                return


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_util_view_is_a_top_level_main_panel_view() -> None:
    tracker = _AncestorTracker()
    tracker.feed(_html())
    assert tracker.util_view_parents is not None, "#utilView is missing from index.html"
    parents = tracker.util_view_parents
    # The panel must not live inside the Claw workspace canvas anymore: that
    # ancestor is display:none outside the claw state, which is what hid the
    # whole util page in production.
    assert not any(parent_id == "clawWorkspace" for _, parent_id in parents)
    assert ("section", "clawWorkspace") not in parents
    assert parents[-1][0] == "main", "util page must be a direct child of <main>"


def test_util_view_visibility_is_owned_by_its_own_state() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-view { display: none;" in css
    assert '.app-shell[data-state="util"] .util-view { display: block' in css
    # The shared chat column and bottom composer must not render underneath
    # the util page, same convention as the other standalone views.
    assert '.app-shell[data-state="util"] .conversation' in css
    assert '.app-shell[data-state="util"] .composer-wrap { display: none !important; }' in css


def test_util_nav_enters_its_state_instead_of_hiding_its_own_ancestor() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert 'shell.dataset.state = "util"' in js
    # The production defect: the handler hid every .claw-workspace, including
    # the ancestor of #utilView.
    assert ".claw-workspace" not in js
    assert "if (utilView.hidden) showUtil()" not in js


def test_shell_state_sync_covers_the_util_state() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert 'state === "util") ? "false" : "page"' in js
    assert 'const utilNav = document.getElementById("utilNavButton");' in js
    assert 'utilNav.setAttribute("aria-current", state === "util" ? "page" : "false")' in js


def test_shipped_services_do_not_advertise_themselves_as_unavailable() -> None:
    html = _html()
    assert 'data-util="sns"' in html and "SNS 홍보" in html
    assert 'data-util="meeting"' in html and "회의정리·활동집" in html
    assert '<span class="util-soon">' not in html
    util_section = html[html.index('id="utilView"') : html.index('id="calendarView"')]
    assert "준비 중" not in util_section
