"""Phase 1 turn QA unification: one Chat/Claw question-answer expression.

Extends #4991 (turn identity) to the remaining turn/state surfaces without
duplicating renderers or forking lane geometry:

* shared gates use `:is([data-state="chat"],[data-state="claw"])` so the same
  stored row renders identically in both states;
* lane tokens (`--padiem-chat-inner-gutter`, conversation width/padding) stay
  Chat-only per the recorded 2026-10-14 decision;
* the manual Claw result card keeps its DOM/execution contract and only mirrors
  the unified answer typography through a thin adapter.
"""

from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


EDITORIAL = _read("padiem-editorial.css")
POLISH = _read("padiem-chat-ui-polish.css")
GUTTER = _read("padiem-glass-gutter-alignment.css")
THEMES = _read("padiem-themes.css")
RICH = _read("padiem-rich.css")
GLASS = _read("padiem-glass.css")
POLISH_ADAPTER = _read("interaction-polish.css")

SHARED = ':is([data-state="chat"],[data-state="claw"])'

# (source, selector fragment that must carry the shared gate)
SHARED_TURN_SURFACES = [
    (EDITORIAL, f"{SHARED} .message {{"),
    (EDITORIAL, f"{SHARED} .assistant-message {{"),
    (EDITORIAL, f"{SHARED} .assistant-message::before {{"),
    (EDITORIAL, f"{SHARED} .assistant-message:last-child::before {{"),
    (EDITORIAL, f"{SHARED} .assistant-avatar {{"),
    (EDITORIAL, f"{SHARED} .assistant-meta {{"),
    (EDITORIAL, f"{SHARED} .assistant-content > p {{"),
    (EDITORIAL, f"{SHARED} .typing {{"),
    (EDITORIAL, f"{SHARED} .typing i {{"),
    (EDITORIAL, f"{SHARED} .typing i:nth-child(2) {{"),
    (EDITORIAL, f"{SHARED} .typing i:nth-child(3) {{"),
    (POLISH, f"{SHARED} .error-box {{"),
    (POLISH, f"{SHARED} .retry-button {{"),
    (GUTTER, f"{SHARED} .error-box {{"),
    (THEMES, f"{SHARED} .answer-action,"),
    (RICH, f"{SHARED} .message-list {{"),
    (RICH, f"{SHARED} .user-message {{"),
    (RICH, f"{SHARED} .message-bubble {{"),
    (RICH, f"{SHARED} .assistant-message {{"),
    (RICH, f"{SHARED} .assistant-message::before {{"),
    (RICH, f"{SHARED} .assistant-avatar {{"),
]


def test_turn_and_state_surfaces_are_shared():
    for source, selector in SHARED_TURN_SURFACES:
        assert selector in source, f"turn surface drifted back to Chat-only: {selector}"


def test_light_and_home_answer_ink_is_shared():
    assert "html[data-theme=\"light\"] .app-shell[data-state=\"chat\"] .answer-action," not in THEMES
    assert "html[data-theme=\"padiem-home\"] .app-shell[data-state=\"chat\"] .answer-action," not in THEMES


def test_lane_geometry_stays_chat_only():
    # Width/padding lanes and gutter-calc recovery rules must not be widened.
    assert ".app-shell[data-state=\"chat\"] .message-list {\n  width: min(860px, 100%);" in EDITORIAL
    assert "--padiem-chat-inner-gutter" in GUTTER
    assert f"{SHARED} .assistant-content > .rich-response {{" not in GUTTER
    assert f"{SHARED} .assistant-content > .error-box {{" not in GUTTER


def test_no_claw_only_turn_overrides():
    # Unification happens through the shared gate, not a second Claw fork.
    for source in (EDITORIAL, POLISH, GUTTER, RICH):
        assert '[data-state="claw"] .assistant-content' not in source
        assert '[data-state="claw"] .assistant-message' not in source
        assert '[data-state="claw"] .assistant-meta' not in source


def test_manual_result_card_mirrors_unified_answer_metrics():
    assert "font-size: 17px;" in POLISH_ADAPTER
    assert "line-height: 1.76;" in POLISH_ADAPTER
    assert ".conversation .claw-request-echo .message-bubble {" in POLISH_ADAPTER
    assert "color: #111a22;" in POLISH_ADAPTER
    assert "html[data-theme=\"padiem-glass\"] .claw-result-body { color: #111a22; }" in GLASS
