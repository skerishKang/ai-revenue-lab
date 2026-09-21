"""A12 provider-independence classification tests (#2786 M4-4 closing item).

The gate must separate an external provider outage from an Engine failure:

  external 5xx preserved as ``error.metadata.upstream_status_code`` -> SKIPPED_UPSTREAM
  Engine 5xx / auth / contract / idempotency / D1 mismatch          -> FAIL

S0 (health + manifest) and S3 (conflict) are mandatory and provider-independent:
they still have to pass on a run whose provider leg was skipped. S4 is only
meaningful when an execution actually happened, so a skipped run records it as
not applicable rather than claiming it passed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = APP_ROOT / "scripts" / "a12_stream_replay_production_smoke.py"

_spec = importlib.util.spec_from_file_location("a12_smoke_classification", SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


def _upstream_error(status: int) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "b14_upstream_error",
            "metadata": {"upstream_status_code": status},
        },
    }


def _engine_error(code: str = "internal_error") -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "metadata": {}}}


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch):
    smoke._failures.clear()
    smoke._skips.clear()
    monkeypatch.setattr(smoke, "CALLER_ID", "a12-test-caller", raising=False)
    monkeypatch.setattr(smoke, "CALLER_SECRET", "not-a-real-secret", raising=False)
    yield
    smoke._failures.clear()
    smoke._skips.clear()


# --- classification primitives -------------------------------------------


def test_upstream_status_extraction_is_bounded() -> None:
    assert smoke._upstream_status_code(_upstream_error(502)) == 502
    assert smoke._upstream_status_code(_upstream_error(599)) == 599
    assert smoke._upstream_status_code(_upstream_error(404)) is None
    assert smoke._upstream_status_code(_engine_error()) is None
    assert smoke._upstream_status_code({"ok": True}) is None
    assert smoke._upstream_status_code(None) is None
    assert smoke._upstream_status_code("not a body") is None
    assert (
        smoke._upstream_status_code({"error": {"metadata": {"upstream_status_code": True}}})
        is None
    )
    assert (
        smoke._upstream_status_code({"error": {"metadata": {"upstream_status_code": "502"}}})
        is None
    )


def test_only_an_engine_preserved_provider_5xx_is_skipped() -> None:
    assert smoke._classify_upstream_skip("S1", 502, [_upstream_error(502)]) is True
    assert smoke._skips and "502" in smoke._skips[0]

    smoke._skips.clear()
    # An Engine 5xx carries no upstream status: it must stay on the failure path.
    assert smoke._classify_upstream_skip("S1", 500, [_engine_error()]) is False
    assert smoke._classify_upstream_skip("S1", 503, []) is False
    assert smoke._classify_upstream_skip("S1", 409, [_upstream_error(502)]) is False
    assert smoke._classify_upstream_skip("S1", 200, [_upstream_error(502)]) is False
    assert smoke._skips == []
    assert smoke._failures == []


# --- stage level ----------------------------------------------------------


def test_s1_provider_5xx_is_a_skip_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke, "_request_stream", lambda **_: (502, [_upstream_error(502)], '{"error":{}}')
    )

    executed, answer = smoke.s1_first_stream_run({"messages": []})

    assert executed is False and answer is None
    assert smoke._failures == []
    assert smoke._skips and "S1" in smoke._skips[0]


def test_s1_engine_5xx_without_the_marker_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "_request_stream", lambda **_: (503, [_engine_error()], "{}"))

    executed, _ = smoke.s1_first_stream_run({"messages": []})

    assert executed is False
    assert smoke._failures and smoke._skips == []


def test_s2_provider_5xx_is_a_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke, "_request_stream", lambda **_: (504, [_upstream_error(504)], "{}")
    )

    assert smoke.s2_replay_stream_run({"messages": []}, "ok") is False
    assert smoke._failures == []
    assert smoke._skips and "S2" in smoke._skips[0]


# --- verdict assembly -----------------------------------------------------


def _patch_mandatory(monkeypatch: pytest.MonkeyPatch, calls: list[str], *, s3_ok: bool = True):
    monkeypatch.setattr(smoke, "s0_health", lambda: (calls.append("S0"), True)[1])

    def s3(_payload: Any) -> bool:
        calls.append("S3")
        if s3_ok:
            return True
        # Mirror the real stage: a contract failure records a failure.
        smoke._fail("S3", "stub conflict status 200 != 409")
        return False

    monkeypatch.setattr(smoke, "s3_conflict_blocks_before_execution", s3)


def test_pass_verdict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    calls: list[str] = []
    _patch_mandatory(monkeypatch, calls)
    monkeypatch.setattr(smoke, "s1_first_stream_run", lambda _p: (True, "OK"))
    monkeypatch.setattr(smoke, "s2_replay_stream_run", lambda _p, _a: (calls.append("S2"), None)[1])
    monkeypatch.setattr(smoke, "s4_d1_row_state", lambda: (calls.append("S4"), True)[1])

    assert smoke.main() == 0

    out = capsys.readouterr().out
    assert "A12_STREAM_REPLAY_SMOKE=PASS" in out
    assert calls == ["S0", "S2", "S3", "S4"]


def test_provider_skip_verdict_keeps_mandatory_stages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[str] = []
    _patch_mandatory(monkeypatch, calls)

    def s1(_payload: Any) -> tuple[bool, None]:
        smoke._classify_upstream_skip("S1", 502, [_upstream_error(502)])
        return False, None

    monkeypatch.setattr(smoke, "s1_first_stream_run", s1)
    monkeypatch.setattr(
        smoke, "s2_replay_stream_run", lambda *_a: pytest.fail("S2 must not run without an execution")
    )
    monkeypatch.setattr(
        smoke, "s4_d1_row_state", lambda: pytest.fail("S4 must not run without an execution")
    )

    assert smoke.main() == 0

    out = capsys.readouterr().out
    assert "A12_STREAM_REPLAY_SMOKE=SKIPPED_UPSTREAM" in out
    assert "MANDATORY_STAGES=S0,S3" in out
    assert "A12_SKIP_REASON=" in out
    assert calls == ["S0", "S3"]


def test_engine_contract_failure_stays_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[str] = []
    _patch_mandatory(monkeypatch, calls, s3_ok=False)
    monkeypatch.setattr(smoke, "s1_first_stream_run", lambda _p: (True, "OK"))
    monkeypatch.setattr(smoke, "s2_replay_stream_run", lambda _p, _a: None)
    monkeypatch.setattr(smoke, "s4_d1_row_state", lambda: True)

    assert smoke.main() == 1

    out = capsys.readouterr().out
    assert "A12_STREAM_REPLAY_SMOKE=PASS" not in out


def test_provider_skip_cannot_mask_an_engine_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_mandatory(monkeypatch, calls, s3_ok=False)

    def s1(_payload: Any) -> tuple[bool, None]:
        smoke._classify_upstream_skip("S1", 502, [_upstream_error(502)])
        return False, None

    monkeypatch.setattr(smoke, "s1_first_stream_run", s1)
    monkeypatch.setattr(smoke, "s4_d1_row_state", lambda: True)

    assert smoke.main() == 1
    assert smoke._skips and smoke._failures


def test_s0_gate_failure_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "s0_health", lambda: False)

    assert smoke.main() == 1


def test_s2_skip_is_recorded_but_the_executed_run_still_checks_d1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[str] = []
    _patch_mandatory(monkeypatch, calls)
    monkeypatch.setattr(smoke, "s1_first_stream_run", lambda _p: (True, "OK"))

    def s2(_payload: Any, _answer: Any) -> None:
        smoke._classify_upstream_skip("S2", 503, [_upstream_error(503)])

    monkeypatch.setattr(smoke, "s2_replay_stream_run", s2)
    monkeypatch.setattr(smoke, "s4_d1_row_state", lambda: (calls.append("S4"), True)[1])

    assert smoke.main() == 0

    out = capsys.readouterr().out
    assert "A12_STREAM_REPLAY_SMOKE=SKIPPED_UPSTREAM" in out
    assert calls == ["S0", "S3", "S4"]
