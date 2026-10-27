"""#5895: a PC turn that runs for minutes must read as work in progress.

The Node test proves the behaviour on the shipped bytes: the read-back stops
only when the stored answer lands or the caller moves on, and reopening the
conversation that started an unfinished PC run continues the same "working on
your PC — elapsed" display and lands the answer in that conversation. This
Python gate keeps that contract inside the normal pytest run and pins that the
client chose no give-up count, no deadline and no page size of its own.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_5895_pc_long_wait_progress.mjs"


def test_pc_long_wait_progress_contract_runs_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_read_back_has_no_client_side_give_up():
    recovery = (STATIC / "chat-pc-result-recovery.js").read_text(encoding="utf-8")

    # The attempt cap is caller-supplied only: with no bound the loop is open.
    assert "? details.maxAttempts : null;" in recovery
    assert "for (var attempt = 0; maxAttempts === null || attempt < maxAttempts; attempt += 1) {" in recovery
    assert "if (maxAttempts === null || attempt + 1 < maxAttempts) await sleep(intervalMs, signal);" in recovery
    # The pre-existing poll interval is reused, not re-chosen, and no deadline
    # or abort is introduced by this change.
    assert "? details.intervalMs : 2000;" in recovery
    assert "Date.now" not in recovery
    assert "deadline" not in recovery

    app = (STATIC / "app.js").read_text(encoding="utf-8")
    resume = app[app.index("async function resumeUnfinishedPcRun("):]
    resume = resume[:resume.index("\n  function renderStoredPcAnswer(")]
    for give_up in ("maxAttempts", "intervalMs", "setTimeout", "AbortController"):
        assert give_up not in resume, give_up
    # The wait is handed the caller's own refresh, so the elapsed time is the
    # shipped clock re-read on each poll rather than a second timer.
    assert "onPending: showWait," in resume
    assert "window.PadiemChatLifecycle?.elapsedClockText" in app


def test_resume_reads_the_owner_history_and_reopens_the_same_conversation():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    lookup = app[app.index("async function findUnfinishedPcRun("):]
    lookup = lookup[:lookup.index("async function resumeUnfinishedPcRun(")]

    # One read of the existing owner-scoped history, with no client page size
    # and no submit of any kind.
    assert 'fetch("/api/claw/runs", {' in lookup
    assert "limit=" not in lookup
    assert "method" not in lookup
    assert "window.PadiemChatPcRecovery?.validRunId?.(run.run_id) === true" in lookup
    assert '(run.status === "pending" || run.status === "running")' in lookup
    assert "run.session?.conversation_id === conversationId" in lookup

    resume = app[app.index("async function resumeUnfinishedPcRun("):]
    resume = resume[:resume.index("\n  function renderStoredPcAnswer(")]
    assert "resolvedPcRuns.has(unfinished.run_id)" in resume
    assert "resolvedPcRuns.add(unfinished.run_id);" in resume
    assert "await openSavedConversation(conversationId);" in resume
    assert 'if (result.kind !== "completed" || result.conversationId !== conversationId) return;' in resume

    # The only call site is the restored conversation itself, after its saved
    # messages are rendered and before the motion resume. It is fire-and-forget:
    # the restore does not wait on the unfinished run.
    restore = app[app.index("async function openSavedConversation("):]
    restore = restore[:restore.index("  // #4471:")]
    call = restore.index("void resumeUnfinishedPcRun(data.conversation.id);")
    assert restore.index("data.conversation.messages.forEach") < call
    assert call < restore.index("window.__padiemConversationMotion?.resume?.()")


def test_the_waiting_copy_names_work_in_progress_with_elapsed_time():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert locale.count('"pc-elapsed-note"') == 2
    assert '"pc-elapsed-note": "PC에서 작업 중 — 경과 {elapsed} · 완료되면 이 대화에 결과가 표시됩니다."' in locale
    assert '"pc-elapsed-note": "Working on your PC — elapsed {elapsed} · the answer will appear in this conversation when it completes."' in locale
    # The existing still-working note stays the fallback when no timestamp is
    # readable, and neither copy reads as a failure or an instruction.
    assert locale.count('"pc-processing-note"') == 2
    for key in ("pc-elapsed-note", "pc-processing-note"):
        for value in _values(locale, key):
            assert "실패" not in value and "오류" not in value, value
            assert "재시도" not in value and "retry" not in value.lower(), value


def _values(locale: str, key: str) -> list[str]:
    return re.findall(rf'"{key}": "([^"]*)"', locale)
