"""#4139 CENTRAL: source-only, fail-closed adapter for a REVIEWED trusted device gateway.

This does not implement a gateway, an unauthenticated enrollment bootstrap,
TLS peer authentication, device attestation, server push, or an HTTP route.
The only credential redemption owner remains CanonicalConnectorEnrollmentAsyncHost.
The injected gateway MUST independently verify the PC's pre-enrollment
challenge-bound bootstrap session; no device_id/ACK JSON/boolean from a browser
or a generic post-enrollment Broker session can establish that authority.

The gateway port has no default production implementation. Nothing here wires
Worker app state or changes deployed feature gates. A live gateway and LOCAL2
sender/DPAPI receiver are separate security-reviewed dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Protocol

from .canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck,
    parse_install_ack,
)
from padiem_control_plane.local_agent_broker_pairing import MAX_PAIRING_CREDENTIAL_BYTES

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PUBLIC_BINDING_FIELDS = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref",
    "credential_ref", "credential_generation", "credential_expires_at",
})
GATEWAY_TRANSPORT_PRODUCTION_ENABLED = False


def _ref(value: Any) -> bool:
    return isinstance(value, str) and _REF.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class GatewayBootstrapLease:
    """Opaque reference minted by the external authenticated device gateway.

    A dataclass is NOT an authenticated identity. The separate gateway
    authenticate_bootstrap_lease check is mandatory. Its durable authority,
    replay controls, nonce, PC/session correlation and expiration live only in
    that reviewed gateway, never in this product process.
    """

    lease_ref: str
    challenge_id: str
    device_id: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not all(_ref(v) for v in (self.lease_ref, self.challenge_id, self.device_id)):
            raise ValueError("unreviewed gateway lease reference")
        if (
            type(self.expires_at) is not datetime
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("gateway lease expiration requires timezone")


class TrustedConnectorGateway(Protocol):
    """Injection-only private gateway port, NOT a browser/HTTP-facing client.

    Implementations must independently authenticate the outbound PC bootstrap,
    bind it to the issued challenge, validate one-time lease durability and
    ensure the authenticated ACK is from that same PC/bootstrap session.
    """

    async def reserve_authenticated_bootstrap(
        self, *, challenge_id: str, device_id: str,
    ) -> GatewayBootstrapLease: ...

    async def authenticate_bootstrap_lease(
        self, *, lease: GatewayBootstrapLease,
        challenge_id: str, device_id: str,
    ) -> bool: ...

    async def transfer_credential_once(
        self, *, lease: GatewayBootstrapLease, credential: bytes,
        binding: dict[str, Any],
    ) -> None: ...

    async def receive_authenticated_install_ack(
        self, *, lease: GatewayBootstrapLease,
    ) -> dict[str, Any]: ...

    async def authenticate_ack_sender(
        self, *, lease: GatewayBootstrapLease,
        ack: DeviceCredentialInstallAck,
    ) -> bool: ...


class CanonicalGatewayProtectedHandoff:
    """Adapt an already-reviewed outbound gateway into the CENTRAL host port.

    Guarantees one local transfer attempt and strict session/binding/ACK
    correlation. The remote gateway MUST additionally enforce durable lease
    uniqueness; a Worker isolate's memory is never replay or identity authority.
    """

    def __init__(
        self, *, gateway: TrustedConnectorGateway | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease: GatewayBootstrapLease | None = None
        self._used = False
        self._ack: DeviceCredentialInstallAck | None = None

    def _lease_live(self) -> bool:
        if self._lease is None:
            return False
        now = self._clock()
        return (
            isinstance(now, datetime)
            and now.tzinfo is not None
            and now.utcoffset() is not None
            and self._lease.expires_at.astimezone(timezone.utc)
            > now.astimezone(timezone.utc)
        )

    async def ready(self, *, challenge_id: str, device_id: str) -> bool:
        if (
            self._gateway is None or self._lease is not None or self._used
            or not _ref(challenge_id) or not _ref(device_id)
        ):
            return False
        gateway = self._gateway
        if any(not callable(getattr(gateway, name, None)) for name in (
            "reserve_authenticated_bootstrap", "authenticate_bootstrap_lease",
            "transfer_credential_once", "receive_authenticated_install_ack",
            "authenticate_ack_sender",
        )):
            return False
        try:
            lease = await gateway.reserve_authenticated_bootstrap(
                challenge_id=challenge_id, device_id=device_id,
            )
            if (
                type(lease) is not GatewayBootstrapLease
                or lease.challenge_id != challenge_id or lease.device_id != device_id
            ):
                return False
            self._lease = lease
            if not self._lease_live():
                self._lease = None
                return False
            authenticated = await gateway.authenticate_bootstrap_lease(
                lease=lease, challenge_id=challenge_id, device_id=device_id,
            )
            if authenticated is not True:
                self._lease = None
                return False
            return True
        except Exception:
            self._lease = None
            return False

    async def deliver_once(
        self, *, challenge_id: str, device_id: str, credential: bytes,
        enrollment: dict[str, Any], now: datetime,
    ) -> DeviceCredentialInstallAck:
        if (
            self._gateway is None or self._lease is None
            or self._used or not self._lease_live()
            or challenge_id != self._lease.challenge_id
            or device_id != self._lease.device_id
        ):
            raise RuntimeError("verified one-time PC gateway session unavailable")
        # A consumed canonical challenge must never be used for another
        # transfer attempt, including after a failed send or broken ACK.
        self._used = True
        if (
            type(enrollment) is not dict
            or not _PUBLIC_BINDING_FIELDS.issubset(enrollment)
            or any(not _ref(enrollment.get(k)) for k in (
                "binding_ref", "device_id", "account_ref", "workspace_ref",
                "credential_ref",
            ))
            or enrollment["device_id"] != device_id
            or type(enrollment.get("credential_generation")) is not int
            or not 1 <= enrollment["credential_generation"] <= 1_000_000
            or type(credential) is not bytes
            or not 16 <= len(credential) <= MAX_PAIRING_CREDENTIAL_BYTES
            or not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError("canonical protected handoff binding invalid")
        # Refuse malformed/stale canonical lifetime rather than forwarding an
        # opaque expiry that LOCAL2 would have to guess about.
        expires_at = enrollment.get("credential_expires_at")
        if not isinstance(expires_at, str):
            raise ValueError("canonical credential expiry is missing")
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except (ValueError, OverflowError) as exc:
            raise ValueError("canonical credential expiry is invalid") from exc
        if (
            expiry.tzinfo is None or expiry.utcoffset() is None
            or expiry.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
        ):
            raise ValueError("canonical credential expiry is stale or naive")
        # Only the canonical facts needed by LOCAL2's protected-store binding
        # projection may travel. No session, consent, owner, or access grants.
        binding = {k: enrollment[k] for k in _PUBLIC_BINDING_FIELDS}
        await self._gateway.transfer_credential_once(
            lease=self._lease, credential=credential, binding=binding,
        )
        raw_ack = await self._gateway.receive_authenticated_install_ack(
            lease=self._lease,
        )
        ack = parse_install_ack(raw_ack)
        if (
            ack.challenge_id != challenge_id or ack.device_id != device_id
            or ack.binding_ref != enrollment["binding_ref"]
            or ack.credential_generation != enrollment["credential_generation"]
            or not self._lease_live()
        ):
            raise ValueError("gateway installation acknowledgement correlation failed")
        self._ack = ack
        return ack

    async def verify_authenticated_ack(
        self, *, challenge_id: str, device_id: str,
        ack: DeviceCredentialInstallAck,
    ) -> bool:
        # An arbitrary copied ACK or possession HMAC is never authenticated.
        if (
            self._gateway is None or self._ack is None or ack is not self._ack
            or self._lease is None or not self._used or not self._lease_live()
            or challenge_id != self._lease.challenge_id
            or device_id != self._lease.device_id
        ):
            return False
        try:
            return await self._gateway.authenticate_ack_sender(
                lease=self._lease, ack=ack,
            ) is True
        except Exception:
            return False


__all__ = [
    "GATEWAY_TRANSPORT_PRODUCTION_ENABLED",
    "GatewayBootstrapLease",
    "TrustedConnectorGateway",
    "CanonicalGatewayProtectedHandoff",
]
