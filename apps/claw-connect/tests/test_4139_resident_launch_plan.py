"""#4139 STEP 3 — the Resident the Connector supervises is actually launchable.

The gap this pins: the Connector built its ``ResidentSupervisor`` with no
environment, so the supervised Resident was started without the canonical
Broker boundary it reads (``BrokerEntry.from_environment``) and refused at once
(``no_configured_broker_boundary``). A tray start therefore never reached a
task-receiving Resident, and nothing in ``status()`` said why.

These tests use a synthetic enrollment record and an injected ``popen`` so no
real Resident, registry key, DPAPI blob, Broker or user file is touched.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw_connect import runtime as runtime_module
from claw_connect.enrollment import (
    LIFECYCLE_CREDENTIAL_EXPIRED,
    LIFECYCLE_PAIRED_OFFLINE,
    LIFECYCLE_REVOKED,
    EnrollmentRecord,
)
from claw_connect.resident_launch import (
    REASON_AUTHORITY_REF_UNCONFIGURED,
    REASON_BROKER_URL_UNCONFIGURED,
    REASON_CREDENTIAL_DIR_INVALID,
    REASON_CREDENTIAL_DIR_UNCONFIGURED,
    REASON_ENROLLMENT_NOT_LIVE,
    REASON_NO_COMMITTED_ENROLLMENT,
    REASON_REQUEST_PORT_UNCONFIGURED,
    RESIDENT_ENV_AUTHORITY_REF,
    RESIDENT_ENV_BROKER_URL,
    RESIDENT_ENV_CREDENTIAL_DIR,
    RESIDENT_ENV_DEVICE_ID,
    RESIDENT_ENV_REQUEST_PORT,
    plan_resident_launch,
)
from claw_connect.resident_supervisor import ResidentSupervisor
from claw_connect.runtime import ConnectApp

DEVICE_ID = "device.4139.resident.launch"
AUTHORITY_REF = "control-plane.local-agent-broker.4139.launch.v1"
REQUEST_PORT = "kagent.local_agent_broker_pairing_handoff_entry:resident_request_port"
BROKER_URL = "https://local-agent.padiem.net"


def _record(**overrides) -> EnrollmentRecord:
    values = {
        "device_id": DEVICE_ID,
        "binding_ref": "binding.4139.1",
        "account_ref": "account.4139",
        "workspace_ref": "workspace.4139",
        "credential_generation": 1,
        "credential_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "device_lifecycle": LIFECYCLE_PAIRED_OFFLINE,
        "revoked": False,
    }
    values.update(overrides)
    return EnrollmentRecord(**values)


def _configured(monkeypatch, tmp_path: Path) -> str:
    credential_dir = tmp_path / "canonical-credential-store"
    monkeypatch.setenv(RESIDENT_ENV_CREDENTIAL_DIR, str(credential_dir))
    monkeypatch.setenv(RESIDENT_ENV_AUTHORITY_REF, AUTHORITY_REF)
    monkeypatch.setenv(RESIDENT_ENV_REQUEST_PORT, REQUEST_PORT)
    monkeypatch.setenv(RESIDENT_ENV_BROKER_URL, BROKER_URL)
    return str(credential_dir)


# -- the plan reuses the Resident's own configuration contract ---------------


def test_plan_reuses_the_exact_environment_keys_the_resident_reads(monkeypatch, tmp_path):
    credential_dir = _configured(monkeypatch, tmp_path)
    plan, reason = plan_resident_launch(record=_record())

    assert reason == "planned"
    assert plan is not None
    # Exactly the Resident's own keys — no sixth key, no secret, no credential.
    assert plan.environment(base={}) == {
        RESIDENT_ENV_DEVICE_ID: DEVICE_ID,
        RESIDENT_ENV_AUTHORITY_REF: AUTHORITY_REF,
        RESIDENT_ENV_CREDENTIAL_DIR: credential_dir,
        RESIDENT_ENV_REQUEST_PORT: REQUEST_PORT,
        RESIDENT_ENV_BROKER_URL: BROKER_URL,
    }


def test_the_broker_url_key_is_pinned_as_the_text_the_factory_reads():
    """Pinned literally, not only as the imported constant.

    ``PADIEM_AGENT_REQUEST_PORT`` names a ``module:factory``; that factory reads
    ``PADIEM_AGENT_BROKER_URL`` itself and refuses without it. A rename on
    either side would spawn a child that dies constructing its request port,
    before it can emit any bounded refusal — so the key is pinned as text.
    """
    assert RESIDENT_ENV_BROKER_URL == "PADIEM_AGENT_BROKER_URL"


def test_plan_never_mints_an_identity_without_a_committed_record(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    plan, reason = plan_resident_launch(record=None)

    assert plan is None
    assert reason == REASON_NO_COMMITTED_ENROLLMENT


@pytest.mark.parametrize(
    "overrides",
    [
        {"binding_ref": None},
        {"revoked": True},
        {"device_lifecycle": LIFECYCLE_REVOKED},
        {"device_lifecycle": LIFECYCLE_CREDENTIAL_EXPIRED},
        {"credential_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ],
    ids=["never-enrolled", "revoked", "revoked-lifecycle", "expired-lifecycle", "expired"],
)
def test_plan_refuses_a_record_that_is_not_live(monkeypatch, tmp_path, overrides):
    _configured(monkeypatch, tmp_path)
    plan, reason = plan_resident_launch(record=_record(**overrides))

    assert plan is None
    assert reason == REASON_ENROLLMENT_NOT_LIVE


@pytest.mark.parametrize(
    "missing, expected",
    [
        (RESIDENT_ENV_CREDENTIAL_DIR, REASON_CREDENTIAL_DIR_UNCONFIGURED),
        (RESIDENT_ENV_AUTHORITY_REF, REASON_AUTHORITY_REF_UNCONFIGURED),
        (RESIDENT_ENV_REQUEST_PORT, REASON_REQUEST_PORT_UNCONFIGURED),
        (RESIDENT_ENV_BROKER_URL, REASON_BROKER_URL_UNCONFIGURED),
    ],
)
def test_plan_refuses_an_unconfigured_canonical_boundary(
    monkeypatch, tmp_path, missing, expected
):
    _configured(monkeypatch, tmp_path)
    monkeypatch.delenv(missing)
    plan, reason = plan_resident_launch(record=_record())

    assert plan is None
    assert reason == expected


@pytest.mark.parametrize(
    "broker_url",
    [
        "",
        "local-agent.padiem.net",  # no scheme: not an origin
        "http://local-agent.padiem.net",  # cleartext credential delivery
        "https://user:pass@local-agent.padiem.net",  # credentials in the URL
        "https://local-agent.padiem.net?debug=1",  # query on the broker origin
        "https://local-agent.padiem.net#frag",
    ],
    ids=["empty", "scheme-less", "cleartext", "userinfo", "query", "fragment"],
)
def test_plan_refuses_a_broker_url_the_resident_must_not_send_a_credential_to(
    monkeypatch, tmp_path, broker_url
):
    """The Resident carries the device credential to this origin.

    The Connector already pins https/443, credentials-free, query-free for the
    broker it enrolls against; the Resident's origin is held to the same
    contract so a plan cannot loosen it.
    """
    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(RESIDENT_ENV_BROKER_URL, broker_url)
    plan, reason = plan_resident_launch(record=_record())

    assert plan is None
    assert reason == REASON_BROKER_URL_UNCONFIGURED


def test_plan_refuses_a_relative_credential_dir(monkeypatch):
    monkeypatch.setenv(RESIDENT_ENV_CREDENTIAL_DIR, "relative/store")
    monkeypatch.setenv(RESIDENT_ENV_AUTHORITY_REF, AUTHORITY_REF)
    monkeypatch.setenv(RESIDENT_ENV_REQUEST_PORT, REQUEST_PORT)
    monkeypatch.setenv(RESIDENT_ENV_BROKER_URL, BROKER_URL)
    plan, reason = plan_resident_launch(record=_record())

    assert plan is None
    assert reason == REASON_CREDENTIAL_DIR_INVALID


def test_plan_safe_dict_exposes_no_secret_or_path(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    plan, _ = plan_resident_launch(record=_record())

    safe = plan.safe_dict()
    assert safe["raw_device_credential"] is False
    assert safe["second_broker_authority"] is False
    assert safe["new_device_identity"] is False
    assert str(tmp_path) not in repr(safe)


# -- the Connector actually starts it, with that environment -----------------


class _FakeProcess:
    """Minimal stand-in so the real supervisor is exercised without a child."""

    def __init__(self) -> None:
        self.pid = 4321
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = 0


class _FakeEnrollment:
    def __init__(self, record) -> None:
        self._record = record
        self.state_dir = Path(".")

    def committed_record(self):
        return self._record

    def project_state(self, *, paused: bool, connected: bool):
        from claw_connect.connection import ConnectionState

        return ConnectionState.OFFLINE

    def status_snapshot(self):
        return {}


class _FakeAutostart:
    def is_enabled(self) -> bool:
        return False

    def register_after_install(self, command, record):
        return None

    def enable(self, command, record) -> None:
        return None

    def disable(self) -> None:
        return None


def _app(monkeypatch, record, calls: list) -> ConnectApp:
    """Build the real app, but capture the child spawn instead of performing it.

    The supervisor factory is patched so the app's own launch-environment
    provider is the one under test — injecting a ready-made supervisor would
    bypass exactly the wiring this regression is about.
    """
    real = ResidentSupervisor

    def factory(command, *, popen=subprocess.Popen, env=None):
        def recording_popen(cmd, **kwargs):
            calls.append({"command": list(cmd), "env": kwargs.get("env")})
            return _FakeProcess()

        return real(command, popen=recording_popen, env=env)

    monkeypatch.setattr(runtime_module, "ResidentSupervisor", factory)
    return ConnectApp(enrollment=_FakeEnrollment(record), autostart=_FakeAutostart())


def test_connect_app_does_not_launch_a_resident_it_cannot_configure(
    monkeypatch, tmp_path
):
    _configured(monkeypatch, tmp_path)
    calls: list = []
    app = _app(monkeypatch, None, calls)

    assert app.start_registered_resident() is False
    assert calls == []
    assert app.status()["resident_launch_reason"] == REASON_NO_COMMITTED_ENROLLMENT


def test_connect_app_launches_the_resident_with_the_canonical_boundary(
    monkeypatch, tmp_path
):
    credential_dir = _configured(monkeypatch, tmp_path)
    calls: list = []
    app = _app(monkeypatch, _record(), calls)

    assert app.start_registered_resident() is True
    assert len(calls) == 1
    env = calls[0]["env"]
    assert env is not None
    assert env[RESIDENT_ENV_DEVICE_ID] == DEVICE_ID
    assert env[RESIDENT_ENV_AUTHORITY_REF] == AUTHORITY_REF
    assert env[RESIDENT_ENV_CREDENTIAL_DIR] == credential_dir
    assert env[RESIDENT_ENV_REQUEST_PORT] == REQUEST_PORT
    assert env[RESIDENT_ENV_BROKER_URL] == BROKER_URL
    assert app.status()["resident_launch_reason"] == "planned"


def test_connect_app_does_not_launch_a_resident_without_the_boundary(
    monkeypatch, tmp_path
):
    _configured(monkeypatch, tmp_path)
    monkeypatch.delenv(RESIDENT_ENV_REQUEST_PORT)
    calls: list = []
    app = _app(monkeypatch, _record(), calls)

    assert app.start_registered_resident() is False
    assert calls == []
    assert app.status()["resident_launch_reason"] == REASON_REQUEST_PORT_UNCONFIGURED


def test_connect_app_does_not_launch_a_resident_without_the_broker_origin(
    monkeypatch, tmp_path
):
    """The factory the plan points at refuses without this key.

    Spawning anyway would produce a child that dies constructing its request
    port — the short-lived process this whole gate exists to prevent.
    """
    _configured(monkeypatch, tmp_path)
    monkeypatch.delenv(RESIDENT_ENV_BROKER_URL)
    calls: list = []
    app = _app(monkeypatch, _record(), calls)

    assert app.start_registered_resident() is False
    assert calls == []
    assert app.status()["resident_launch_reason"] == REASON_BROKER_URL_UNCONFIGURED


def test_planning_alone_never_spawns_a_process(monkeypatch, tmp_path):
    """The launch plan is read by the gate too, so it must stay side-effect free."""
    _configured(monkeypatch, tmp_path)
    calls: list = []
    app = _app(monkeypatch, _record(), calls)

    assert app._resident_environment() is not None
    assert app._resident_environment() is not None
    assert calls == []


def test_connect_app_never_spawns_once_the_registration_is_gone(
    monkeypatch, tmp_path
):
    """The plan gates the action, then the environment is resolved again.

    ``start_registered_resident()`` resolves the committed enrollment to decide
    whether the Resident is launchable, and the supervisor resolves the same
    environment again at the spawn. Between the two the enrollment can be
    revoked, replaced, or switched off by the owner. In that window the old
    supervisor would have run ``Popen`` with no ``env`` argument, so the child
    would have inherited the parent environment and started a Resident nobody
    had configured. Nothing may be spawned here.
    """
    _configured(monkeypatch, tmp_path)
    calls: list = []
    # The plan still succeeds; only the environment the supervisor resolves at
    # spawn time has gone away. Patched before construction, because the
    # supervisor captures this provider when ConnectApp is built.
    monkeypatch.setattr(ConnectApp, "_resident_environment", lambda self: None)
    app = _app(monkeypatch, _record(), calls)

    assert app.resident_launch_reason() == "planned"
    assert app.start_registered_resident() is False
    assert calls == []
    assert app.status()["resident_running"] is False
