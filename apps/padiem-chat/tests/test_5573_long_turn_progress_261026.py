"""#5573 §7: a long turn has to look alive on both ends of the wire.

Three contracts, in the source-contract style the Chat UI already uses:

* the elapsed clock is started by the request and stopped by the terminal state,
  and nothing about it ends a turn;
* the two-minute sentence is one line of copy that appears only after two
  minutes of real waiting;
* the server keeps the stream writable with an SSE comment line, and the
  browser's own parser treats a comment line as transport, never as content.

No provider, B14 or Engine call happens here.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = Path(__file__).resolve().parents[1] / "app"
APPS = Path(__file__).resolve().parents[2]

LIFECYCLE = (STATIC / "message-lifecycle.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
STYLES = (STATIC / "capability-presentation.css").read_text(encoding="utf-8")
CHAT_ROUTES = (APP / "chat_routes.py").read_text(encoding="utf-8")
LIVE_EVENTS = (APP / "claw_live_events.py").read_text(encoding="utf-8")
ENGINE_SERVICE = (APPS / "padiem-ai-engine" / "app" / "orchestration_service.py").read_text(
    encoding="utf-8"
)

LONG_WAIT_COPY = "오래 걸리고 있어요 — 계속 진행 중입니다"


def _function_source(source: str, name: str) -> str:
    start = source.index(name)
    depth = source.index("{", start)
    end = source.index("}", depth)
    while source.count("{", start, end + 1) != source.count("}", start, end + 1):
        end = source.index("}", end + 1)
    return source[start:end + 1]


def _python_block(source: str, name: str) -> str:
    start = source.index(name)
    tail = source[start:]
    stop = re.search(r"\n(?=(?:async def |def |@|class ))", tail[1:])
    return tail[: stop.start() + 1] if stop else tail


def test_the_elapsed_clock_follows_the_request_and_never_ends_the_turn():
    # The clock is owned by the lifecycle module, and the card only renders it
    # while the turn is really live.
    assert "const turnStartedAt = new WeakMap();" in LIFECYCLE
    assert "function startTurnClock(article) {" in LIFECYCLE
    assert "function stopTurnClock(article) {" in LIFECYCLE
    assert "if (typeof setInterval === \"function\") {" in LIFECYCLE
    assert "turnClockTimers.set(article, setInterval(() => syncTurnClock(article), 1000));" in LIFECYCLE
    # A host without timers must still render, not throw: the card recomputes the
    # clock on every render, so the interval is only what makes it tick in between.
    assert "if (timer !== undefined && typeof clearInterval === \"function\") clearInterval(timer);" in LIFECYCLE
    assert 'elapsed.dataset.turnElapsed = "true";' in LIFECYCLE
    assert "if (view.live && !pcProgressByArticle.has(article)) {" in LIFECYCLE
    # A PC turn already carries the Engine's own elapsed label; the card must not
    # show two clocks for one run.
    pc_status = _function_source(LIFECYCLE, "function taskStatusFor(")
    assert 'Math.floor(pc.elapsed / 1000)' in pc_status
    # Started where the request starts, and stopped by the terminal state itself.
    streaming = _function_source(APP_JS, "async function requestStreamingAnswer(")
    completed = _function_source(APP_JS, "async function requestCompletedAnswer(")
    assert streaming.index("startTurnClock") < streaming.index("chatTransport.request")
    assert completed.index("startTurnClock") < completed.index("chatTransport.requestCompleted")
    assert "if (terminalCatalog[state]) stopTurnClock(article);" in LIFECYCLE
    # The clock ticks; it never aborts, rejects or counts down to a limit.
    assert "abort" not in _function_source(LIFECYCLE, "function startTurnClock(")
    assert "reject" not in _function_source(LIFECYCLE, "function syncTurnClock(")
    assert re.search(r"clearTimeout\(.*\)\s*;\s*//.*deadline", LIFECYCLE) is None
    assert "elapsedClockText" in LIFECYCLE.split("window.PadiemChatLifecycle")[1]


def test_the_two_minute_sentence_is_one_line_of_copy_and_starts_only_after_two_minutes():
    assert "const TURN_LONG_WAIT_MILLISECONDS = 120_000;" in LIFECYCLE
    assert LIFECYCLE.count(LONG_WAIT_COPY) == 1
    assert 'longWait.dataset.turnLongWait = "true";' in LIFECYCLE
    assert 'longWait.setAttribute("role", "status");' in LIFECYCLE
    assert "longWait.hidden = true;" in LIFECYCLE
    # The only thing that reveals it is measured waiting, never a promise about
    # when the turn will finish.
    assert "longWait.hidden = waited < TURN_LONG_WAIT_MILLISECONDS;" in LIFECYCLE
    assert "remaining" not in LIFECYCLE.lower()
    assert "timeout" not in _function_source(LIFECYCLE, "function syncTurnClock(").lower()
    assert ".capability-long-wait {" in STYLES and ".capability-elapsed {" in STYLES


def test_the_stream_stays_open_with_a_comment_line_and_no_deadline():
    assert 'SSE_KEEPALIVE = b": keepalive\\n\\n"' in CHAT_ROUTES
    assert "SSE_KEEPALIVE_SECONDS = 15.0" in CHAT_ROUTES
    body = _python_block(CHAT_ROUTES, "async def _stream_with_keepalive(")
    # The gap timer shields the real read, so a keepalive can never cancel it.
    assert "asyncio.wait_for(asyncio.shield(pending), timeout=interval)" in body
    assert "yield _KEEPALIVE_SENTINEL" in body
    assert "pending = None" in body
    assert "raise" in body  # an upstream failure still surfaces as a failure
    # #5479: any exit - including a close at the yield point - cancels the
    # read nobody will receive; the settled paths leave it done, a no-op.
    assert "finally:" in body
    assert "if pending is not None and not pending.done():" in body
    # The general lane is the one that needed it.
    assert "async for item in _stream_with_keepalive(stream):" in CHAT_ROUTES
    assert "yield SSE_KEEPALIVE" in CHAT_ROUTES
    # The PC turn already had a heartbeat: the Engine emits one and Chat relays it.
    assert "PC_STREAM_HEARTBEAT_SECONDS = 10.0" in ENGINE_SERVICE
    assert "heartbeat" in LIVE_EVENTS and 'if kind == "heartbeat":' in LIVE_EVENTS
    # A comment line is transport for the browser too: it is dropped, not shown.
    assert 'if (!line || line.startsWith(":")) return;' in TRANSPORT


def test_a_stream_closed_between_keepalives_cancels_the_read_nobody_receives():
    """#5479: a client that left closes the generator at its yield point.

    GeneratorExit is not a CancelledError, so the shielded upstream read
    needs its own guarantee: closing the stream cancels the read nobody
    will receive instead of leaving it running on the loop.
    """
    import asyncio

    from app.chat_routes import _KEEPALIVE_SENTINEL, _stream_with_keepalive

    state = {"cancelled": False}

    async def slow_upstream():
        try:
            yield "a"
            await asyncio.sleep(30)
            yield "b"
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def scenario():
        gen = _stream_with_keepalive(slow_upstream(), interval=1.0)
        assert await gen.__anext__() == "a"
        assert await gen.__anext__() is _KEEPALIVE_SENTINEL
        await gen.aclose()
        for _ in range(3):
            await asyncio.sleep(0)
        assert state["cancelled"] is True

    asyncio.run(scenario())


def test_the_roster_read_started_early_dies_with_the_turn_that_left_it():
    """#5479: the catalog read (#5614) is cancelled when the turn never awaits it.

    The read overlaps the PC work context, and the PC target checks may refuse
    the turn before the roster is ever evaluated - or the client may leave
    mid-flight. Either way the read ends with the turn instead of finishing
    for nobody; a task the evaluation awaited is done, where the guard is a
    no-op.
    """
    claw_general = (APP / "claw_general_routes.py").read_text(encoding="utf-8")
    start = claw_general.index(
        "catalog_task, catalog_unavailable = _start_selectable_model_read("
    )
    span = claw_general[start:claw_general.index("    live_requested = (")]
    assert span.count("    finally:") == 1
    assert "if catalog_task is not None and not catalog_task.done():" in span
    assert span.index("await catalog_task") < span.index("    finally:")
