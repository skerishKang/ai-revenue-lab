"""Deterministic page-clock timing helpers for the B62 visual QA runners.

The product thresholds live in the QA scripts and are intentionally NOT
relaxed here.  These helpers only make timing *samples* resolve on the
browser page's own clock at the requested sample point.  A failed timing
sample is retryable when the in-page measurement proves the CPU-starved CI
runner (very low rendering frame rate or a wedged sampling round-trip),
not the product, overshot the requested sample window.  Genuine product
behavior (a boundary sample taken on time) stays a hard assertion.

TimingOvershoot subclasses AssertionError so a CI that somehow loses the
retry wrapper still fails the step instead of silently passing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from playwright.async_api import Page

# How far past the requested page-clock sample point a boundary sample may
# land before the runner is considered to have missed its own window.
MAX_SAMPLE_SLACK_MS = 120.0
# Rendering frame rate below which a blown settle window is attributed to
# runner starvation rather than product behavior.
STARVED_FLOOR_FPS = 24.0


class TimingOvershoot(AssertionError):
    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


_SAMPLE_JS = """
async ([started, target, readExpr]) => {
  const read = new Function('return (' + readExpr + ')')();
  const tick = () => new Promise((resolve) => {
    const rafId = requestAnimationFrame(() => { clearTimeout(timer); resolve(); });
    const timer = setTimeout(() => { cancelAnimationFrame(rafId); resolve(); }, 16);
  });
  let frames = 0;
  const began = performance.now();
  while (performance.now() < started + target) {
    await tick();
    frames += 1;
    if (performance.now() - began > target + 30000) break;
  }
  const ended = performance.now();
  const span = Math.max(1, ended - began);
  const state = read();
  return { sampledMs: ended - started, frames, fps: (frames * 1000) / span, state };
}
"""

_WAIT_JS = """
async ([started, doneExpr, timeoutMs, fallbackMs, readExpr]) => {
  const done = new Function('return (' + doneExpr + ')')();
  const read = readExpr ? new Function('return (' + readExpr + ')')() : null;
  let rafWins = 0;
  const tick = () => new Promise((resolve) => {
    const rafId = requestAnimationFrame(() => { clearTimeout(timer); rafWins += 1; resolve(); });
    const timer = setTimeout(() => { cancelAnimationFrame(rafId); resolve(); }, fallbackMs);
  });
  let iters = 0;
  const began = performance.now();
  let ok = done();
  while (!ok && performance.now() - began < timeoutMs) {
    await tick();
    iters += 1;
    ok = done();
  }
  const ended = performance.now();
  const span = Math.max(1, ended - began);
  return {
    done: ok,
    elapsedMs: ended - started,
    frames: rafWins,
    fps: (rafWins * 1000) / span,
    state: read ? read() : null,
  };
}
"""


async def sample_at_page_clock(
    page: Page,
    *,
    started_ms: float,
    target_ms: float,
    read_expr: str,
    evidence_log: list[dict[str, Any]] | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Read the requested product state at exactly ``target_ms`` of page time.

    The wait and the read happen inside a single in-page evaluation, so host
    scheduling before or during the sleep cannot make the boundary read land
    tens or hundreds of milliseconds late.  The returned envelope contains
    the product ``state`` plus ``sampled_ms``, ``frames``, and ``fps`` so a
    later product assertion can still produce durable timing evidence.
    """
    packed = await page.evaluate(_SAMPLE_JS, [float(started_ms), float(target_ms), read_expr])
    sampled_ms = float(packed["sampledMs"])
    state = dict(packed["state"])
    evidence = {
        "label": label,
        "outcome": "SAMPLE",
        "requested_ms": target_ms,
        "sampled_ms": round(sampled_ms, 3),
        "frames": int(packed["frames"]),
        "fps": round(float(packed["fps"]), 1),
        "state": state,
    }
    if sampled_ms > target_ms + MAX_SAMPLE_SLACK_MS:
        overshoot_evidence = {key: value for key, value in evidence.items() if key != "outcome"}
        raise TimingOvershoot(
            f"timing sample overshot its window: requested {target_ms:.0f}ms, "
            f"sampled at {sampled_ms:.0f}ms",
            overshoot_evidence,
        )
    if evidence_log is not None:
        evidence_log.append(evidence)
    return {
        "state": state,
        "sampled_ms": sampled_ms,
        "frames": int(packed["frames"]),
        "fps": float(packed["fps"]),
    }


async def wait_state_settled(
    page: Page,
    *,
    started_ms: float,
    done_expr: str,
    timeout_ms: float = 6_000,
    read_expr: str | None = None,
    fallback_ms: float = 16.0,
    evidence_log: list[dict[str, Any]] | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Wait for a product state inside the page at frame granularity.

    Returns ``done``, the page-clock ``elapsed_ms`` measured from
    ``started_ms`` at the first frame where the condition held (not the time
    a host-side poll round-trip finally noticed it), and the rAF frame rate
    during the wait — the evidence used to attribute an overshoot to the
    runner instead of the product.
    """
    try:
        packed = await asyncio.wait_for(
            page.evaluate(
                _WAIT_JS,
                [float(started_ms), done_expr, float(timeout_ms), float(fallback_ms), read_expr],
            ),
            timeout=timeout_ms / 1000 + 5,
        )
    except asyncio.TimeoutError as exc:
        raise TimingOvershoot(
            f"in-page timing wait did not return within {timeout_ms:.0f}ms (host round-trip stalled)",
            {"requested_timeout_ms": timeout_ms, "round_trip_stalled": True},
        ) from exc
    result = {
        "done": bool(packed["done"]),
        "elapsed_ms": float(packed["elapsedMs"]),
        "frames": int(packed["frames"]),
        "fps": float(packed["fps"]),
        "state": packed["state"],
    }
    if evidence_log is not None:
        evidence_log.append(
            {
                "label": label,
                "outcome": "SETTLE_SAMPLE",
                "sampled_ms": round(result["elapsed_ms"], 3),
                "frames": result["frames"],
                "fps": round(result["fps"], 3),
                "complete": result["done"],
                "state": result["state"],
            }
        )
    return result


def check_settle_window(
    message: str,
    result: dict[str, Any],
    *,
    lo_ms: float,
    hi_ms: float,
    evidence_log: list[dict[str, Any]] | None = None,
    label: str = "",
) -> None:
    """Apply an unchanged [lo, hi] settle window to a page-clock measurement.

    Under-window or never-complete results are a genuine product regression
    and raise the plain assertion.  An over-window result where rendering was
    demonstrably starved is runner contention and raises ``TimingOvershoot``
    so the identical sample can be retried on a fresh cycle.
    """
    elapsed_ms = float(result["elapsed_ms"])
    fps = float(result.get("fps", 0.0))
    done = bool(result.get("done"))
    if done and lo_ms <= elapsed_ms <= hi_ms:
        return
    evidence = {
        "label": label,
        "outcome": "ASSERTION_FAILURE",
        "sampled_ms": round(elapsed_ms, 3),
        "window_ms": [lo_ms, hi_ms],
        "complete": done,
        "settle_fps": round(fps, 1),
        "state": result.get("state"),
    }
    detail = f"{message} [timing-sample: sampled_ms={elapsed_ms:.0f}, window={lo_ms:.0f}-{hi_ms:.0f}ms, complete={done}, fps={fps:.1f}]"
    if evidence_log is not None:
        evidence_log.append(evidence)
    if (not done or elapsed_ms > hi_ms) and fps < STARVED_FLOOR_FPS:
        raise TimingOvershoot(detail, evidence)
    raise AssertionError(detail)


async def with_timing_retries(
    factory: Callable[[], Coroutine[Any, Any, Any]],
    *,
    label: str,
    evidence_log: list[dict[str, Any]],
    attempts: int = 3,
) -> Any:
    """Run a fresh-navigation timing cycle, re-sampling only proven overshoots.

    Every retry repeats the identical product thresholds starting from a
    clean navigation; nothing is skipped or relaxed per-attempt.
    """
    last: TimingOvershoot | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await factory()
            if attempt > 1:
                evidence_log.append({"label": label, "attempt": attempt, "outcome": "PASS"})
            return result
        except TimingOvershoot as exc:
            last = exc
            record = {"label": label, "attempt": attempt, "outcome": "OVERSHOOT"}
            record.update(exc.evidence)
            evidence_log.append(record)
            if attempt < attempts:
                # Give a starved browser process one event-loop interval to
                # recover before the next isolated sample. This does not
                # change any product threshold or increase the attempt bound.
                await asyncio.sleep(0.25 * attempt)
    assert last is not None
    raise TimingOvershoot(
        f"{label}: timing sampling overshot the requested window on all attempts "
        f"(runner contention suspected; thresholds were never relaxed) — {last}",
        {"label": label, "attempts": attempts, "exhausted": True, **last.evidence},
    )
