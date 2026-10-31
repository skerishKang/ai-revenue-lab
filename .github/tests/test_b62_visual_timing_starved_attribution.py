"""#5210: a starved renderer must not turn a settled product state into a lane
failure, in either direction of the settle window.

The B62 visual QA settle windows ([1800, 3600] ms for the peel, [1600, 3600]
ms for the reassembly) live in the QA scripts and are never widened here.  A
settle is only ever *observed* at a rendered frame, so a renderer that the
measurement itself proves to be starved (below ``STARVED_FLOOR_FPS``) can
report the very same settled product state just outside the window in either
direction: a slow frame stretches the observed duration past the ceiling, and
a coarse frame grid can land the observation just under the floor.

Both are runner contention and take the existing identical-threshold retry
path.  A healthy renderer keeps the hard assertion, and an exhausted retry
still fails the lane.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".github/scripts/b62_visual_timing.py"

# The helper only needs playwright for type annotations, and the browser QA
# contract jobs run without the browser package installed.
if "playwright.async_api" not in sys.modules:
    _playwright = types.ModuleType("playwright")
    _async_api = types.ModuleType("playwright.async_api")
    _async_api.Page = object
    _playwright.async_api = _async_api
    sys.modules["playwright"] = _playwright
    sys.modules["playwright.async_api"] = _async_api

spec = importlib.util.spec_from_file_location("b62_visual_timing", SOURCE)
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


LO = 1_600
HI = 3_600


class StarvedSettleAttributionTest(unittest.TestCase):
    def _check(self, *, elapsed_ms, fps, done=True, lo=LO, hi=HI, evidence=None):
        return timing.check_settle_window(
            "settle",
            {"elapsed_ms": elapsed_ms, "fps": fps, "done": done},
            lo_ms=lo,
            hi_ms=hi,
            evidence_log=evidence,
            label="glass-female-recover-settle",
        )

    def test_a_settled_sample_inside_the_window_never_fails(self):
        for fps in (9.9, 24.0, 60.0):
            for elapsed in (LO, 1_800.0, 3_600):
                self._check(elapsed_ms=elapsed, fps=fps)

    def test_under_window_on_a_starved_renderer_is_retryable(self):
        # The measured COM2 reassembly: settled, 24ms under the floor, 9.9 FPS.
        with self.assertRaises(timing.TimingOvershoot):
            self._check(elapsed_ms=1_576, fps=9.9)

    def test_over_window_on_a_starved_renderer_stays_retryable(self):
        # The measured COM2 peel before the wall-clock driver fix.
        with self.assertRaises(timing.TimingOvershoot):
            self._check(elapsed_ms=5_642, fps=4.6)

    def test_never_complete_on_a_starved_renderer_stays_retryable(self):
        with self.assertRaises(timing.TimingOvershoot):
            self._check(elapsed_ms=2_000, fps=4.6, done=False)

    def test_a_healthy_renderer_keeps_the_hard_assertion(self):
        for elapsed_ms, done in ((1_576, True), (5_642, True), (2_000, False)):
            with self.assertRaises(AssertionError) as caught:
                self._check(elapsed_ms=elapsed_ms, fps=60.0, done=done)
            self.assertNotIsInstance(caught.exception, timing.TimingOvershoot)

    def test_the_starvation_floor_is_exact(self):
        # fps == STARVED_FLOOR_FPS is a healthy renderer and stays a hard failure.
        with self.assertRaises(AssertionError) as caught:
            self._check(elapsed_ms=1_576, fps=timing.STARVED_FLOOR_FPS)
        self.assertNotIsInstance(caught.exception, timing.TimingOvershoot)
        self.assertEqual(timing.STARVED_FLOOR_FPS, 24.0)
        with self.assertRaises(timing.TimingOvershoot):
            self._check(elapsed_ms=1_576, fps=timing.STARVED_FLOOR_FPS - 0.1)

    def test_the_window_is_reported_verbatim(self):
        evidence: list[dict] = []
        with self.assertRaises(timing.TimingOvershoot):
            self._check(elapsed_ms=1_576, fps=9.9, evidence=evidence)
        self.assertEqual(evidence[-1]["window_ms"], [LO, HI])
        self.assertEqual(evidence[-1]["sampled_ms"], 1_576)
        self.assertEqual(evidence[-1]["settle_fps"], 9.9)
        self.assertTrue(evidence[-1]["complete"])
        self.assertEqual(evidence[-1]["label"], "glass-female-recover-settle")

    def test_an_exhausted_retry_still_fails_the_lane(self):
        # The retry path may re-sample with identical thresholds, but it must
        # never turn an out-of-window settle into a pass.
        self.assertTrue(issubclass(timing.TimingOvershoot, AssertionError))
        attempts: list[int] = []

        async def factory():
            attempts.append(1)
            raise timing.TimingOvershoot("overshoot", {"label": "glass-female-recover-settle"})

        evidence: list[dict] = []
        with self.assertRaises(timing.TimingOvershoot) as caught:
            asyncio.run(
                timing.with_timing_retries(
                    factory, label="glass-female-recover-settle", evidence_log=evidence
                )
            )
        self.assertEqual(len(attempts), 3)
        self.assertEqual([entry["outcome"] for entry in evidence], ["OVERSHOOT"] * 3)
        self.assertTrue(caught.exception.evidence["exhausted"])
        self.assertEqual(caught.exception.evidence["attempts"], 3)


if __name__ == "__main__":
    unittest.main()
