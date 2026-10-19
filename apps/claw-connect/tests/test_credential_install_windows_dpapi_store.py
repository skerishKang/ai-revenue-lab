"""#4139 LOCAL2 — the canonical Windows DPAPI store against the local install gate.

CENTRAL's credential-authority decision (`PADIEM_CONNECTOR_4139_CREDENTIAL_AUTHORITY_TRANSPORT_DECISION_20261012.md`,
Decision B) requires LOCAL2 to *integrate* the existing protected-storage contracts, not
duplicate them. The fake stores in ``test_credential_install_confirmation.py`` pin the
receiver against a lying projection; this file drives the real ``kagent``
``ProtectedFileDeviceCredentialStore`` with the real current-user DPAPI port on Windows and
proves:

* save plus a matching readback confirms installation, and the acknowledgement is keyed
  with the bytes the canonical store actually persisted;
* no record on disk carries the plaintext credential;
* the protected record is bound to the exact binding context, so a changed account,
  credential ref or generation cannot be read back as if it matched;
* a binding the canonical store rejects (revoked, expired) is never reported installed;
* a record damaged after ``save`` is refused even though its projection looked correct,
  ``delete`` really removes the secret, and a redeemed challenge stays single-use.

Non-Windows runners skip with the reason stated, because the shipped artifact is
``os: ["win32"]`` and DPAPI has no POSIX equivalent. The real-process harness
``verify_windows_live.py`` is deliberately untouched: it starts supervised processes and
mutates per-user state, so it stays outside any CI gate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
KAGENT_SRC = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"

sys.path.insert(0, str(ROOT))

from claw_connect.credential_install import (  # noqa: E402
    INSTALL_ACK_TRANSCRIPT_VERSION,
    REDEEMED_CHALLENGE_SINGLE_USE,
    CredentialInstallError,
    LocalStoreCredentialReceiver,
)

# The canonical pairing factory issues 32 bytes; 16-4096 is the protocol ack bound, not
# the generic protected-store capacity (16384).
CREDENTIAL = hashlib.sha256(b"#4139 synthetic connector device credential").digest()[:32]
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(days=30)

if os.name != "nt":
    pytest.skip(
        "win32-only product surface: DPAPI has no POSIX equivalent (not a missing-dependency skip)",
        allow_module_level=True,
    )

if not KAGENT_SRC.is_dir():
    pytest.skip(
        f"canonical kagent store root not found where expected: {KAGENT_SRC}",
        allow_module_level=True,
    )

sys.path.insert(0, str(KAGENT_SRC))

try:
    from kagent.contracts import ContractError  # noqa: E402
    from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle  # noqa: E402
    from kagent.local_agent_secure_transport import (  # noqa: E402
        ProtectedFileDeviceCredentialStore,
        WindowsDpapiProtectedDataPort,
    )
except Exception as exc:  # pragma: no cover - environment, not product behaviour
    pytest.skip(
        f"canonical kagent protected store is not importable here: {exc!r}",
        allow_module_level=True,
    )


def _binding(**overrides) -> DeviceBinding:
    values = {
        "device_id": "pc-win-contract-1",
        "binding_ref": "binding-win-contract-1",
        "account_ref": "acct-win-contract-1",
        "workspace_ref": "ws-win-contract-1",
        "credential_ref": "credref-win-contract-1",
        "credential_generation": 7,
        "issued_at": NOW,
        "credential_expires_at": EXPIRES,
        "state": DeviceLifecycle.PAIRED_OFFLINE,
    }
    values.update(overrides)
    return DeviceBinding(**values)


def _store(tmp_path: Path) -> ProtectedFileDeviceCredentialStore:
    return ProtectedFileDeviceCredentialStore(
        base_dir=tmp_path, protected_data=WindowsDpapiProtectedDataPort()
    )


def _receiver(store) -> LocalStoreCredentialReceiver:
    return LocalStoreCredentialReceiver(store=store, now_factory=lambda: NOW)


def _install(receiver, *, binding, challenge_id="challenge-win-1"):
    return receiver.install_once(
        challenge_id=challenge_id,
        device_id=binding.device_id,
        credential=CREDENTIAL,
        binding=binding,
    )


def _disk_payload(tmp_path: Path) -> bytes:
    return b"".join(sorted(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()))


def test_real_dpapi_save_and_readback_confirms_installation(tmp_path):
    store = _store(tmp_path)
    binding = _binding()
    assert store is not None and WindowsDpapiProtectedDataPort is not None
    assert DeviceBinding is not None

    confirmation = _install(_receiver(store), binding=binding)
    assert confirmation.installed is True
    assert confirmation.confirmed_by_local_store is True
    assert confirmation.raw_credential_persisted is False
    assert confirmation.binding_ref == binding.binding_ref
    assert confirmation.device_id == binding.device_id
    assert confirmation.credential_generation == binding.credential_generation
    assert confirmation.proof_kind == "protected_store_save_readback"
    assert confirmation.transcript_version == INSTALL_ACK_TRANSCRIPT_VERSION

    # The credential really round-trips through DPAPI, and the acknowledgement is keyed
    # with what the canonical store holds rather than with the caller's copy alone.
    persisted = store.load(binding=binding, now=NOW)
    assert persisted == CREDENTIAL
    transcript = "\n".join(
        (
            INSTALL_ACK_TRANSCRIPT_VERSION,
            "challenge-win-1",
            binding.device_id,
            binding.binding_ref,
            str(binding.credential_generation),
        )
    ).encode("utf-8")
    assert confirmation.proof_hex == hmac.new(persisted, transcript, hashlib.sha256).hexdigest()


def test_dpapi_record_never_carries_the_plaintext_credential(tmp_path):
    store = _store(tmp_path)
    _install(_receiver(store), binding=_binding())
    payload = _disk_payload(tmp_path)
    assert payload, "the canonical store must have written a protected record"
    assert CREDENTIAL not in payload
    assert CREDENTIAL.hex().encode("ascii") not in payload
    assert b"protected_blob_b64" in payload
    assert b"windows_dpapi_current_user" in payload


class _StoreThatLosesWhatItWrote:
    """Canonical store whose persisted record is damaged immediately after ``save``.

    This is the real-DPAPI version of "do not trust the save projection": the store still
    returns a correct projection, but the bytes on disk no longer belong to this binding
    context, so only an actual readback can expose it.
    """

    def __init__(self, store, base_dir: Path):
        self._store = store
        self._base = Path(base_dir)

    def save(self, *, binding, credential, now):
        projection = self._store.save(binding=binding, credential=credential, now=now)
        for path in sorted(self._base.glob("*.credential.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            record["account_ref"] = "acct-win-contract-tampered"
            path.write_text(json.dumps(record), encoding="utf-8")
        return projection

    def load(self, *, binding, now):
        return self._store.load(binding=binding, now=now)


def test_readback_of_a_damaged_record_refuses_confirmation(tmp_path):
    store = _StoreThatLosesWhatItWrote(_store(tmp_path), tmp_path)
    with pytest.raises(CredentialInstallError) as exc:
        _install(_receiver(store), binding=_binding(), challenge_id="challenge-win-7")
    assert str(exc.value) == "protected store readback failed"
    # The projection alone looked perfect, so a save-only confirmation would have
    # reported this PC as enrolled over a record DPAPI cannot serve.


def test_delete_removes_the_persisted_credential(tmp_path):
    store = _store(tmp_path)
    binding = _binding()
    _install(_receiver(store), binding=binding)
    assert store.load(binding=binding, now=NOW) == CREDENTIAL

    store.delete(binding.binding_ref)
    assert _disk_payload(tmp_path) == b""
    with pytest.raises(ContractError):
        store.load(binding=binding, now=NOW)


def test_protected_record_is_bound_to_the_exact_binding_context(tmp_path):
    store = _store(tmp_path)
    persisted = _binding()
    _install(_receiver(store), binding=persisted)

    # Each of these describes a different binding context over the same stored record.
    # DPAPI entropy plus the stored context must refuse to serve them as a match, so no
    # changed scope/credential/generation can be read back as "the installed one".
    for other in (
        _binding(account_ref="acct-win-contract-2"),
        _binding(workspace_ref="ws-win-contract-2"),
        _binding(credential_ref="credref-win-contract-2"),
        _binding(credential_generation=8),
    ):
        with pytest.raises(ContractError):
            store.load(binding=other, now=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"state": DeviceLifecycle.REVOKED},
        {"state": DeviceLifecycle.CREDENTIAL_EXPIRED},
        {"state": DeviceLifecycle.UNPAIRED},
        {
            "issued_at": NOW - timedelta(days=1),
            "credential_expires_at": NOW - timedelta(seconds=1),
        },
    ],
)
def test_a_binding_the_canonical_store_rejects_is_never_reported_installed(
    tmp_path, overrides
):
    store = _store(tmp_path)
    with pytest.raises(CredentialInstallError) as exc:
        _install(_receiver(store), binding=_binding(**overrides), challenge_id="challenge-win-9")
    assert str(exc.value) == "protected store save failed"
    # Nothing was written, so a later readback of the real binding still has to succeed
    # for the receiver rather than inherit a half-installed state.
    assert _disk_payload(tmp_path) == b""
    _install(_receiver(store), binding=_binding(), challenge_id="challenge-win-10")


def test_redeemed_challenge_stays_single_use_against_the_real_store(tmp_path):
    receiver = _receiver(_store(tmp_path))
    binding = _binding()
    _install(receiver, binding=binding)
    with pytest.raises(CredentialInstallError) as exc:
        _install(receiver, binding=binding)
    assert str(exc.value) == REDEEMED_CHALLENGE_SINGLE_USE


def test_connector_keeps_no_credential_and_no_product_scope_in_its_own_record():
    # One account/PC registration shared by every product: the connector's local record
    # stores no credential material and no product dimension, and this module adds no
    # second store of its own.
    from claw_connect import enrollment

    assert enrollment.RECORD_KEYS.isdisjoint(
        {
            "credential",
            "credential_b64",
            "raw_device_credential",
            "protected_blob_b64",
            "product_id",
            "products",
        }
    )
    assert not any(
        field in enrollment.RECORD_KEYS for field in ("account_scope_grants", "grants")
    )
    with pytest.raises(TypeError):
        enrollment.EnrollmentRecord(device_id="pc-1", credential_b64="x")  # type: ignore[call-arg]
