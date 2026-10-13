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
import os
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
def _unwritable_state_dir(monkeypatch, connector) -> None:
    """Fail the persistence *writer*, which is the seam the commit actually uses.

    Patching `flush` would no longer inject anything: `complete_login` stages a
    candidate and hands it to `_write` directly, so the writer (and `os.replace`
    below it) is where a real unwritable state directory fails. The first-launch
    record is materialised first, so this breaks the *commit* and not the
    `_load_or_create` that happens before any redemption.
    """
    connector.record()

    def _boom(record):
        raise OSError("state directory is unwritable")

    monkeypatch.setattr(connector, "_write", _boom)


def test_a_success_that_cannot_be_persisted_leaves_no_enrolled_state(tmp_path, monkeypatch):
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    device_id = connector.record().device_id

    _unwritable_state_dir(monkeypatch, connector)
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

    _unwritable_state_dir(monkeypatch, connector)
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


# -- window 1, alias/visibility boundary (CENTRAL review 2026-10-13) -------------
# `record()` returns the shared record object, so a caller can hold that exact
# reference across a login. Restoring `self._record` after a failed write does not
# restore the object that caller already has, so the receipt is staged into a
# private candidate and published only after the write completed. The tests below
# pin that boundary: a failed write, an in-progress write, a failed atomic replace,
# and the positive case where a completed write must still become visible.
def test_a_failed_write_never_touches_the_already_published_record_object(
    tmp_path, monkeypatch
):
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    old = connector.record()
    device_id = old.device_id

    _unwritable_state_dir(monkeypatch, connector)
    with pytest.raises(OSError):
        connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)

    # The object handed out before the failure is the one still published, and it
    # still says "never enrolled" — an alias-safe rollback, not an attribute swap.
    assert old is connector.record()
    assert old.binding_ref is None
    assert old.account_ref is None
    assert old.workspace_ref is None
    assert old.credential_generation is None
    assert old.enrolled_at is None
    assert old.is_enrolled() is False

    # Disk and every projection agree with the held object.
    durable = _durable(tmp_path)
    assert durable["binding_ref"] is None
    assert durable["device_id"] == device_id
    assert connector.device_identity()["binding_ref"] is None
    snapshot = connector.status_snapshot()
    assert snapshot["enrolled"] is False, snapshot
    assert snapshot["binding_ref"] is None, snapshot


def test_an_in_progress_write_cannot_expose_the_staged_receipt(tmp_path, monkeypatch):
    """The record visible *during* the write attempt is still the pre-login one."""
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    old = connector.record()
    observed: list[tuple[object, object]] = []

    def _write_and_fail(record):
        observed.append((connector.record(), record))
        raise OSError("state directory is unwritable")

    monkeypatch.setattr(connector, "_write", _write_and_fail)
    with pytest.raises(OSError):
        connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)

    assert len(observed) == 1
    published_during_write, staged = observed[0]
    assert published_during_write is old
    assert published_during_write.binding_ref is None
    # The candidate did carry the receipt, but it was a separate object that was
    # never published, so it cannot be observed through any connector accessor.
    assert staged is not old
    assert staged.binding_ref == BINDING
    assert connector.record() is old
    assert connector.status_snapshot()["enrolled"] is False


def test_a_failed_atomic_replace_publishes_nothing_and_leaves_only_a_tmp_residue(
    tmp_path, monkeypatch
):
    """Deeper than a monkeypatched `flush`: the real temp-file + `os.replace` seam."""
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    old = connector.record()
    stable = _durable(tmp_path)

    real_replace = os.replace

    def _refuse_replace(src, dst, *args, **kwargs):
        if str(dst).endswith("enrollment.json"):
            raise OSError("atomic replace refused")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", _refuse_replace)
    with pytest.raises(OSError):
        connector.complete_login(challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW)

    assert old is connector.record()
    assert old.binding_ref is None
    assert connector.status_snapshot()["enrolled"] is False
    # The durable record was never replaced, so it is byte-identical.
    assert _durable(tmp_path) == stable
    # The staged candidate reached the temp file, so its residue is the only trace.
    # It is never read back, and a restarted process ignores it.
    assert (tmp_path / "enrollment.json.tmp").exists()
    restarted = _connector(tmp_path, RedeemedOnceThenRefused())
    assert restarted.record().binding_ref is None
    assert restarted.record().device_id == stable["device_id"]


def test_a_successful_write_publishes_the_new_record_and_leaves_the_old_view_intact(
    tmp_path,
):
    """Positive regression: staging must not stop a completed write from landing."""
    port = RedeemedOnceThenRefused()
    connector = _connector(tmp_path, port)
    old = connector.record()

    result = connector.complete_login(
        challenge_id=CHALLENGE, pairing_code=PAIRING_CODE, now=NOW
    )

    published = connector.record()
    assert published is not old                 # staged, not mutated in place
    assert published.binding_ref == result.binding_ref == BINDING
    assert published.account_ref == ACCOUNT
    assert published.workspace_ref == WORKSPACE
    assert published.credential_generation == 1
    assert published.is_enrolled() is True
    # The pre-login object is unchanged, so a caller that held it never sees a
    # binding it was never told about.
    assert old.binding_ref is None
    assert old.is_enrolled() is False
    assert connector.status_snapshot()["enrolled"] is True
    assert connector.device_identity()["binding_ref"] == BINDING
    assert _durable(tmp_path)["binding_ref"] == BINDING


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
