"""#4139 — the ingress budget must be the Engine budget it fronts.

The Engine's own model request budget is a Python constant published in
``openapi.json``; the ingress that fronts the model route is JavaScript and
cannot import it. This test is the seam that keeps the two from drifting apart
again: the ingress used to read 128 KiB and collect a completed answer at 1 MiB,
so a model request the Engine would have admitted was refused at the front door,
and a healthy large answer came back as ``engine_response_too_large``.

It also pins the opposite direction: the non-model Engine guard stays where it
was, because loosening the model path is not a licence to loosen tool, control,
memory and approval routes in the same sweep.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.service import (
    MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES,
    MAX_REQUEST_BODY_BYTES,
)
from padiem_ai_core.b14_execution import MAX_CONFIGURED_B14_RESPONSE_BYTES

ROOT = Path(__file__).resolve().parents[1]
INGRESS = ROOT / "ingress" / "worker.mjs"


def _literal(name: str) -> int:
    """One finite numeric literal from the ingress source (``6_000_000`` or
    ``8 * 1024 * 1024``); nothing else is evaluated."""
    source = INGRESS.read_text(encoding="utf-8")
    match = re.search(
        r"const " + re.escape(name) + r" = ([0-9_]+(?:\s*\*\s*[0-9_]+)*);", source
    )
    assert match is not None, name + " is no longer a finite numeric literal"
    value = 1
    for factor in re.findall(r"\d[\d_]*", match.group(1)):
        value *= int(factor.replace("_", ""))
    return value


def test_ingress_request_budget_equals_the_engine_model_budget() -> None:
    # #4379: neither side declares a PADIEM model-request byte total. The
    # ingress literal and the Engine constant must both be absent, so the
    # two cannot drift apart again.
    assert MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES is None
    assert "const MAX_REQUEST_BODY_BYTES = null;" in INGRESS.read_text(
        encoding="utf-8"
    )


def test_ingress_response_budget_equals_the_completed_json_contract() -> None:
    assert _literal("MAX_RESPONSE_BYTES") == MAX_CONFIGURED_B14_RESPONSE_BYTES


def test_ingress_serves_only_the_model_execute_route() -> None:
    """The wider ingress bound is scoped to the route it actually fronts."""
    source = INGRESS.read_text(encoding="utf-8")
    assert 'if (url.pathname !== EXECUTE_PATH) {' in source
    assert source.count("MAX_REQUEST_BODY_BYTES") >= 2


def test_non_model_engine_guard_is_not_released_in_the_same_sweep() -> None:
    # The non-model Engine guard stays a bounded guard: releasing the model path
    # is not a licence to release the tool, control, memory and approval routes.
    # #5573 raised its value 128 KiB -> 1 MiB by Owner decision; it is not removed.
    assert MAX_REQUEST_BODY_BYTES == 1024 * 1024  # Owner decision 2026-10-24 (#5573)
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    assert "else MAX_REQUEST_BODY_BYTES" in worker
