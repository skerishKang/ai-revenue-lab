"""#4139 — durable device binding so a registered PC can restart itself.

The one supervised Resident is handed its binding in-process at enrollment: the
Web-issued challenge is redeemed and the resulting ``DeviceBinding`` lives only
in that process's memory. The credential bytes are durable (the canonical
``ProtectedFileDeviceCredentialStore``), but the *binding* was not — so after a
logout/logon or a tray restart the Resident had nothing to resume from and
refused with ``handoff_refused``, even though the PC was already registered.

This module persists that binding next to the credential it belongs to, in the
same canonical credential directory, using the **same** ``ProtectedDataPort``
(Windows DPAPI, current user). It introduces no new store, authority, route or
credential path.

What is deliberately *not* written to disk:

* the raw device credential — it stays only in the canonical protected store;
* the pairing code and the pairing challenge id — one-shot, never persisted;
* ``credential_ref`` in the clear — it is stored **DPAPI-protected**, under an
  entropy derived from the binding it belongs to. The protection is not
  circular (it does not depend on ``credential_ref`` itself), so it can be
  unprotected on the next start, while a copy of the file alone is useless
  without the current Windows user's DPAPI key.

Why ``credential_ref`` must be recoverable at all: it is the DPAPI entropy
preimage for the canonical credential record (``sha256(canonical(context))``
where the context holds ``sha256(credential_ref)``). Without it a resumed
binding could not unprotect its own credential, and any substitute reference
would change the fingerprint the local broker authority checks — so the resumed
binding would no longer be the binding the server issued. It is a bounded,
non-secret reference by contract (``local_agent_secure_transport._ref`` refuses
a value that contains credential material), and it is protected here anyway.

    SECOND_CREDENTIAL_STORE=0
    RAW_CREDENTIAL_PERSISTED=0
    CREDENTIAL_REF_PLAINTEXT_ON_DISK=0
    PAIRING_CODE_PERSISTED=0
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError
from .local_agent_pairing import DeviceBinding, DeviceLifecycle
from .local_agent_secure_transport import ProtectedDataPort, _aware, _ref

#: The binding record is a sibling of the credential records it belongs to.
DEVICE_BINDING_FILENAME = "device-binding.json"
DEVICE_BINDING_CONTRACT_VERSION = "claw-local-agent-device-binding.v1"
#: Entropy domain for the protected ``credential_ref``. Versioned so a future
#: rotation is an explicit migration rather than a silent reinterpretation.
_REF_ENTROPY_TRANSCRIPT = b"claw-local-agent-credential-ref.v1"
#: Bounded so a corrupt or hostile file can never be read as a large payload.
MAX_BINDING_RECORD_BYTES = 16_384
#: Lifecycle states a *resumable* binding may be in. Revoked, expired, unpaired
#: and update-required devices are refused by the canonical rule instead of
#: being resumed into a session the server would reject anyway.
_RESUMABLE_STATES = frozenset({DeviceLifecycle.PAIRED_OFFLINE, DeviceLifecycle.ONLINE})
_RECORD_KEYS = frozenset(
    {
        "contract_version",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "issued_at",
        "credential_expires_at",
        "state",
        "credential_ref_protected_b64",
        "protection",
    }
)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be ISO-8601 text")
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")), field_name)
    except ValueError as exc:
        raise ContractError(f"{field_name} must be valid ISO-8601 text") from exc


def _ref_entropy(binding_ref: str) -> bytes:
    """Entropy binding the protected reference to this exact device binding.

    Derived from the *public* binding ref, never from ``credential_ref`` itself,
    so unprotecting does not require the value it is protecting.
    """
    return hashlib.sha256(_REF_ENTROPY_TRANSCRIPT + b":" + binding_ref.encode("utf-8")).digest()


@dataclass(frozen=True)
class ResumedDeviceBinding:
    """A binding rebuilt from disk.

    It carries no credential: the caller must load that from the canonical
    protected store *with this binding*, which is what proves the rebuilt
    context is the one the credential was protected under.
    """

    binding: DeviceBinding

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DEVICE_BINDING_CONTRACT_VERSION,
            "binding": self.binding.safe_dict(),
            "raw_device_credential": False,
            "credential_ref_exposed": False,
            "resumed_from_disk": True,
        }


class ProtectedDeviceBindingStore:
    """Durable, secret-free binding record in the canonical credential directory."""

    def __init__(
        self,
        *,
        base_dir: str | os.PathLike[str],
        protected_data: ProtectedDataPort,
    ) -> None:
        path = Path(base_dir).expanduser()
        if not path.is_absolute():
            raise ContractError("device binding base_dir must be absolute")
        if not hasattr(protected_data, "protect") or not hasattr(protected_data, "unprotect"):
            raise ContractError("protected_data must implement protect/unprotect")
        path.mkdir(parents=True, exist_ok=True)
        self._base_dir = path.resolve()
        self._protected_data = protected_data

    @property
    def path(self) -> Path:
        return self._base_dir / DEVICE_BINDING_FILENAME

    def save(self, *, binding: DeviceBinding, now: datetime) -> Path:
        """Persist the binding. The raw credential is never part of this record."""
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        now = _aware(now, "now")
        protected = self._protected_data.protect(
            binding.credential_ref.encode("utf-8"), entropy=_ref_entropy(binding.binding_ref)
        )
        if not isinstance(protected, bytes) or not protected:
            raise ContractError("protected-data adapter returned an invalid reference payload")
        record = {
            "contract_version": DEVICE_BINDING_CONTRACT_VERSION,
            "binding_ref": binding.binding_ref,
            "device_id": binding.device_id,
            "account_ref": binding.account_ref,
            "workspace_ref": binding.workspace_ref,
            "credential_generation": binding.credential_generation,
            "issued_at": _iso(binding.issued_at),
            "credential_expires_at": _iso(binding.credential_expires_at),
            "state": binding.state.value,
            "credential_ref_protected_b64": base64.b64encode(protected).decode("ascii"),
            "protection": "windows_dpapi_current_user",
        }
        encoded = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_BINDING_RECORD_BYTES:
            raise ContractError("device binding record exceeds repository bound")
        destination = self.path
        fd, temp_name = tempfile.mkstemp(prefix=".pending-", suffix=".binding", dir=self._base_dir)
        try:
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return destination

    def load(self, *, device_id: str, now: datetime) -> ResumedDeviceBinding:
        """Rebuild the binding for ``device_id``. Fails closed on any doubt."""
        now = _aware(now, "now")
        device_id = _ref(device_id, "device_id")
        record = self._read_record()
        if record["device_id"] != device_id:
            # A binding that belongs to another device must never be resumed
            # into this one, even when both records share a directory.
            raise ContractError("device binding record belongs to another device")
        try:
            credential_ref = self._protected_data.unprotect(
                base64.b64decode(record["credential_ref_protected_b64"], validate=True),
                entropy=_ref_entropy(record["binding_ref"]),
            ).decode("utf-8")
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ContractError("protected device credential reference is invalid") from exc
        state = DeviceLifecycle(record["state"])
        binding = DeviceBinding(
            device_id=record["device_id"],
            binding_ref=record["binding_ref"],
            account_ref=record["account_ref"],
            workspace_ref=record["workspace_ref"],
            credential_ref=credential_ref,
            credential_generation=record["credential_generation"],
            issued_at=_parse_iso(record["issued_at"], "issued_at"),
            credential_expires_at=_parse_iso(record["credential_expires_at"], "credential_expires_at"),
            state=state,
        )
        if state not in _RESUMABLE_STATES:
            raise ContractError("device binding is not resumable in its current lifecycle")
        if now >= binding.credential_expires_at:
            raise ContractError("device binding credential is expired")
        return ResumedDeviceBinding(binding=binding)

    def exists(self) -> bool:
        return self.path.is_file()

    def delete(self) -> None:
        """Forget this binding (logout / unpair). The credential store is separate."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    def _read_record(self) -> dict[str, Any]:
        path = self.path
        try:
            with path.open("rb") as handle:
                encoded = handle.read(MAX_BINDING_RECORD_BYTES + 1)
        except FileNotFoundError as exc:
            raise ContractError("no durable device binding is stored") from exc
        if len(encoded) > MAX_BINDING_RECORD_BYTES:
            raise ContractError("device binding record is too large")
        try:
            record = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("device binding record is invalid") from exc
        if type(record) is not dict or set(record) != _RECORD_KEYS:
            raise ContractError("device binding record schema is closed")
        if record["contract_version"] != DEVICE_BINDING_CONTRACT_VERSION:
            raise ContractError("device binding record contract version is unsupported")
        if record["protection"] != "windows_dpapi_current_user":
            raise ContractError("device binding record protection mode is invalid")
        for field_name in ("binding_ref", "device_id", "account_ref", "workspace_ref"):
            _ref(record[field_name], field_name)
        generation = record["credential_generation"]
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ContractError("device binding credential_generation is invalid")
        if not isinstance(record["credential_ref_protected_b64"], str) or not record["credential_ref_protected_b64"]:
            raise ContractError("device binding protected reference is missing")
        return record


__all__ = [
    "DEVICE_BINDING_CONTRACT_VERSION",
    "DEVICE_BINDING_FILENAME",
    "MAX_BINDING_RECORD_BYTES",
    "ProtectedDeviceBindingStore",
    "ResumedDeviceBinding",
]
