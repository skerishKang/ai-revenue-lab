"""Inventory relay, retries, queue routing and production startup (no live PC)."""
import copy
from unittest.mock import Mock, patch

import pytest

from kagent.local_agent_mesh_drive_reporter import (
    DRIVE_REFRESH_SECONDS, DRIVES_PATH, DRIVE_TARGETS_PATH, MeshDriveReporter,
)
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor, POLL_PATH

NODE = "node//synthetic-pc-one"
OTHER = "node//unpaired-pc"
DRIVE = {"path": "C:/", "name": "System", "kind": "fixed",
         "free_bytes": 200, "total_bytes": 500}
USB = {"path": "E:/", "name": "USB", "kind": "removable",
       "free_bytes": 30, "total_bytes": 100}


def test_changed_snapshots_only_and_retry_after_queue_failure():
    rows = [{"device_id": NODE, "drives": [DRIVE]}]
    sent = []
    status = 200

    def post(path, payload):
        if path == DRIVE_TARGETS_PATH:
            return 200, {"ok": True, "device_ids": [NODE]}
        assert path == DRIVES_PATH
        sent.append(copy.deepcopy(payload))
        return status, {"ok": status == 200}

    reporter = MeshDriveReporter(post=post, source=lambda ids: rows)
    assert reporter.tick() == 1
    assert reporter.tick() == 0
    rows[0]["drives"] = [USB, DRIVE]
    status = 503
    assert reporter.tick() == 0
    status = 200
    assert reporter.tick() == 1  # Failed send did not acknowledge this snapshot.
    rows[0]["drives"] = [DRIVE, USB]
    assert reporter.tick() == 0  # Order alone is not a changed inventory.
    rows[0]["drives"] = []
    assert reporter.tick() == 1
    assert sent[-1]["drives"] == []


def test_failed_probe_is_not_a_drive_removal_and_unpaired_nodes_are_never_reported():
    post = Mock(side_effect=lambda path, payload: (
        (200, {"ok": True, "device_ids": [NODE]}) if path == DRIVE_TARGETS_PATH
        else (200, {"ok": True})))
    source = Mock(return_value=[{"device_id": OTHER, "drives": [DRIVE]},
                               {"device_id": NODE, "drives": None}])
    reporter = MeshDriveReporter(post=post, source=source)
    assert reporter.tick() == 0
    source.assert_called_once_with([NODE])
    assert post.call_count == 1
    source.side_effect = OSError("synthetic disconnected PC")
    assert reporter.tick() == 0
    assert post.call_count == 2


@pytest.mark.parametrize("targets", [None, {}, [None], ["bad\nnode"]])
def test_unusable_target_authority_never_probes_pc(targets):
    source = Mock()
    reporter = MeshDriveReporter(post=lambda *a: (200, {"ok": True, "device_ids": targets}),
                                 source=source)
    assert reporter.tick() == 0
    source.assert_not_called()


def test_paused_executor_does_not_read_pc_or_queue():
    post, source = Mock(), Mock()
    reporter = MeshDriveReporter(post=post, source=source, may_report=lambda: False)
    assert reporter.tick() == 0
    post.assert_not_called()
    source.assert_not_called()
    reporter._may_report = Mock(side_effect=OSError("unavailable authority"))
    assert reporter.tick() == 0


def test_unpaired_then_repaired_device_reports_again():
    targets = [NODE]
    sent = []
    def post(path, payload):
        if path == DRIVE_TARGETS_PATH:
            return 200, {"ok": True, "device_ids": targets[:]}
        sent.append(payload)
        return 200, {"ok": True}
    reporter = MeshDriveReporter(post=post, source=lambda ids: [{"device_id": NODE, "drives": [DRIVE]}])
    assert reporter.tick() == 1
    targets.clear()
    assert reporter.tick() == 0
    targets.append(NODE)
    assert reporter.tick() == 1


def executor(**kwargs):
    return OracleMeshExecutor(chat_origin="https://chat.example.test",
        channel_secret="synthetic-channel-secret", read_port=Mock(), **kwargs)


def test_reports_use_authenticated_8797_and_do_not_refresh_command_watchdog(capsys):
    lane = executor(queue_origin="http://127.0.0.1:8797")
    lane._last_round_at = 1
    response = Mock(status=200)
    response.read.return_value = b'{"ok":true}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    with patch("urllib.request.build_opener", return_value=opener):
        for path in (DRIVES_PATH, DRIVE_TARGETS_PATH):
            lane._https_post(path, {})
            request = opener.open.call_args.args[0]
            assert request.full_url == "http://127.0.0.1:8797" + path
            assert dict(request.header_items())["X-oracle-mesh-secret"] == "synthetic-channel-secret"
            assert lane._last_round_at == 1
        lane._https_post(POLL_PATH, None)
        assert lane._last_round_at > 1
    assert "synthetic-channel-secret" not in str(capsys.readouterr())


def test_only_queue_executor_starts_one_independent_reporter():
    assert DRIVE_REFRESH_SECONDS == 30
    with patch.object(MeshDriveReporter, "start") as start:
        assert executor().start_drive_reporting(Mock()) is None
        start.assert_not_called()
        lane = executor(queue_origin="http://127.0.0.1:8797")
        first = lane.start_drive_reporting(Mock())
        assert lane.start_drive_reporting(Mock()) is first
        assert start.call_count == 2  # start itself is idempotent.


def test_production_entrypoint_automatically_wires_existing_mesh_credentials():
    import kagent.local_agent_oracle_mesh_executor as entry
    import kagent.local_agent_mesh_drive_inventory as inventory
    class Stop(Exception):
        pass
    lane = Mock()
    lane.load_pending.return_value = False
    lane.run_once.side_effect = Stop
    password_provider = Mock()
    env = {"ORACLE_MESH_PASSWORD_FILE": "fixture-password-path",
           "ORACLE_MESH_CHANNEL_SECRET_FILE": "fixture-channel-path",
           "ORACLE_MESH_MESHCTRL_JS": "fixture-meshctrl.js",
           "ORACLE_MESH_LOGIN_USER": "synthetic",
           "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
           "ORACLE_MESH_QUEUE_ORIGIN": "http://127.0.0.1:8797"}
    with patch.object(entry, "deployment_secret_password_provider", return_value=password_provider), \
         patch.object(entry, "_read_secret_file", return_value="synthetic-channel-secret"), \
         patch.object(entry, "make_oracle_mesh_executor", return_value=lane), \
         patch.object(inventory, "MeshDriveInventorySource") as source:
        with pytest.raises(Stop):
            entry.main(env)
        source.assert_called_once_with(meshctrl_js="fixture-meshctrl.js",
            mesh_url="wss://127.0.0.1:4443", login_user="synthetic", password_provider=password_provider)
        lane.start_drive_reporting.assert_called_once_with(source.return_value)
        password_provider.assert_not_called()
