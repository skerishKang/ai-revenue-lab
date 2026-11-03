"""COM2 Engine-lane mount (2026-11-03): the host composes the lanes like the Worker.

The internal Engine routes (/internal/claw/engine-desktop, /internal/claw/
engine-pc-files) and the connector's mesh-read request route sat inside the #4139
owner-enrollment mount block, which the Cloudflare entry arms with real
Identity+Broker Service Bindings. COM2 has neither binding, so the whole block —
and every Engine lane inside it — never mounted, and a signed Engine call died at
the static catch-all with 405 before its own proof was ever checked. A websocket to
the connector gateway path hit the same catch-all and surfaced as a 500
AssertionError traceback.

These tests build the real host app and pin: a named lane mounts and reaches its
own gates, an unnamed host still does not mount, the secret length rule is shared,
and a websocket is refused explicitly with the gateway off.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import local_cpython

SECRET = "desktop-shared-" + "x" * 40
DESKTOP_PATH = "/internal/claw/engine-desktop"
PC_FILES_PATH = "/internal/claw/engine-pc-files"
MESH_REQUEST_PATH = "/api/claw/connector/mesh-reads/request"
GATEWAY_WSS_PATH = "/api/claw/connector/gateway/session"


def _host_env(tmp_path, monkeypatch, *, lane_named=True, desktop_secret=True):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    if desktop_secret:
        monkeypatch.setenv("CLAW_ENGINE_DESKTOP_SECRET", SECRET)
    else:
        monkeypatch.delenv("CLAW_ENGINE_DESKTOP_SECRET", raising=False)
    if lane_named:
        monkeypatch.setenv("ORACLE_MESH_CHANNEL_SECRET", "channel-" + "y" * 40)
        monkeypatch.setenv("ORACLE_MESH_EXECUTION_MODE", "mesh")
        monkeypatch.setenv("ORACLE_MESH_LEGACY_MAP_LANE", "off")
    else:
        for name in (
            "ORACLE_MESH_CHANNEL_SECRET", "ORACLE_MESH_EXECUTION_MODE",
            "ORACLE_MESH_OWNERSHIP_MAP", "ORACLE_MESH_LEGACY_MAP_LANE",
        ):
            monkeypatch.delenv(name, raising=False)


def _run_status_body() -> bytes:
    return json.dumps(
        {"subject_id": "sub_mount_probe", "run_id": "run_mount_probe", "mode": "run_status"},
        separators=(",", ":"),
    ).encode()


def _signed_headers(body: bytes, secret: str = SECRET) -> dict[str, str]:
    timestamp = str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Claw-Engine-Time": timestamp,
        "X-Claw-Engine-Proof": hmac.new(
            secret.encode(), timestamp.encode("ascii") + b"." + body, hashlib.sha256,
        ).hexdigest(),
    }


def test_the_named_host_mounts_the_engine_lanes_and_reaches_their_own_gates(
    tmp_path, monkeypatch, capsys,
):
    _host_env(tmp_path, monkeypatch)
    app = local_cpython.build_app()
    assert "[local] engine_lanes=mounted_pending_source" in capsys.readouterr().out

    body = _run_status_body()
    with TestClient(app) as client:
        desktop = client.post(DESKTOP_PATH, content=body, headers=_signed_headers(body))
        assert desktop.headers["content-type"].startswith("application/json")
        # Proof verified first: the lane answers with its own next gate, never the
        # catch-all's 405 text answer.
        assert desktop.status_code == 503, desktop.text
        assert desktop.json()["error"]["code"] in (
            "claw_engine_identity_unavailable", "canonical_session_required",
        )

        files_body = json.dumps(
            {"subject_id": "sub_mount_probe", "run_id": "run_mount_probe",
             "device_id": None, "mode": "context"},
            separators=(",", ":"),
        ).encode()
        files = client.post(PC_FILES_PATH, content=files_body, headers=_signed_headers(files_body))
    assert files.status_code in (401, 403, 503), files.text
    assert files.headers["content-type"].startswith("application/json")


def test_the_mesh_read_request_lane_is_mounted_and_stays_fail_closed(tmp_path, monkeypatch):
    _host_env(tmp_path, monkeypatch)
    app = local_cpython.build_app()
    body = json.dumps(
        {"device_id": "dev_1", "run_id": "run_1", "root_ref": "root_1",
         "path_relative": "notes.txt", "confirmed": True},
        separators=(",", ":"),
    ).encode()

    with TestClient(app) as client:
        response = client.post(
            MESH_REQUEST_PATH, content=body, headers={"Content-Type": "application/json"}
        )

    # Mounted: the owner lane answers with its own refusal instead of the 405.
    assert response.status_code in (400, 401, 403, 503), response.text
    assert response.headers["content-type"].startswith("application/json")


def test_an_unnamed_host_still_leaves_the_engine_lanes_unmounted(tmp_path, monkeypatch, capsys):
    _host_env(tmp_path, monkeypatch, lane_named=False)
    app = local_cpython.build_app()
    assert "[local] engine_lanes=unmounted" in capsys.readouterr().out

    body = _run_status_body()
    with TestClient(app) as client:
        response = client.post(DESKTOP_PATH, content=body, headers=_signed_headers(body))
    assert response.status_code == 405


@pytest.mark.parametrize("value", ["", "s" * 31])
def test_a_short_engine_secret_keeps_the_mounted_lane_refusing_before_the_body(
    value, tmp_path, monkeypatch,
):
    _host_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAW_ENGINE_DESKTOP_SECRET", value)
    app = local_cpython.build_app()

    body = _run_status_body()
    with TestClient(app) as client:
        response = client.post(DESKTOP_PATH, content=body, headers=_signed_headers(body))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "claw_engine_desktop_unconfigured"


def test_a_websocket_is_refused_explicitly_while_the_gateway_is_off(tmp_path, monkeypatch):
    _host_env(tmp_path, monkeypatch)
    monkeypatch.delenv("PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED", raising=False)
    app = local_cpython.build_app()

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(GATEWAY_WSS_PATH):
            pass
