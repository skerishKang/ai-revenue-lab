"""#4139: browser-only multi-device targeting projection must remain fail-closed.

These tests execute the real production-loaded handoff module in Node (no
mocked server, no live pairing, no bot credentials, no user PC side effects).
"""
import json
import subprocess
import tempfile
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "static" / "claw-local-handoff.js"


def project(directory, selected=None):
    script = (
        "global.window=globalThis;\n"
        + MODULE.read_text(encoding="utf-8")
        + "\nconst f=window.PadiemClawLocalHandoff.deriveDeviceDirectory;\n"
        + "const output=f("
        + json.dumps(directory, ensure_ascii=False)
        + ","
        + json.dumps(selected)
        + ");\nconsole.log(JSON.stringify(output));"
    )
    # The script is written to a file instead of being passed inline: an
    # inline argument is bounded by the Windows command-line limit, and the
    # module plus a full directory payload can cross it on a real run.
    with tempfile.TemporaryDirectory() as work_dir:
        script_path = Path(work_dir) / "projection.cjs"
        script_path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            ["node", str(script_path)], capture_output=True, text=True, check=True,
        )
    return json.loads(result.stdout)


def online(device_id="office", **extra):
    return {"deviceId": device_id, "state": "CONNECTED", "usable": True, **extra}


def test_unverified_or_unscoped_source_is_never_usable():
    for directory in (None, {}, {"available": True, "devices": [online()]},
                      {"available": True, "ownerScoped": False, "devices": [online()]},
                      {"available": False, "ownerScoped": True, "devices": [online()]}):
        result = project(directory, "office")
        assert result["available"] is False
        assert result["canTarget"] is False
        assert result["devices"] == []


def test_exact_target_is_required_even_for_single_online_pc():
    directory = {"available": True, "ownerScoped": True, "devices": [online()]}
    assert project(directory)["reason"] == "device_selection_required"
    assert project(directory)["selectedDeviceId"] is None
    chosen = project(directory, "office")
    assert chosen["canTarget"] is True
    assert chosen["selectedDeviceId"] == "office"


def test_multiple_pc_online_offline_order_and_selection():
    directory = {"available": True, "ownerScoped": True, "devices": [
        online("home", deviceName="집 PC", platform="Windows"),
        {"deviceId": "laptop", "state": "OFFLINE", "usable": False, "deviceName": "노트북"},
        online("office", deviceName="사무실 PC"),
    ]}
    result = project(directory, "office")
    assert [d["deviceId"] for d in result["devices"]] == ["home", "laptop", "office"]
    assert result["canTarget"] is True
    assert result["selectedDevice"]["deviceName"] == "사무실 PC"
    assert project(directory, "laptop")["reason"] == "device_not_online"
    assert project(directory, "home")["canTarget"] is True
    assert project(directory, "old-pc")["canTarget"] is False


def test_false_online_claim_cannot_resurrect_expired_or_revoked_device():
    for patch in [
        {"expired": True},
        {"revoked": True},
        {"usable": False},
        {"state": "OFFLINE"},
        {"state": "REVOKED"},
        {"state": "MAGIC_ONLINE"},
        {"state": "PAIRING"},
    ]:
        item = online(**patch)
        directory = {"available": True, "ownerScoped": True, "devices": [item]}
        assert project(directory, "office")["canTarget"] is False, patch


def test_an_expired_credential_stays_visible_as_its_own_reason():
    """#3099: the surface must be able to name the real reason.

    An expired credential and a PC that is merely offline are different
    problems with different fixes. The server already distinguishes them, so
    the projection must carry the fact to the surface instead of collapsing
    both into one generic line. It stays presentation only: an expired row
    stays unselectable.
    """
    expired = project(
        {"available": True, "ownerScoped": True,
         "devices": [{"deviceId": "office", "state": "OFFLINE", "usable": False,
                      "expired": True}]},
        None,
    )
    row = expired["devices"][0]
    assert row["expired"] is True
    assert row["selectable"] is False
    assert row["online"] is False

    offline = project(
        {"available": True, "ownerScoped": True,
         "devices": [{"deviceId": "office", "state": "OFFLINE", "usable": False}]},
        None,
    )
    assert offline["devices"][0]["expired"] is False

    revoked = project(
        {"available": True, "ownerScoped": True,
         "devices": [{"deviceId": "office", "state": "REVOKED", "usable": False,
                      "revoked": True}]},
        None,
    )
    assert revoked["devices"][0]["revoked"] is True
    assert revoked["devices"][0]["expired"] is False


def test_invalid_and_duplicate_device_identity_reject_whole_directory():
    for items in [
        [online("a"), online("a")],
        [online("home"), {"deviceId": "not safe/..", "state": "CONNECTED", "usable": True}],
        [{"deviceId": "", "state": "CONNECTED", "usable": True}],
        [online("a" * 129)],
        [online(" home")],
        [None],
        ["home"],
    ]:
        result = project({"available": True, "ownerScoped": True, "devices": items}, "a")
        assert result["available"] is False
        assert result["canTarget"] is False


def test_unbounded_device_directory_refused_not_silently_truncated():
    items = [online(f"pc-{i}") for i in range(25)]
    result = project({"available": True, "ownerScoped": True, "devices": items}, "pc-0")
    assert result["available"] is False
    assert result["canTarget"] is False


def test_no_secrets_or_private_session_data_in_client_projection():
    device = online(
        "office",
        credential="secret-value",
        pairingToken="do-not-expose",
        sessionToken="do-not-expose",
        stdout="private-content",
        account_ref="victim-account",
        workspace_ref="victim-workspace",
    )
    projection = project({"available": True, "ownerScoped": True, "devices": [device]}, "office")
    content = json.dumps(projection)
    assert projection["canTarget"] is True
    for forbidden in ("do-not-expose", "victim-", "private-content", "secret-value"):
        assert forbidden not in content


def test_broker_unknown_fields_never_grant_selection_or_execution():
    directory = {"available": True, "ownerScoped": True, "devices": [
        {"deviceId": "pc", "state": "CONNECTED", "canExecute": True, "approved": True}
    ]}
    result = project(directory, "pc")
    assert result["canTarget"] is False
    assert "approved" not in str(result)
    assert "canExecute" not in str(result)


def test_browser_module_has_no_new_transport_persistence_or_pairing_authority():
    src = MODULE.read_text(encoding="utf-8")
    assert "deriveDeviceDirectory" in src
    assert "new WebSocket" not in src
    assert "fetch(" not in src
    assert "localStorage" not in src
    assert "sessionStorage" not in src
    assert "atob(" not in src
    assert "btoa(" not in src


def test_executable_mesh_target_is_selectable_without_a_broker_heartbeat():
    item = {
        "deviceId": "mesh-pc", "deviceName": None, "platform": None,
        "state": "ACTION_REQUIRED", "usable": False,
        "executable": True, "selectable": True,
    }
    directory = {"available": True, "ownerScoped": True, "devices": [item]}
    unselected = project(directory)
    assert unselected["devices"][0]["executable"] is True
    assert unselected["devices"][0]["selectable"] is True
    assert unselected["canTarget"] is False
    chosen = project(directory, "mesh-pc")
    assert chosen["canTarget"] is True
    assert chosen["selectedDevice"]["executable"] is True
    assert chosen["selectedDevice"]["online"] is False


def test_executable_flag_never_promotes_revoked_expired_or_unflagged_rows():
    base = {
        "deviceId": "mesh-pc", "state": "ACTION_REQUIRED", "usable": False,
        "executable": True, "selectable": True,
    }
    for patch in ({"revoked": True}, {"expired": True}, {"state": "REVOKED"}):
        directory = {"available": True, "ownerScoped": True,
                     "devices": [{**base, **patch}]}
        assert project(directory, "mesh-pc")["canTarget"] is False, patch
    # A selectable hint without the executable fact is not enough.
    directory = {"available": True, "ownerScoped": True, "devices": [{
        "deviceId": "mesh-pc", "state": "ACTION_REQUIRED", "usable": False,
        "executable": False, "selectable": True,
    }]}
    chosen = project(directory, "mesh-pc")
    assert chosen["devices"][0]["selectable"] is False
    assert chosen["canTarget"] is False
