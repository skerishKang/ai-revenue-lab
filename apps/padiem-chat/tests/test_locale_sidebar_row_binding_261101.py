"""#6564: the locale layer must not address a sidebar row as if it were a demo card.

The auth/history browser QA (``.github/scripts/b62_auth_history_browser_qa.py``)
timed out in ``_wait_history_title`` because ``locale.js`` still carried the
document-wide bindings ``.recent-item:nth-of-type(1..3)`` from the recommended
-question list that #1735 removed. Every live sidebar row is built with that
same class (project row, conversation row, search hit, saved answer), so the
first row that happened to render before the boot locale paint was rewritten
with starter copy: the stored title disappeared from the screen and the starter
prompt landed in its ``data-prompt``. The same boot paint also re-entered the
app through ``padiem:localechange``, which opened a new session generation and
dropped the conversation read that was still in flight, leaving the loading
skeleton on screen until something else reloaded.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
OUTPUTS = (STATIC / "outputs.js").read_text(encoding="utf-8")
SEARCH = (STATIC / "conversation-search.js").read_text(encoding="utf-8")


def test_locale_copy_never_addresses_the_sidebar_row_class() -> None:
    # Premise: these are the rows that carry the class locale.js must not bind.
    for row in (
        'button.className = "recent-item project-item"',
        'button.className = "recent-item history-item"',
    ):
        assert row in APP
    assert 'row.className = "recent-item history-item conversation-search-hit"' in SEARCH
    assert 'button.className = "recent-item output-item"' in OUTPUTS
    # The class is live UI only, so no locale selector may name it at all.
    assert ".recent-item" not in LOCALE


def test_locale_bindings_address_only_the_surviving_starter_surface() -> None:
    # The demo prompt copy stays where the cards actually live: the starter grid.
    assert 'setPrompt(".starter:nth-child(2)", "starterLife", lang);' in LOCALE
    assert 'setPrompt("#writingStarterButton", "starterWriting", lang);' in LOCALE
    # #1735: the sidebar recommendation list is gone, so its title is gone too.
    assert '"#recentTitle"' not in LOCALE
    assert 'id="recentTitle"' not in INDEX


def test_localechange_reports_a_language_change_not_the_first_paint() -> None:
    # A paint that changes nothing must not re-enter the app boot; app.js answers
    # the event with applyAuthState(), which opens a new session generation.
    assert 'const previous = document.documentElement.lang;' in LOCALE
    assert 'if (previous !== locale) {' in LOCALE
    dispatch = 'window.dispatchEvent(new CustomEvent("padiem:localechange", { detail: { lang: locale } }));'
    assert LOCALE.count(dispatch) == 1
    guarded = LOCALE.split(dispatch)[0].rstrip().splitlines()[-1].strip()
    assert guarded == "if (previous !== locale) {"


def test_first_paint_no_change_assumption_is_declared_in_markup() -> None:
    # The guard above only skips the boot dispatch while the document already
    # declares the boot locale. A missing or different attribute must re-notify.
    assert re.match(r"(?i)^<!doctype html>\s*<html lang=\"ko\">", INDEX)


def test_the_boot_locale_still_switches_for_a_requested_language() -> None:
    # ?lang=en changes the declared locale, so the repaint signal still fires.
    assert "function getUrlLocale()" in LOCALE
    assert 'return normalizeLocale(new URLSearchParams(window.location.search).get("lang"));' in LOCALE
    assert "document.getElementById(\"languagePicker\")?.addEventListener" in LOCALE
