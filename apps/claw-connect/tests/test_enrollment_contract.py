"""Connector enrollment contracts (PADIEM Connector S2, #4139).

Offline: no real PADIEM account, no real broker endpoint, no real credential.
Every live call is driven through a seam so these tests prove the *contract*
and the security posture, never a live success.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.connection import ConnectionState
from claw_connect.enrollment import (
    LIFECYCLE_CREDENTIAL_EXPIRED,
    LIFECYCLE_ONLINE,
    LIFECYCLE_PAIRED_OFFLINE,
    LIFECYCLE_REVOKED,
    LIFECYCLE_UNPAIRED,
    BrokerNotConfiguredError,
    ConnectorEnrollment,
    EnrollmentContractError,
    EnrollmentRecord,
    project_connector_status,
)


BROKER_URL = "https://broker.padiem.net"
CHALLENGE = "chal-9f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e"
CODE = "0123456789abcdef0123456789abcdef"


def _now() -> datetime:
    return datetime(2026, 10, 12, 6, 0, 0, tzinfo=timezone.utc)


class _Lifecycle(str, Enum):
    UNPAIRED = LIFECYCLE_UNPAIRED
    PAIRED_OFFLINE = LIFECYCLE_PAIRED_OFFLINE
    ONLINE = LIFECYCLE_ONLINE
    REVOKED = LIFECYCLE_REVOKED
    CREDENTIAL_EXPIRED = LIFECYCLE_CREDENTIAL_EXPIRED


@dataclass(frozen=True, slots=True)
class _FakeBinding:
    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_expires_at: datetime
    state: _Lifecycle


class _FakePairingClient:
    """Mimics kagent.local_agent_broker_pairing_client's return shape only."""

    def __init__(
        self,
        *,
        broker_base_url: str,
        device_id: str,
        state: _Lifecycle = _Lifecycle.PAIRED_OFFLINE,
    ) -> None:
        self._broker_base_url = broker_base_url
        self._device_id = device_id
        self._state = state

    def redeem(self, *, challenge_id, pairing_code, device_id, now):  # noqa: ANN001
        assert self._broker_base_url
        binding = _FakeBinding(
            device_id=device_id,
            binding_ref=f"binding-{device_id[:8]}",
            account_ref="acct-canonical-1",
            workspace_ref="ws-canonical-1",
            credential_generation=1,
            credential_expires_at=now + timedelta(hours=12),
            state=self._state,
        )
        return _FakeEnrollment(binding, self._state)


def _factory(state: _Lifecycle = _Lifecycle.PAIRED_OFFLINE):
    def build(**kw):
        return _FakePairingClient(**kw, state=state)

    return build


@dataclass(frozen=True, slots=True)
class _FakeEnrollment:
    binding: _FakeBinding
    state: _Lifecycle


def _service(tmp_path, *, broker_url: str = "", factory=None, state=None):
    kwargs = {"state_dir": tmp_path / "state", "broker_base_url": broker_url}
    if factory is not None:
        kwargs["pairing_client_factory"] = factory
    if state is not None:
        kwargs["state"] = state  # type: ignore[arg-type]
    return ConnectorEnrollment(**kwargs)


# --- status projection -------------------------------------------------------
def test_status_precedence_never_lets_connected_override_blocked():
    assert project_connector_status(
        enrolled=True, blocked=True, paused=False, connecting=False, connected=True
    ) is ConnectionState.REVOKED


def test_status_precedence_unenrolled_can_never_look_connected():
    assert project_connector_status(
        enrolled=False, blocked=False, paused=False, connecting=False, connected=True
    ) is ConnectionState.UNREGISTERED


@pytest.mark.parametrize(
    "blocked, paused, connecting, connected, expected",
    [
        (False, False, True, False, ConnectionState.CONNECTING),
        (True, False, True, False, ConnectionState.REVOKED),
        (False, True, True, False, ConnectionState.PAUSED),
        (False, False, False, True, ConnectionState.CONNECTED),
        (False, False, False, False, ConnectionState.OFFLINE),
    ],
)
def test_status_projects_every_required_operator_state(
    blocked, paused, connecting, connected, expected
):
    assert project_connector_status(
        enrolled=True, blocked=blocked, paused=paused,
        connecting=connecting, connected=connected,
    ) is expected


# --- first-run identity ------------------------------------------------------
def test_fresh_device_is_unregistered_and_has_a_stable_device_id(tmp_path):
    first = _service(tmp_path).record()
    assert first.is_enrolled() is False
    assert first.binding_ref is None
    assert _service(tmp_path).record().device_id == first.device_id


def test_device_id_generation_is_opaque_and_matches_the_broker_grammar(tmp_path):
    from claw_connect.enrollment import _SAFE_REF_RE

    device_id = _service(tmp_path).record().device_id
    assert _SAFE_REF_RE.fullmatch(device_id)
    assert len(device_id) == 32


# --- pairing material validation --------------------------------------------
@pytest.mark.parametrize(
    "code",
    ["", "ABC", "0123456789ABCDEF0123456789ABCDEF", "0" * 31, "0" * 33, "g" * 32, None],
)
def test_complete_login_rejects_a_malformed_pairing_code(tmp_path, code):
    service = _service(
        tmp_path / "s", broker_url=BROKER_URL, factory=_factory()
    )
    with pytest.raises(EnrollmentContractError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=code, now=_now())
    assert service.record().is_enrolled() is False


@pytest.mark.parametrize("challenge", ["", "x" * 600, "has space", "line\nbreak", None])
def test_complete_login_rejects_a_malformed_challenge_id(tmp_path, challenge):
    service = _service(
        tmp_path / "s", broker_url=BROKER_URL, factory=_factory()
    )
    with pytest.raises(EnrollmentContractError):
        service.complete_login(challenge_id=challenge, pairing_code=CODE, now=_now())


# --- broker endpoint configuration (fail closed) -----------------------------
@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://broker.padiem.net",          # plaintext
        "https://user:pw@broker.padiem.net", # URL credentials
        "https://broker.padiem.net:8443",    # non-443 port
        "https://broker.padiem.net/?a=1",    # query
        "https://broker.padiem.net/#frag",   # fragment
        "not a url",
    ],
)
def test_unsafe_broker_endpoint_is_refused(tmp_path, url):
    service = _service(
        tmp_path / "s", broker_url=url, factory=_factory()
    )
    with pytest.raises((EnrollmentContractError, BrokerNotConfiguredError)):
        service.broker_configured()
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False


def test_enrollment_fails_closed_when_no_broker_endpoint_is_configured(tmp_path):
    # The current production reality: the LOCAL1 pairing route is not activated.
    service = _service(tmp_path)
    assert service.broker_configured() is False
    with pytest.raises(BrokerNotConfiguredError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    # No binding may be recorded, and nothing may look enrolled or connected.
    record = _service(tmp_path).record()
    assert record.is_enrolled() is False
    assert record.binding_ref is None
    assert service.project_state(connected=True) is ConnectionState.UNREGISTERED
    assert service.status_snapshot()["broker_endpoint_configured"] is False


def test_enrollment_fails_closed_when_the_canonical_client_is_not_wired(tmp_path):
    service = _service(tmp_path, broker_url=BROKER_URL)
    with pytest.raises(BrokerNotConfiguredError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False


def test_the_device_id_is_stable_from_the_very_first_launch(tmp_path):
    # The pairing code is redeemed against this exact identity, so the id must
    # be persisted before any login happens, not minted lazily per run.
    first = _service(tmp_path).record()
    assert _service(tmp_path).record().device_id == first.device_id
    assert _service(tmp_path).state_file.exists()


# --- successful redemption through the canonical client ----------------------
def _redeem(service):
    return service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())


def test_successful_redemption_produces_a_paired_offline_binding(tmp_path):
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        factory=_factory(),
    )
    result = _redeem(service)
    assert result.lifecycle == LIFECYCLE_PAIRED_OFFLINE
    assert result.binding_ref
    assert result.account_ref
    assert result.workspace_ref

    record = service.record()
    assert record.is_enrolled() is True
    assert record.device_lifecycle == LIFECYCLE_PAIRED_OFFLINE
    assert record.revoked is False
    assert service.project_state(connected=True) is ConnectionState.OFFLINE


def test_enrollment_persists_the_broker_device_id_across_instances(tmp_path):
    first = _service(tmp_path, broker_url=BROKER_URL, factory=_factory())
    result = _redeem(first)
    device_id = first.record().device_id

    reopened = _service(tmp_path, broker_url=BROKER_URL)
    assert reopened.record().device_id == device_id
    assert reopened.record().binding_ref == result.binding_ref
    assert reopened.status_snapshot()["device_id"] == device_id


def test_logout_keeps_the_device_id_but_forgets_the_binding(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    device_id = service.record().device_id
    _redeem(service)

    service.clear_enrollment()
    record = service.record()
    assert record.binding_ref is None
    assert record.device_lifecycle == LIFECYCLE_UNPAIRED
    # The Broker identity survives so a re-login does not register a second PC.
    assert record.device_id == device_id
    assert service.project_state(connected=True) is ConnectionState.UNREGISTERED


def test_re_enrollment_reuses_the_same_device_id(tmp_path):
    factory = lambda **kw: _FakePairingClient(**kw)  # noqa: E731
    service = _service(tmp_path, broker_url=BROKER_URL, factory=factory)
    first_device_id = service.record().device_id
    first = _redeem(service)

    service.mark_revoked("revoked_by_operator")
    assert service.project_state() is ConnectionState.REVOKED

    service.clear_enrollment()
    second = _redeem(service)
    assert service.record().device_id == first_device_id
    assert second.binding_ref == first.binding_ref


# --- ONLINE only via server projection --------------------------------------
def test_local_connected_claim_alone_never_reaches_connected(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    # paired_offline + a locally resumed controller is NOT connected.
    assert service.project_state(connected=True) is ConnectionState.OFFLINE

    service.mark_online()  # only ever set from a server-projected observation
    assert service.project_state(connected=True) is ConnectionState.CONNECTED


def test_a_non_offline_binding_from_the_canonical_client_is_refused(tmp_path):
    service = _service(tmp_path, broker_url=BROKER_URL, factory=_factory(_Lifecycle.ONLINE))
    with pytest.raises(EnrollmentContractError):
        _redeem(service)
    assert service.record().is_enrolled() is False


# --- revoke / expiry blocking ------------------------------------------------
def test_revocation_blocks_and_survives_a_local_online_claim(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    service.mark_online()
    assert service.project_state(connected=True) is ConnectionState.CONNECTED

    service.mark_revoked("owner_revoked")
    assert service.project_state(connected=True) is ConnectionState.REVOKED
    assert service.project_state(connected=True, paused=True) is ConnectionState.REVOKED
    assert service.status_snapshot()["blocked"] is True
    assert service.status_snapshot()["blocked_reason"] == "owner_revoked"


def test_expired_credential_blocks_auto_start(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    service.mark_credential_expired()
    assert service.record().device_lifecycle == LIFECYCLE_CREDENTIAL_EXPIRED
    assert service.project_state(connected=True) is ConnectionState.REVOKED
    assert service.status_snapshot()["blocked"] is True


def test_observed_offline_is_recorded_without_claiming_online(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    service.mark_online()
    service.mark_offline()
    assert service.record().device_lifecycle == LIFECYCLE_PAIRED_OFFLINE
    assert service.project_state(connected=True) is ConnectionState.OFFLINE


# --- persistence safety ------------------------------------------------------
def test_the_persisted_record_never_contains_secret_material(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    raw = service.state_file.read_text(encoding="utf-8")

    for forbidden in (CODE, CHALLENGE, "credential_b64", "pairing_code", "challenge_id"):
        assert forbidden not in raw
    data = json.loads(raw)
    assert set(data) == set(EnrollmentRecord.from_dict(data).to_dict())
    # Only the protected credential may name "credential" at all, and only as a
    # generation/expiry bound, never as material.
    assert "credential_generation" in data
    assert "credential_expires_at" in data


def test_the_enrollment_result_projection_is_secret_free(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    result = _redeem(service).safe_dict()
    assert result["raw_device_credential"] is False
    assert result["pairing_code_persisted"] is False
    assert result["public_inbound_port"] is False
    assert CODE not in json.dumps(result)


def test_status_snapshot_is_json_serialisable_and_secret_free(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    snapshot = service.status_snapshot(connected=True)
    json.dumps(snapshot)
    assert snapshot["enrolled"] is True
    assert snapshot["raw_device_credential"] is False
    assert snapshot["public_inbound_port"] is False
    assert snapshot["device_id"] == service.record().device_id


# --- record schema is closed --------------------------------------------------
def test_an_unknown_record_shape_is_refused(tmp_path):
    service = _service(tmp_path)
    service.state_file.parent.mkdir(parents=True, exist_ok=True)
    service.state_file.write_text(
        json.dumps({"contract_version": "claw-connector-enrollment.v1", "extra": 1}),
        encoding="utf-8",
    )
    with pytest.raises(EnrollmentContractError):
        _service(tmp_path).record()


def test_an_old_contract_version_is_refused(tmp_path):
    service = _service(tmp_path)
    service.state_file.parent.mkdir(parents=True, exist_ok=True)
    stale = EnrollmentRecord(device_id="a" * 32).to_dict()
    stale["contract_version"] = "claw-connector-enrollment.v0"
    service.state_file.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(EnrollmentContractError):
        _service(tmp_path).record()


# --- security posture --------------------------------------------------------
def test_the_connector_opens_no_inbound_socket_and_no_port_mapping():
    for path in (ROOT / "claw_connect").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "listen(" not in source, path.name
        assert "bind((" not in source, path.name
        assert "UpnP" not in source and "upnp" not in source, path.name


def test_no_new_password_or_cookie_store_is_introduced():
    """No credential-capture API is used anywhere in the Connector.

    This scans for the API identifiers a browser-password/cookie harvester would
    use. It is deliberately an identifier check, not a prose check, so the
    modules may still *document* that they refuse to collect such material.
    """
    for path in (ROOT / "claw_connect").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "wininet", "Login Data", "browser_cookie(", "getpass(",
            "credentialvault(", "keyring", "sqlite3.connect",
        ):
            assert forbidden not in source, f"{path.name} uses {forbidden}"


def test_autostart_remains_opt_in_and_unaffected_by_enrollment(tmp_path, monkeypatch):
    from claw_connect.autostart import Autostart, MemoryRunKeyStore

    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(tmp_path / "state"))
    store = MemoryRunKeyStore()
    autostart = Autostart("PadiemClawConnect", store)
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_factory()
    )
    _redeem(service)
    # Enrolling a PC must never silently opt it into running at logon.
    assert autostart.is_enabled() is False
    assert store.values == {}


# --- the supervised Resident is the real one, never a placeholder ------------
def test_the_default_supervised_command_targets_the_canonical_kagent_module():
    from claw_connect.resident_supervisor import (
        RESIDENT_ENTRY_MODULE,
        default_resident_command,
    )

    command = default_resident_command()
    assert RESIDENT_ENTRY_MODULE == "kagent.local_agent_resident_process"
    assert RESIDENT_ENTRY_MODULE in command
    # No `-c pass`-style placeholder may survive in an operational default.
    assert not any(part in ("-c", "pass") for part in command)


def test_no_placeholder_resident_command_is_used_anywhere():
    for path in (ROOT / "claw_connect").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for placeholder in ('"-c", "pass"', "'-c pass'", '"pass"'):
            assert placeholder not in source, f"{path.name} still uses {placeholder}"


def test_resident_source_root_resolution(tmp_path, monkeypatch):
    from claw_connect.resident_path import (
        RESIDENT_SRC_ENV_VAR,
        resident_src_root,
        write_resident_config,
    )

    # The environment override wins, then the installer-written config.
    monkeypatch.setenv(RESIDENT_SRC_ENV_VAR, r"D:\kagent\src")
    assert resident_src_root(state_dir=tmp_path) == r"D:\kagent\src"
    monkeypatch.delenv(RESIDENT_SRC_ENV_VAR, raising=False)

    written = write_resident_config(
        tmp_path, r"E:\repo\apps\korean-ai-code-agent\src"
    )
    assert written.name == "resident.json"
    assert resident_src_root(state_dir=tmp_path) == (
        r"E:\repo\apps\korean-ai-code-agent\src"
    )

    # Absent, unreadable or malformed configuration resolves to None so the
    # caller falls back to the canonical module name instead of guessing a path.
    assert resident_src_root(state_dir=tmp_path / "nothing-here") is None
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "resident.json").write_text("{", encoding="utf-8")
    assert resident_src_root(state_dir=broken) is None
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "resident.json").write_text('{"src_root": "x", "other": 1}', encoding="utf-8")
    assert resident_src_root(state_dir=extra) is None


def test_connect_app_supervises_the_real_resident(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(tmp_path / "state"))
    from claw_connect.runtime import ConnectApp

    app = ConnectApp(enrollment=ConnectorEnrollment(state_dir=tmp_path / "state"))
    command = " ".join(app.supervisor.command)
    assert "kagent.local_agent_resident_process" in command
    assert "pass" not in command
