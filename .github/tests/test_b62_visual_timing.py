"""Focused evidence-contract tests for the B62 page-clock timing helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / ".github" / "scripts" / "b62_visual_timing.py"
SPEC = importlib.util.spec_from_file_location("b62_visual_timing", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)


class _FakePage:
    def __init__(self, packed: dict) -> None:
        self.packed = packed

    async def evaluate(self, _script: str, _args: list[object]) -> dict:
        return self.packed


@pytest.mark.asyncio
async def test_sample_returns_state_and_page_clock_evidence() -> None:
    state = {"progress": 0.71, "portalOpacity": 0.62}
    evidence: list[dict] = []
    sample = await timing.sample_at_page_clock(
        _FakePage({"sampledMs": 903.5, "frames": 54, "fps": 59.8, "state": state}),
        started_ms=100.0,
        target_ms=900.0,
        read_expr="() => ({})",
        evidence_log=evidence,
        label="glass-mid-900ms",
    )

    assert sample == {
        "state": state,
        "sampled_ms": 903.5,
        "frames": 54,
        "fps": 59.8,
    }
    assert evidence == [
        {
            "label": "glass-mid-900ms",
            "outcome": "SAMPLE",
            "requested_ms": 900.0,
            "sampled_ms": 903.5,
            "frames": 54,
            "fps": 59.8,
            "state": state,
        }
    ]


def test_normal_assertion_failure_records_settle_timing_and_state() -> None:
    evidence: list[dict] = []
    result = {
        "done": True,
        "elapsed_ms": 3_701.25,
        "frames": 90,
        "fps": 58.0,
        "state": {"progress": 0.04, "fragVisible": 0},
    }

    with pytest.raises(AssertionError, match="sampled_ms=3701"):
        timing.check_settle_window(
            "reassembly must settle slowly",
            result,
            lo_ms=1_600,
            hi_ms=3_600,
            evidence_log=evidence,
            label="glass-recover-settle",
        )

    assert evidence == [
        {
            "label": "glass-recover-settle",
            "outcome": "ASSERTION_FAILURE",
            "sampled_ms": 3701.25,
            "window_ms": [1600, 3600],
            "complete": True,
            "settle_fps": 58.0,
            "state": {"progress": 0.04, "fragVisible": 0},
        }
    ]


@pytest.mark.asyncio
async def test_overshoot_evidence_retains_sample_state() -> None:
    state = {"progress": 0.67}
    with pytest.raises(timing.TimingOvershoot) as caught:
        await timing.sample_at_page_clock(
            _FakePage({"sampledMs": 1_050.0, "frames": 4, "fps": 3.5, "state": state}),
            started_ms=100.0,
            target_ms=900.0,
            read_expr="() => ({})",
        )

    assert caught.value.evidence == {
        "label": "",
        "requested_ms": 900.0,
        "sampled_ms": 1050.0,
        "frames": 4,
        "fps": 3.5,
        "state": state,
    }
