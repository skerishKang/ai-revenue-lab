"""#5554 TTFT: the outgoing-request gate must not add seconds before the request.

The shipped composer waits for the tier restore before it lets a message leave
the browser. Measured in production, that wait was 3.0-8.7s of a 14.6-29.0s
first-answer time, because the restore re-read the account selection and the
window-focus refresh was serialized into the same chain.

These tests drive the SHIPPED ``static/product-capabilities.js`` in Node with a
browser stub and assert the observable behaviour:

* the account-selection read and the administrator probe overlap,
* a background (window focus) refresh never holds an outgoing request,
* the gate still waits for the restore of the generation it depends on, so a
  request never leaves with a tier that was not verified yet (#5222).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent / "ttft_gate_harness.js"


@pytest.fixture(scope="module")
def harness_result() -> dict:
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        pytest.skip("node is not available in this environment")
    completed = subprocess.run(
        [node, str(HARNESS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.stdout, completed.stderr
    payload = json.loads(completed.stdout)
    assert "error" not in payload, payload.get("error")
    return payload


def test_the_two_independent_restore_reads_overlap(harness_result: dict) -> None:
    """The selection read must not wait for the administrator probe."""

    assert harness_result["s1_issued"].count("model-selection") == 1
    assert harness_result["s1_issued"].count("admin") == 1
    assert harness_result["s1_selection_before_admin"] is True


def test_a_window_focus_refresh_does_not_hold_an_outgoing_request(
    harness_result: dict,
) -> None:
    """A background refresh must never become a request's prerequisite."""

    assert harness_result["s2_resolved_while_later_generation_pending"] is True


def test_the_gate_still_waits_for_the_verified_restore(harness_result: dict) -> None:
    """#5222: a request never leaves with a tier that was not verified yet."""

    assert harness_result["s3_resolved_before_restore"] is False
    assert harness_result["s3_resolved_after_restore"] is True


def test_the_shipped_composer_waits_for_the_tier_restore() -> None:
    """The gate contract itself stays in the shipped composer."""

    source = (ROOT / "static/product-capabilities.js").read_text(encoding="utf-8")
    assert "const pending = tierRestoreTail || authRefreshTail;" in source
    assert "if (!background) tierRestoreTail = run;" in source
    assert 'refreshAuth({background: true});' in source
