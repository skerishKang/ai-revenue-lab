"""#4469: the Claw public web search lane must leave one bounded journal line.

Before this, the lane logged nothing per turn: success stages were never emitted
and every refusal was folded into "no search" silently. These tests pin the
event contract (fixed stage/outcome codes, source count, duration) and — just as
important — that no query, digest, evidence text, URL or exception message can
reach the log.

The emitter is swapped for a recorder here; a separate test drives the real
emitter through a handler attached to the logger, so the wiring is covered
without depending on the process-wide logging configuration.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app import claw_general_routes
from app.claw_general_routes import _claw_public_search_grounding

LOGGER_NAME = "padiem_chat.request"
QUERY = "2026 광주 청년창업 지원사업 신청기간 모집 공고"
USER_TEXT = "올해도 신청할 수 있어?"
FENCED = "웹 근거 사용 규칙:\n[1] {\"title\": \"공고\", \"snippet\": \"2026년 신청 기간\"}"
SOURCE = {
    "url": "https://example.org/notice",
    "title": "2026년 공고",
    "retrieved_at": "2026-10-15T00:00:00Z",
}
NO_SEARCH = {"needs_search": False, "reason": "stable_reference"}
NEEDS_SEARCH = {"needs_search": True, "query": QUERY, "reason": "volatile_business_fact"}
BASE_KEYS = {"event", "stage", "outcome", "sources", "duration_ms"}


@pytest.fixture
def recorded(monkeypatch):
    events: list[dict[str, object]] = []
    monkeypatch.setattr(claw_general_routes, "default_emitter", events.append)
    return events


def _request(*, enabled: bool = True):
    state = SimpleNamespace()
    if enabled:
        state.claw_web_search_enabled = True
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _adapter(client):
    return SimpleNamespace(_runner=SimpleNamespace(_client=client))


class _Client:
    """Stands in for the two Engine operations; nothing leaves this process."""

    def __init__(
        self,
        *,
        verdict=None,
        evidence=None,
        judge_error: BaseException | None = None,
        evidence_error: BaseException | None = None,
    ):
        self.verdict = NEEDS_SEARCH if verdict is None else verdict
        self.evidence = (
            {"sources": [SOURCE], "grounding_context": FENCED}
            if evidence is None else evidence
        )
        self.judge_error = judge_error
        self.evidence_error = evidence_error

    async def search_judgement(self, *, conversation, agent):
        if self.judge_error is not None:
            raise self.judge_error
        return self.verdict

    async def search_evidence(self, *, query, agent):
        if self.evidence_error is not None:
            raise self.evidence_error
        return self.evidence


def _run(client, *, enabled: bool = True, model_id: str | None = "test/selected-model"):
    return asyncio.run(
        _claw_public_search_grounding(
            _request(enabled=enabled),
            _adapter(client),
            [{"role": "user", "content": USER_TEXT}],
            model_id=model_id,
        )
    )


def test_the_switch_off_stays_as_quiet_as_today(recorded):
    _run(_Client(), enabled=False)

    assert recorded == []


def test_a_no_search_verdict_logs_decide_ok_then_ground_skipped(recorded):
    context, sources = _run(_Client(verdict=NO_SEARCH))

    assert (context, sources) == (None, ())
    assert [(event["stage"], event["outcome"]) for event in recorded] == [
        ("decide", "ok"),
        ("ground", "skipped"),
    ]
    for event in recorded:
        assert set(event) == BASE_KEYS
        assert event["sources"] == 0
        assert event["duration_ms"] >= 0.0


def test_a_successful_search_logs_the_stage_and_source_count(recorded):
    context, sources = _run(_Client())

    assert context == FENCED
    assert sources == (
        {"url": SOURCE["url"], "title": SOURCE["title"], "retrieved_at": SOURCE["retrieved_at"]},
    )
    assert [(event["stage"], event["outcome"]) for event in recorded] == [
        ("decide", "ok"),
        ("ground", "ok"),
    ]
    assert recorded[1]["sources"] == 1
    # Not one byte of the query, the conversation, the evidence or the URL.
    for event in recorded:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        assert QUERY not in line
        assert USER_TEXT not in line
        assert SOURCE["url"] not in line
        assert FENCED not in line


def test_a_judge_failure_logs_only_the_exception_class(recorded):
    context, sources = _run(_Client(judge_error=ValueError(f"private detail {QUERY}")))

    assert (context, sources) == (None, ())
    assert [(event["stage"], event["outcome"]) for event in recorded] == [("decide", "error")]
    assert recorded[0]["error"] == "ValueError"
    for event in recorded:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        assert QUERY not in line
        assert "private detail" not in line


def test_an_evidence_failure_logs_only_the_exception_class(recorded):
    context, sources = _run(_Client(evidence_error=TimeoutError("engine slow")))

    assert (context, sources) == (None, ())
    assert [(event["stage"], event["outcome"]) for event in recorded] == [
        ("decide", "ok"),
        ("ground", "error"),
    ]
    assert recorded[1]["error"] == "TimeoutError"
    for event in recorded:
        assert "engine slow" not in json.dumps(event, ensure_ascii=False)


def test_rejected_provenance_is_an_error_line_not_a_silent_skip(recorded):
    _run(_Client(evidence={"sources": [], "grounding_context": FENCED}))

    assert [(event["stage"], event["outcome"]) for event in recorded] == [
        ("decide", "ok"),
        ("ground", "error"),
    ]
    assert recorded[1]["error"] == "invalid_evidence"
    assert recorded[1]["sources"] == 0


def test_a_missing_model_id_is_a_skipped_decision(recorded):
    context, sources = _run(_Client(), model_id=None)

    assert (context, sources) == (None, ())
    assert [(event["stage"], event["outcome"]) for event in recorded] == [("decide", "skipped")]


def test_the_real_emitter_writes_one_json_line():
    logger = logging.getLogger(LOGGER_NAME)
    lines: list[str] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    handler = _Handler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        claw_general_routes.default_emitter({
            "event": "claw_web_search", "stage": "decide", "outcome": "ok",
            "sources": 0, "duration_ms": 1.5,
        })
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "claw_web_search"
