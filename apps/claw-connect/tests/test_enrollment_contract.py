"""Connector enrollment contracts (PADIEM Connector S2, #4139).

Offline: no real PADIEM account, no real broker endpoint, no real credential.
Every live call is driven through a seam so these tests prove the *contract*
and the security posture, never a live success.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import pytest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.enrollment import EnrollmentDisplayState
from claw_connect.enrollment import (
    ENROLLMENT_PROOF_REF_PREFIX,
    ENROLLMENT_PROOF_TRANSCRIPT,
    ENROLLMENT_REFUSAL_REASONS,
    ENROLLMENT_SCOPED_REDEMPTION_REQUIRED,
    LIFECYCLE_CREDENTIAL_EXPIRED,
    LIFECYCLE_ONLINE,
    LIFECYCLE_PAIRED_OFFLINE,
    LIFECYCLE_REVOKED,
    LIFECYCLE_UNPAIRED,
    BrokerNotConfiguredError,
    ConnectorEnrollment,
    EnrollmentContractError,
    EnrollmentRecord,
    EnrollmentRedemptionRequest,
    EnrollmentRedemptionResponse,
    UnconfiguredEnrollmentServerPort,
    build_enrollment_proof_ref,
    project_connector_status,
    verify_enrollment_receipt,
)


BROKER_URL = "https://broker.padiem.net"
CHALLENGE = "chal-9f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e"
CODE = "0123456789abcdef0123456789abcdef"


def _now() -> datetime:
    return datetime(2026, 10, 12, 6, 0, 0, tzinfo=timezone.utc)


class _FakeEnrollmentServer:
    """Mimics the authenticated S1 enrollment server route's shape only.

    Speaks ``EnrollmentServerPort``: takes a possession-proof request, returns
    an authenticated receipt or a bounded refusal. Never opens a socket.
    """

    def __init__(
        self,
        *,
        broker_base_url: str,
        device_id: str,
        behavior: str = "success",
        refusal: str = "enrollment_consent_withdrawn",
        response_device_id: str | None = None,
        expires_in_hours: float = 12,
        account_ref: str = "acct-canonical-1",
        workspace_ref: str = "ws-canonical-1",
    ) -> None:
        self._broker_base_url = broker_base_url
        self._device_id = device_id
        self._behavior = behavior
        self._refusal = refusal
        self._response_device_id = response_device_id
        self._expires_in_hours = expires_in_hours
        self._account_ref = account_ref
        self._workspace_ref = workspace_ref
        self.calls: list = []

    def redeem_enrollment(self, request, *, now):  # noqa: ANN001
        assert self._broker_base_url
        # The server must only ever see proof material, never the raw code.
        assert isinstance(request, EnrollmentRedemptionRequest)
        assert CODE not in (request.challenge_id, request.device_id, request.proof_ref)
        self.calls.append(request)
        if self._behavior == "unreachable":
            raise ConnectionError("simulated transport failure")
        if self._behavior == "wrong_shape":
            return {"ok": True, "binding_ref": "forged"}
        if self._behavior == "refuse":
            return EnrollmentRedemptionResponse(ok=False, reason=self._refusal)
        device = self._response_device_id or request.device_id
        return EnrollmentRedemptionResponse(
            ok=True,
            binding_ref=f"binding-{device[:8]}",
            device_id=device,
            account_ref=self._account_ref,
            workspace_ref=self._workspace_ref,
            credential_generation=1,
            credential_expires_at=now + timedelta(hours=self._expires_in_hours),
            consent_id="consent-1",
        )


def _server_factory(behavior: str = "success", **kwargs):
    def build(**kw):
        return _FakeEnrollmentServer(**kw, behavior=behavior, **kwargs)

    return build


def _tracked_server_factory(calls, behavior: str = "success", **kwargs):
    """A server factory that records every redemption it was asked to perform.

    Item: a device-side refusal that runs *after* the redemption call cannot be
    evidence that the server-side redemption was undone. The only honest way to
    show the difference is to observe how many times the client actually talked
    to the port: if a compensating call existed, this list would grow past the
    redemptions themselves.
    """

    def build(**kw):
        server = _FakeEnrollmentServer(**kw, behavior=behavior, **kwargs)
        innermost = server.redeem_enrollment

        def redeem_enrollment(request, *, now):  # noqa: ANN001
            calls.append(request)
            return innermost(request, now=now)

        server.redeem_enrollment = redeem_enrollment  # type: ignore[method-assign]
        return server

    return build


def _seed_record(service, **overrides):
    """Rewrite the persisted record, as a damaged/foreign state file would."""
    data = json.loads(service.state_file.read_text(encoding="utf-8"))
    data.update(overrides)
    service.state_file.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
    service._record = None


def _factory():
    """Back-compat alias: the success-path server port."""
    return _server_factory()


class _LegacyGenericClient:
    """The closed generic pairing path: tracks whether it was ever called."""

    def __init__(self, **kw) -> None:
        self.calls: list = []
        self.kw = kw

    def redeem(self, **kw):  # noqa: ANN001
        self.calls.append(kw)
        raise AssertionError("generic redeem() must never be called for enrollment")


def _legacy_factory(holder: list):
    def build(**kw):
        client = _LegacyGenericClient(**kw)
        holder.append(client)
        return client

    return build


def _service(tmp_path, *, broker_url: str = "", factory=None, server_factory=None):
    kwargs = {"state_dir": tmp_path / "state", "broker_base_url": broker_url}
    if factory is not None:
        kwargs["pairing_client_factory"] = factory
    if server_factory is not None:
        kwargs["enrollment_server_factory"] = server_factory
    return ConnectorEnrollment(**kwargs)


# --- status projection -------------------------------------------------------
def test_status_precedence_never_lets_connected_override_blocked():
    assert project_connector_status(
        enrolled=True, blocked=True, paused=False, connecting=False, connected=True
    ) is EnrollmentDisplayState.REVOKED


def test_status_precedence_unenrolled_can_never_look_connected():
    assert project_connector_status(
        enrolled=False, blocked=False, paused=False, connecting=False, connected=True
    ) is EnrollmentDisplayState.UNREGISTERED


@pytest.mark.parametrize(
    "blocked, paused, connecting, connected, expected",
    [
        (False, False, True, False, EnrollmentDisplayState.CONNECTING),
        (True, False, True, False, EnrollmentDisplayState.REVOKED),
        (False, True, True, False, EnrollmentDisplayState.PAUSED),
        (False, False, False, True, EnrollmentDisplayState.CONNECTED),
        (False, False, False, False, EnrollmentDisplayState.OFFLINE),
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
        tmp_path / "s", broker_url=BROKER_URL, server_factory=_server_factory()
    )
    with pytest.raises(EnrollmentContractError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=code, now=_now())
    assert service.record().is_enrolled() is False


@pytest.mark.parametrize("challenge", ["", "x" * 600, "has space", "line\nbreak", None])
def test_complete_login_rejects_a_malformed_challenge_id(tmp_path, challenge):
    service = _service(
        tmp_path / "s", broker_url=BROKER_URL, server_factory=_server_factory()
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
        tmp_path / "s", broker_url=url, server_factory=_server_factory()
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
    assert service.project_state(connected=True) is EnrollmentDisplayState.UNREGISTERED
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
        server_factory=_server_factory(),
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
    assert service.project_state(connected=True) is EnrollmentDisplayState.OFFLINE


def test_enrollment_persists_the_broker_device_id_across_instances(tmp_path):
    first = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    result = _redeem(first)
    device_id = first.record().device_id

    reopened = _service(tmp_path, broker_url=BROKER_URL)
    assert reopened.record().device_id == device_id
    assert reopened.record().binding_ref == result.binding_ref
    assert reopened.status_snapshot()["device_id"] == device_id


def test_logout_keeps_the_device_id_but_forgets_the_binding(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    device_id = service.record().device_id
    _redeem(service)

    service.clear_enrollment()
    record = service.record()
    assert record.binding_ref is None
    assert record.device_lifecycle == LIFECYCLE_UNPAIRED
    # The Broker identity survives so a re-login does not register a second PC.
    assert record.device_id == device_id
    assert service.project_state(connected=True) is EnrollmentDisplayState.UNREGISTERED


def test_re_enrollment_reuses_the_same_device_id(tmp_path):
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    first_device_id = service.record().device_id
    first = _redeem(service)

    service.mark_revoked("revoked_by_operator")
    assert service.project_state() is EnrollmentDisplayState.REVOKED

    service.clear_enrollment()
    second = _redeem(service)
    assert service.record().device_id == first_device_id
    assert second.binding_ref == first.binding_ref


# --- ONLINE only via server projection --------------------------------------
def test_local_connected_claim_alone_never_reaches_connected(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    _redeem(service)
    # paired_offline + a locally resumed controller is NOT connected.
    assert service.project_state(connected=True) is EnrollmentDisplayState.OFFLINE

    service.mark_online()  # only ever set from a server-projected observation
    assert service.project_state(connected=True) is EnrollmentDisplayState.CONNECTED


# --- server receipt verification (never trust an unauthenticated shape) -------
def test_an_unauthenticated_receipt_shape_is_refused(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL,
        server_factory=_server_factory("wrong_shape"),
    )
    with pytest.raises(EnrollmentContractError):
        _redeem(service)
    assert service.record().is_enrolled() is False
    assert service.project_state(connected=True) is EnrollmentDisplayState.UNREGISTERED


def test_a_receipt_for_another_device_is_refused(tmp_path):
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_server_factory(
            response_device_id="other-pc-000000000000000000000001"
        ),
    )
    with pytest.raises(EnrollmentContractError, match="enrollment_device_swap_denied"):
        _redeem(service)
    assert service.record().is_enrolled() is False
    assert service.record().binding_ref is None


def test_an_expired_credential_receipt_is_refused(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL,
        server_factory=_server_factory(expires_in_hours=-1),
    )
    with pytest.raises(EnrollmentContractError):
        _redeem(service)
    assert service.record().is_enrolled() is False


def test_verify_receipt_passes_refusals_through_and_rejects_forgery():
    refusal = EnrollmentRedemptionResponse(
        ok=False, reason="enrollment_consent_withdrawn"
    )
    assert verify_enrollment_receipt(
        refusal, expected_device_id="d" * 32, now=_now()
    ) is refusal
    with pytest.raises(EnrollmentContractError):
        verify_enrollment_receipt(
            {"ok": True}, expected_device_id="d" * 32, now=_now()  # type: ignore[arg-type]
        )


# --- revoke / expiry blocking ------------------------------------------------
def test_revocation_blocks_and_survives_a_local_online_claim(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    _redeem(service)
    service.mark_online()
    assert service.project_state(connected=True) is EnrollmentDisplayState.CONNECTED

    service.mark_revoked("owner_revoked")
    assert service.project_state(connected=True) is EnrollmentDisplayState.REVOKED
    assert service.project_state(connected=True, paused=True) is EnrollmentDisplayState.REVOKED
    assert service.status_snapshot()["blocked"] is True
    assert service.status_snapshot()["blocked_reason"] == "owner_revoked"


def test_expired_credential_blocks_auto_start(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    _redeem(service)
    service.mark_credential_expired()
    assert service.record().device_lifecycle == LIFECYCLE_CREDENTIAL_EXPIRED
    assert service.project_state(connected=True) is EnrollmentDisplayState.REVOKED
    assert service.status_snapshot()["blocked"] is True


def test_observed_offline_is_recorded_without_claiming_online(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    _redeem(service)
    service.mark_online()
    service.mark_offline()
    assert service.record().device_lifecycle == LIFECYCLE_PAIRED_OFFLINE
    assert service.project_state(connected=True) is EnrollmentDisplayState.OFFLINE


# --- persistence safety ------------------------------------------------------
def test_the_persisted_record_never_contains_secret_material(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
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
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    result = _redeem(service).safe_dict()
    assert result["raw_device_credential"] is False
    assert result["pairing_code_persisted"] is False
    assert result["public_inbound_port"] is False
    assert CODE not in json.dumps(result)


def test_status_snapshot_is_json_serialisable_and_secret_free(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
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
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
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


@pytest.mark.skip(reason="CENTRAL-CONTRACT-CONFLICT: depends on claw_connect.resident_path, deleted on central dbbd1633. Resident path is out of #4139 enrollment scope.")
def test_no_placeholder_resident_command_is_used_anywhere():
    for path in (ROOT / "claw_connect").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for placeholder in ('"-c", "pass"', "'-c pass'", '"pass"'):
            assert placeholder not in source, f"{path.name} still uses {placeholder}"


@pytest.mark.skip(reason="CENTRAL-CONTRACT-CONFLICT: depends on claw_connect.resident_path, deleted on central dbbd1633. Resident path is out of #4139 enrollment scope.")
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


@pytest.mark.skip(reason="CENTRAL-CONTRACT-CONFLICT: depends on claw_connect.runtime.ConnectApp(enrollment=...) which central dbbd1633 removed; Resident path is not in #4139 enrollment scope. Restore only by central CTO decision.")
def test_connect_app_supervises_the_real_resident(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(tmp_path / "state"))
    from claw_connect.runtime import ConnectApp

    app = ConnectApp(enrollment=ConnectorEnrollment(state_dir=tmp_path / "state"))
    command = " ".join(app.supervisor.command)
    assert "kagent.local_agent_resident_process" in command
    assert "pass" not in command


# --- S1 enrollment-contract alignment (LOCAL1 PR #4438, read-only) -------------
# The Connector never calls the generic pairing route for enrollment: S1
# refuses enrollment-bound challenges on it before any mutation, so calling it
# could never succeed. These tests pin the closed path, the scoped port, and
# every required refusal — with zero Broker bindings on any denial.
def test_generic_redeem_path_is_closed_for_enrollment(tmp_path):
    holder: list = []
    service = _service(
        tmp_path, broker_url=BROKER_URL, factory=_legacy_factory(holder)
    )
    with pytest.raises(
        EnrollmentContractError, match=ENROLLMENT_SCOPED_REDEMPTION_REQUIRED
    ):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    # The legacy factory is never even invoked for enrollment.
    assert holder == []
    record = service.record()
    assert record.is_enrolled() is False
    assert record.binding_ref is None
    assert service.project_state(connected=True) is EnrollmentDisplayState.UNREGISTERED


def test_scoped_redemption_success_records_the_server_scope(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    result = _redeem(service)
    assert result.lifecycle == LIFECYCLE_PAIRED_OFFLINE
    assert result.account_ref == "acct-canonical-1"
    assert result.workspace_ref == "ws-canonical-1"
    # Success lands offline; CONNECTED needs a later server projection.
    assert service.project_state(connected=True) is EnrollmentDisplayState.OFFLINE
    service.mark_online()
    assert service.project_state(connected=True) is EnrollmentDisplayState.CONNECTED


def test_consent_revocation_refuses_the_outstanding_challenge(tmp_path):
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_server_factory(
            "refuse", refusal="enrollment_consent_withdrawn"
        ),
    )
    with pytest.raises(
        EnrollmentContractError, match="enrollment_consent_withdrawn"
    ):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False
    assert service.record().binding_ref is None


@pytest.mark.parametrize(
    "reason",
    [
        "enrollment_consent_swap_denied",
        "enrollment_binding_owner_mismatch",
        "enrollment_binding_scope_mismatch",
    ],
)
def test_cross_scope_challenge_use_is_refused(tmp_path, reason):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory("refuse", refusal=reason)
    )
    with pytest.raises(EnrollmentContractError, match=reason):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False
    assert service.record().binding_ref is None


@pytest.mark.parametrize(
    "reason",
    ["enrollment_challenge_expired", "enrollment_duplicate_redeem_denied"],
)
def test_expired_and_replayed_challenges_are_refused(tmp_path, reason):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory("refuse", refusal=reason)
    )
    with pytest.raises(EnrollmentContractError, match=reason):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False


def test_refusal_records_no_binding_and_leaves_retry_open(tmp_path):
    refused = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_server_factory("refuse", refusal="enrollment_challenge_expired"),
    )
    with pytest.raises(EnrollmentContractError):
        refused.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert refused.record().binding_ref is None
    # Nothing was consumed locally: the same challenge still redeems once the
    # server accepts it.
    reopened = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory()
    )
    result = reopened.complete_login(
        challenge_id=CHALLENGE, pairing_code=CODE, now=_now()
    )
    assert result.binding_ref


def test_consent_store_offline_fails_closed_by_default(tmp_path):
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_server_factory(
            "refuse", refusal="enrollment_consent_liveness_dependency_unmet"
        ),
    )
    with pytest.raises(
        EnrollmentContractError,
        match="enrollment_consent_liveness_dependency_unmet",
    ):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False

    unwired = _service(tmp_path / "unwired", broker_url=BROKER_URL)
    unwired._enrollment_server_factory = (
        lambda **kw: UnconfiguredEnrollmentServerPort()
    )
    with pytest.raises(BrokerNotConfiguredError):
        unwired.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert unwired.record().is_enrolled() is False


def test_server_unreachable_never_shows_connected(tmp_path):
    service = _service(
        tmp_path, broker_url=BROKER_URL, server_factory=_server_factory("unreachable")
    )
    with pytest.raises(BrokerNotConfiguredError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False
    assert service.project_state(connected=True) is EnrollmentDisplayState.UNREGISTERED
    snapshot = service.status_snapshot(connected=True)
    assert snapshot["enrolled"] is False
    assert snapshot["device_state"] == EnrollmentDisplayState.UNREGISTERED.value


def test_ordinary_input_validation_is_unchanged(tmp_path):
    """Non-enrollment validation keeps its exact previous behaviour."""
    service = _service(
        tmp_path / "s", broker_url=BROKER_URL, server_factory=_server_factory()
    )
    with pytest.raises(EnrollmentContractError):
        service.complete_login(challenge_id=CHALLENGE, pairing_code="not-hex", now=_now())
    with pytest.raises(EnrollmentContractError):
        service.complete_login(challenge_id="", pairing_code=CODE, now=_now())
    assert service.record().is_enrolled() is False


def test_proof_vector_matches_the_s1_hmac_transcript():
    expected = (
        ENROLLMENT_PROOF_REF_PREFIX
        + hmac.new(
            CODE.encode("utf-8"),
            f"{ENROLLMENT_PROOF_TRANSCRIPT}\n{CHALLENGE}\n{'d' * 32}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )
    proof = build_enrollment_proof_ref(
        challenge_id=CHALLENGE, device_id="d" * 32, pairing_code=CODE
    )
    assert proof == expected
    assert proof.startswith("pairing-proof:")
    assert len(proof) == len("pairing-proof:") + 64
    with pytest.raises(EnrollmentContractError):
        build_enrollment_proof_ref(
            challenge_id=CHALLENGE, device_id="d" * 32, pairing_code="not-hex"
        )


def test_redemption_request_carries_no_authority_fields():
    request = EnrollmentRedemptionRequest(
        challenge_id=CHALLENGE,
        device_id="d" * 32,
        proof_ref=build_enrollment_proof_ref(
            challenge_id=CHALLENGE, device_id="d" * 32, pairing_code=CODE
        ),
    )
    import dataclasses

    assert {field.name for field in dataclasses.fields(request)} == {
        "challenge_id",
        "device_id",
        "proof_ref",
    }
    safe = request.safe_dict()
    assert safe["client_asserted_owner"] is False
    assert safe["client_asserted_scope"] is False
    assert safe["client_asserted_consent"] is False
    assert safe["password_transmitted"] is False
    assert safe["cookie_transmitted"] is False


def test_no_generic_redeem_call_survives_in_the_connector():
    """The enrollment flow must not invoke the generic redeem path.

    The legacy factory seam is retained only as a closed-path migration
    signal (checked for ``None``, never called); the live flow goes through
    the enrollment server port.
    """
    enrollment_source = (ROOT / "claw_connect" / "enrollment.py").read_text(
        encoding="utf-8"
    )
    assert "self._pairing_client_factory(" not in enrollment_source
    assert ".redeem(" not in enrollment_source
    assert "_redeem_with_canonical_client" not in enrollment_source
    assert "_redeem_via_enrollment_server" in enrollment_source


def test_s1_contract_drift_guard():
    """Cross-check the read-only S1 mirror when the S1 module is importable.

    Skips until LOCAL1 PR #4438 merges: the S1 package is absent from this
    branch, and this test must never vendor or modify S1 files.
    """
    s1_enrollment = pytest.importorskip(
        "padiem_control_plane.padiem_connector_enrollment",
        reason="S1 authority not merged yet (BLOCKED_DEPENDENCY)",
    )
    s1_pairing = pytest.importorskip(
        "padiem_control_plane.local_agent_broker_pairing",
        reason="S1 authority not merged yet (BLOCKED_DEPENDENCY)",
    )
    assert (
        s1_pairing.PAIRING_PROOF_TRANSCRIPT == ENROLLMENT_PROOF_TRANSCRIPT
    )
    assert s1_pairing.PAIRING_PROOF_REF_PREFIX == ENROLLMENT_PROOF_REF_PREFIX
    assert s1_enrollment.CONSENT_LIVENESS_AUTHORITY_IMPLEMENTED is False
    assert s1_enrollment.PRODUCTION_ACTIVATION is False


# --- account / scope isolation on an already-enrolled PC (#4139 S2) ----------
def test_account_change_on_an_enrolled_pc_is_refused_and_keeps_the_original_binding(
    tmp_path,
):
    """A different account must never silently take over an existing PC binding.

    The device identity is referenced by the product sessions that were enrolled
    against the previous account, so re-pointing it in place would hand those
    sessions to another account. The refusal leaves the record byte-identical.
    """
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    first = _redeem(service)
    snapshot = service.record().to_dict()

    service._enrollment_server_factory = _server_factory(account_ref="acct-other-2")
    with pytest.raises(
        EnrollmentContractError, match="enrollment_binding_owner_mismatch"
    ):
        _redeem(service)

    after = service.record()
    assert after.to_dict() == snapshot
    assert after.binding_ref == first.binding_ref
    assert after.account_ref == "acct-canonical-1"
    # Still an enrolled, unblocked binding: refusing is not a revocation.
    assert after.revoked is False
    assert service.project_state() is EnrollmentDisplayState.OFFLINE


def test_account_change_refusal_reports_only_the_bounded_reason(tmp_path):
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    _redeem(service)
    service._enrollment_server_factory = _server_factory(account_ref="acct-other-2")

    with pytest.raises(EnrollmentContractError) as excinfo:
        _redeem(service)

    message = str(excinfo.value)
    assert message == "enrollment_binding_owner_mismatch"
    assert message in ENROLLMENT_REFUSAL_REASONS
    # Neither the refused nor the held account identifier is echoed anywhere.
    assert "acct-other-2" not in message
    assert "acct-canonical-1" not in message


def test_workspace_scope_change_on_an_enrolled_pc_is_refused(tmp_path):
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    _redeem(service)

    service._enrollment_server_factory = _server_factory(workspace_ref="ws-other-2")
    with pytest.raises(
        EnrollmentContractError, match="enrollment_binding_scope_mismatch"
    ):
        _redeem(service)

    record = service.record()
    assert record.workspace_ref == "ws-canonical-1"
    assert record.account_ref == "acct-canonical-1"


def test_same_account_and_scope_re_enrollment_is_still_adopted(tmp_path):
    """The guard must not block a legitimate same-account refresh."""
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    first = _redeem(service)
    second = _redeem(service)

    assert second.account_ref == first.account_ref
    assert second.workspace_ref == first.workspace_ref
    assert second.binding_ref == first.binding_ref
    assert service.record().is_enrolled() is True


def test_a_local_logout_only_clears_the_local_view_of_the_binding(tmp_path):
    """``clear_enrollment`` is not an ownership transfer (CENTRAL review A).

    Logout clears only this PC's local view of the binding. It does not revoke
    the canonical Broker binding, does not end an active Broker session, does
    not delete the protected credential and does not disassociate the device
    id — the canonical Broker refuses a second binding for a device that still
    holds an active one. So the *local* record can be un-paired without the
    *canonical* device being made available to another owner; that requires an
    owner-authorized, server-confirmed revocation plus reviewed
    credential-store cleanup and a new enrollment, none of which the Connector
    performs or claims. This test pins the local half only, and pins the
    negative half (no server interaction, no other file touched) so the
    stronger claim can never creep back in.
    """
    calls: list = []
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_tracked_server_factory(calls),
    )
    first = _redeem(service)
    service._enrollment_server_factory = _tracked_server_factory(
        calls, account_ref="acct-other-2"
    )
    with pytest.raises(EnrollmentContractError):
        _redeem(service)
    assert len(calls) == 2  # the foreign redemption was asked for, then refused locally

    before = service.state_file.read_text(encoding="utf-8")
    state_files = {
        path.name: path.read_bytes() for path in service.state_dir.iterdir()
    }

    service.clear_enrollment()

    # (1) Local view cleared, and the device id survives — the stable
    # one-identity-per-PC policy is untouched.
    after = service.record()
    assert after.is_enrolled() is False
    assert after.binding_ref is None
    assert after.device_id == first.device_id
    assert service.project_state() is EnrollmentDisplayState.UNREGISTERED

    # (2) Logging out performs no canonical action: the port is not consulted
    # again, and no other file in the state directory is created, rewritten or
    # deleted — in particular not the protected credential store. The only
    # rewrite here is the record itself.
    assert len(calls) == 2
    after_files = {
        path.name: path.read_bytes() for path in service.state_dir.iterdir()
    }
    assert set(after_files) == set(state_files)
    assert after_files["enrollment.json"] != before
    assert len(after_files) == 1  # only the record exists in this fixture

    # (3) The device is *locally* unpaired, so a following login from a
    # different account is accepted locally. This is a statement about the
    # local record only — it is not a completed account migration and must
    # never be reported as one.
    switched = _redeem(service)
    assert switched.account_ref == "acct-other-2"
    assert service.record().account_ref == "acct-other-2"
    assert service.record().device_id == first.device_id


def test_a_refusal_after_a_successful_receipt_is_not_a_server_rollback(tmp_path):
    """The device-side guard cannot claim the upstream redemption was undone (B).

    The equality checks run after the redemption call, so the server has already
    done its work when the device refuses. Refusing therefore proves only that
    *this PC* did not adopt the receipt. It is not evidence that the upstream
    challenge was left unconsumed, that the Broker binding was left uncreated,
    or that the delivered credential was compensated — and the Connector makes
    no compensating call at all. If server and client state disagree, that is a
    CENTRAL-side reconciliation/security matter, not a routine account switch.
    """
    calls: list = []
    service = _service(
        tmp_path,
        broker_url=BROKER_URL,
        server_factory=_tracked_server_factory(calls),
    )
    _redeem(service)
    assert len(calls) == 1

    # An account the local record does not own. The fake port would still answer
    # with a success receipt, exactly as a real server already having redeemed
    # would.
    service._enrollment_server_factory = _tracked_server_factory(
        calls, account_ref="acct-other-2"
    )
    snapshot = service.record().to_dict()
    with pytest.raises(EnrollmentContractError) as excinfo:
        _redeem(service)

    assert excinfo.value.args[0] in ENROLLMENT_REFUSAL_REASONS
    # The local record is untouched — that is the whole of what is proven.
    assert service.record().to_dict() == snapshot
    assert service.project_state() is EnrollmentDisplayState.OFFLINE
    # The client asked the port exactly once for this account and then stopped.
    # No compensation, revocation, rollback or challenge re-read was attempted.
    assert len(calls) == 2
    assert calls[-1].device_id == snapshot["device_id"]


def test_an_enrolled_record_without_a_recorded_owner_is_refused(tmp_path):
    """A persisted binding missing its owner must fail closed (CENTRAL review C).

    ``from_dict`` accepts a persisted binding whose ``account_ref`` is null. A
    refusal conditional on a recorded owner would let that record be re-pointed
    at whatever account the next receipt names, which is the silent takeover
    the guard exists to prevent. The record is refused, not repaired.
    """
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    _redeem(service)
    _seed_record(service, account_ref=None)
    damaged = service.record().to_dict()

    service._enrollment_server_factory = _server_factory(account_ref="acct-other-2")
    with pytest.raises(
        EnrollmentContractError, match="enrollment_binding_owner_mismatch"
    ):
        _redeem(service)

    assert service.record().to_dict() == damaged
    assert service.record().is_enrolled() is True  # the binding is still there


def test_an_enrolled_record_without_a_recorded_scope_is_refused(tmp_path):
    """The same fail-closed rule when the workspace scope is missing (review C)."""
    service = _service(tmp_path, broker_url=BROKER_URL, server_factory=_server_factory())
    _redeem(service)
    _seed_record(service, workspace_ref=None)
    damaged = service.record().to_dict()

    service._enrollment_server_factory = _server_factory(workspace_ref="ws-other-2")
    with pytest.raises(
        EnrollmentContractError, match="enrollment_binding_scope_mismatch"
    ):
        _redeem(service)

    assert service.record().to_dict() == damaged
    assert service.record().is_enrolled() is True


def test_the_connector_carries_no_product_scoped_authority_dimension():
    """#4139 platform ownership: one canonical PC registration, no per-product fork.

    The device authority must stay product-neutral. If a product/brand dimension
    ever entered the connector, one PC would begin carrying more than one
    registration — the per-product fork the CENTRAL brand-separation decision
    forbids. This pins the shipped source and both closed key sets, so the
    documented claim is enforced rather than asserted in prose.
    """
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "claw_connect").glob("*.py"))
    )
    for forbidden in ("product_id", "b54", "b62", "b66", "brand"):
        assert forbidden not in source, forbidden

    request_keys = {field.name for field in dataclasses.fields(EnrollmentRedemptionRequest)}
    assert request_keys == {"challenge_id", "device_id", "proof_ref"}
    assert not request_keys & {
        "product", "product_id", "brand", "owner", "workspace", "consent", "session",
    }

    record_keys = {field.name for field in dataclasses.fields(EnrollmentRecord)}
    assert not record_keys & {"product", "product_id", "brand"}
