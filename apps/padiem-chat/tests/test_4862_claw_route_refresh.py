"""#4862: Claw survives a browser refresh because it is a real product route.

The Claw nav entry only mutated ``.app-shell[data-state]``; no URL path
recorded the destination, and the boot path restored ``#padiem-automation``
only. A reload therefore always landed on the Chat home.

Contract bound here (static, network-free, no Production mutation):

* Claw records a restorable fragment next to the existing Automation one.
* Leaving Claw (an explicit Chat switch) strips it again.
* Boot restores Claw from that fragment, and Automation keeps its own.
* An unknown fragment restores nothing and falls back to the Chat home.
* The fragment carries destination identity only. No user id, session token,
  conversation id or browser storage may join the routing state, so a reload
  after logout or an account switch cannot surface the previous user's
  conversation or device state.

The behavioural proof that a reload now keeps Claw is the recorded authenticated
browser run on Production; this file is the focused load-bearing regression for
the shipped source.
"""

from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"
AUTOMATION_HASH = "#padiem-automation"
CLAW_HASH = "#padiem-claw"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_route_hash_constants_are_single_source() -> None:
    src = _source()
    assert 'const AUTOMATION_ROUTE_HASH = "#padiem-automation";' in src
    assert f'const CLAW_ROUTE_HASH = "{CLAW_HASH}";' in src
    # The literal fragment may only appear in the constant declaration; every
    # other use has to go through the constant or the route drifts again.
    assert src.count('"#padiem-automation"') == 1
    assert src.count(f'"{CLAW_HASH}"') == 1


def test_entering_claw_records_the_route() -> None:
    src = _source()
    assert 'state === "claw" && !isClawRoute' in src
    assert "basePath + CLAW_ROUTE_HASH" in src


def test_leaving_claw_strips_the_route() -> None:
    src = _source()
    assert 'state !== "claw" && isClawRoute' in src
    # An explicit Chat switch flips the shell to "chat" in showConversation(),
    # which then runs setNavActive(); that is the strip path.
    assert 'shell.dataset.state = "chat";' in src


def test_boot_restores_both_routes() -> None:
    src = _source()
    assert "if (window.location.hash === AUTOMATION_ROUTE_HASH) openClawAutomation();" in src
    assert f"else if (window.location.hash === CLAW_ROUTE_HASH) openClawWorkspace();" in src
    # Automation must keep priority when both could never match, and the
    # automation restore must stay a strict equality test so an unknown or
    # tampered fragment restores nothing.
    assert src.count("openClawAutomation();") == 1
    assert src.count("openClawWorkspace();\n  automationDestinationReady") == 1


def test_route_carries_no_identity_or_storage() -> None:
    src = _source()
    assert "localStorage" not in src
    assert "sessionStorage" not in src
    # The fragment is a fixed destination name, never a composed identity.
    for banned in ("userId", "sessionToken", "conversationId", "deviceId"):
        assert f"CLAW_ROUTE_HASH + {banned}" not in src
