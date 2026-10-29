"""#6127: a server that cannot answer is not a visitor who is not signed in.

Production intermittently returns HTTP 500 on `GET /api/auth/status` (measured 6 of 16
sequential requests, and 43 of 136 rows in a bounded worker tail, with
`NoGilError: Attempted to use PyProxy when Python GIL not held` at cpuTime 0-1ms -
so the throw is at request entry, not CPU exhaustion). The council entry page read
that 500 exactly like a signed-out `200`, so a logged-in user was told to log in.

These tests run the SHIPPED `static/council-app.js` in the Node harness against four
different answers from the same endpoint. The gate must stay closed in every case;
only the report to the user may differ.
"""

from __future__ import annotations

from _council_module import run

FAILURE_MESSAGE = "로그인 상태 확인에 실패했습니다. 다시 시도해 주세요."
SIGNED_OUT_BADGE = "로그인 필요"
UNAVAILABLE_BADGE = "로그인 확인 실패"


def case(name: str) -> dict:
    found = [row for row in run("auth_states")["cases"] if row["name"] == name]
    assert len(found) == 1, name
    return found[0]


def test_the_gate_stays_closed_in_every_answer() -> None:
    """The part that must not change: nothing is attached unless the server says so."""
    for name in ("signed_out_200", "forbidden_401", "fault_500", "network_throw",
                 "ok_200_unparseable"):
        row = case(name)
        assert row["initSignedIn"] is False, name
        assert row["anyToolBuilt"] is False, name
        assert row["panelHidden"] is False, name
        # the way to obtain a session must survive a server fault
        assert row["loginActionHidden"] is False, name


def test_a_server_fault_is_reported_as_a_fault_not_as_a_logout() -> None:
    for name in ("fault_500", "network_throw", "ok_200_unparseable"):
        row = case(name)
        assert row["initUnavailable"] is True, name
        assert row["badge"] == UNAVAILABLE_BADGE, name
        assert row["status"] == FAILURE_MESSAGE, name


def test_a_real_verdict_is_reported_quietly_as_signed_out() -> None:
    # 200 {authenticated:false} and 401 are both answers ABOUT the visitor, so they
    # must not raise the server-fault wording - and must not claim a fault either.
    for name in ("signed_out_200", "forbidden_401"):
        row = case(name)
        assert row["initUnavailable"] is False, name
        assert row["badge"] == SIGNED_OUT_BADGE, name
        assert row["status"] == "", name


def test_the_two_verdicts_and_the_two_faults_are_each_distinguishable() -> None:
    assert case("signed_out_200")["badge"] != case("fault_500")["badge"]
    assert case("signed_out_200")["status"] != case("fault_500")["status"]
    assert case("forbidden_401")["badge"] == case("signed_out_200")["badge"], \
        "401 is a not-allowed verdict, not a server fault"
    assert case("network_throw")["badge"] == case("fault_500")["badge"], \
        "a request that never answered is the same state as a 5xx"


def test_the_fault_wording_reuses_the_message_the_login_path_already_uses() -> None:
    # No new copy: enterSignedIn() has said this since #5942 when a status read
    # failed after a login attempt. The two paths added for #6127 - the initial
    # read and picking a tool while the state is unknown - use the same words,
    # so the app can never tell one user two different stories.
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "static" / "council-app.js").read_text(encoding="utf-8")
    assert js.count(FAILURE_MESSAGE) == 3, "post-login read + initial read + tool-pick read"


def test_the_status_read_is_not_cached() -> None:
    """A 500 must not be replayed from the HTTP cache on the next page load."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "static" / "council-app.js").read_text(encoding="utf-8")
    call = js[js.index('fetch("/api/auth/status"'):]
    head = call[:call.index("});")]
    assert 'cache: "no-store"' in head, head
    assert "fail-closed" in js
