from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import re
from typing import Any, Protocol
from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_control_plane_https import (
    ControlPlaneHttpsOperation,
    StdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_pairing import DeviceBinding, DeviceLifecycle
from .local_agent_secure_transport import (
    DeviceCredentialStore,
    OutboundTransportConfig,
    StoredDeviceCredentialProjection,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
PAIRING_PROOF_TRANSCRIPT = "claw-local-agent-pairing-proof.v1"
PAIRING_PROOF_REF_PREFIX = "pairing-proof:"
PAIRING_CODE_HEX_CHARS = 32
_PAIRING_CODE_RE = re.compile(rf"^[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}$")
_PROOF_REF_RE = re.compile(rf"^{re.escape(PAIRING_PROOF_REF_PREFIX)}[0-9a-f]{{64}}$")
MAX_ENROLLMENT_CREDENTIAL_BYTES = 4_096
MAX_ENROLLMENT_CLOCK_SKEW_SECONDS = 300

_ENROLLMENT_KEYS = frozenset(
    {
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_ref",
        "credential_generation",
        "issued_at",
        "credential_expires_at",
        "challenge_id",
        "server_owned_binding_refs",
        "raw_device_credential",
        "production_ready",
    }
)
_ENROLLMENT_RESPONSE_KEYS = frozenset({"ok", "enrollment", "credential_b64", "credential_returned_once"})
_PAIRING_ERROR_KEYS = frozenset({"ok", "error"})
_PAIRING_ERROR_PAYLOAD_KEYS = frozenset({"code", "message"})


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def _positive_int(value: Any, field_name: str, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be an integer between {minimum} and {maximum} without coercion")
    return value


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _closed_mapping(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ContractError(f"{label} schema mismatch")
    return value


def pairing_proof_ref(*, challenge_id: str, device_id: str, pairing_code: str) -> str:
    """Desktop-side HMAC-SHA256 possession proof for broker pairing redemption.

    This must stay byte-identical to the control-plane authority derivation
    (`padiem_control_plane.local_agent_broker_pairing.pairing_proof_ref`). The
    cross-contract test suite pins that equality instead of trusting it.
    """

    challenge_id = _ref(challenge_id, "challenge_id")
    device_id = _ref(device_id, "device_id")
    if not isinstance(pairing_code, str) or not _PAIRING_CODE_RE.fullmatch(pairing_code):
        raise ContractError("pairing code must be exact lowercase hexadecimal text")
    message = f"{PAIRING_PROOF_TRANSCRIPT}\n{challenge_id}\n{device_id}".encode("utf-8")
    digest = hmac.new(pairing_code.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{PAIRING_PROOF_REF_PREFIX}{digest}"


class BrokerPairingHttpsOperation(str, Enum):
    """Outbound-only pairing route names of the authenticated broker transport."""

    CHALLENGE = "v1/broker/pairings/challenge"
    REDEEM = "v1/broker/pairings/redeem"


class BrokerPairingHttpsJsonRequestPort(Protocol):
    def post(
        self,
        *,
        config: OutboundTransportConfig,
        operation: BrokerPairingHttpsOperation,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...


class StdlibPinnedHttpsBrokerPairingJsonRequestPort(StdlibPinnedHttpsJsonRequestPort):
    """Existing pinned stdlib HTTPS source plus the pairing redemption route.

    Pairing route names resolve against the same pinned broker base path as every
    other outbound broker route, so a deployment that mounts the broker transport
    at the host root receives exactly ``/v1/broker/pairings/redeem``.
    """

    def _path(
        self,
        config: OutboundTransportConfig,
        operation: ControlPlaneHttpsOperation | BrokerPairingHttpsOperation,
    ) -> tuple[str, int, str]:
        if operation not in (BrokerPairingHttpsOperation.CHALLENGE, BrokerPairingHttpsOperation.REDEEM):
            return super()._path(config, operation)
        host, port, _ = super()._path(config, ControlPlaneHttpsOperation.POLL)
        base = (urlsplit(config.endpoint.url).path or "/").rstrip("/")
        path = f"{base}/{operation.value}" if base else f"/{operation.value}"
        return host, port, path


@dataclass(frozen=True, slots=True)
class LocalAgentBrokerEnrollment:
    """Desktop-side result of one successful challenge-proof redemption.

    The raw device credential is deliberately absent from this projection: it was
    written straight into the protected credential store and is only ever loaded
    again at request time by the canonical credential store port.

    This object cannot produce an ONLINE binding. Redemption only ever yields
    `PAIRED_OFFLINE`; the canonical server-backed ONLINE projection is owned by
    `kagent.local_agent_server_projection` and requires a real broker session
    plus a server-owned heartbeat, exactly as the merged #3083 desktop-shell
    rule requires.
    """

    binding: DeviceBinding
    pairing_challenge_id: str
    enrolled_at: datetime
    stored: StoredDeviceCredentialProjection

    def __post_init__(self) -> None:
        if not isinstance(self.binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        if self.binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
            raise ContractError("a freshly redeemed device binding must be PAIRED_OFFLINE")
        object.__setattr__(self, "pairing_challenge_id", _ref(self.pairing_challenge_id, "pairing_challenge_id"))
        object.__setattr__(self, "enrolled_at", _aware(self.enrolled_at, "enrolled_at"))
        if not isinstance(self.stored, StoredDeviceCredentialProjection):
            raise ContractError("stored must be StoredDeviceCredentialProjection")
        if self.stored.binding_ref != self.binding.binding_ref:
            raise ContractError("protected credential store persisted a different device binding")
        if self.stored.credential_generation != self.binding.credential_generation:
            raise ContractError("protected credential store persisted a different credential generation")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-local-agent-broker-enrollment.v1",
            "device_id": self.binding.device_id,
            "binding_ref": self.binding.binding_ref,
            "account_ref": self.binding.account_ref,
            "workspace_ref": self.binding.workspace_ref,
            "credential_generation": self.binding.credential_generation,
            "credential_expires_at": _iso(self.binding.credential_expires_at),
            "pairing_challenge_id": self.pairing_challenge_id,
            "enrolled_at": _iso(self.enrolled_at),
            "credential_store_protection": self.stored.protection,
            "credential_persisted_once": True,
            "binding_state": self.binding.state.value,
            "online_requires_server_projection": True,
            "local_online_claim": False,
            "raw_device_credential": False,
            "pairing_code_persisted": False,
            "public_inbound_port": False,
            "live_broker_configured": False,
            "production_ready": False,
        }


class UnconfiguredLocalAgentBrokerPairingClient:
    def redeem(self, **_: Any) -> LocalAgentBrokerEnrollment:
        raise ContractError("real Local Agent broker pairing client is not configured")


class LocalAgentBrokerPairingClient:
    """Outbound-only desktop enrollment through the pinned broker HTTPS authority.

    The client never listens on a socket, never needs a public inbound port and
    never holds pairing-challenge issuance authority (that belongs to the signed-in
    cloud session). It proves possession of the one-time pairing code, persists the
    returned device credential through the canonical protected credential store,
    and hands the resident host a binding plus an ONLINE projection.
    """

    def __init__(
        self,
        *,
        config: OutboundTransportConfig,
        credential_store: DeviceCredentialStore,
        request_port: BrokerPairingHttpsJsonRequestPort | None = None,
    ) -> None:
        if not isinstance(config, OutboundTransportConfig):
            raise ContractError("config must be OutboundTransportConfig")
        for method_name in ("save", "load"):
            if not callable(getattr(credential_store, method_name, None)):
                raise ContractError("credential_store must implement save and load")
        self._config = config
        self._credential_store = credential_store
        self._request_port = request_port or StdlibPinnedHttpsBrokerPairingJsonRequestPort()
        if not callable(getattr(self._request_port, "post", None)):
            raise ContractError("request_port must implement post")

    def _post(
        self,
        *,
        operation: BrokerPairingHttpsOperation,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        return self._request_port.post(
            config=self._config,
            operation=operation,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    def _credential(self, value: Any) -> bytes:
        if not isinstance(value, str) or not value:
            raise ContractError("broker pairing response omitted credential material")
        try:
            credential = base64.b64decode(value, validate=True)
        except (TypeError, ValueError) as exc:
            raise ContractError("broker pairing credential is not valid base64") from exc
        if not credential or len(credential) > MAX_ENROLLMENT_CREDENTIAL_BYTES:
            raise ContractError("broker pairing credential is empty or exceeds the size bound")
        return credential

    def _binding(
        self,
        response: dict[str, Any],
        *,
        challenge_id: str,
        device_id: str,
        now: datetime,
    ) -> tuple[DeviceBinding, bytes]:
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ContractError("broker pairing response is invalid")
        if response["ok"] is False:
            if frozenset(response) != _PAIRING_ERROR_KEYS:
                raise ContractError("broker pairing error response schema mismatch")
            error = _closed_mapping(response["error"], _PAIRING_ERROR_PAYLOAD_KEYS, "broker pairing error")
            code = _ref(error["code"], "broker_error_code")
            raise ContractError(f"broker rejected broker pairing redemption: {code}")
        response = _closed_mapping(response, _ENROLLMENT_RESPONSE_KEYS, "broker pairing response")
        if response["credential_returned_once"] is not True:
            raise ContractError("broker pairing redemption did not confirm one-time credential delivery")
        enrollment = _closed_mapping(response["enrollment"], _ENROLLMENT_KEYS, "broker pairing enrollment")
        if enrollment["server_owned_binding_refs"] is not True:
            raise ContractError("broker pairing enrollment did not confirm server-owned binding references")
        if enrollment["raw_device_credential"] is not False:
            raise ContractError("broker pairing enrollment attempted credential expansion")
        if _ref(enrollment["device_id"], "device_id") != device_id:
            raise ContractError("broker pairing enrollment device does not match the redeeming device")
        if _ref(enrollment["challenge_id"], "challenge_id") != challenge_id:
            raise ContractError("broker pairing enrollment challenge mismatch")
        issued_at = _timestamp(enrollment["issued_at"], "issued_at")
        if abs((issued_at - now).total_seconds()) > MAX_ENROLLMENT_CLOCK_SKEW_SECONDS:
            raise ContractError("broker pairing enrollment is outside the accepted clock skew")
        credential = self._credential(response["credential_b64"])
        binding = DeviceBinding(
            device_id=_ref(enrollment["device_id"], "device_id"),
            binding_ref=_ref(enrollment["binding_ref"], "binding_ref"),
            account_ref=_ref(enrollment["account_ref"], "account_ref"),
            workspace_ref=_ref(enrollment["workspace_ref"], "workspace_ref"),
            credential_ref=_ref(enrollment["credential_ref"], "credential_ref"),
            credential_generation=_positive_int(enrollment["credential_generation"], "credential_generation"),
            issued_at=issued_at,
            credential_expires_at=_timestamp(enrollment["credential_expires_at"], "credential_expires_at"),
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        if binding.credential_expires_at <= now:
            raise ContractError("broker pairing returned an already expired device credential")
        return binding, credential

    def redeem(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        device_id: str,
        now: datetime,
    ) -> LocalAgentBrokerEnrollment:
        now = _aware(now, "now")
        challenge_id = _ref(challenge_id, "challenge_id")
        device_id = _ref(device_id, "device_id")
        proof_ref = pairing_proof_ref(
            challenge_id=challenge_id,
            device_id=device_id,
            pairing_code=pairing_code,
        )
        response = self._post(
            operation=BrokerPairingHttpsOperation.REDEEM,
            payload={
                "challenge_id": challenge_id,
                "device_id": device_id,
                "proof_ref": proof_ref,
                "now": _iso(now),
            },
            timeout_seconds=min(self._config.poll_timeout_seconds, 30),
        )
        binding, credential = self._binding(
            response,
            challenge_id=challenge_id,
            device_id=device_id,
            now=now,
        )
        stored = self._credential_store.save(binding=binding, credential=credential, now=now)
        if not isinstance(stored, StoredDeviceCredentialProjection):
            raise ContractError("protected credential store returned an invalid projection")
        return LocalAgentBrokerEnrollment(
            binding=binding,
            pairing_challenge_id=challenge_id,
            enrolled_at=now,
            stored=stored,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-local-agent-broker-pairing-client.v1",
            "pairing_proof_algorithm": PAIRING_PROOF_ALGORITHM,
            "pairing_proof_transcript": PAIRING_PROOF_TRANSCRIPT,
            "pairing_routes": sorted(operation.value for operation in BrokerPairingHttpsOperation),
            "outbound_only": True,
            "public_inbound_port": False,
            "upnp_port_forward_supported": False,
            "client_challenge_authority": False,
            "caller_endpoint_override": False,
            "tls_required": True,
            "canonical_credential_store_reused": True,
            "raw_pairing_code_logged": False,
            "raw_device_credential_logged": False,
            "live_broker_configured": False,
            "real_user_pairing_canary": False,
            "production_mutation": False,
            "production_ready": False,
        }


OUTBOUND_ONLY_ENROLLMENT = True
ONLINE_REQUIRES_SERVER_PROJECTION = True
LOCAL_ONLINE_CLAIM = False
REDEMPTION_STATE = "paired_offline"
PAIRING_PROOF_ALGORITHM = "HMAC-SHA256"
PAIRING_ROUTE_BASE_PATH_RESOLUTION = "pinned_broker_base_path"
CLIENT_CHALLENGE_AUTHORITY = False
PUBLIC_INBOUND_PORT = False
UPNP_PORT_FORWARD_SUPPORTED = False
CALLER_ENDPOINT_OVERRIDE = False
TLS_REQUIRED = True
CANONICAL_CREDENTIAL_STORE_REUSED = True
RAW_PAIRING_CODE_LOGGED = False
RAW_DEVICE_CREDENTIAL_LOGGED = False
LIVE_BROKER_CONFIGURED = False
REAL_USER_PAIRING_CANARY = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
