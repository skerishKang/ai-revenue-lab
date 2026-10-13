"""#4139 LOCAL2 — what actually blocks an interrupted or restarted enrollment.

The six windows in the #4490 follow-up directive are reproduced here against the shipped
modules, and each assertion names the authority that actually closes it:

* the **canonical Broker/server** consumes a pairing challenge once;
* the **local persistent record** is the device's only durable enrollment state;
* the **protected store** is the only local installation proof.

The in-memory `_consumed_challenges` set in `credential_install.py` is deliberately *not*
treated as a durable guard: it cannot survive a Windows process restart, and nothing here may
claim that it does.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    CredentialInstallError,
    LocalStoreCredentialReceiver,
)
from claw_connect.enrollment import (  # noqa: E402
    ConnectorEnrollment,
    EnrollmentContractError,
    EnrollmentRedemptionResponse,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(days=180)
PAIRING_CODE = "b" * 32
CHALLENGE = "challenge-win-1"
ACCOUNT = "acct-win-1"
WORKSPACE = "ws-win-1"
BINDING = "binding-win-1"


class RedeemedOnceThenRefused:
    """Mirrors the canonical Broker: first redeem succeeds, a replay is refused."""

    def __init__(self, **scope):
        self.calls = 0
        self.scope = {"account_ref": ACCOUNT, "workspace_ref": WORKSPACE, **scope}

    def redeem_enrollment(self, request, *, now):
        self.calls += 1
        if self.calls > 1:
            return EnrollmentRedemptionResponse(
                ok=False, reason="enrollment_duplicate_redeem_denied", retryable=False
            )
        return EnrollmentRedemptionResponse(
            ok=True,
            binding_ref=BINDING,
            device_id=request.device_id,
            account_ref=self.scope["account_ref"],
            workspace_ref=self.scope["workspace_ref"],
            credential_generation=1,
            credential_expires_at=EXPIRES,
            consent_id="consent-win-1",
        )


def _connector(tmp_path: Path, port: RedeemedOnceThenRefused) -> ConnectorEnrollment:
    return ConnectorEnrollment(
        state_dir=tmp_path,
        broker_base_url="https://broker.padiem.net",
        enrollment_server_factory=lambda **_kwargs: port,
        clock=lambda: NOW,
    )


def _durable(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "enrollment.json").read_text(encoding="utf-8"))


# -- window 1 & 5: the server accepted, the PC could not persist -----------------
def test_a_success_that_cannot_be_persisted_leaves_no_enrolled_state(tmp_path, monkeypatch):
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    device_id = connector.record().device_id

    def _boom():
        raise OSError("state directory is unwritable")

    monkeypatch.setattr(connector, "flush", _boom)
    with pytest.raises(OSError):
        connector.complete_login(
            challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW
        )

    # Nothing was persisted, so the durable record still says "never enrolled".
    assert port.calls == 1
    durable = _durable(tmp_path)
    assert durable["binding_ref"] is None
    assert durable["device_id"] == device_id

    # The in-process view must agree with what is on disk. Holding the receipt in
    # memory after a failed write would keep the tray, `status_snapshot` and
    # `device_identity` reporting an enrollment this PC does not own.
    after = connector.status_snapshot()
    assert after["enrolled"] is False, after
    assert after["binding_ref"] is None, after
    assert connector.device_identity()["binding_ref"] is None


def test_retrying_the_consumed_challenge_after_a_persistence_failure_stays_refused(
    tmp_path, monkeypatch
):
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)

    def _boom():
        raise OSError("state directory is unwritable")

    monkeypatch.setattr(connector, "flush", _boom)
    with pytest.raises(OSError):
        connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)
    monkeypatch.undo()

    # A retry with the same challenge reaches the server, which has already spent it.
    # The refusal is bounded and no binding appears locally.
    with pytest.raises(EnrollmentContractError) as exc:
        connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)
    assert str(exc.value) == "enrollment_duplicate_redeem_denied"
    assert port.calls == 2
    assert connector.status_snapshot()["enrolled"] is False
    assert _durable(tmp_path)["binding_ref"] is None
    # Only the canonical Broker can decide whether another challenge is granted; a
    # LOCAL2 test double that refuses every second redeem proves the replay is not
    # silently accepted on this device, and nothing here claims a new challenge works.


# -- window 5: a killed write and a restarted process ----------------------------
def test_a_damaged_or_torn_state_file_blocks_and_is_never_forged_over(tmp_path):
    path = tmp_path / "enrollment.json"
    for damaged in (
        "",
        "{",
        '{"device_id": "pc_abc123456789"}',
        '["not", "a", "record"]',
        '{"contract_version":"padiem.connector-enrollment-record.v1","device_id":7}',
    ):
        path.write_text(damaged, encoding="utf-8")
        connector = _connector(tmp_path, RedeemedOnceThenRefused())
        with pytest.raises(EnrollmentContractError):
            connector.record()
        # The unreadable evidence is preserved, and no fresh device identity is
        # minted behind it (which would fork the one-PC-one-device policy).
        assert path.read_text(encoding="utf-8") == damaged


def test_a_tmp_residue_from_a_killed_write_leaves_the_durable_record_alone(tmp_path):
    connector = _connector(tmp_path, RedeemedOnceThenRefused())
    connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)
    stable = _durable(tmp_path)
    (tmp_path / "enrollment.json.tmp").write_text(
        '{"device_id": "pc_victim"}', encoding="utf-8"
    )

    restarted = _connector(tmp_path, RedeemedOnceThenRefused())
    assert restarted.record().device_id == stable["device_id"]
    assert restarted.record().binding_ref == BINDING
    restarted.flush()
    assert _durable(tmp_path) == stable


def test_the_local_challenge_guard_does_not_survive_a_process_restart(tmp_path):
    """Documents the boundary rather than claiming more than the code provides.

    `_consumed_challenges` is per-instance, so a restarted Connector can present the
    same challenge to the install path again. Durable single use is enforced by the
    canonical Broker's consumed state and by the protected store's own binding
    context — not by this set, and no LOCAL2 message may imply otherwise.
    """

    @dataclass(frozen=True)
    class Binding:
        binding_ref: str
        device_id: str
        account_ref: str
        workspace_ref: str
        credential_generation: int

    @dataclass(frozen=True)
    class Projection:
        binding_ref: str
        device_id: str
        account_ref: str
        workspace_ref: str
        credential_generation: int

    class Store:
        def __init__(self):
            self.saved = 0

        def save(self, *, binding, credential, now):
            self.saved += 1
            return Projection(
                binding_ref=binding.binding_ref,
                device_id=binding.device_id,
                account_ref=binding.account_ref,
                workspace_ref=binding.workspace_ref,
                credential_generation=binding.credential_generation,
            )

        def load(self, *, binding, now):
            return CREDENTIAL

    store = Store()
    binding = Binding(BINDING, "pc_abc123", ACCOUNT, WORKSPACE, 3)
    first = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    assert first.install_once(
        challenge_id=CHALLENGE, device_id="pc_abc123", credential=CREDENTIAL, binding=binding
    ).installed is True

    restarted = LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)
    assert restarted.install_once(
        challenge_id=CHALLENGE, device_id="pc_abc123", credential=CREDENTIAL, binding=binding
    ).installed is True
    assert store.saved == 2


# -- window 2/3/4: the protected store's own scope correspondence --------------
CREDENTIAL = b"synthetic-windows-device-credential-032"


@dataclass(frozen=True)
class _Binding:
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int


@dataclass(frozen=True)
class _Projection:
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int


class _Store:
    """Canonical-shaped store that can lie about one scope field at a time."""

    def __init__(self, **wrong):
        self._wrong = wrong
        self.saved = 0

    def save(self, *, binding, credential, now):
        self.saved += 1
        return _Projection(
            binding_ref=self._wrong.get("binding_ref", binding.binding_ref),
            device_id=self._wrong.get("device_id", binding.device_id),
            account_ref=self._wrong.get("account_ref", binding.account_ref),
            workspace_ref=self._wrong.get("workspace_ref", binding.workspace_ref),
            credential_generation=self._wrong.get(
                "credential_generation", binding.credential_generation
            ),
        )

    def load(self, *, binding, now):
        return CREDENTIAL


def _install(store, binding):
    return LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW).install_once(
        challenge_id=CHALLENGE,
        device_id=binding.device_id,
        credential=CREDENTIAL,
        binding=binding,
    )


def test_a_projection_naming_the_same_account_and_workspace_is_confirmed():
    binding = _Binding(BINDING, "pc_abc123", ACCOUNT, WORKSPACE, 3)
    confirmation = _install(_Store(), binding)
    assert confirmation.installed is True
    assert confirmation.binding_ref == BINDING


@pytest.mark.parametrize(
    "wrong",
    [
        {"account_ref": "acct-other"},
        {"workspace_ref": "ws-other"},
        {"binding_ref": "binding-other"},
        {"device_id": "pc-other"},
        {"credential_generation": 4},
    ],
)
def test_a_projection_for_another_account_or_workspace_is_never_confirmed(wrong):
    binding = _Binding(BINDING, "pc_abc123", ACCOUNT, WORKSPACE, 3)
    with pytest.raises(CredentialInstallError):
        _install(_Store(**wrong), binding)


def test_a_store_that_omits_the_scope_fields_is_rejected_not_assumed_correct():
    class _NarrowProjection:
        binding_ref = BINDING
        device_id = "pc_abc123"
        credential_generation = 3

    class _NarrowProjectionStore:
        def save(self, *, binding, credential, now):
            return _NarrowProjection()

        def load(self, *, binding, now):
            return CREDENTIAL

    binding = _Binding(BINDING, "pc_abc123", ACCOUNT, WORKSPACE, 3)
    with pytest.raises(CredentialInstallError):
        _install(_NarrowProjectionStore(), binding)


# -- window 3: saved and read back, but never acknowledged --------------------
def test_an_unacknowledged_install_leaves_its_record_and_claims_nothing():
    """A save+readback can succeed while the process dies before any ACK exists.

    LOCAL2 deletes nothing here — a safe removal would need the canonical
    revocation decision — and reports no completion. The residue therefore stays a
    reconciliation item behind the security hold rather than becoming a silent
    "recovered" or "rolled back" claim.
    """
    from claw_connect.credential_install import (
        RECOVERY_SECURITY_HOLD,
        plan_install_failure_recovery,
    )

    class _TrackingStore(_Store):
        def __init__(self, **wrong):
            super().__init__(**wrong)
            self.deleted: list[str] = []

        def delete(self, binding_ref):
            self.deleted.append(binding_ref)

    store = _TrackingStore()
    binding = _Binding(BINDING, "pc_abc123", ACCOUNT, WORKSPACE, 3)
    confirmation = _install(store, binding)
    assert confirmation.installed is True
    assert store.deleted == []          # no implicit cleanup, no fake rollback

    # Nothing about this confirmation asserts a server-side outcome: it names the
    # binding and the possession proof only, and carries no credential material.
    payload = confirmation.safe_dict()
    assert payload["raw_credential_persisted"] is False
    assert CREDENTIAL not in json.dumps(payload).encode("utf-8", "ignore")

    # An acknowledgement that never reached the server is an unconfirmed state, so
    # the only permitted local disposition is the hold, never a completed recovery.
    hold = plan_install_failure_recovery(revocation_confirmed=None)
    assert hold.action == RECOVERY_SECURITY_HOLD
    assert hold.report_enrolled is False
    assert hold.retry_same_challenge is False
    assert hold.retransmit_credential is False

    # Same process, same receiver: the redeemed challenge cannot be presented twice.
    same_receiver = LocalStoreCredentialReceiver(store=_TrackingStore(), now_factory=lambda: NOW)
    same_receiver.install_once(
        challenge_id=CHALLENGE, device_id=binding.device_id,
        credential=CREDENTIAL, binding=binding,
    )
    with pytest.raises(CredentialInstallError):
        same_receiver.install_once(
            challenge_id=CHALLENGE, device_id=binding.device_id,
            credential=CREDENTIAL, binding=binding,
        )
