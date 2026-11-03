"""Bounded P01 stage-time line (#6772): names and milliseconds only."""

from __future__ import annotations

import re

from app.engine_timing import EngineTiming


def _line(**overrides) -> str:
    timing = EngineTiming()
    timing.mark("admission_start")
    timing.mark("admission_end")
    timing.mark("core_start")
    timing.mark("core_end")
    timing.add_receipt_since(0.0)
    values = {
        "run_hash": "0123456789abcdef",
        "trace_id": "b62_orch_0123456789abcdef",
        "b14_ms": 840,
        "outcome": "ok",
    }
    values.update(overrides)
    return timing.line(**values)


def test_line_has_only_stage_names_milliseconds_and_existing_tokens() -> None:
    line = _line()

    assert line.startswith("engine_timing ")
    assert re.fullmatch(
        r"engine_timing run_hash=[a-f0-9]{16} trace_id=b62_orch_[a-f0-9]{16}"
        r" admission_ms=\d+\.\d core_ms=\d+\.\d b14_ms=840"
        r" receipt_ms=\d+\.\d total_ms=\d+\.\d outcome=ok",
        line,
    )


def test_unbounded_tokens_fall_back_to_none() -> None:
    line = _line(run_hash="not a token", trace_id="b62_orch_1 question")

    assert "run_hash=none" in line
    assert "trace_id=none" in line


def test_unknown_outcome_is_bounded() -> None:
    assert "outcome=error" in _line(outcome="user text")


def test_unmeasured_stages_stay_negative() -> None:
    timing = EngineTiming()

    line = timing.line(
        run_hash=None,
        trace_id=None,
        b14_ms=-1,
        outcome="refused",
    )

    assert "admission_ms=-1.0" in line
    assert "core_ms=-1.0" in line
    assert "b14_ms=-1" in line
    assert "receipt_ms=0.0" in line
