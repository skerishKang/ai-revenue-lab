"""Trusted first-party caller identity contract for Padiem AI Engine.

The Engine is already Service-Binding-only. This module adds the missing
application identity/authentication primitive without changing the existing
execute/stream wire paths yet.

Plaintext caller credentials are deliberately never stored in registry records
or public projections. A trusted deployment adapter may hash a secret supplied
from server-side secret storage and compare it against the configured digest.
Caller identity can narrow which ``app_id`` values that service may submit; it
can never widen Core permissions, Tool grants, entitlement, or B14 routing.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Iterable


MAX_ENGINE_CALLERS = 64
MAX_CALLER_APP_IDS = 32
MIN_CALLER_SECRET_BYTES = 32
MAX_CALLER_SECRET_BYTES = 512

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ServiceIdentityError(ValueError):
    """Safe service-identity validation/authentication failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("service identity error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ServiceIdentityError(
            "invalid_service_identity",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _app_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ServiceIdentityError(
            "invalid_service_identity",
            "allowed_app_ids must be an iterable of identifiers",
        )
    checked = tuple(_identifier("allowed app id", value) for value in values)
    if not 1 <= len(checked) <= MAX_CALLER_APP_IDS:
        raise ServiceIdentityError(
            "invalid_service_identity",
            f"allowed_app_ids must contain 1 to {MAX_CALLER_APP_IDS} values",
        )
    if len(set(checked)) != len(checked):
        raise ServiceIdentityError(
            "invalid_service_identity",
            "allowed_app_ids must not contain duplicates",
        )
    return checked


def caller_secret_digest(secret: str | bytes) -> str:
    """Hash a high-entropy server-side caller credential for registry storage.

    This is not a password KDF. The contract requires a machine-generated secret
    with at least 32 bytes of entropy/length and stores only its SHA-256 digest.
    The plaintext is expected to live in deployment secret storage.
    """

    if isinstance(secret, str):
        raw = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        raw = bytes(secret)
    else:
        raise ServiceIdentityError(
            "invalid_service_credential",
            "caller credential must be text or bytes",
        )
    if not MIN_CALLER_SECRET_BYTES <= len(raw) <= MAX_CALLER_SECRET_BYTES:
        raise ServiceIdentityError(
            "invalid_service_credential",
            f"caller credential must contain {MIN_CALLER_SECRET_BYTES} to {MAX_CALLER_SECRET_BYTES} bytes",
        )
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class TrustedEngineCaller:
    """Server-configured first-party Engine caller identity."""

    caller_id: str
    allowed_app_ids: tuple[str, ...]
    credential_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_id", _identifier("caller_id", self.caller_id))
        object.__setattr__(self, "allowed_app_ids", _app_ids(self.allowed_app_ids))
        if (
            not isinstance(self.credential_sha256, str)
            or not _SHA256_RE.fullmatch(self.credential_sha256)
        ):
            raise ServiceIdentityError(
                "invalid_service_identity",
                "credential_sha256 must be a lowercase SHA-256 digest",
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "caller_id": self.caller_id,
            "allowed_app_ids": list(self.allowed_app_ids),
        }


@dataclass(frozen=True, slots=True)
class EngineCallerRegistry:
    callers: tuple[TrustedEngineCaller, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.callers, tuple) or any(
            not isinstance(caller, TrustedEngineCaller) for caller in self.callers
        ):
            raise ServiceIdentityError(
                "invalid_service_identity",
                "callers must be a tuple of TrustedEngineCaller values",
            )
        if not 1 <= len(self.callers) <= MAX_ENGINE_CALLERS:
            raise ServiceIdentityError(
                "invalid_service_identity",
                f"caller registry must contain 1 to {MAX_ENGINE_CALLERS} callers",
            )
        caller_ids = tuple(caller.caller_id for caller in self.callers)
        if len(set(caller_ids)) != len(caller_ids):
            raise ServiceIdentityError(
                "duplicate_service_caller",
                "caller registry must not contain duplicate caller IDs",
            )

    def caller(self, caller_id: str) -> TrustedEngineCaller:
        caller_id = _identifier("caller_id", caller_id)
        for caller in self.callers:
            if caller.caller_id == caller_id:
                return caller
        raise ServiceIdentityError(
            "unknown_service_caller",
            "Engine caller is not registered",
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedEngineCaller:
    """Successful server-side caller authentication result."""

    caller_id: str
    app_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "caller_id", _identifier("caller_id", self.caller_id))
        object.__setattr__(self, "app_id", _identifier("app_id", self.app_id))

    def to_public_dict(self) -> dict[str, str]:
        return {"caller_id": self.caller_id, "app_id": self.app_id}


def authenticate_engine_caller(
    *,
    registry: EngineCallerRegistry,
    caller_id: str,
    credential: str | bytes,
    requested_app_id: str,
) -> AuthenticatedEngineCaller:
    """Authenticate one internal caller and bind it to the requested app.

    Credential comparison is constant-time over SHA-256 digests. Failure output
    never reveals whether caller identity or credential was the differing part.
    App authorization is checked only after successful credential verification.
    """

    if not isinstance(registry, EngineCallerRegistry):
        raise ServiceIdentityError(
            "invalid_service_identity",
            "registry must be EngineCallerRegistry",
        )
    requested_app_id = _identifier("requested_app_id", requested_app_id)

    try:
        caller = registry.caller(caller_id)
        supplied_digest = caller_secret_digest(credential)
    except ServiceIdentityError as exc:
        if exc.code == "invalid_service_credential":
            raise
        raise ServiceIdentityError(
            "service_authentication_failed",
            "Engine caller authentication failed",
        ) from None

    if not hmac.compare_digest(caller.credential_sha256, supplied_digest):
        raise ServiceIdentityError(
            "service_authentication_failed",
            "Engine caller authentication failed",
        )
    if requested_app_id not in caller.allowed_app_ids:
        raise ServiceIdentityError(
            "service_app_not_authorized",
            "Engine caller is not authorized for the requested application",
        )

    return AuthenticatedEngineCaller(
        caller_id=caller.caller_id,
        app_id=requested_app_id,
    )
