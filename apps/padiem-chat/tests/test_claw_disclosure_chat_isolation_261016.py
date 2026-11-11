"""Claw-only execution and memory disclosure never follow a Chat turn."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
#7216 R5 step 5a/A2: showConversation and runs-read/memory moved into modules.
CONV = (STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")
RUN_HISTORY = (STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")
MEM = (STATIC / "chat-memory-module.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def test_show_chat_resets_stale_claw_disclosures_without_destroying_runs():
    start = CONV.index("function showConversation(")
    end = CONV.index("function addUserMessage(", start)
    chunk = CONV[start:end]
    assert 'deps.shell.dataset.state = "chat";' in chunk
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
    assert '/api/claw/runs?limit=' in RUN_HISTORY
    assert 'deps.shell.dataset.state === "claw"' in MEM
    assert 'deps.authState.authenticated === true' in MEM


def test_7459_chat_state_never_reexposes_claw_panels():
    """Chat 대화 중(empty-state 숨김)에도 패널을 display:block으로 되살리면 안 된다."""
    assert '.app-shell[data-state="chat"] .empty-state[hidden] ~' not in CSS
