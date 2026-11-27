"""B54 Claw general composer: per-stage timing events (#7809).

Moved verbatim out of ``claw_general_routes``, which re-exports every name so existing
importers (and the tests that patch these names) keep working. Stage names and the
event shape are data the production telemetry reads: do not rename them.
"""

from __future__ import annotations

import time
from typing import Any

from .request_telemetry import emit_stage_event

# #5554: bounded per-stage timing for the Claw turn. The route already had a
# whole-request duration, which cannot say which of the (many) serial Engine,
# D1 and provider steps actually held the answer. These stage events use the
# existing request telemetry contract: a fixed stage name, a duration and the
# request id only - never the message, model response, session or file text.
CLAW_STAGE_ROUTE = "claw.route"
CLAW_STAGE_HISTORY = "claw.history"
CLAW_STAGE_SESSION = "claw.b54_session"
CLAW_STAGE_DRIVE = "claw.drive"
CLAW_STAGE_PC_CONTEXT = "claw.pc_context"
CLAW_STAGE_CATALOG = "claw.catalog"
CLAW_STAGE_QUOTA = "claw.quota"
CLAW_STAGE_JUDGEMENT = "claw.search_judgement"
CLAW_STAGE_ANSWER = "claw.answer"
CLAW_STAGE_PERSIST = "claw.persist"


def _claw_stage(stage: str, started: float, *, outcome: str = "ok") -> None:
    """Emit one bounded stage duration; telemetry never fails the turn."""
    try:
        emit_stage_event(
            stage=stage,
            outcome=outcome,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
    except Exception:
        pass


async def _claw_timed(stage: str, awaitable: Any) -> Any:
    """Await one preflight read and record its own duration."""
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        _claw_stage(stage, started)
