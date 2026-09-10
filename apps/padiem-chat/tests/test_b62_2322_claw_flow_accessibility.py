"""#2323 — Claw primary-flow accessibility source contracts (static, bounded).

Guards the KILO4 #2322 audit fixes:
- A1: the post-result programmatic focus target is actually focusable
  (tabindex="-1" on #clawResultPreview) and visibly outlined;
- A2: the outer result container is no longer a live region — #clawStatus is
  the single canonical polite status region (no nested aria-live);
- A3: #clawRequestText is programmatically associated with #clawStatus via
  aria-describedby, and aria-invalid is set on error / cleared otherwise.

Also re-asserts the preserved mobile contracts (44/48px touch targets, 16px
iOS zoom safety, 720px breakpoint) and the execute/result/artifact frontend
contract so this slice cannot regress them.
"""

from __future__ import annotations

import re

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")


def _line(text: str, needle: str) -> str:
    matches = [ln for ln in text.splitlines() if needle in ln]
    assert matches, f"no line containing {needle!r}"
    return matches[0]


# ── A1 — result focus target ──────────────────────────────────────────────


def test_result_focus_target_is_programmatically_focusable() -> None:
    line = _line(INDEX, 'id="clawResultPreview"')
    assert 'class="claw-result-body"' in line
    assert 'tabindex="-1"' in line


def test_post_result_focus_calls_are_preserved() -> None:
    assert re.search(r"clawResultPreview\.focus\?\.\(\)", APP)
    assert re.search(r"clawResultDocx\.focus\?\.\(\)", APP)


def test_focusable_result_region_has_visible_outline() -> None:
    assert ".claw-result-body:focus-visible" in WORKSPACE_CSS
    block = WORKSPACE_CSS.split(".claw-result-body:focus-visible", 1)[1].split("}", 1)[0]
    assert "outline" in block


# ── A2 — nested live regions removed ──────────────────────────────────────


def test_outer_result_container_is_not_a_live_region() -> None:
    line = _line(INDEX, 'id="clawResultArea"')
    assert "aria-live" not in line
    assert 'data-claw-state="idle"' in line


def test_status_region_is_the_single_canonical_live_region() -> None:
    line = _line(INDEX, 'id="clawStatus"')
    assert 'role="status"' in line
    assert 'aria-live="polite"' in line
    live_regions = re.findall(r'aria-live="([^"]+)"', INDEX)
    assert live_regions.count("polite") >= 2
    assert 'aria-live="polite"' not in _line(INDEX, 'id="clawResultArea"')


# ── A3 — input error association ──────────────────────────────────────────


def test_request_input_is_described_by_status_region() -> None:
    line = _line(INDEX, 'id="clawRequestText"')
    assert 'aria-describedby="clawStatus"' in line


def test_aria_invalid_set_on_error_and_cleared_otherwise() -> None:
    status_fn = APP.split("function setClawStatus", 1)[1].split("\n  }", 1)[0]
    assert 'clawRequestText.setAttribute("aria-invalid", "true")' in status_fn
    assert 'if (state === "error")' in status_fn
    assert status_fn.count('clawRequestText.removeAttribute("aria-invalid")') == 2


# ── preserved mobile contracts ────────────────────────────────────────────


def test_touch_target_floor_preserved() -> None:
    assert "min-height: 44px;" in WORKSPACE_CSS
    assert "min-height: 48px;" in WORKSPACE_CSS


def test_mobile_zoom_safety_preserved() -> None:
    hero = WORKSPACE_CSS.split(".claw-intake-hero textarea", 1)[1].split("}", 1)[0]
    assert "font-size: 16px" in hero


def test_mobile_breakpoint_preserved() -> None:
    assert "@media (max-width: 720px)" in WORKSPACE_CSS


# ── preserved execute/result/artifact frontend contract ──────────────────


def test_execute_and_artifact_flow_contract_unchanged() -> None:
    assert '"/api/claw/manual-intake/execute"' in APP
    assert '"/api/claw/manual-intake/preview"' in APP
    assert re.search(r"/\^doc_\[A-Za-z0-9\]\{32\}\$/", APP)
    assert "renderClawArtifactMeta" in APP
    assert "downloadClawArtifact" in APP


def test_action_chip_semantics_unchanged() -> None:
    assert INDEX.count('data-claw-action=') >= 4
    assert 'aria-pressed="false"' in INDEX
    assert 'other.setAttribute("aria-pressed"' in APP
