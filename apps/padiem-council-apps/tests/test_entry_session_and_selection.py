"""#5942: the entry page logs the visitor in, and the card they chose is waiting.

The behavioural harness runs the SHIPPED `static/council-app.js` against a
recording fake of the EXISTING endpoints. Nothing here re-implements a login: the
assertions are that the page uses the server's own credential contract, keeps the
fail-closed gate while signed out, and carries the chosen tool across the login,
a refresh and a lapsed session.
"""

from __future__ import annotations

from _council_module import run

STATUS_PENDING_MESSAGE = "로그인이 필요합니다. 선택한 업무(SNS 홍보)는 로그인 후 이 화면에서 바로 이어집니다."
STATUS_EXPIRED_MESSAGE = "세션이 만료되었습니다. 다시 로그인하면 이 화면에서 이어나갑니다."


def phase(observation: dict, name: str) -> dict:
    found = [row for row in observation["phases"] if row["name"] == name]
    assert len(found) == 1, name
    return found[0]


def test_signed_out_visit_offers_the_in_page_login_and_builds_no_tool() -> None:
    signed_out = phase(run("auth"), "signed_out")
    # The gate itself is unchanged: no builder is attached until the server says
    # this cookie is authenticated.
    assert signed_out["initSignedIn"] is False
    assert signed_out["anyToolBuilt"] is False
    assert signed_out["badge"] == "로그인 필요"
    # ...and the login is offered HERE, with the server's own method list.
    assert signed_out["panelHidden"] is True
    assert signed_out["actionHidden"] is True
    assert signed_out["googleHidden"] is False


def test_choosing_a_card_while_signed_out_remembers_the_tool_without_calling_api() -> None:
    observation = run("auth")
    signed_out = phase(observation, "signed_out")
    picked = phase(observation, "pick_while_signed_out")
    assert picked["state"]["pending"] == "sns"
    assert picked["state"]["signedIn"] is False
    assert picked["anyToolBuilt"] is False
    assert picked["snsBodyHidden"] is True
    assert picked["status"] == STATUS_PENDING_MESSAGE
    # Choosing a card asked for a login; it did not reach tool data. The status
    # probe appears twice because the module also runs once at load, which is a
    # harness artifact of calling init() explicitly.
    assert set(signed_out["requests"]) == {"GET /api/auth/status"}
    assert set(picked["requests"]) == {"GET /api/auth/status"}
    failed = phase(observation, "failed_login")
    assert set(failed["requests"]) == {"GET /api/auth/status", "POST /api/auth/password/login"}


def test_a_failed_credential_shows_the_servers_single_non_disclosing_message() -> None:
    failed = phase(run("auth"), "failed_login")
    assert failed["status"] == "이메일 또는 비밀번호가 올바르지 않습니다."
    assert failed["passwordCleared"] is True
    assert failed["state"]["signedIn"] is False
    assert failed["anyToolBuilt"] is False
    assert failed["panelHidden"] is False


def test_the_in_page_login_continues_into_the_tool_the_visitor_picked() -> None:
    signed_in = phase(run("auth"), "signed_in_continues")
    assert signed_in["state"] == {
        "signedIn": True, "built": True, "bound": True, "selected": "sns", "pending": None,
    }
    assert signed_in["badge"] == "로그인됨"
    assert signed_in["panelHidden"] is True
    assert signed_in["status"] == ""
    # All three tools are hosted, exactly one panel is open.
    assert signed_in["toolsBuilt"] == "111"
    assert signed_in["selectedHidden"] is False
    assert signed_in["otherHidden"] is True
    assert signed_in["ariaExpanded"] == "true"
    assert signed_in["activeClass"] is True
    assert signed_in["otherActiveClass"] is False


def test_a_lapsed_session_returns_to_the_login_panel_and_keeps_the_selection() -> None:
    lapsed = phase(run("auth"), "session_lapsed")
    assert lapsed["state"]["signedIn"] is False
    assert lapsed["state"]["selected"] == "sns"
    assert lapsed["panelHidden"] is False
    assert lapsed["badge"] == "로그인 필요"
    assert lapsed["status"] == STATUS_EXPIRED_MESSAGE
    # The failure is said on the notice line, not painted into the draft area,
    # and the save button is blocked until a generation succeeds.
    assert lapsed["notice"] == "생성 실패: 로그인이 필요합니다. 다시 로그인해 주세요."
    assert lapsed["noticeTone"] == "error"
    assert lapsed["draftKept"] == ""
    assert lapsed["saveDisabled"] is True


def test_one_card_click_opens_exactly_one_tool_and_the_next_closes_it() -> None:
    steps = {row["label"]: row for row in run("selection")["steps"]}
    init = steps["init"]
    assert init["signedIn"] is True and init["built"] is True
    assert init["selected"] is None
    assert (init["speechHidden"], init["snsHidden"], init["meetingHidden"]) == (True, True, True)
    # One handler per card: a second binding would toggle twice inside one click
    # and the panel would never open for the user.
    assert init["speechClickHandlers"] == 1

    opened = steps["open_speech"]
    assert opened["selected"] == "speech"
    assert opened["speechHidden"] is False
    assert (opened["snsHidden"], opened["meetingHidden"]) == (True, True)
    assert opened["speechExpanded"] == "true"
    assert opened["activeCards"] == 1

    closed = steps["close_speech"]
    assert closed["selected"] is None
    assert (closed["speechHidden"], closed["snsHidden"], closed["meetingHidden"]) == (True, True, True)
    assert closed["speechExpanded"] == "false"

    assert steps["open_meeting"]["selected"] == "meeting"
    switched = steps["switch_to_sns"]
    assert switched["selected"] == "sns"
    assert switched["snsHidden"] is False
    assert switched["meetingHidden"] is True
    assert switched["speechHidden"] is True
    assert switched["activeCards"] == 1
    # Selecting a tool is a UI state: no API call beyond what init already made.
    # Opening a tool also reads the PC pairing once (the calm "connect your
    # computer" guidance); selecting never writes anything.
    assert set(run("selection")["endpoints"]) <= {
        "GET /api/auth/status", "GET /api/projects", "GET /api/projects/p1/files",
        "GET /api/pc/pairings",
    }


def test_the_entry_css_holds_every_control_at_the_chat_touch_floor() -> None:
    """Chat's own rule is 44px for anything a finger hits (util-menu.css
    .util-tab/.util-generate). The card chooser, the login form and the tool
    actions are stated here so a later edit cannot shrink them back."""
    from pathlib import Path

    css = Path(__file__).resolve().parents[1].joinpath("static/council-app.css").read_text(encoding="utf-8")
    for selector in (
        ".council-card-select",
        ".council-form input,",
        ".council-generate,",
        ".council-badge-action",
        ".council-google",
    ):
        assert selector in css, selector
    # The floor is declared for the form fields, both primary buttons, the header
    # action and the Google link, and for the small controls in one place.
    assert css.count("min-height: 44px") >= 6, css.count("min-height: 44px")
    assert ":focus-visible" in css, "a keyboard user must see where the focus is"
    for breakpoint in ("max-width: 900px", "max-width: 390px", "min-width: 1200px"):
        assert breakpoint in css, breakpoint
    # One open tool takes the row, so a long textarea is not squeezed into a column.
    active = css[css.index(".council-card.active"):]
    assert "grid-column: 1 / -1" in active[:400]


def test_the_entry_borrows_chat_tokens_instead_of_restating_them() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "static" / "council-app.css").read_text(encoding="utf-8")
    assert '/padiem-themes.css' in html, "the theme authority stays Chat's"
    assert "--council-bg: var(--page-bg, var(--bg))" in css
    assert "--council-accent: var(--accent)" in css
    # No colour literal may survive: a hard hex here would not follow the theme.
    assert not any(token in css for token in ("#fff", "#ffffff", "#1c1e26", "#3556c7")), "colour literal"


def test_the_login_uses_the_existing_credential_contract_and_nothing_more() -> None:
    observation = run("auth")
    assert set(observation["endpoints"]) == {
        "GET /api/auth/status",
        "POST /api/auth/password/login",
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/chat/stream",
        "GET /api/pc/pairings",
    }
    # identifier + password: the shipped login body. No token, no provider field,
    # no second session shape.
    assert observation["loginAttemptKeys"]
    assert set(map(tuple, observation["loginAttemptKeys"])) == {("identifier", "password")}
    assert observation["alerts"] == []
    assert observation["pageErrors"] == []


def test_selection_returns_from_the_url_or_host_storage_and_refuses_anything_else() -> None:
    results = {row["label"]: row for row in run("auth_routing")["results"]}
    assert results["hash"]["selected"] == "meeting"
    assert results["hash"]["openBody"] == "councilMeetingBody"
    assert results["bare_hash"]["selected"] == "sns"
    assert results["remembered"]["selected"] == "speech"
    # A fragment or a stored value that names nothing in the tool set opens nothing:
    # the selection can never be steered to another surface.
    assert results["unknown_hash"]["selected"] is None
    assert results["unknown_hash"]["openBody"] == ""
    assert results["hostile_stored"]["selected"] is None
    assert run("auth_routing")["pageErrors"] == []
