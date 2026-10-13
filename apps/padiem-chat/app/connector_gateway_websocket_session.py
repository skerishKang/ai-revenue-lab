"""#4139 CENTRAL source-only, device-initiated ONE-SOCKET credential handoff.

No new public route is mounted. This handler is only callable by a future
explicit operator-reviewed WebSocket composition. The same WSS connection
must carry pre-redemption pairing-code POP, a single signed fetch, the
canonical Broker credential and the DPAPI-readback ACK. No process-global
queue, bearer escrow, second Broker redeem, retry, or cached raw credential.

A WSS URL is NOT hardware attestation. The separate trusted TLS verifier
must check the actual ingress connection using server-owned evidence.
A stolen pairing code can still impersonate its owner until redeemed; the
operator consent, anti-replay and PC security review remain release gates.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
import json
from typing import Any, Callable, Protocol

from .canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck, parse_install_ack,
)
from .canonical_connector_gateway_handoff import (
    CanonicalGatewayProtectedHandoff, GatewayBootstrapLease,
)
from .control_plane_identity import IdentityBridgeError

PRODUCTION_WEBSOCKET_ROUTE_MOUNTED = False
PRODUCTION_WEBSOCKET_CREDENTIAL_DELIVERY_ENABLED = False
MAX_DEVICE_FRAME_CHARS = 8192
MAX_INSTALL_ACK_BODY_BYTES = 3072

# Keep socket operations bounded but NEVER cancel an entire canonical Host
# redemption after the Broker has issued the one-time device credential.
MAX_TLS_VERIFY_SECONDS = 5.0
MAX_BOOTSTRAP_FRAME_SECONDS = 10.0
MAX_GATEWAY_BROKER_RPC_SECONDS = 8.0
MAX_SOCKET_SEND_SECONDS = 8.0
MAX_WINDOWS_ACK_SECONDS = 25.0


async def _recv_frame(socket: Any, *, timeout: float) -> str:
    return await asyncio.wait_for(socket.receive_text(), timeout=timeout)


async def _send_frame(socket: Any, message: str) -> None:
    await asyncio.wait_for(
        socket.send_text(message), timeout=MAX_SOCKET_SEND_SECONDS,
    )


class TrustedIngressPort(Protocol):
    async def verify(self, websocket: Any) -> bool: ...


class CanonicalPrivateGatewayBroker(Protocol):
    async def gateway_bootstrap_rpc(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("duplicate JSON key")
        result[k] = v
    return result


def _decode(raw: str, *, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, str) or not 0 < len(raw) <= MAX_DEVICE_FRAME_CHARS:
        raise ValueError("device session frame invalid")
    value = json.loads(raw, object_pairs_hook=_unique)
    if type(value) is not dict or set(value) != keys:
        raise ValueError("device session frame shape invalid")
    return value


def _ref(value: Any) -> bool:
    return (type(value) is str and 1 <= len(value) <= 256
            and all(c.isascii() and (c.isalnum() or c in "._:@+-") for c in value))


def _proof(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _closed_receipt(reply: Any, expected: frozenset[str]) -> dict[str, Any]:
    if type(reply) is not dict or set(reply) != {"ok", "gateway"} or reply["ok"] is not True:
        raise ValueError("canonical gateway refused")
    receipt = reply["gateway"]
    if type(receipt) is not dict or set(receipt) != expected:
        raise ValueError("canonical gateway receipt invalid")
    return receipt


async def _rpc(broker: CanonicalPrivateGatewayBroker,
               operation: str, args: dict[str, Any],
               shape: frozenset[str]) -> dict[str, Any]:
    receipt = await asyncio.wait_for(
        broker.gateway_bootstrap_rpc({"operation": operation, "args": args}),
        timeout=MAX_GATEWAY_BROKER_RPC_SECONDS,
    )
    return _closed_receipt(receipt, shape)


_BEGIN = frozenset({"type", "challenge_id", "device_id", "proof_ref"})
_FINISH = frozenset({"type", "lease_ref", "proof_hex"})
_FETCH = frozenset({"type", "counter", "proof_hex"})
_ACK = frozenset({"type", "counter", "proof_hex", "body_b64"})
_BEGIN_RECEIPT = frozenset({
    "challenge_id", "device_id", "lease_ref", "nonce_hex", "expires_at",
    "credential", "challenge_consumed",
})
_FINISH_RECEIPT = frozenset({
    "challenge_id", "device_id", "lease_ref", "verified", "credential",
    "challenge_consumed",
})
_ACTION_RECEIPT = frozenset({
    "challenge_id", "device_id", "lease_ref", "action", "counter", "authenticated",
})
_BINDING = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref",
    "credential_ref", "credential_generation", "credential_expires_at",
})


class SingleSocketAuthenticatedGateway:
    """Per-connection transport implementing TrustedConnectorGateway.

    Session authority persists in canonical Broker DO; this instance holds
    only the currently live PC socket, the one lease and a single ACK claim.
    The Broker authorization is checked on the literal signed payload bytes.
    """

    def __init__(self, *, socket: Any, broker: CanonicalPrivateGatewayBroker,
                 lease: GatewayBootstrapLease, authenticated: bool):
        self._socket = socket
        self._broker = broker
        self._lease = lease
        self._authenticated = authenticated is True
        self._sent = False
        self._acked = False
        self._ack_payload: dict[str, Any] | None = None

    async def reserve_authenticated_bootstrap(self, *,
                                               challenge_id: str, device_id: str) -> GatewayBootstrapLease:
        if (not self._authenticated or self._sent or challenge_id != self._lease.challenge_id
            or device_id != self._lease.device_id):
            raise ValueError("PC outbound lease not verified")
        return self._lease

    async def authenticate_bootstrap_lease(self, *, lease: GatewayBootstrapLease,
                                           challenge_id: str, device_id: str) -> bool:
        return (self._authenticated is True and lease is self._lease
                and challenge_id == lease.challenge_id and device_id == lease.device_id
                and datetime.now(timezone.utc) < lease.expires_at)

    async def transfer_credential_once(self, *, lease: GatewayBootstrapLease,
                                       credential: bytes, binding: dict[str, Any]) -> None:
        if (not self._authenticated or self._sent or lease is not self._lease
            or type(credential) is not bytes or not 16 <= len(credential) <= 4096
            or type(binding) is not dict or set(binding) != _BINDING
            or binding["device_id"] != lease.device_id):
            raise ValueError("protected credential transfer refused")
        # A transport error after attempted send is never retryable: the
        # canonical Broker has already consumed the challenge.
        self._sent = True
        await _send_frame(self._socket, json.dumps({
            "type": "credential_once", "challenge_id": lease.challenge_id,
            "device_id": lease.device_id, "lease_ref": lease.lease_ref,
            "binding": binding,
            "credential_b64": base64.b64encode(credential).decode("ascii"),
        }, separators=(",", ":"), ensure_ascii=True))

    async def receive_authenticated_install_ack(self, *,
                                                  lease: GatewayBootstrapLease) -> dict[str, Any]:
        if not self._sent or self._acked or lease is not self._lease:
            raise ValueError("ACK not expected on this PC connection")
        message = _decode(await _recv_frame(self._socket, timeout=MAX_WINDOWS_ACK_SECONDS), keys=_ACK)
        if (message["type"] != "install_ack" or type(message["counter"]) is not int
            or message["counter"] != 2 or not _proof(message["proof_hex"])):
            raise ValueError("unexpected ACK frame")
        encoded = message["body_b64"]
        if type(encoded) is not str or len(encoded) > (MAX_INSTALL_ACK_BODY_BYTES * 4 // 3 + 8):
            raise ValueError("ACK body invalid")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("ACK body encoding invalid") from exc
        if (not raw or len(raw) > MAX_INSTALL_ACK_BODY_BYTES
            or base64.b64encode(raw).decode("ascii") != encoded):
            raise ValueError("ACK body noncanonical")
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        ack = parse_install_ack(decoded)
        authorized = await _rpc(self._broker, "authorize", {
            "challenge_id": lease.challenge_id, "device_id": lease.device_id,
            "lease_ref": lease.lease_ref, "action": "install_ack",
            "counter": 2, "body_b64": encoded, "proof_hex": message["proof_hex"],
        }, _ACTION_RECEIPT)
        if (authorized["challenge_id"] != lease.challenge_id
            or authorized["device_id"] != lease.device_id
            or authorized["lease_ref"] != lease.lease_ref
            or authorized["action"] != "install_ack"
            or authorized["counter"] != 2 or authorized["authenticated"] is not True):
            raise ValueError("Broker ACK sender correlation failed")
        self._ack_payload = ack.safe_dict()
        self._acked = True
        return self._ack_payload

    async def authenticate_ack_sender(self, *, lease: GatewayBootstrapLease,
                                      ack: DeviceCredentialInstallAck) -> bool:
        return (self._acked is True and self._authenticated is True
                and lease is self._lease and type(ack) is DeviceCredentialInstallAck
                and ack.safe_dict() == self._ack_payload)


async def run_device_initiated_enrollment(
    socket: Any, *, trusted_tls: TrustedIngressPort | None,
    broker: CanonicalPrivateGatewayBroker | None,
    host_factory: Callable[..., Any] | None,
) -> None:
    """Unmounted WSS handler; single socket is both auth and secret channel.

    host_factory(handoff=...) MUST construct the existing canonical async
    Identity+Broker owner, never another redemption service. Zero production
    composition currently provides these three trusted dependencies.
    """
    if (not callable(getattr(trusted_tls, "verify", None))
        or not callable(getattr(broker, "gateway_bootstrap_rpc", None))
        or not callable(host_factory)
        or getattr(socket.url, "scheme", "") != "wss"
        or socket.headers.get("origin") is not None
        or socket.headers.get("cookie") is not None):
        await socket.close(code=1008)
        return
    try:
        if await asyncio.wait_for(trusted_tls.verify(socket), timeout=MAX_TLS_VERIFY_SECONDS) is not True:
            await socket.close(code=1008)
            return
    except Exception:
        await socket.close(code=1011)
        return
    await socket.accept()
    try:
        begin = _decode(await _recv_frame(socket, timeout=MAX_BOOTSTRAP_FRAME_SECONDS), keys=_BEGIN)
        if (begin["type"] != "begin" or not _ref(begin["challenge_id"])
            or not _ref(begin["device_id"])
            or type(begin["proof_ref"]) is not str
            or not begin["proof_ref"].startswith("pairing-proof:")
            or not _proof(begin["proof_ref"][len("pairing-proof:"):])):
            raise ValueError("bootstrap request invalid")
        challenge, device = begin["challenge_id"], begin["device_id"]
        started = await _rpc(broker, "begin", {
            "challenge_id": challenge, "device_id": device,
            "proof_ref": begin["proof_ref"],
        }, _BEGIN_RECEIPT)
        if (started["challenge_id"] != challenge or started["device_id"] != device
            or started["credential"] is not False or started["challenge_consumed"] is not False
            or not _proof(started.get("nonce_hex")) or not _ref(started.get("lease_ref"))):
            raise ValueError("bootstrap reservation invalid")
        try:
            expiry = datetime.fromisoformat(started["expires_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("bootstrap time invalid") from exc
        if (expiry.tzinfo is None or expiry.utcoffset() is None
            or datetime.now(timezone.utc) >= expiry):
            raise ValueError("bootstrap lease already expired")
        lease = GatewayBootstrapLease(
            lease_ref=started["lease_ref"], challenge_id=challenge,
            device_id=device, expires_at=expiry,
        )
        await _send_frame(socket, json.dumps({"type": "nonce",
            "challenge_id": challenge, "device_id": device,
            "lease_ref": lease.lease_ref, "nonce_hex": started["nonce_hex"],
            "expires_at": started["expires_at"],
        }, separators=(",", ":")))
        finish = _decode(await _recv_frame(socket, timeout=MAX_BOOTSTRAP_FRAME_SECONDS), keys=_FINISH)
        if (finish["type"] != "finish" or finish["lease_ref"] != lease.lease_ref
            or not _proof(finish["proof_hex"])):
            raise ValueError("bootstrap finish invalid")
        proof = await _rpc(broker, "finish", {
            "challenge_id": challenge, "device_id": device,
            "lease_ref": lease.lease_ref, "proof_hex": finish["proof_hex"],
        }, _FINISH_RECEIPT)
        if (proof["challenge_id"] != challenge or proof["device_id"] != device
            or proof["lease_ref"] != lease.lease_ref or proof["verified"] is not True
            or proof["credential"] is not False or proof["challenge_consumed"] is not False):
            raise ValueError("bootstrap proof denied")
        await _send_frame(socket, json.dumps({
            "type": "bootstrap_verified", "lease_ref": lease.lease_ref,
            "credential": False,
        }, separators=(",", ":")))
        fetch = _decode(await _recv_frame(socket, timeout=MAX_BOOTSTRAP_FRAME_SECONDS), keys=_FETCH)
        if (fetch["type"] != "credential_fetch" or type(fetch["counter"]) is not int
            or fetch["counter"] != 1 or not _proof(fetch["proof_hex"])):
            raise ValueError("credential request invalid")
        received = await _rpc(broker, "authorize", {
            "challenge_id": challenge, "device_id": device,
            "lease_ref": lease.lease_ref, "action": "credential_fetch",
            "counter": 1, "body_b64": "", "proof_hex": fetch["proof_hex"],
        }, _ACTION_RECEIPT)
        if (received["challenge_id"] != challenge or received["device_id"] != device
            or received["lease_ref"] != lease.lease_ref
            or received["counter"] != 1 or received["action"] != "credential_fetch"
            or received["authenticated"] is not True):
            raise ValueError("credential request proof denied")
        gateway = SingleSocketAuthenticatedGateway(
            socket=socket, broker=broker, lease=lease, authenticated=True,
        )
        protected = CanonicalGatewayProtectedHandoff(gateway=gateway)
        host = host_factory(handoff=protected)
        if not callable(getattr(host, "redeem", None)):
            raise ValueError("canonical enrollment host unavailable")
        try:
            result = await host.redeem(
                challenge_id=challenge, device_id=device, proof_ref=begin["proof_ref"],
            )
        except IdentityBridgeError as exc:
            # Only Host codes that *require an exact authoritative Broker
            # revoke receipt* may report revoked. A failure/timeout or
            # unconfirmed revocation MUST return security_hold, never retry.
            status = (
                "revoked" if exc.code in {
                    "enrollment_credential_handoff_failed",
                    "enrollment_consent_changed_during_redeem",
                } and gateway._sent else "security_hold"
            )
            await _send_frame(socket, json.dumps({"type": "terminal",
                "status": status, "can_retry_challenge": False,
            }, separators=(",", ":")))
            await socket.close(code=1000)
            return
        # Success is *only* the original Broker+Identity host receipt after
        # true DPAPI-transcript and same-connection Broker-signed ACK proofs.
        if (type(result) is not dict or result.get("lifecycle") != "paired_offline"
            or result.get("raw_device_credential") is not False
            or result.get("dispatch_authorized") is not False
            or gateway._acked is not True):
            raise ValueError("canonical host enrollment receipt invalid")
        await _send_frame(socket, json.dumps({"type": "terminal",
            "status": "paired_offline", "can_retry_challenge": False,
        }, separators=(",", ":")))
    except Exception:
        # No raw credentials or Broker status details in an error envelope.
        # The host is responsible for canonical compensation after redeem.
        await socket.close(code=1011)
    else:
        await socket.close(code=1000)


__all__ = [
    "PRODUCTION_WEBSOCKET_ROUTE_MOUNTED",
    "PRODUCTION_WEBSOCKET_CREDENTIAL_DELIVERY_ENABLED",
    "SingleSocketAuthenticatedGateway",
    "run_device_initiated_enrollment",
]
