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
import re
from types import SimpleNamespace
from typing import Any, Protocol

from .credential_install import ProtectedCredentialReceiverPort
from .enrollment import (
    ConnectorEnrollment, EnrollmentContractError, EnrollmentPersistenceError,
    EnrollmentResult, LIFECYCLE_PAIRED_OFFLINE, build_enrollment_proof_ref,
)
from .credential_install import plan_install_failure_recovery
from dataclasses import replace

WSS_DEVICE_TRANSPORT_PRODUCTION_WIRED = False
WSS_DEVICE_ENROLLMENT_PRODUCTION_ENABLED = False
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
    """Receipt after a verified terminal frame, NOT a persisted enrollment."""

    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_expires_at: datetime
    lifecycle: str = "paired_offline"
    local_record_committed: bool = False
    online: bool = False


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
        confirmation = receiver.install_once(
            challenge_id=challenge_id, device_id=device_id,
            credential=credential, binding=SimpleNamespace(**binding),
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



async def run_and_stage_review_only_device_enrollment(
    *, enrollment: ConnectorEnrollment, socket: DeviceTextSocket,
    trusted_tls: TrustedDeviceTls, receiver: ProtectedCredentialReceiverPort,
    challenge_id: str, pairing_code: str, now: datetime | None = None,
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
        device_id=current.device_id, now=moment,
    )
    # Nothing from an unsigned JSON receipt can manufacture a new owner here:
    # the result is usable only after the *same socket* confirmed the keyed
    # readback ACK and the canonical Host's exact offline terminal response.
    if (delivery.device_id != current.device_id or delivery.online
        or delivery.local_record_committed or delivery.lifecycle != LIFECYCLE_PAIRED_OFFLINE):
        raise DeviceSessionRefused("device_terminal_receipt_invalid")
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
