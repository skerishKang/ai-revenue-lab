"""B54 Claw general: public search evidence and journal helpers (#7809 3/13).

Existing definitions moved verbatim. Runtime contracts and telemetry event
names are unchanged; the entry module continues to re-export every name.
"""

from __future__ import annotations

import re
import time
from typing import Any

from starlette.requests import Request

from .claw_search_decision import (
    build_judgement_digest,
    evidence_agent,
    verdict_from_model,
)
from .request_telemetry import default_emitter


CLAW_PUBLIC_SEARCH_STATE_FLAG = "claw_web_search_enabled"
MAX_CLAW_SEARCH_SOURCES = 5
MAX_CLAW_SEARCH_SOURCE_TITLE_CHARS = 200
CLAW_GROUNDING_PREAMBLE_MARKER = "웹 근거 사용 규칙"

# #4469: the search lane had no per-turn evidence in the journal. One bounded
# line per completed stage replaces guesswork: fixed stage/outcome codes, a
# source count and a duration. The query, conversation digest, evidence text
# and every URL stay out of it, and telemetry never fails the turn.
CLAW_WEB_SEARCH_EVENT = "claw_web_search"
_SAFE_ERROR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _emit_claw_web_search(
    stage: str,
    outcome: str,
    *,
    duration_ms: float,
    sources: int = 0,
    error: str | None = None,
) -> None:
    """Emit one bounded journal line for a public web search stage."""

    if stage not in ("decide", "ground") or outcome not in ("ok", "skipped", "error"):
        return
    try:
        event: dict[str, object] = {
            "event": CLAW_WEB_SEARCH_EVENT,
            "stage": stage,
            "outcome": outcome,
            "sources": max(0, int(sources)),
            "duration_ms": max(0.0, round(float(duration_ms), 1)),
        }
        # Only an exception class name, never its message or any request text.
        if error is not None and _SAFE_ERROR_NAME.fullmatch(error):
            event["error"] = error
        default_emitter(event)
    except Exception:
        pass



def _project_search_sources(raw: Any) -> tuple[dict[str, str], ...] | None:
    """Verified provenance only: https URL, title and retrieval timestamp."""

    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    projected: list[dict[str, str]] = []
    for item in raw[:MAX_CLAW_SEARCH_SOURCES]:
        if not isinstance(item, dict):
            return None
        url = item.get("url")
        title = item.get("title")
        retrieved_at = item.get("retrieved_at")
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        if not isinstance(title, str) or not isinstance(retrieved_at, str):
            return None
        projected.append({
            "url": url[:2048],
            "title": title[:MAX_CLAW_SEARCH_SOURCE_TITLE_CHARS],
            "retrieved_at": retrieved_at[:64],
        })
    return tuple(projected)


async def _claw_public_search_grounding(
    request: Request, adapter: Any, messages: Any, *, model_id: str | None = None
) -> tuple[str | None, tuple[dict[str, str], ...]]:
    """Let the model decide, then reuse the existing Engine evidence operation once.

    The conversation digest stays inside Padiem. Only a query that survives this lane's
    own privacy and length checks may reach a provider, and grounding plus provenance
    stand or fall together. Any refusal degrades to the pre-search answer surface.
    """

    denied = (None, ())
    if getattr(request.app.state, CLAW_PUBLIC_SEARCH_STATE_FLAG, False) is not True:
        # The lane is off: today's quiet turn stays quiet, with no new log line.
        return denied
    decide_started = time.perf_counter()
    client = getattr(getattr(adapter, "_runner", None), "_client", None)
    judge = getattr(client, "search_judgement", None)
    search_evidence = getattr(client, "search_evidence", None)
    if not callable(judge) or not callable(search_evidence):
        _emit_claw_web_search(
            "decide", "skipped", duration_ms=_elapsed_ms(decide_started),
        )
        return denied
    digest = build_judgement_digest(messages)
    if digest is None:
        _emit_claw_web_search(
            "decide", "skipped", duration_ms=_elapsed_ms(decide_started),
        )
        return denied
    if not isinstance(model_id, str) or not model_id.strip():
        _emit_claw_web_search(
            "decide", "skipped", duration_ms=_elapsed_ms(decide_started),
        )
        return denied
    agent = evidence_agent(model_id)
    try:
        verdict = verdict_from_model(await judge(conversation=digest, agent=agent))
    except Exception as exc:
        _emit_claw_web_search(
            "decide", "error", duration_ms=_elapsed_ms(decide_started),
            error=type(exc).__name__,
        )
        return denied
    _emit_claw_web_search("decide", "ok", duration_ms=_elapsed_ms(decide_started))
    if not verdict.should_search:
        _emit_claw_web_search("ground", "skipped", duration_ms=0.0)
        return denied
    ground_started = time.perf_counter()
    try:
        evidence = await search_evidence(query=verdict.query, agent=agent)
    except Exception as exc:
        _emit_claw_web_search(
            "ground", "error", duration_ms=_elapsed_ms(ground_started),
            error=type(exc).__name__,
        )
        return denied
    if not isinstance(evidence, dict):
        _emit_claw_web_search(
            "ground", "error", duration_ms=_elapsed_ms(ground_started),
            error="invalid_evidence",
        )
        return denied
    sources = _project_search_sources(evidence.get("sources"))
    context = evidence.get("grounding_context")
    if sources is None:
        # Provenance that cannot be shown means the claim cannot be made either.
        _emit_claw_web_search(
            "ground", "error", duration_ms=_elapsed_ms(ground_started),
            error="invalid_evidence",
        )
        return denied
    # #4379/#6848: no PADIEM total on the evidence text. The model's own
    # registered window, applied where the registry is read, is the bound; this
    # lane still requires the shape and Core's untrusted-data preamble.
    if not isinstance(context, str) or not context.strip():
        _emit_claw_web_search(
            "ground", "error", duration_ms=_elapsed_ms(ground_started),
            error="invalid_evidence",
        )
        return denied
    if CLAW_GROUNDING_PREAMBLE_MARKER not in context:
        # Without Core's untrusted-data preamble the text would enter the prompt as
        # ordinary context, which is exactly the promotion this route forbids.
        _emit_claw_web_search(
            "ground", "error", duration_ms=_elapsed_ms(ground_started),
            error="invalid_evidence",
        )
        return denied
    _emit_claw_web_search(
        "ground", "ok", sources=len(sources), duration_ms=_elapsed_ms(ground_started),
    )
    return context, sources
