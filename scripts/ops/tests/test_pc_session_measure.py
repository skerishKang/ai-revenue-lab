"""Offline contract for the PC session measurement tool (#7065 slice 10).

The tool module is loaded from the worktree file itself (the changed file),
so every test here reads the exact revision under review. Wall clock and
monotonic clock are both frozen: ``FakeClock`` fixes monotonic time and
``fixed_now`` fixes the current wall time together.
"""
from __future__ import annotations

import importlib.util
import pathlib
import threading
from datetime import datetime, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "pc_session_measure", REPO / "scripts" / "ops" / "pc_session_measure.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure = _load()

FIXED_NOW = datetime(2026, 11, 14, 13, 0, 0, tzinfo=timezone.utc)
ON = {"PADIEM_MCP_PC_SESSION_ENABLED": "true", "PADIEM_CHAT_PC_SESSION_ENABLED": "true"}
FAKE_SECRET = "Bearer FAKE-VALUE-00000000.example-only"


class FakeClock:
    """Frozen wall + monotonic pair: sleep advances monotonic only."""

    def __init__(self) -> None:
        self.t = 1000.0
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self.t

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds

    def now(self) -> datetime:
        return FIXED_NOW


class FakeClient:
    """Scripted fake session server: latencies, outputs, failures, cleanup
    lag, and the per-PC interactive session limit (max_live, default 4):
    the (max_live + 1)-th live session is refused with ``limit_error_code``
    (default ``pc_session_limit``) unless ``max_live=None`` disables it."""

    def __init__(self, clock: FakeClock, *, latencies=None, output="ok",
                 fail_starts=0, fail_roundtrip_calls=(), cleanup_delay=0.0,
                 switch_off=False, kill_after_roundtrips=None,
                 latency_overrides=None, max_live=4,
                 limit_error_code="pc_session_limit"):
        self.clock = clock
        self.latencies = list(latencies) if latencies is not None else [1.0]
        self.output = output
        self.fail_starts = fail_starts
        self.fail_roundtrip_calls = set(fail_roundtrip_calls)
        self.cleanup_delay = cleanup_delay
        self.switch_off = switch_off
        self.kill_after = kill_after_roundtrips
        self.latency_overrides = dict(latency_overrides or {})
        self.max_live = max_live
        self.limit_error_code = limit_error_code
        self._lock = threading.Lock()
        self._seq = 0
        self._stopped_at: dict = {}
        self._roundtrips_done = 0
        self._live = 0
        self.started_count = 0
        self.stopped_count = 0

    def start(self, command=""):
        if self.switch_off:
            raise measure.SessionError("pc_session_disabled")
        with self._lock:
            self.started_count += 1
            if self.fail_starts > 0:
                self.fail_starts -= 1
                raise measure.SessionError("pc_session_limit")
            if self.max_live is not None and self._live >= self.max_live:
                raise measure.SessionError(self.limit_error_code)
            self._seq += 1
            handle = "fake-%d" % self._seq
            self._live += 1
        self.clock.sleep(0.05)
        return handle

    def roundtrip(self, handle, text):
        with self._lock:
            self._roundtrips_done += 1
            call_no = self._roundtrips_done
            delay = self.latency_overrides.get(
                call_no, self.latencies[0] if len(self.latencies) == 1
                else self.latencies.pop(0))
            fail = call_no in self.fail_roundtrip_calls
        if fail:
            raise measure.SessionError("pc_session_unavailable")
        self.clock.sleep(delay)
        return self.output

    def stop(self, handle):
        with self._lock:
            self.stopped_count += 1
            self._stopped_at[handle] = self.clock.monotonic()
            if self._live > 0:
                self._live -= 1
        self.clock.sleep(0.05)

    def is_alive(self, handle):
        with self._lock:
            if self.kill_after is not None and self._roundtrips_done >= self.kill_after:
                return False
            stopped_at = self._stopped_at.get(handle)
            if stopped_at is None:
                return True
            return (self.clock.monotonic() - stopped_at) < self.cleanup_delay


def _run(client_maker, **kwargs):
    clock = FakeClock()
    client = client_maker(clock)
    factory_calls = []

    def factory(device):
        factory_calls.append(device)
        return client

    kwargs.setdefault("devices", ["comp1"])
    kwargs.setdefault("environ", dict(ON))
    result = measure.run_measurement(
        factory, monotonic=clock.monotonic, sleep=clock.sleep,
        should_stop=kwargs.pop("should_stop", lambda: False), **kwargs)
    return result, factory_calls, clock


def test_switch_off_does_nothing():
    client = FakeClient(FakeClock())
    for environ in ({}, {"PADIEM_MCP_PC_SESSION_ENABLED": "true"},
                    {"PADIEM_CHAT_PC_SESSION_ENABLED": "true"},
                    {"PADIEM_MCP_PC_SESSION_ENABLED": "false",
                     "PADIEM_CHAT_PC_SESSION_ENABLED": "true"}):
        result, calls, _ = _run(lambda c: client, environ=environ)
        assert result["verdict"] == "SWITCH_OFF"
        assert calls == []
    assert client.started_count == 0


def test_switch_on_variants():
    assert measure.switches_enabled(ON)
    assert measure.switches_enabled({"PADIEM_MCP_PC_SESSION_ENABLED": "1",
                                     "PADIEM_CHAT_PC_SESSION_ENABLED": "TRUE"})
    assert not measure.switches_enabled({"PADIEM_MCP_PC_SESSION_ENABLED": "true"})


def test_server_side_switch_off():
    result, _, _ = _run(lambda c: FakeClient(c, switch_off=True))
    assert result["verdict"] == "SWITCH_OFF"


def test_pass_all_criteria():
    client = FakeClient(FakeClock(), latencies=[1.0])
    result, calls, _ = _run(lambda c: client)
    assert result["verdict"] == "PASS"
    assert result["concurrent"] == {"started": 30, "failures": 0, "rounds": 8,
                                    "per_round": 4, "limit": "REJECTED",
                                    "passed": True}
    assert result["roundtrips"]["count"] == 120
    assert result["roundtrips"]["passed"] is True
    assert result["cleanup"]["passed"] is True
    assert result["secret_hits"] == 0
    assert result["keep"]["skipped"] is True
    assert result["remaining"] == 0
    assert calls == ["comp1"]


def test_summary_line_carries_only_numbers_and_codes():
    result, _, _ = _run(lambda c: FakeClient(c))
    line = measure.summary_line(result)
    assert line.startswith("PC_SESSION_MEASURE verdict=PASS ")
    assert " rounds=" in line and " per_round=" in line
    assert " limit=REJECTED" in line
    assert "fake-" not in line  # session handles never printed
    assert "comp1" not in line


def test_concurrent_round_failure_fails():
    result, _, _ = _run(lambda c: FakeClient(c, fail_starts=1))
    assert result["verdict"] == "FAIL"
    assert result["concurrent"]["failures"] == 1
    assert result["concurrent"]["started"] == 29
    assert result["concurrent"]["rounds"] == 8
    assert result["concurrent"]["limit"] == "REJECTED"
    assert result["concurrent"]["passed"] is False


def test_concurrent_rounds_two_devices_split():
    """PC-count × 4 per round, rounds repeat to 30, limit check on one PC."""
    clock = FakeClock()
    clients = {"comp1": FakeClient(clock), "comp2": FakeClient(clock)}
    result = measure.run_measurement(
        lambda device: clients[device], devices=["comp1", "comp2"],
        environ=dict(ON), monotonic=clock.monotonic, sleep=clock.sleep)
    concurrent = result["concurrent"]
    assert concurrent["per_round"] == 8
    assert concurrent["rounds"] == 4  # 8+8+8+6
    assert concurrent["started"] == 30
    assert concurrent["failures"] == 0
    assert concurrent["limit"] == "REJECTED"
    assert result["verdict"] == "PASS"
    assert result["remaining"] == 0
    # comp1: 15 rounds + 4 held + 1 refused attempt + roundtrip probe
    # + cleanup probe; comp2: 15 rounds only
    assert clients["comp1"].started_count == 22
    assert clients["comp2"].started_count == 15


def test_over_limit_session_opened_fails_and_is_closed():
    clock = FakeClock()
    client = FakeClient(clock, max_live=None)  # fake without the per-PC limit
    result = measure.run_measurement(
        lambda device: client, devices=["comp1"], environ=dict(ON),
        monotonic=clock.monotonic, sleep=clock.sleep)
    assert result["concurrent"]["limit"] == "OPENED"
    assert result["concurrent"]["passed"] is False
    assert result["verdict"] == "FAIL"
    # 30 rounds + 4 held + 1 over-limit extra + roundtrip probe + cleanup
    # probe; every opened session closed again
    assert client.started_count == 37
    assert client.stopped_count >= 35
    assert result["remaining"] == 0


def test_over_limit_other_error_fails():
    clock = FakeClock()
    client = FakeClient(clock, limit_error_code="pc_session_unavailable")
    result = measure.run_measurement(
        lambda device: client, devices=["comp1"], environ=dict(ON),
        monotonic=clock.monotonic, sleep=clock.sleep)
    assert result["concurrent"]["limit"] == "ERROR"
    assert result["concurrent"]["passed"] is False
    assert result["verdict"] == "FAIL"
    assert result["remaining"] == 0


def test_concurrent_failure_fails():
    result, _, _ = _run(lambda c: FakeClient(c, fail_starts=2))
    assert result["verdict"] == "FAIL"
    assert result["concurrent"]["failures"] == 2
    assert result["concurrent"]["passed"] is False


@pytest.mark.parametrize("maker,expect_pass", [
    (lambda c: FakeClient(c, latencies=[9.0]), False),          # median 9 s
    (lambda c: FakeClient(c, latency_overrides={60: 21.0}), False),  # max 21 s
    (lambda c: FakeClient(c, latencies=[1.0]), True),
])
def test_roundtrip_latency_failure_fails(maker, expect_pass):
    result, _, _ = _run(maker)
    assert result["roundtrips"]["passed"] is expect_pass
    if not expect_pass:
        assert result["verdict"] == "FAIL"


def test_roundtrip_success_rate_failure_fails():
    result, _, _ = _run(lambda c: FakeClient(c, fail_roundtrip_calls={31, 32, 33}))  # 3/120 = 97.5%
    assert result["roundtrips"]["success_rate"] < 0.99
    assert result["roundtrips"]["passed"] is False
    assert result["verdict"] == "FAIL"


def test_cleanup_delay_failure_fails():
    result, _, _ = _run(lambda c: FakeClient(c, cleanup_delay=6.0))
    assert result["cleanup"]["passed"] is False
    assert result["cleanup"]["elapsed_s"] >= 5.0
    assert result["verdict"] == "FAIL"


def test_secret_in_output_fails_and_is_not_printed():
    result, _, _ = _run(lambda c: FakeClient(c, output=FAKE_SECRET))
    assert result["secret_hits"] > 0
    assert result["verdict"] == "FAIL"
    line = measure.summary_line(result)
    assert FAKE_SECRET not in line
    assert "FAKE-VALUE" not in line


@pytest.mark.parametrize("text,cls", [
    ("Authorization: abcdefghijklmnop", "auth_header"),
    ("Cookie: session=abcdefgh", "cookie"),
    ("eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturepart", "jwt"),
    ("sk-proj" + "FAKEFAKEFAKEFAKE", "api_key"),
    ("user@example.invalid", "account_email"),
    ("a" * 64, "hex_token"),
])
def test_secret_patterns(text, cls):
    counts = measure.scan_secrets([text])
    assert counts[cls] >= 1
    assert sum(counts.values()) >= 1


def test_secret_scan_clean_text():
    assert sum(measure.scan_secrets(["ok", "prompt> ", "echo 42"]).values()) == 0


def test_keep_excluded_by_default():
    result, _, _ = _run(lambda c: FakeClient(c))
    assert result["keep"] == {"skipped": True, "held_s": 0.0, "passed": False}
    assert "keep=SKIPPED" in measure.summary_line(result)


def test_keep_check_pass():
    result, _, _ = _run(lambda c: FakeClient(c), keep_check=True, keep_seconds=180.0)
    assert result["keep"]["skipped"] is False
    assert result["keep"]["passed"] is True
    assert result["keep"]["held_s"] >= 180.0
    assert result["verdict"] == "PASS"


def test_keep_check_session_death_fails():
    result, _, _ = _run(lambda c: FakeClient(c, kill_after_roundtrips=152), keep_check=True, keep_seconds=180.0)
    assert result["keep"]["passed"] is False
    assert result["verdict"] == "FAIL"


def test_interrupt_closes_all_sessions():
    clock = FakeClock()
    state = {"roundtrips": 0}

    class InterruptClient(FakeClient):
        def roundtrip(self, handle, text):
            out = super().roundtrip(handle, text)
            with self._lock:
                self._roundtrips_done += 1
            return out

    client = InterruptClient(clock)

    def should_stop():
        return state["roundtrips"] >= 10

    # Count roundtrips through the fake itself: flip the flag after 10 calls
    # of the roundtrip phase by wrapping the runner's sleep-free path.
    orig_roundtrip = client.roundtrip

    def counting_roundtrip(handle, text):
        out = orig_roundtrip(handle, text)
        state["roundtrips"] += 1
        return out

    client.roundtrip = counting_roundtrip
    result = measure.run_measurement(
        lambda device: client, devices=["comp1"], environ=dict(ON),
        monotonic=clock.monotonic, sleep=clock.sleep, should_stop=should_stop)
    assert result["verdict"] == "INTERRUPTED"
    assert result["remaining"] == 0
    assert client.stopped_count >= client.started_count - 1  # every open session closed


def test_main_switch_off_needs_no_token(capsys, tmp_path):
    clock = FakeClock()
    code = measure.main(["measure"], environ={}, monotonic=clock.monotonic,
                        sleep=clock.sleep, wall_now=clock.now)
    assert code == measure.EXIT_SWITCH_OFF
    out = capsys.readouterr().out
    assert out == measure.summary_line(
        measure.run_measurement(lambda d: None, devices=["comp1"], environ={},
                                monotonic=clock.monotonic, sleep=clock.sleep)) + "\n"


def test_median_helper():
    assert measure._median([1.0, 3.0, 2.0]) == 2.0
    assert measure._median([]) == 0.0
