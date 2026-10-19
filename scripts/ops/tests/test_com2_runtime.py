from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "com2_runtime.py"


def _load():
    spec = importlib.util.spec_from_file_location("com2_runtime_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime = _load()

B62_HEALTH = {
    "status": "ok",
    "app": "padiem-chat",
    "runtime": "b14",
    "live_enabled": True,
}
P01_HEALTH = {
    "status": "ok",
    "service": "padiem-ai-engine",
    "completed_run": True,
    "streaming_run": True,
    "service_identity": "required_for_all_non_health_routes",
}
B14_HEALTH = {"status": "ok", "app": "korean-ai-platform"}


class FakeService:
    def __init__(self, body: dict | None, *, status: int = 200, port: int = 0):
        payload = json.dumps(body or {}).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server contract
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def component(name: str, port: int) -> object:
    path = "/internal/v1/health" if name == "p01" else "/health"
    return runtime.Component(name, "http", port, "start.ps1", path)


def loopback_reader(_port: int):
    return {"127.0.0.1": 1}


def test_parse_listen_addresses_handles_ipv4_and_ipv6_wildcards():
    text = "\n".join(
        [
            "  TCP    127.0.0.1:18764        0.0.0.0:0              LISTENING       1234",
            "  TCP    [::]:18731             [::]:0                 LISTENING       5678",
            "  TCP    127.0.0.1:18717        0.0.0.0:0              LISTENING       999",
        ]
    )
    assert runtime.parse_listen_addresses(text, 18764) == {"127.0.0.1": 1234}
    assert runtime.parse_listen_addresses(text, 18731) == {"::": 5678}
    assert runtime.parse_listen_addresses(text, 18717) == {"127.0.0.1": 999}
    assert runtime.parse_listen_addresses(text, 19000) == {}


def test_collect_status_marks_healthy_and_reports_products(tmp_path):
    b62 = FakeService(B62_HEALTH)
    b14 = FakeService(B14_HEALTH)
    try:
        report = runtime.collect_status(
            tmp_path,
            components=(component("b62", b62.port), component("b14", b14.port)),
            state={"components": {}},
            address_reader=loopback_reader,
        )
    finally:
        b62.stop()
        b14.stop()

    assert report["components"]["b62"]["healthy"] is True
    assert report["components"]["b62"]["contract"] is True
    assert report["components"]["b62"]["loopback_only"] is True
    assert report["components"]["b14"]["healthy"] is True
    assert report["products"]["chat"] == "ready"
    assert report["products"]["claw"] == "ready"
    assert report["products"]["engine"] == "degraded"
    assert report["products"]["quote"] == "source_missing"
    assert report["healthy"] is True


def test_collect_status_fails_non_loopback_listener(tmp_path):
    b62 = FakeService(B62_HEALTH)
    try:
        report = runtime.collect_status(
            tmp_path,
            components=(component("b62", b62.port),),
            state={"components": {}},
            address_reader=lambda _port: {"0.0.0.0": 1},
        )
    finally:
        b62.stop()

    assert report["components"]["b62"]["loopback_only"] is False
    assert report["components"]["b62"]["healthy"] is False
    assert "b62:non_loopback_listener" in report["issues"]


def test_collect_status_rejects_wrong_health_contract(tmp_path):
    b62 = FakeService({"status": "ok", "app": "other", "runtime": "b14"})
    try:
        report = runtime.collect_status(
            tmp_path,
            components=(component("b62", b62.port),),
            state={"components": {}},
            address_reader=loopback_reader,
        )
    finally:
        b62.stop()

    assert report["components"]["b62"]["health"] is True
    assert report["components"]["b62"]["contract"] is False
    assert report["components"]["b62"]["healthy"] is False
    assert "b62:health_contract_failed" in report["issues"]


def test_ensure_does_not_launch_or_kill_when_everything_is_healthy(tmp_path):
    b62 = FakeService(B62_HEALTH)
    launched: list[str] = []
    stopped: list[int] = []
    try:
        report = runtime.ensure(
            tmp_path,
            components=(component("b62", b62.port),),
            launcher=lambda comp, _root, _log: launched.append(comp.name) or os.getpid(),
            stopper=stopped.append,
            address_reader=loopback_reader,
            timeout=5.0,
            health_timeout=2.0,
        )
    finally:
        b62.stop()

    assert report["healthy"] is True
    assert launched == []
    assert stopped == []
    assert report["actions"] == [{"component": "b62", "action": "already_healthy"}]
    assert (tmp_path / runtime.STATE_DIR_NAME / runtime.STATUS_NAME).is_file()


def test_ensure_starts_missing_component_and_records_managed_state(tmp_path):
    holder: dict[str, FakeService] = {}
    launched: list[str] = []

    # Reserve a port with a disposable listener, then use it for the component.
    probe = FakeService(B62_HEALTH)
    port = probe.port
    probe.stop()
    comp = component("b62", port)

    def launcher_on_port(_comp, _root, _log):
        launched.append(_comp.name)
        holder["server"] = FakeService(B62_HEALTH, port=port)
        return os.getpid()

    try:
        report = runtime.ensure(
            tmp_path,
            components=(comp,),
            launcher=launcher_on_port,
            stopper=lambda _pid: None,
            address_reader=loopback_reader,
            timeout=5.0,
            health_timeout=2.0,
        )
    finally:
        if "server" in holder:
            holder["server"].stop()

    assert launched == ["b62"]
    assert report["components"]["b62"]["healthy"] is True
    assert report["actions"][0]["action"] == "started"
    assert report["actions"][0]["ready"] is True
    state = runtime.load_state(tmp_path)
    assert state["components"]["b62"]["pid"] == os.getpid()


def test_ensure_never_kills_unmanaged_unhealthy_listener(tmp_path):
    b62 = FakeService({"status": "fail"}, status=500)
    stopped: list[int] = []
    launched: list[str] = []
    try:
        report = runtime.ensure(
            tmp_path,
            components=(component("b62", b62.port),),
            launcher=lambda comp, _root, _log: launched.append(comp.name) or os.getpid(),
            stopper=stopped.append,
            address_reader=loopback_reader,
            timeout=1.0,
            health_timeout=1.0,
        )
    finally:
        b62.stop()

    assert launched == []
    assert stopped == []
    assert report["actions"] == [
        {"component": "b62", "action": "unmanaged_unhealthy_untouched"}
    ]
    assert report["healthy"] is False


def test_ensure_restarts_only_managed_unhealthy_component(tmp_path):
    b62 = FakeService({"status": "fail"}, status=500)
    launched: list[str] = []
    stopped: list[int] = []
    holder: dict[str, FakeService] = {}

    def stopper(pid: int) -> None:
        stopped.append(pid)
        b62.stop()

    def launcher(comp, _root, _log):
        launched.append(comp.name)
        holder["server"] = FakeService(B62_HEALTH, port=stopped_port)
        return os.getpid()

    stopped_port = b62.port
    state = {
        "kind": runtime.KIND,
        "components": {
            "b62": {"pid": os.getpid(), "started_utc": "2026-10-19T00:00:00Z"},
        },
    }
    runtime.save_state(tmp_path, state)
    try:
        report = runtime.ensure(
            tmp_path,
            components=(component("b62", b62.port),),
            launcher=launcher,
            stopper=stopper,
            address_reader=loopback_reader,
            timeout=5.0,
            health_timeout=2.0,
            restart_cooldown_seconds=0.0,
        )
    finally:
        if "server" in holder:
            holder["server"].stop()

    assert stopped == [os.getpid()]
    assert launched == ["b62"]
    assert report["actions"][0]["action"] == "restarted"
    assert report["actions"][0]["ready"] is True
    assert report["components"]["b62"]["healthy"] is True


def test_restart_and_stop_refuse_unmanaged_components(tmp_path):
    comp = runtime.Component("b62", "http", 9, "start.ps1", "/health")
    for operation in (
        lambda: runtime.restart(tmp_path, "b62", components=(comp,)),
        lambda: runtime.stop_component(tmp_path, "b62", components=(comp,)),
    ):
        try:
            operation()
        except runtime.RuntimeError_ as error:
            assert str(error) == "not_supervised"
        else:  # pragma: no cover - failure path
            raise AssertionError("expected not_supervised")


def test_ensure_restarts_managed_process_that_has_no_listener(tmp_path):
    probe = FakeService(B62_HEALTH)
    port = probe.port
    probe.stop()
    comp = component("b62", port)
    runtime.save_state(
        tmp_path,
        {"kind": runtime.KIND, "components": {"b62": {"pid": os.getpid()}}},
    )
    stopped: list[int] = []
    launched: list[str] = []
    holder: dict[str, FakeService] = {}

    def launcher(component_, _root, _log):
        launched.append(component_.name)
        holder["server"] = FakeService(B62_HEALTH, port=port)
        return os.getpid()

    try:
        report = runtime.ensure(
            tmp_path,
            components=(comp,),
            launcher=launcher,
            stopper=stopped.append,
            address_reader=loopback_reader,
            timeout=5.0,
            health_timeout=2.0,
            restart_cooldown_seconds=0.0,
        )
    finally:
        if "server" in holder:
            holder["server"].stop()

    assert stopped == [os.getpid()]
    assert launched == ["b62"]
    assert report["actions"][0]["action"] == "restarted"
    assert report["components"]["b62"]["healthy"] is True


def test_stop_removes_managed_state(tmp_path):
    comp = runtime.Component("b62", "http", 9, "start.ps1", "/health")
    runtime.save_state(
        tmp_path,
        {"kind": runtime.KIND, "components": {"b62": {"pid": 4242}}},
    )
    stopped: list[int] = []
    report = runtime.stop_component(tmp_path, "b62", components=(comp,), stopper=stopped.append)
    assert stopped == [4242]
    assert report["stopped"] is True
    assert runtime.load_state(tmp_path)["components"] == {}


def test_lock_prevents_overlapping_runs(tmp_path):
    lock = runtime.acquire_lock(tmp_path)
    try:
        try:
            runtime.acquire_lock(tmp_path)
        except runtime.RuntimeBusy:
            pass
        else:  # pragma: no cover - failure path
            raise AssertionError("expected RuntimeBusy")
    finally:
        runtime.release_lock(lock)
    lock = runtime.acquire_lock(tmp_path)
    runtime.release_lock(lock)


def test_verify_reports_loopback_and_product_readiness(tmp_path):
    b62 = FakeService(B62_HEALTH)
    try:
        report = runtime.verify(
            tmp_path,
            components=(component("b62", b62.port),),
            address_reader=loopback_reader,
        )
    finally:
        b62.stop()

    assert report["passed"] is True
    assert report["checks"]["b62"]["loopback_only"] is True
    assert report["products"]["chat"] == "ready"
    assert report["products"]["claw"] == "ready"
    assert report["b66"]["http_listener"] is False


def test_verify_marks_unknown_loopback_evidence_without_failing(tmp_path):
    b62 = FakeService(B62_HEALTH)
    try:
        report = runtime.verify(
            tmp_path,
            components=(component("b62", b62.port),),
            address_reader=lambda _port: None,
        )
    finally:
        b62.stop()

    assert report["passed"] is True
    assert report["checks"]["b62"]["loopback_only"] is None
    assert report["checks"]["b62"]["loopback_evidence"] == "unavailable"


def test_install_task_dry_run_writes_nothing(tmp_path):
    report = runtime.install_task(
        tmp_path,
        script_path=tmp_path / "com2_runtime.py",
        dry_run=True,
    )
    assert report["dry_run"] is True
    assert report["registered"] is False
    assert "ensure" in report["launcher_content"]
    assert "/ST" in report["command"]
    assert "/F" not in report["command"]
    assert not (tmp_path / runtime.STATE_DIR_NAME / "run-supervisor.ps1").exists()


def test_cli_accepts_root_after_subcommand(tmp_path):
    args = runtime._build_parser().parse_args(["ensure", "--root", str(tmp_path)])
    assert args.command == "ensure"
    assert args.root == str(tmp_path)


def test_install_task_force_and_launcher_failure_logging(tmp_path):
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    report = runtime.install_task(
        tmp_path,
        script_path=tmp_path / "com2_runtime.py",
        force=True,
        runner=runner,
    )
    assert report["registered"] is True
    assert "/F" in calls[0]
    launcher = (tmp_path / runtime.STATE_DIR_NAME / "run-supervisor.ps1").read_text(
        encoding="utf-8"
    )
    assert "ensure --root" in launcher
    assert "Add-Content" in launcher
    assert "supervisor.log" in launcher
