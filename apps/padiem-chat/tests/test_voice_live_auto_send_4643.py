"""#4643: Mode 2/3/4 submit one confirmed turn per utterance.

The behavioural proof is the browser journey in
``browser_voice_live_auto_send_4643.py``: a confirmed Live turn is submitted
exactly once while the microphone stays open, and Mode 1 never submits
anything. A bare ``browser_*.py`` file is not collected by pytest, so this
module carries the part of the contract that the offline lanes can hold: the
composer's accepted-turn event and the mode gate that must not drop it.
"""

from __future__ import annotations

from _support import composer_voice_source as sheets

COMPOSER_JS = sheets.voice_composer_js()
MENU_JS = sheets.voice_ui_menu_js()
BROWSER_JOURNEY = sheets.voice_browser_journey_path()


def test_the_composer_accepts_a_confirmed_turn_while_the_run_is_open() -> None:
    source = COMPOSER_JS
    # The accepted turn may arrive while the run is open (Mode 2/3/4) or while
    # it is stopping (the chunk path).
    assert "isSameRun(myRun) && stoppingRun !== myRun" in source, (
        "the composer must accept a confirmed turn of the run that is still open"
    )
    # The event itself carries no send: the mode gate decides.
    assert "padiem:voice-accepted-turn" in source
    assert "requestSubmit" not in source


def test_the_mode_gate_does_not_drop_an_accepted_turn_because_the_run_is_open() -> None:
    source = MENU_JS
    assert "padiem:voice-accepted-turn" in source
    # The run authority is the generation/session pair, not the run state: an
    # open microphone run must not swallow its own confirmed turn.
    assert "c.active ||" not in source, (
        "the mode gate must not drop an accepted turn while the run is open"
    )
    assert "c.generation !== info.composerGeneration" in source
    assert "c.sessionToken !== info.sessionToken" in source
    # The basic mode never submits: the gate is the mode, not the run state.
    assert 'if (st.mode !== "live") return;' in source


def test_the_browser_journey_exists() -> None:
    assert BROWSER_JOURNEY.exists(), (
        "the browser journey that proves the per-utterance auto-send must exist"
    )
    source = sheets.voice_browser_journey()
    assert "test_a_confirmed_turn_is_submitted_once_while_the_microphone_stays_open" in source
    assert "test_mode1_never_submits_anything" in source
