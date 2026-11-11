"""#7459 - the account row must not flash a guest sign-in entry on first load.

The auth status is read after the shell renders. Until it answers, the account
row stays neutral: it keeps its space, but draws neither the sign-in button nor
an unconfirmed initial. Chat keeps no browser storage (the persistence audit
forbids it), so nothing is remembered between loads; a confirmed answer simply
replaces the placeholder.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
INDEX = (BASE / "index.html").read_text(encoding="utf-8")
AUTH = (BASE / "auth-session.js").read_text(encoding="utf-8")
CAPABILITIES = (BASE / "product-capabilities.js").read_text(encoding="utf-8")
CSS = (BASE / "sidebar-utility.css").read_text(encoding="utf-8")


def test_first_paint_claims_neither_a_guest_entry_nor_an_initial() -> None:
    container = re.search(r'<div class="sidebar-account[^"]*"[^>]*>', INDEX)
    assert container is not None
    assert 'data-account-state="pending"' in container.group(0)

    avatar = re.search(
        r'<span class="account-avatar" id="accountAvatar"[^>]*>([^<]*)</span>', INDEX
    )
    assert avatar is not None
    assert " hidden" in avatar.group(0)
    assert avatar.group(1).strip() == ""

    login = re.search(r'<button class="login-button" id="loginButton"[^>]*>', INDEX)
    assert login is not None
    assert " hidden" in login.group(0)
    assert 'id="loginPending"' in INDEX


def test_pending_projection_keeps_the_row_with_a_neutral_placeholder() -> None:
    assert 'if (state === "pending")' in CAPABILITIES
    assert (
        "return { accountHidden: false, loginHidden: true, loginDisabled: true, accountNameHidden: true };"
        in CAPABILITIES
    )
    assert "pendingLogin.hidden = !pending" in CAPABILITIES
    assert '[data-account-state="pending"] #loginPending' in CSS


def test_nothing_is_remembered_in_browser_storage() -> None:
    for source in (AUTH, CAPABILITIES):
        assert "localStorage" not in source
        assert "sessionStorage" not in source
        assert "lastSignedIn" not in source
        assert "account-hint" not in source and "accountHint" not in source
    assert "account-hint" not in CSS
