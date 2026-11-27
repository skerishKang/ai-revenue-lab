"""#7809 1/13 — the stage timing helpers keep their behaviour in claw_general_stage.

The helpers moved verbatim out of claw_general_routes. Their behaviour was only covered
indirectly (a full route turn); this pins it where it is defined, so a later change to the
stage module cannot silently drop a stage event, change its default outcome or let a telemetry
failure fail a turn.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from _support.claw_general_modules import find_attr, patch_bound


def _capture(monkeypatch):
    events = []

    def emit(*, stage, outcome, duration_ms, **extra):
        events.append({"stage": stage, "outcome": outcome, "duration_ms": duration_ms, **extra})

    patch_bound(monkeypatch, "emit_stage_event", emit)
    return events


def test_a_stage_event_is_a_fixed_name_an_outcome_and_a_duration(monkeypatch):
    events = _capture(monkeypatch)
    stage = find_attr("_claw_stage")
    started = time.perf_counter()

    stage("claw.route", started)
    stage("claw.route", started, outcome="error")

    assert [(e["stage"], e["outcome"]) for e in events] == [
        ("claw.route", "ok"), ("claw.route", "error"),
    ]
    assert all(set(e) == {"stage", "outcome", "duration_ms"} for e in events)
    assert all(isinstance(e["duration_ms"], float) and e["duration_ms"] >= 0.0 for e in events)


def test_a_telemetry_failure_never_fails_the_turn(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("telemetry unavailable")

    patch_bound(monkeypatch, "emit_stage_event", broken)

    find_attr("_claw_stage")("claw.route", time.perf_counter())  # must not raise


def test_a_timed_read_records_its_own_stage_even_when_it_raises(monkeypatch):
    events = _capture(monkeypatch)
    timed = find_attr("_claw_timed")

    async def finished():
        return 7

    async def failed():
        raise ValueError("read failed")

    assert asyncio.run(timed("claw.drive", finished())) == 7
    with pytest.raises(ValueError):
        asyncio.run(timed("claw.history", failed()))

    assert [(e["stage"], e["outcome"]) for e in events] == [
        ("claw.drive", "ok"), ("claw.history", "ok"),
    ]
