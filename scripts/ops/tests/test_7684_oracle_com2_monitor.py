from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from urllib import error

import pytest

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "oracle_com2_monitor" / "oracle_com2_monitor.py"
UNIT = BASE / "oracle_com2_monitor" / "systemd" / "padiem-com2-monitor.service"
TIMER = BASE / "oracle_com2_monitor" / "systemd" / "padiem-com2-monitor.timer"
EXAMPLE = BASE / "oracle_com2_monitor" / "config.example.json"


def _load():
    spec = importlib.util.spec_from_file_location("oracle_com2_monitor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


monitor = _load()


def observation(now=1000.0, age=10.0, chat=200, mesh=200):
    return monitor.Observation(
        now=now,
        heartbeat_age_seconds=age,
        chat_status=chat,
        mesh_status=mesh,
    )


def config_file(tmp_path, **overrides):
    data = {
        "heartbeat_path": str(tmp_path / "heartbeat.json"),
        "heartbeat_stale_seconds": 180,
        "chat_status_url": "https://chat.example.test/health",
        "mesh_status_url": "https://mesh.example.test/",
        "failure_threshold": 2,
        "timeout_seconds": 5,
        "state_path": str(tmp_path / "state.json"),
    }
    data.update(overrides)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def test_single_failure_is_pending_and_silent():
    state, alert = monitor.evaluate(None, observation(age=999.0))
    assert alert is None
    assert state["status"] == monitor.STATUS_PENDING
    assert state["consecutive_failures"] == 1


def test_two_consecutive_failures_emit_one_fault_alert():
    first, alert = monitor.evaluate(None, observation(now=1000.0, chat=503))
    assert alert is None
    second, alert = monitor.evaluate(first, observation(now=1300.0, chat=503))
    assert alert == monitor.ALERT_FAULT
    assert second["status"] == monitor.STATUS_FAULT
    assert second["consecutive_failures"] == 2


def test_repeated_failure_is_suppressed_while_the_fault_is_active():
    first, _ = monitor.evaluate(None, observation(now=1000.0, mesh=None))
    fault, _ = monitor.evaluate(first, observation(now=1300.0, mesh=None))
    again, alert = monitor.evaluate(fault, observation(now=1600.0, mesh=None))
    assert alert is None
    assert again["status"] == monitor.STATUS_FAULT
    assert again["consecutive_failures"] == 3


def test_recovery_alerts_once_and_then_stays_quiet():
    first, _ = monitor.evaluate(None, observation(now=1000.0, age=999.0))
    fault, _ = monitor.evaluate(first, observation(now=1300.0, age=999.0))
    recovered, alert = monitor.evaluate(fault, observation(now=1600.0))
    assert alert == monitor.ALERT_RECOVERY
    assert recovered["status"] == monitor.STATUS_HEALTHY
    assert recovered["consecutive_failures"] == 0
    quiet, alert = monitor.evaluate(recovered, observation(now=1900.0))
    assert alert is None


def test_a_new_episode_after_recovery_can_alert_again():
    first, _ = monitor.evaluate(None, observation(now=1000.0, age=999.0))
    fault, _ = monitor.evaluate(first, observation(now=1300.0, age=999.0))
    recovered, _ = monitor.evaluate(fault, observation(now=1600.0))
    pending, _ = monitor.evaluate(recovered, observation(now=1900.0, age=999.0))
    again, alert = monitor.evaluate(pending, observation(now=2200.0, age=999.0))
    assert alert == monitor.ALERT_FAULT


def test_heartbeat_missing_and_stale_are_distinct_failures():
    missing = observation(age=None, chat=200, mesh=200)
    stale = observation(age=181.0, chat=200, mesh=200)
    assert missing.failures(180) == ("heartbeat_missing",)
    assert stale.failures(180) == ("heartbeat_stale",)
    assert observation(age=180.0).failures(180) == ()


def test_each_public_endpoint_must_answer_2xx():
    failed = observation(chat=503, mesh=None)
    assert failed.failures(180) == ("chat_http_503", "mesh_unreachable")
    assert observation(chat=204, mesh=200).failures(180) == ()


def test_failed_notification_does_not_commit_the_fault_and_is_retried(tmp_path):
    path, data = config_file(tmp_path)
    failed = observation(now=1000.0, age=999.0, chat=200, mesh=200)
    first = monitor.run_once(
        path,
        now=1000.0,
        observer=lambda _cfg, _now: failed,
        notifier=lambda _message: None,
    )
    assert first == 0
    assert json.loads(Path(data["state_path"]).read_text())["status"] == monitor.STATUS_PENDING

    def unavailable(_message):
        raise monitor.NotifyError("telegram_network_error")

    assert monitor.run_once(
        path,
        now=1300.0,
        observer=lambda _cfg, _now: observation(now=1300.0, age=999.0),
        notifier=unavailable,
    ) == 1
    assert json.loads(Path(data["state_path"]).read_text())["status"] == monitor.STATUS_PENDING

    delivered = []
    assert monitor.run_once(
        path,
        now=1600.0,
        observer=lambda _cfg, _now: observation(now=1600.0, age=999.0),
        notifier=delivered.append,
    ) == 0
    state = json.loads(Path(data["state_path"]).read_text())
    assert state["status"] == monitor.STATUS_FAULT
    assert state["last_alert_kind"] == monitor.ALERT_FAULT
    assert len(delivered) == 1


def test_successful_fault_alert_is_not_repeated_on_the_next_run(tmp_path):
    path, data = config_file(tmp_path)
    calls = []
    assert monitor.run_once(
        path,
        now=1000.0,
        observer=lambda _cfg, _now: observation(now=1000.0, age=999.0),
        notifier=calls.append,
    ) == 0
    assert monitor.run_once(
        path,
        now=1300.0,
        observer=lambda _cfg, _now: observation(now=1300.0, age=999.0),
        notifier=calls.append,
    ) == 0
    assert monitor.run_once(
        path,
        now=1600.0,
        observer=lambda _cfg, _now: observation(now=1600.0, age=999.0),
        notifier=calls.append,
    ) == 0
    assert len(calls) == 1
    assert json.loads(Path(data["state_path"]).read_text())["status"] == monitor.STATUS_FAULT


def test_alert_message_contains_no_url_or_credential(tmp_path):
    _path, data = config_file(tmp_path, telegram_token="must-not-appear")
    state, _ = monitor.evaluate(None, observation(now=1000.0, chat=503))
    state, alert = monitor.evaluate(state, observation(now=1300.0, chat=503))
    message = monitor.format_alert(
        alert,
        state,
        observation(now=1300.0, chat=503),
        failure_threshold=2,
    )
    assert "장애 감지" in message
    assert "2회" in message
    assert "HTTP 503" in message
    assert "https://" not in message
    assert "must-not-appear" not in message
    assert "chat.example.test" not in message


def test_telegram_failure_does_not_expose_token_chat_or_response():
    class Failer:
        def __call__(self, _req, timeout=None):
            raise error.URLError("sensitive response detail")

    notifier = monitor.TelegramNotifier(
        "TOKEN-MUST-NOT-LEAK", "CHAT-MUST-NOT-LEAK", opener=Failer()
    )
    with pytest.raises(monitor.NotifyError) as info:
        notifier("hello")
    rendered = str(info.value)
    assert "TOKEN-MUST-NOT-LEAK" not in rendered
    assert "CHAT-MUST-NOT-LEAK" not in rendered
    assert "sensitive" not in rendered


def test_oversized_telegram_message_is_rejected_before_network():
    called = []

    def opener(_req, timeout=None):
        called.append(True)
        raise AssertionError("network must not be reached")

    notifier = monitor.TelegramNotifier("token", "chat", opener=opener)
    with pytest.raises(monitor.NotifyError) as info:
        notifier("x" * 4097)
    assert str(info.value) == "telegram_message_too_large"
    assert called == []


def test_state_round_trip_and_corrupt_state_fall_back_to_healthy(tmp_path):
    path = tmp_path / "state.json"
    state = {
        **monitor._default_state(1000.0),
        "status": monitor.STATUS_PENDING,
        "consecutive_failures": 1,
    }
    monitor.write_state(path, state)
    assert monitor.load_state(path)["status"] == monitor.STATUS_PENDING
    path.write_text("{not json", encoding="utf-8")
    loaded = monitor.load_state(path)
    assert loaded["status"] == monitor.STATUS_HEALTHY
    assert loaded["consecutive_failures"] == 0


def test_config_rejects_too_low_threshold(tmp_path):
    path, _data = config_file(tmp_path, failure_threshold=1)
    with pytest.raises(monitor.MonitorError) as info:
        monitor.load_config(path)
    assert str(info.value) == "config_failure_threshold_too_low"


def test_systemd_units_define_a_five_minute_boot_enabled_timer():
    service = UNIT.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/padiem/com2-monitor.env" in service
    assert "ExecStart=/usr/bin/python3 /opt/padiem/com2-monitor/oracle_com2_monitor.py" in service
    assert "StateDirectory=padiem/com2-monitor" in service
    assert "ReadWritePaths=/var/lib/padiem/com2-monitor" in service
    assert "OnBootSec=2min" in timer
    assert "OnUnitActiveSec=5min" in timer
    assert "WantedBy=timers.target" in timer
    assert "TELEGRAM_BOT_TOKEN=" not in service
    assert "TELEGRAM_CHAT_ID=" not in service


def test_example_config_has_urls_and_no_secret_values():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert data["chat_status_url"] == "https://chat.padiem.net/health"
    assert data["mesh_status_url"] == "https://mesh.padiem.net/"
    assert data["failure_threshold"] == 2
    serialized = json.dumps(data).lower()
    assert "token" not in serialized
    assert "chat_id" not in serialized
    assert "secret" not in serialized
