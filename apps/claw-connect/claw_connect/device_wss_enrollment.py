"""Review-only PC counterpart of CENTRAL #4476 one-socket WSS handoff.

NO production WebSocket is constructed here. A future vetted transport must
verify the TLS peer and exact WSS route independently. Tests inject a fake
socket and verifier. The source-only device state machine sends pairing-code
possession proofs and only acknowledges a credential after the canonical
protected store confirms save + matching readback.

No browser session/cookie, new credential DB, second Broker or retry after
redemption. A terminal frame is NOT a durable local enrollment record.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Protocol

from .credential_install import ProtectedCredentialReceiverPort
from .enrollment import (
    ConnectorEnrollment, EnrollmentContractError, EnrollmentPersistenceError,
    EnrollmentResult, LIFECYCLE_PAIRED_OFFLINE, build_enrollment_proof_ref,
)
from .credential_install import plan_install_failure_recovery
from dataclasses import replace

WSS_DEVICE_TRANSPORT_PRODUCTION_WIRED = False
WSS_DEVICE_ENROLLMENT_PRODUCTION_ENABLED = False
#: The existing canonical protected binding store (kagent) is what makes a
#: registered PC restartable without re-registration. Enrollment does not own a
#: second store: it reuses that one or fails closed.
CANONICAL_BINDING_STORE_REUSED = True
BINDING_PERSISTED_BEFORE_ENROLLMENT_PUBLISH = True
#: The canonical protected credential directory the Resident itself resumes from.
_CANONICAL_CREDENTIAL_DIR_ENV = "PADIEM_AGENT_CREDENTIAL_DIR"
MAX_FRAME_CHARS = 8192
MAX_CREDENTIAL_BYTES = 4096
FRAME_TIMEOUT_SECONDS = 10.0
INSTALL_ACK_TIMEOUT_SECONDS = 25.0
BOOTSTRAP_TRANSCRIPT = "padiem.connector-gateway-bootstrap.v1"
SESSION_TRANSCRIPT = "padiem.connector-gateway-session.v1"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")
_LEASE = re.compile(r"^gateway\.[0-9a-f]{32}$")
_BINDING = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref",
    "credential_ref", "credential_generation", "credential_expires_at",
})


class DeviceSessionRefused(RuntimeError):
    """Bounded local refusal; never includes a wire frame or secret."""


class DeviceTextSocket(Protocol):
    async def send_text(self, message: str) -> None: ...
    async def receive_text(self) -> str: ...
    async def close(self) -> None: ...


class TrustedDeviceTls(Protocol):
    async def verify(self, socket: DeviceTextSocket) -> bool: ...


@dataclass(frozen=True)
class DeviceSessionResult:
    """Receipt after a verified terminal frame, NOT a persisted enrollment.

    ``canonical_binding`` is the ONE canonical ``kagent.local_agent_pairing``
    DeviceBinding this session installed the credential under. It is carried out
    of the session for exactly one reason: the same binding must be made durable
    in the existing protected binding store *before* any enrollment record is
    published, so a restarted PC can resume instead of refusing. It is a
    bounded, non-secret reference set — never the credential.
    """

    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_expires_at: datetime
    lifecycle: str = "paired_offline"
    local_record_committed: bool = False
    online: bool = False
    canonical_binding: Any | None = None


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise DeviceSessionRefused("device_wire_duplicate_key")
        out[key] = value
    return out


def _frame(raw: Any, fields: frozenset[str]) -> dict[str, Any]:
    if type(raw) is not str or not 0 < len(raw) <= MAX_FRAME_CHARS:
        raise DeviceSessionRefused("device_wire_size_invalid")
    try:
        parsed = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, TypeError) as exc:
        raise DeviceSessionRefused("device_wire_invalid_json") from exc
    if type(parsed) is not dict or set(parsed) != fields:
        raise DeviceSessionRefused("device_wire_fields_invalid")
    return parsed


def _ref(value: Any) -> bool:
    return type(value) is str and _SAFE_REF.fullmatch(value) is not None


def _proof(value: Any) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _wire(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def _timestamp(value: Any, now: datetime) -> datetime:
    if type(value) is not str:
        raise DeviceSessionRefused("device_credential_expiry_invalid")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeviceSessionRefused("device_credential_expiry_invalid") from exc
    if moment.tzinfo is None or moment.utcoffset() is None or moment <= now:
        raise DeviceSessionRefused("device_credential_expired")
    return moment


def _mac(code: str, *parts: str, key: bytes | None = None) -> str:
    return hmac.new(
        code.encode("ascii") if key is None else key,
        "\n".join(parts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _action_mac(
    *, code: str, challenge_id: str, device_id: str, nonce: str,
    lease: str, action: str, counter: int, body: bytes,
) -> str:
    session_key = hmac.new(
        code.encode("ascii"),
        "\n".join((SESSION_TRANSCRIPT, challenge_id, device_id, nonce, lease)).encode(),
        hashlib.sha256,
    ).digest()
    return _mac(
        code, SESSION_TRANSCRIPT, action, str(counter),
        hashlib.sha256(body).hexdigest(), key=session_key,
    )


def canonical_kagent_binding_factory(
    fields: dict[str, Any], *, now: datetime, expires_at: datetime,
) -> Any:
    """Construct the ONE existing kagent DeviceBinding, not a lookalike.

    The actual DPAPI ProtectedFileDeviceCredentialStore requires its canonical
    DeviceBinding type, complete with issued_at and lifecycle. A generic object
    falsely passes a synthetic fake store but fails on the real Windows store.
    Missing kagent fails closed before any credential is written or ACK sent.
    """
    try:
        from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
    except ImportError as exc:
        raise DeviceSessionRefused("canonical_kagent_binding_not_installed") from exc
    try:
        return DeviceBinding(
            device_id=fields["device_id"],
            binding_ref=fields["binding_ref"],
            account_ref=fields["account_ref"],
            workspace_ref=fields["workspace_ref"],
            credential_ref=fields["credential_ref"],
            credential_generation=fields["credential_generation"],
            issued_at=now, credential_expires_at=expires_at,
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
    except Exception as exc:
        raise DeviceSessionRefused("canonical_device_binding_invalid") from exc


async def _send(socket: DeviceTextSocket, content: dict[str, Any]) -> None:
    await asyncio.wait_for(socket.send_text(_wire(content)), timeout=FRAME_TIMEOUT_SECONDS)


async def _receive(socket: DeviceTextSocket, fields: frozenset[str]) -> dict[str, Any]:
    return _frame(
        await asyncio.wait_for(socket.receive_text(), timeout=FRAME_TIMEOUT_SECONDS),
        fields,
    )


async def run_review_only_device_session(
    *, socket: DeviceTextSocket, trusted_tls: TrustedDeviceTls,
    receiver: ProtectedCredentialReceiverPort, challenge_id: str,
    device_id: str, pairing_code: str, now: datetime | None = None,
    binding_factory: Callable[..., Any] = canonical_kagent_binding_factory,
) -> DeviceSessionResult:
    """Exercise the exact server WSS contract; no production transport supplied.

    On failure *after* credential redemption the socket is closed WITHOUT an ACK;
    the canonical server must compensate. Neither retry nor local enrollment
    success may be inferred from a disconnected socket.
    """
    if not (_ref(challenge_id) and _ref(device_id)
            and type(pairing_code) is str and _CODE.fullmatch(pairing_code)):
        raise DeviceSessionRefused("device_session_input_invalid")
    if not callable(getattr(receiver, "ready", None)) or not receiver.ready(
        challenge_id=challenge_id, device_id=device_id,
    ):
        raise DeviceSessionRefused("protected_store_not_ready")
    if not callable(getattr(trusted_tls, "verify", None)):
        raise DeviceSessionRefused("trusted_tls_verifier_missing")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise DeviceSessionRefused("device_clock_invalid")
    try:
        if await asyncio.wait_for(trusted_tls.verify(socket), timeout=5.0) is not True:
            raise DeviceSessionRefused("trusted_tls_required")
        await _send(socket, {
            "type": "begin", "challenge_id": challenge_id,
            "device_id": device_id, "proof_ref": build_enrollment_proof_ref(
                challenge_id=challenge_id, device_id=device_id, pairing_code=pairing_code,
            ),
        })
        first = await _receive(socket, frozenset({
            "type", "challenge_id", "device_id", "lease_ref", "nonce_hex", "expires_at",
        }))
        lease = first["lease_ref"]
        nonce = first["nonce_hex"]
        if (first["type"] != "nonce" or first["challenge_id"] != challenge_id
            or first["device_id"] != device_id or type(lease) is not str
            or _LEASE.fullmatch(lease) is None or not _proof(nonce)):
            raise DeviceSessionRefused("device_nonce_correlation_invalid")
        _timestamp(first["expires_at"], clock)
        await _send(socket, {
            "type": "finish", "lease_ref": lease,
            "proof_hex": _mac(
                pairing_code, BOOTSTRAP_TRANSCRIPT, challenge_id, device_id,
                nonce, lease,
            ),
        })
        verified = await _receive(socket, frozenset({"type", "lease_ref", "credential"}))
        if (verified != {"type": "bootstrap_verified", "lease_ref": lease,
                         "credential": False}):
            raise DeviceSessionRefused("device_bootstrap_not_verified")
        await _send(socket, {
            "type": "credential_fetch", "counter": 1,
            "proof_hex": _action_mac(
                code=pairing_code, challenge_id=challenge_id, device_id=device_id,
                nonce=nonce, lease=lease, action="credential_fetch",
                counter=1, body=b"",
            ),
        })
        delivery = await _receive(socket, frozenset({
            "type", "challenge_id", "device_id", "lease_ref", "binding",
            "credential_b64",
        }))
        if (delivery["type"] != "credential_once"
            or delivery["challenge_id"] != challenge_id
            or delivery["device_id"] != device_id
            or delivery["lease_ref"] != lease
            or type(delivery["binding"]) is not dict
            or set(delivery["binding"]) != _BINDING):
            raise DeviceSessionRefused("device_delivery_correlation_invalid")
        binding = delivery["binding"]
        if (binding["device_id"] != device_id
            or not all(_ref(binding[key]) for key in (
                "binding_ref", "device_id", "account_ref",
                "workspace_ref", "credential_ref",
            )) or type(binding["credential_generation"]) is not int
            or not 1 <= binding["credential_generation"] <= 1_000_000):
            raise DeviceSessionRefused("device_binding_invalid")
        expiry = _timestamp(binding["credential_expires_at"], clock)
        encoded = delivery["credential_b64"]
        if type(encoded) is not str or len(encoded) > 5472:
            raise DeviceSessionRefused("device_credential_encoding_invalid")
        try:
            credential = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DeviceSessionRefused("device_credential_encoding_invalid") from exc
        if (not 16 <= len(credential) <= MAX_CREDENTIAL_BYTES
            or base64.b64encode(credential).decode("ascii") != encoded):
            raise DeviceSessionRefused("device_credential_encoding_invalid")
        # This is the ONLY place the raw credential enters protected storage.
        # The receiver checks binding scope and reads back bytes from its store.
        if not callable(binding_factory):
            raise DeviceSessionRefused("canonical_binding_factory_missing")
        canonical_binding = binding_factory(binding, now=clock, expires_at=expiry)
        confirmation = receiver.install_once(
            challenge_id=challenge_id, device_id=device_id,
            credential=credential, binding=canonical_binding,
        )
        if (confirmation.installed is not True
            or confirmation.confirmed_by_local_store is not True
            or confirmation.challenge_id != challenge_id
            or confirmation.device_id != device_id
            or confirmation.binding_ref != binding["binding_ref"]
            or confirmation.credential_generation != binding["credential_generation"]
            or not _proof(confirmation.proof_hex)):
            raise DeviceSessionRefused("device_install_not_confirmed")
        safe = confirmation.safe_dict()
        body = _wire({key: safe[key] for key in (
            "challenge_id", "device_id", "binding_ref", "credential_generation",
            "proof_kind", "transcript_version", "local_store_confirmed", "proof_hex",
        )}).encode("utf-8")
        await _send(socket, {
            "type": "install_ack", "counter": 2,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "proof_hex": _action_mac(
                code=pairing_code, challenge_id=challenge_id, device_id=device_id,
                nonce=nonce, lease=lease, action="install_ack",
                counter=2, body=body,
            ),
        })
        # This is a server-owned terminal result, not a new entitlement.
        terminal = await _receive(socket, frozenset({
            "type", "status", "can_retry_challenge",
        }))
        if (terminal != {"type": "terminal", "status": "paired_offline",
                         "can_retry_challenge": False}):
            raise DeviceSessionRefused("device_terminal_security_hold")
        return DeviceSessionResult(
            device_id=device_id, binding_ref=binding["binding_ref"],
            account_ref=binding["account_ref"], workspace_ref=binding["workspace_ref"],
            credential_generation=binding["credential_generation"],
            credential_expires_at=expiry,
            # The exact canonical binding the credential was installed under.
            canonical_binding=canonical_binding,
        )
    except DeviceSessionRefused:
        raise
    except Exception as exc:
        raise DeviceSessionRefused("device_session_security_hold") from exc
    finally:
        try:
            await asyncio.wait_for(socket.close(), timeout=2.0)
        except Exception:
            pass



def canonical_binding_store(*, base_dir: str, protected_data: Any | None = None) -> Any:
    """The ONE existing protected binding store, or a bounded refusal.

    ``kagent.local_agent_device_binding_store.ProtectedDeviceBindingStore`` is
    the canonical durable binding record, protected by the same current-user
    DPAPI port as the credential. The Connector reuses it instead of owning a
    second store or a plaintext binding file, and a machine where the canonical
    Agent package is not installed fails closed rather than publishing an
    enrollment it cannot resume.
    """
    configured = base_dir.strip() if isinstance(base_dir, str) else ""
    if not configured:
        raise DeviceSessionRefused("canonical_credential_dir_unconfigured")
    root = Path(configured).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise DeviceSessionRefused("canonical_credential_dir_unavailable")
    try:
        from kagent.local_agent_device_binding_store import ProtectedDeviceBindingStore
        from kagent.local_agent_secure_transport import WindowsDpapiProtectedDataPort
    except ImportError as exc:
        raise DeviceSessionRefused("canonical_binding_store_not_installed") from exc
    # Never a second protection mode: the canonical current-user DPAPI port, on
    # the canonical credential directory the Resident itself resumes from.
    protection = (
        protected_data if protected_data is not None else WindowsDpapiProtectedDataPort()
    )
    return ProtectedDeviceBindingStore(base_dir=root, protected_data=protection)


def resolve_canonical_binding_store() -> Any:
    """Default store for the real path: the canonical credential directory."""
    return canonical_binding_store(
        base_dir=os.environ.get(_CANONICAL_CREDENTIAL_DIR_ENV, ""),
    )


def persist_and_verify_canonical_binding(
    store: Any, *, binding: Any, now: datetime,
) -> Any:
    """Persist the binding and prove it restores, or refuse.

    The save is followed by a *readback through the same store* and a full fact
    comparison, because a record that cannot be rebuilt is not a binding a
    restarted Resident could resume from — and an enrollment may never be
    published on the strength of a write nobody verified.
    """
    if (store is None
            or not callable(getattr(store, "save", None))
            or not callable(getattr(store, "load", None))):
        raise DeviceSessionRefused("canonical_binding_store_unavailable")
    try:
        store.save(binding=binding, now=now)
    except Exception as exc:
        raise DeviceSessionRefused("device_binding_not_durable") from exc
    try:
        resumed = store.load(device_id=binding.device_id, now=now)
    except Exception as exc:
        raise DeviceSessionRefused("device_binding_restore_refused") from exc
    restored = getattr(resumed, "binding", None)
    if (restored is None
            or restored.binding_ref != binding.binding_ref
            or restored.device_id != binding.device_id
            or restored.account_ref != binding.account_ref
            or restored.workspace_ref != binding.workspace_ref
            or restored.credential_generation != binding.credential_generation
            or restored.credential_ref != binding.credential_ref
            or restored.credential_expires_at != binding.credential_expires_at):
        raise DeviceSessionRefused("device_binding_restore_mismatch")
    return resumed


async def run_and_stage_review_only_device_enrollment(
    *, enrollment: ConnectorEnrollment, socket: DeviceTextSocket,
    trusted_tls: TrustedDeviceTls, receiver: ProtectedCredentialReceiverPort,
    challenge_id: str, pairing_code: str, now: datetime | None = None,
    binding_factory: Callable[..., Any] = canonical_kagent_binding_factory,
    binding_store: Any | None = None,
) -> EnrollmentResult:
    """Preserve the existing stage-then-publish contract after WSS terminal.

    An existing binding or unresolved post-redeem hold cannot be overwritten.
    The stable first-launch device identity is minted BEFORE the WSS begins.
    A local write failure leaves the prior shared record unchanged and reports
    the existing same-Broker-owner security_hold; no same-code retry occurs.

    This is only a composition seam for later independently reviewed trusted
    PC WSS transport. It cannot mount a socket or turn on production.
    """
    if type(enrollment) is not ConnectorEnrollment:
        raise DeviceSessionRefused("device_enrollment_authority_invalid")
    if enrollment.reconciliation_hold() is not None:
        raise DeviceSessionRefused("device_existing_security_hold")
    current = enrollment.record()
    if current.revoked or current.is_enrolled():
        raise DeviceSessionRefused("device_existing_binding_requires_owner_revoke")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise DeviceSessionRefused("device_clock_invalid")
    delivery = await run_review_only_device_session(
        socket=socket, trusted_tls=trusted_tls, receiver=receiver,
        challenge_id=challenge_id, pairing_code=pairing_code,
        device_id=current.device_id, now=moment, binding_factory=binding_factory,
    )
    # Nothing from an unsigned JSON receipt can manufacture a new owner here:
    # the result is usable only after the *same socket* confirmed the keyed
    # readback ACK and the canonical Host's exact offline terminal response.
    if (delivery.device_id != current.device_id or delivery.online
        or delivery.local_record_committed or delivery.lifecycle != LIFECYCLE_PAIRED_OFFLINE):
        raise DeviceSessionRefused("device_terminal_receipt_invalid")
    # #4139 STEP 4: the credential is durable and the server has confirmed its
    # offline terminal, but the *binding* was still only in this process's
    # memory — so a restarted PC had nothing to resume from. Make the same
    # canonical binding durable in the existing protected binding store and
    # prove it restores BEFORE the enrollment record is published. A store that
    # cannot persist or cannot read back fails closed onto the existing
    # reconciliation hold; the enrollment is never reported.
    canonical_binding = delivery.canonical_binding
    try:
        if canonical_binding is None:
            raise DeviceSessionRefused("device_canonical_binding_missing")
        store = (
            binding_store if binding_store is not None
            else resolve_canonical_binding_store()
        )
        persist_and_verify_canonical_binding(
            store, binding=canonical_binding, now=moment,
        )
    except DeviceSessionRefused as exc:
        hold = EnrollmentPersistenceError(
            recovery=plan_install_failure_recovery(revocation_confirmed=None),
            challenge_id=challenge_id, device_id=current.device_id,
            binding_ref=delivery.binding_ref, account_ref=delivery.account_ref,
            workspace_ref=delivery.workspace_ref,
            credential_generation=delivery.credential_generation,
        )
        enrollment._reconciliation_hold = hold.safe_dict()
        raise hold from exc
    candidate = replace(current)
    candidate.binding_ref = delivery.binding_ref
    candidate.account_ref = delivery.account_ref
    candidate.workspace_ref = delivery.workspace_ref
    candidate.credential_generation = delivery.credential_generation
    candidate.credential_expires_at = delivery.credential_expires_at
    candidate.enrolled_at = moment
    candidate.device_lifecycle = LIFECYCLE_PAIRED_OFFLINE
    candidate.revoked = False
    candidate.blocked_reason = None
    try:
        enrollment._write(candidate)
    except Exception as exc:
        # Revocation cannot be guessed from a local filesystem error; this is
        # precisely the existing #4476 source-only OWNER reconciliation hold.
        hold = EnrollmentPersistenceError(
            recovery=plan_install_failure_recovery(revocation_confirmed=None),
            challenge_id=challenge_id, device_id=current.device_id,
            binding_ref=delivery.binding_ref, account_ref=delivery.account_ref,
            workspace_ref=delivery.workspace_ref,
            credential_generation=delivery.credential_generation,
        )
        enrollment._reconciliation_hold = hold.safe_dict()
        raise hold from exc
    enrollment._record = candidate
    enrollment._reconciliation_hold = None
    return EnrollmentResult(
        device_id=current.device_id, binding_ref=delivery.binding_ref,
        account_ref=delivery.account_ref, workspace_ref=delivery.workspace_ref,
        credential_generation=delivery.credential_generation,
        credential_expires_at=delivery.credential_expires_at,
        enrolled_at=moment, lifecycle=LIFECYCLE_PAIRED_OFFLINE,
    )
