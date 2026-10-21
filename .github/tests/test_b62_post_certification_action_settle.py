"""#5210 — the post-certification copy/download clicks wait on measured geometry.

`b62_post_certification_browser_qa.py` died at `Locator.click()` on COM2 with
"element is not stable" after the full 30s actionability budget, because the turn
publishes `data-terminal-actions-safe` while its own box is still re-wrapping. The
suite sits at position 9 of the COM2 Generic Browser lane, so that one failure kept
the Glass visual tail (Zoom / Shell / Gutter) from ever executing.

The guard has to stay a guard:

* it waits for a measured *quiet period*, not consecutive-equal frames — a plateau
  can precede the reflow, and the consecutive-frames version was measured settling
  at `x=438.11` before the row moved to `x=442.13`;
* it still performs the real user click, never a DOM-existence substitute;
* it is bounded below Playwright's actionability timeout, so it is not a disguised
  timeout increase;
* a degenerate zero-width rect is a failure, not "quiet".
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / ".github/scripts/b62_post_certification_browser_qa.py"
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"

# Sibling CI contract tests install their own partial `playwright.async_api` stub
# and whichever is collected first owns sys.modules, so the names this suite
# imports are added to whatever module object is already registered.
_api = sys.modules.get("playwright.async_api")
if _api is None:
    _api = types.ModuleType("playwright.async_api")
    _playwright = sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    _playwright.async_api = _api
    sys.modules["playwright.async_api"] = _api
for _name in ("Browser", "BrowserContext", "Locator", "Page", "Route", "async_playwright"):
    if not hasattr(_api, _name):
        setattr(_api, _name, object)

# Importing the suite would otherwise create its evidence directory under the
# read-only checkout of the plan job.
os.environ["B62_QA_OUT_DIR"] = tempfile.mkdtemp(prefix="b62-post-cert-settle-")

_spec = importlib.util.spec_from_file_location("b62_post_cert_qa", QA)
qa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qa)


class _Target:
    def __init__(self) -> None:
        self.waited: list[str] = []

    async def wait_for(self, **kwargs) -> None:
        self.waited.append(kwargs["state"])


class _Assistant:
    def __init__(self, target: _Target) -> None:
        self._target = target

    def locator(self, selector: str) -> _Target:
        return self._target


class _Page:
    def __init__(self, result: dict) -> None:
        self._result = result
        self.args: object = None

    async def evaluate(self, script: str, arg: object = None) -> dict:
        self.args = arg
        return self._result


def _settle(**overrides) -> dict:
    result = {
        "found": True,
        "settled": True,
        "frames": 12,
        "moves": [],
        "elapsed_ms": 2_113,
        "rect": "442.13,752.17,26.00,26.00,turn_h=8521.92",
    }
    result.update(overrides)
    return result


def _call(page: _Page, assistant: _Assistant) -> dict:
    return asyncio.run(
        qa._wait_for_action_geometry_settled(page, assistant, ".answer-copy", "copy")
    )


class SettleGuardFailsClosed(unittest.TestCase):
    def test_a_quiet_laid_out_action_is_returned(self) -> None:
        target = _Target()
        page = _Page(_settle())
        report = _call(page, _Assistant(target))
        self.assertEqual(report["rect"], "442.13,752.17,26.00,26.00,turn_h=8521.92")
        self.assertEqual(target.waited, ["visible"])

    def test_geometry_that_never_goes_quiet_is_a_failure_not_a_retry(self) -> None:
        page = _Page(_settle(settled=False, moves=[{"t_ms": 1, "rect": "x"}]))
        with self.assertRaises(AssertionError) as caught:
            _call(page, _Assistant(_Target()))
        self.assertIn("never went quiet", str(caught.exception))
        self.assertIn("1 measured moves", str(caught.exception))

    def test_a_missing_action_is_a_failure(self) -> None:
        page = _Page(_settle(found=False, settled=False, rect=None))
        with self.assertRaises(AssertionError) as caught:
            _call(page, _Assistant(_Target()))
        self.assertIn("disappeared before the click", str(caught.exception))

    def test_a_zero_width_rect_is_not_accepted_as_quiet(self) -> None:
        page = _Page(_settle(rect="603.13,757.17,0.00,26.00,turn_h=8531.92"))
        with self.assertRaises(AssertionError) as caught:
            _call(page, _Assistant(_Target()))
        self.assertIn("no laid-out geometry", str(caught.exception))

    def test_the_probe_arguments_are_the_declared_bounds(self) -> None:
        page = _Page(_settle())
        _call(page, _Assistant(_Target()))
        self.assertEqual(
            page.args,
            [
                ".answer-copy",
                qa._SETTLE_STABLE_FRAMES,
                qa._SETTLE_QUIET_MS,
                qa._SETTLE_BUDGET_MS,
            ],
        )


class SettleGuardIsNotATimeoutIncrease(unittest.TestCase):
    def test_the_quiet_window_is_time_based_not_consecutive_frames(self) -> None:
        script = qa._ACTION_GEOMETRY_SETTLE_JS
        self.assertIn("quiet_since", script)
        self.assertIn("now - quiet_since >= quietMs", script)
        self.assertIn("turn.getBoundingClientRect()", script)
        # Measured: the turn box moved ~489ms after publish and re-wrapped at
        # ~1.1s, so a window shorter than that can settle on the plateau.
        self.assertGreaterEqual(qa._SETTLE_QUIET_MS, 1_000)

    def test_the_budget_stays_below_the_click_actionability_timeout(self) -> None:
        self.assertLess(qa._SETTLE_BUDGET_MS, 30_000)
        self.assertLess(qa._SETTLE_QUIET_MS, qa._SETTLE_BUDGET_MS)


class UserActionVerificationStays(unittest.TestCase):
    def test_both_actions_are_still_clicked_notmerely_present(self) -> None:
        source = QA.read_text(encoding="utf-8")
        self.assertIn("await copy_button.click()", source)
        self.assertIn("await download_button.click()", source)
        self.assertIn("await more.click()", source)
        self.assertIn('async with page.expect_download() as download_info', source)
        self.assertIn("await page.evaluate(\"navigator.clipboard.readText()\")", source)

    def test_both_clicks_are_preceded_by_the_measured_settle_guard(self) -> None:
        source = QA.read_text(encoding="utf-8")
        for selector, click in (
            ('".answer-copy", "copy"', "await copy_button.click()"),
            ('".answer-download", "download"', "await download_button.click()"),
        ):
            self.assertIn(selector, source)
            self.assertLess(
                source.index(selector),
                source.index(click),
                f"{click} no longer waits for measured geometry",
            )

    def test_the_canary_lane_still_runs_the_suite_and_the_tail_together(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(".github/scripts/b62_post_certification_browser_qa.py", workflow)
        self.assertIn(".github/scripts/b62_browser_qa_tail_parallel.py", workflow)
        step = workflow.index("Post-certification long-answer and mobile hardening QA")
        self.assertNotIn(
            "continue-on-error",
            workflow[step:workflow.index("b62_post_certification_browser_qa.py", step)],
            "the failing suite must not be neutralised to unblock the tail",
        )


if __name__ == "__main__":
    unittest.main()
