"""Claw-only execution and memory disclosure never follow a Chat turn."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def test_show_chat_resets_stale_claw_disclosures_without_destroying_runs():
    start = APP.index("function showConversation(")
    end = APP.index("function addUserMessage(", start)
    chunk = APP[start:end]
    assert 'shell.dataset.state = "chat";' in chunk
    for identity in ("clawRunHistoryDisclosure", "clawRunHistory",
                     "clawApprovedDisclosure", "clawApprovedMemory"):
        assert identity in chunk
    assert "node.hidden = true;" in chunk
    assert 'node.tagName === "DETAILS"' in chunk
    assert "replaceChildren()" not in chunk


def test_claw_disclosures_are_css_hidden_outside_claw_state():
    assert "CLAW_DISCLOSURE_CHAT_ISOLATION_20261016" in CSS
    assert '.app-shell:not([data-state="claw"])' in CSS
    assert "#clawRunHistoryDisclosure" in CSS
    assert "#clawApprovedDisclosure" in CSS
    assert "display: none !important" in CSS


def test_claw_owner_scoped_history_contract_survives():
    assert '/api/claw/runs?limit=' in APP
    assert 'shell.dataset.state === "claw"' in APP
    assert 'authState.authenticated === true' in APP
