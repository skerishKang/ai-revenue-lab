"""#5479 - a failed auth-status read must not remove the sign-in entry point.

**The defect this pins.** The Chat Python Worker can fail to answer *any* route
when the Cloudflare runtime loses the GIL while it initializes a Python
instance (``NoGilError: Attempted to use PyProxy when Python GIL not held``,
``cloudflare/workerd#6624``). The exception is raised inside
``preparePython`` -> ``initPyInstance``, before the Worker dispatches a route,
so ``/api/auth/status`` returns a 5xx exactly like every other route.

The client then collapsed three different situations into one session state:

1. the server answered and reported that the session store is not ready
   (``unavailable``),
2. the status request never produced an answer at all - a network failure, or
   the runtime failure above (``unreachable``),
3. the session really expired (``expired``).

and the ``unavailable`` presentation hid the account area *and* the login
button, then disabled the button. A transient backend failure therefore
removed the only way to sign in: the user was locked out until a page reload
happened to win the race.

**The contract.**

1. an unreadable session state keeps the account area and the login button
   visible and enabled,
2. the login button retries the status instead of being a dead end,
3. ``unavailable`` and ``unreachable`` are told apart, and only ``unreachable``
   claims the status could not be read.

The presentation rule is a table in ``static/app.js`` and the other
projections read that same table, so this test evaluates the shipped rule
itself instead of a copy of it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
APP = (BASE / "app.js").read_text(encoding="utf-8")
CAPABILITIES = (BASE / "product-capabilities.js").read_text(encoding="utf-8")
LOCALE = (BASE / "locale.js").read_text(encoding="utf-8")
OUTPUTS = (BASE / "outputs.js").read_text(encoding="utf-8")

#: Every session state the client can be in.
SESSION_STATES = (
    "pending",
    "signed_in",
    "guest",
    "expired",
    "unavailable",
    "unreachable",
)


def _presentation_table() -> dict:
    """Read the shipped presentation rule out of ``app.js``.

    The literal is written as strict JSON so the test evaluates the rule the
    browser runs, not a re-implementation of it.
    """
    start = APP.index("const SESSION_PRESENTATION = {")
    start = APP.index("{", start)
    depth = 0
    for index in range(start, len(APP)):
        char = APP[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                literal = APP[start : index + 1]
                break
    else:  # pragma: no cover - a malformed app.js fails every other test too
        raise AssertionError("SESSION_PRESENTATION literal is not closed")
    return json.loads(literal)


def _old_presentation(old_state: str) -> dict:
    """The pre-#5479 rule, kept only to prove the defect existed.

    The old client had no state for an unreadable status: a failed request was
    projected as "unavailable", which is what hid the button.
    """
    unavailable = old_state == "unavailable"
    return {
        "accountHidden": unavailable,
        "loginHidden": unavailable or old_state == "signed_in",
        "loginDisabled": unavailable,
        "accountNameHidden": unavailable,
    }


def test_the_shipped_presentation_rule_keeps_the_sign_in_entry_point_reachable():
    """The rule every projection reads keeps the button when the state is unread."""
    table = _presentation_table()
    assert set(table) == set(SESSION_STATES)
    row = table["unreachable"]
    assert row["accountHidden"] is False, "an unread state hid the account area"
    assert row["loginHidden"] is False, "an unread state hid the login button"
    assert row["loginDisabled"] is False, "an unread state disabled the login button"
    # A signed-in account still shows its profile instead of the sign-in button.
    assert table["signed_in"]["loginHidden"] is True
    # A guest and an expired session both need the sign-in button.
    for state in ("guest", "expired"):
        assert table[state]["loginHidden"] is False
        assert table[state]["loginDisabled"] is False
    # "pending" is "not read yet": nothing is claimed, so nothing is shown.
    assert table["pending"]["loginHidden"] is True
    assert table["pending"]["loginDisabled"] is True


def test_the_server_own_verdict_still_hides_the_entry_point():
    """``unavailable`` is the server's word and keeps the reviewed contract.

    When the server answers that the session store is not ready there is
    nothing to sign into, so the account area and the login button stay
    hidden. The account session browser QA pins exactly this, and this fix
    does not move it.
    """
    table = _presentation_table()
    assert table["unavailable"]["accountHidden"] is True
    assert table["unavailable"]["loginHidden"] is True
    assert table["unavailable"]["loginDisabled"] is True
    # Only the unread state differs from it.
    assert table["unreachable"]["loginHidden"] is False
    assert table["unreachable"]["loginDisabled"] is False


def test_an_unread_state_is_not_claimed_as_an_unknown_one():
    """``pending`` (not read yet) is not ``unreachable`` (read and failed)."""
    table = _presentation_table()
    assert table["pending"] != table["unreachable"]
    assert table["pending"]["loginHidden"] is True
    assert table["unreachable"]["loginHidden"] is False


def test_the_old_rule_really_did_remove_the_sign_in_entry_point():
    """Differential proof: the rule this replaces locked the user out."""
    # The old client projected a failed status read as "unavailable".
    old = _old_presentation("unavailable")
    assert old["loginHidden"] is True
    assert old["accountHidden"] is True
    assert old["loginDisabled"] is True
    new = _presentation_table()["unreachable"]
    assert new["loginHidden"] is False
    assert new["accountHidden"] is False
    assert new["loginDisabled"] is False


def test_the_rule_is_read_from_the_table_and_shared_with_the_other_projections():
    assert "SESSION_PRESENTATION[sessionState] || SESSION_PRESENTATION.unreachable" in APP
    assert "window.PadiemSessionPresentation = resolveSessionPresentation;" in APP
    assert "loginButton.hidden = presentation.loginHidden;" in APP
    assert "loginButton.disabled = presentation.loginDisabled;" in APP
    assert "accountContainer.hidden = presentation.accountHidden;" in APP
    # The second projection reads the same rule instead of its own copy.
    assert "window.PadiemSessionPresentation(state)" in CAPABILITIES
    assert "loginButton.hidden = shared.loginHidden;" in CAPABILITIES
    assert "loginButton.hidden = shared.loginHidden;" not in APP
    assert "loginButton.hidden = shared.loginHidden;" in CAPABILITIES
    # And the self-check compares the DOM against that same rule.
    assert "loginButton.hidden !== shared.loginHidden" in CAPABILITIES


def test_an_unreadable_status_is_a_distinct_session_state():
    """``unreachable`` is the client's word; ``unavailable`` stays the server's."""
    assert 'authState.status_reachable === false ? "unreachable" : "unavailable"' in APP
    assert "status_reachable: false" in APP
    # The flag is read in the session-state rule and in the retry handler, and
    # it is set in exactly one place: the failed status request.
    assert APP.count("status_reachable") == 3
    # The second projection reads the same distinction: no answer at all means
    # the request never loaded, which is "unreachable", not "unavailable" and
    # not the "pending" state it starts in.
    assert "function sessionStateForPresentation()" in CAPABILITIES
    assert 'return auth.statusReachable === false ? "unreachable" : "pending";' in CAPABILITIES
    assert "UNREACHABLE_AUTH" in CAPABILITIES
    assert "nextAuth = answer.ok ? projectAuth(answer.data) : UNREACHABLE_AUTH;" in CAPABILITIES
    assert '"pending", "unavailable", "unreachable", "guest", "signed_in", "expired"' in LOCALE


def test_the_login_button_retries_the_status_instead_of_being_a_dead_end():
    """Clicking the button while the state is unknown re-reads the status."""
    handler = APP.split('loginButton.addEventListener("click", async () => {', 1)[1]
    handler = handler.split("});", 1)[0]
    assert "if (!authState.ready) {" in handler
    assert "await loadAuthStatus();" in handler
    assert "setNote(" in handler
    # The old handler returned without doing anything at all.
    assert "if (!authState.ready) return;" not in handler


def test_the_two_failure_kinds_say_different_things():
    """A transient failure is not "login is not configured"."""
    ko, en = LOCALE.split("en: {", 1)
    for block in (ko, en):
        assert '"login-unavailable-title"' in block
        assert '"login-unreachable-title"' in block
    ko_unavailable = re.search(r'"login-unavailable-title":\s*"([^"]+)"', ko).group(1)
    ko_unreachable = re.search(r'"login-unreachable-title":\s*"([^"]+)"', ko).group(1)
    en_unavailable = re.search(r'"login-unavailable-title":\s*"([^"]+)"', en).group(1)
    en_unreachable = re.search(r'"login-unreachable-title":\s*"([^"]+)"', en).group(1)
    assert ko_unavailable != ko_unreachable
    assert en_unavailable != en_unreachable
    # The unavailable message keeps its own wording: the server said so.
    assert "not configured" in en_unavailable
    assert "설정되지 않았습니다" in ko_unavailable
    # The unreachable message says the status could not be read.
    assert "try again" in en_unreachable
    assert "다시 시도" in ko_unreachable
    # app.js asks for the unreachable message only for the unreachable state.
    assert 'uiT(sessionState === "unreachable" ? "login-unreachable-title" : "login-unavailable-title")' in APP
    # product-capabilities.js and outputs.js use the same two messages.
    assert 'state === "unreachable"' in CAPABILITIES
    assert "copy.unreachableTitle" in CAPABILITIES
    assert "copy.unavailableTitle" in CAPABILITIES
    assert '"login-unreachable-title"' in OUTPUTS


def test_the_account_identity_is_not_invented_for_an_unknown_state():
    """An unknown account shows no name; it does not show a guest identity."""
    table = _presentation_table()
    for state in ("unavailable", "unreachable"):
        assert table[state]["accountNameHidden"] is True
    assert table["guest"]["accountNameHidden"] is False


def test_the_session_contract_is_not_weakened():
    """The fix is presentation only: no check, cookie or hash rule changes."""
    assert "PBKDF2_ALGORITHM" in (BASE.parent / "app" / "password_auth.py").read_text(
        encoding="utf-8"
    )
    # The server still owns the session verdict.
    assert 'authState.authenticated === true' in APP
    assert "authenticated = ready && authState.authenticated === true" in APP
    # A failed read is still not an authenticated account.
    assert "authenticated: false" in APP
