from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any, Callable, Protocol

from .contracts import ControlPlaneContractError
from .local_agent_broker import BrokerDeviceBinding, InMemoryLocalAgentBrokerAuthority

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CODE_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
_PAIRING_CODE_RE = re.compile(r"^[0-9a-f]{32}$")
PROOF_REF_RE = re.compile(r"^pairing-proof:[0-9a-f]{64}$")

PAIRING_PROOF_TRANSCRIPT = "claw-local-agent-pairing-proof.v1"
PAIRING_CODE_TRANSCRIPT = "claw-local-agent-pairing-code.v1"
PAIRING_PROOF_REF_PREFIX = "pairing-proof:"
PAIRING_CODE_HEX_CHARS = 32
MIN_PAIRING_TTL_SECONDS = 30
MAX_PAIRING_TTL_SECONDS = 600
MAX_PENDING_PAIRING_CHALLENGES = 4_096
# #3102: bounded per-scope challenge issuance. The capacity ceiling above is a
# global guard; this one stops any single account/workspace from minting an
# unbounded stream of live pairing codes. It is deliberately scoped to broker
# pairing only and is not a general identity, session or rate authority.
#
# `None` means "not yet configured", which is the correct source-only posture:
# Production activation is a separate CENTRAL decision, and this deployment is
# still off. A deployment binds a positive limit at activation time, and
# `safe_dict()` reports which posture is in force.
MIN_PAIRING_ISSUANCE_RATE_LIMIT = 1
MAX_PAIRING_ISSUANCE_RATE_LIMIT = 60
DEFAULT_PAIRING_ISSUANCE_RATE_LIMIT: int | None = None
PAIRING_ISSUANCE_WINDOW_SECONDS = 600
# #3102: the issuance counter map is itself an abuse surface, so it is bounded
# independently of the pending-challenge capacity. Scopes that have been idle
# for a full window are pruned, and the map is additionally capped so a burst of
# brand-new scopes cannot grow it without limit.
MAX_TRACKED_PAIRING_ISSUANCE_SCOPES = 4_096
MIN_PAIRING_CREDENTIAL_TTL_SECONDS = 300
MAX_PAIRING_CREDENTIAL_TTL_SECONDS = 2_592_000
DEFAULT_PAIRING_CREDENTIAL_TTL_SECONDS = 2_592_000
MAX_PAIRING_CREDENTIAL_BYTES = 4_096


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_pairing_reference",
            f"{field_name} must be a bounded safe reference",
        )
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError("invalid_pairing_timestamp", f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ControlPlaneContractError(
            "invalid_pairing_value",
            f"{field_name} must be an integer between {minimum} and {maximum} without coercion",
        )
    return value


def _default_code_nonce_factory() -> str:
    return secrets.token_hex(16)


def _default_credential_factory() -> bytes:
    return secrets.token_bytes(32)


def pairing_proof_message(*, challenge_id: str, device_id: str) -> bytes:
    """Canonical #3080 pairing transcript shared byte-for-byte with the desktop agent.

    The transcript is deliberately explicit and versioned so both sides can be
    proved identical instead of merely assumed compatible.
    """

    challenge_id = _ref(challenge_id, "challenge_id")
    device_id = _ref(device_id, "device_id")
    return f"{PAIRING_PROOF_TRANSCRIPT}\n{challenge_id}\n{device_id}".encode("utf-8")


def pairing_proof_ref(*, challenge_id: str, device_id: str, pairing_code: str) -> str:
    """HMAC-SHA256 possession proof over the canonical pairing transcript.

    The desktop agent computes this value with the one-time pairing code it
    received from the signed-in browser. Server-side verification recomputes the
    same value from deployment-pepper-derived code material, so a raw pairing
    code never has to be persisted anywhere.
    """

    if not isinstance(pairing_code, str) or not _PAIRING_CODE_RE.fullmatch(pairing_code):
        raise ControlPlaneContractError(
            "invalid_pairing_code",
            "pairing code must be lowercase hexadecimal pairing-code text",
        )
    digest = hmac.new(
        pairing_code.encode("utf-8"),
        pairing_proof_message(challenge_id=challenge_id, device_id=device_id),
        hashlib.sha256,
    ).hexdigest()
    return f"{PAIRING_PROOF_REF_PREFIX}{digest}"


@dataclass(frozen=True, slots=True)
class BrokerPairingChallenge:
    """Server-owned single-use pairing challenge projection."""

    challenge_id: str
    account_ref: str
    workspace_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("challenge_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        lifetime = (expires - issued).total_seconds()
        if lifetime <= 0 or lifetime > MAX_PAIRING_TTL_SECONDS:
            raise ControlPlaneContractError(
                "invalid_pairing_challenge",
                "pairing challenge lifetime must be positive and at most 600 seconds",
            )
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "single_use": True,
            "client_time_authority": False,
            "raw_pairing_secret": False,
        }


@dataclass(frozen=True, slots=True)
class BrokerPairingEnrollment:
    """Server-owned enrollment result for one redeemed device.

    This projection intentionally excludes the raw device credential. The
    credential is returned exactly once by the redeem boundary and is persisted
    only as a deployment-pepper digest inside the canonical broker authority.
    """

    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_ref: str
    credential_generation: int
    issued_at: datetime
    credential_expires_at: datetime
    challenge_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "binding_ref",
            "device_id",
            "account_ref",
            "workspace_ref",
            "credential_ref",
            "challenge_id",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(
            self,
            "credential_generation",
            _positive_int(self.credential_generation, "credential_generation", minimum=1, maximum=1_000_000),
        )
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.credential_expires_at, "credential_expires_at")
        if expires <= issued:
            raise ControlPlaneContractError(
                "invalid_pairing_enrollment",
                "pairing credential expiry must follow enrollment",
            )
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "credential_expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_ref": self.credential_ref,
            "credential_generation": self.credential_generation,
            "issued_at": self.issued_at.isoformat(),
            "credential_expires_at": self.credential_expires_at.isoformat(),
            "challenge_id": self.challenge_id,
            "server_owned_binding_refs": True,
            "raw_device_credential": False,
            "production_ready": False,
        }


class BrokerPairingAuthorityPort(Protocol):
    def issue_challenge(
        self,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> tuple[BrokerPairingChallenge, str]:
        ...

    def redeem(
        self,
        *,
        challenge_id: str,
        device_id: str,
        proof_ref: str,
        now: datetime,
    ) -> tuple[BrokerPairingEnrollment, bytes]:
        ...


class UnconfiguredBrokerPairingAuthority:
    def issue_challenge(self, **_: Any) -> tuple[BrokerPairingChallenge, str]:
        raise RuntimeError("Local Agent broker pairing authority is not configured")

    def redeem(self, **_: Any) -> tuple[BrokerPairingEnrollment, bytes]:
        raise RuntimeError("Local Agent broker pairing authority is not configured")


@dataclass(frozen=True, slots=True)
class _PendingBrokerPairingChallenge:
    challenge: BrokerPairingChallenge
    code_nonce: str
    redeemed_at: datetime | None = None
    redeemed_device_id: str | None = None
    redeemed_binding_ref: str | None = None


class InMemoryBrokerPairingAuthority:
    """Deterministic single-use broker pairing authority for repository conformance.

    Security properties:

    - the pairing code is derived from the deployment pepper plus a per-challenge
      nonce, so the authority persists no raw pairing secret at all;
    - a challenge is consumed before its binding is registered, so a replay can
      never mint a second binding from one code;
    - device bindings and credential digests are created exclusively by the
      canonical broker authority (`InMemoryLocalAgentBrokerAuthority`), so replay,
      generation and revoke semantics stay single-sourced;
    - account/workspace scope always comes from the stored server-side challenge,
      never from the redeeming caller.

    This authority is deliberately in-memory: it holds no durable state and must
    not be treated as a production pairing store.
    """

    def __init__(
        self,
        *,
        pepper: bytes,
        authority: InMemoryLocalAgentBrokerAuthority,
        code_nonce_factory: Callable[[], str] | None = None,
        credential_factory: Callable[[], bytes] | None = None,
        credential_ttl_seconds: int = DEFAULT_PAIRING_CREDENTIAL_TTL_SECONDS,
        issuance_rate_limit: int = DEFAULT_PAIRING_ISSUANCE_RATE_LIMIT,
    ) -> None:
        if not isinstance(pepper, bytes) or len(pepper) < 16:
            raise ControlPlaneContractError(
                "invalid_pairing_pepper",
                "broker pairing pepper must contain at least 16 bytes",
            )
        if not isinstance(authority, InMemoryLocalAgentBrokerAuthority):
            raise ControlPlaneContractError(
                "invalid_pairing_authority",
                "authority must be InMemoryLocalAgentBrokerAuthority",
            )
        for name, factory in (
            ("code_nonce_factory", code_nonce_factory),
            ("credential_factory", credential_factory),
        ):
            if factory is not None and not callable(factory):
                raise ControlPlaneContractError("invalid_pairing_factory", f"{name} must be callable")
        self._pepper = pepper
        self._authority = authority
        self._code_nonce_factory = code_nonce_factory or _default_code_nonce_factory
        self._credential_factory = credential_factory or _default_credential_factory
        self._credential_ttl_seconds = _positive_int(
            credential_ttl_seconds,
            "credential_ttl_seconds",
            minimum=MIN_PAIRING_CREDENTIAL_TTL_SECONDS,
            maximum=MAX_PAIRING_CREDENTIAL_TTL_SECONDS,
        )
        # #3102: bounded issuance per account/workspace scope. Stored as a
        # counter plus the window start, never as a secret. `None` leaves the
        # bound unbound until an activation binds it.
        if issuance_rate_limit is not None:
            self._issuance_rate_limit = _positive_int(
                issuance_rate_limit,
                "issuance_rate_limit",
                minimum=MIN_PAIRING_ISSUANCE_RATE_LIMIT,
                maximum=MAX_PAIRING_ISSUANCE_RATE_LIMIT,
            )
        else:
            self._issuance_rate_limit = None
        self._issuance_counters: dict[tuple[str, str], tuple[datetime, int]] = {}
        self._pending: dict[str, _PendingBrokerPairingChallenge] = {}

    @property
    def pending_challenge_count(self) -> int:
        return len(self._pending)

    def _pairing_code(self, *, challenge_id: str, code_nonce: str) -> str:
        message = f"{PAIRING_CODE_TRANSCRIPT}\n{challenge_id}\n{code_nonce}".encode("utf-8")
        return hmac.new(self._pepper, message, hashlib.sha256).hexdigest()[:PAIRING_CODE_HEX_CHARS]

    def _prune(self, *, now: datetime) -> None:
        for challenge_id in [
            key for key, pending in self._pending.items() if now >= pending.challenge.expires_at
        ]:
            del self._pending[challenge_id]

    def _enforce_issuance_rate_limit(
        self,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
    ) -> None:
        """Bound live pairing-code issuance for one account/workspace scope.

        The scope is keyed by the **pair itself**, never by a joined string, so
        two distinct (account, workspace) pairs can never collapse into one rate
        bucket regardless of which separator characters a future reference format
        admits. Nothing but a window start and an integer count is retained.
        """
        if self._issuance_rate_limit is None:
            # Source-only posture: Production activation is not done, so no
            # per-scope bound is bound yet. The global pending capacity still
            # applies, and `safe_dict()` reports this explicitly.
            return
        self._prune_issuance_counters(now=now)
        scope = (account_ref, workspace_ref)
        window_start, issued = self._issuance_counters.get(scope, (now, 0))
        elapsed = (now - window_start).total_seconds()
        if elapsed >= PAIRING_ISSUANCE_WINDOW_SECONDS:
            window_start, issued = now, 0
        if issued >= self._issuance_rate_limit:
            raise ControlPlaneContractError(
                "pairing_issuance_rate_limited",
                "broker pairing challenge issuance exceeded the bounded per-scope rate",
            )
        if scope not in self._issuance_counters and (
            len(self._issuance_counters) >= MAX_TRACKED_PAIRING_ISSUANCE_SCOPES
        ):
            # Fail closed. A new scope is refused rather than admitted by
            # evicting a live counter: evicting an unexpired counter would forget
            # that scope's consumed budget and hand it a fresh one, turning the
            # abuse guard into a way to *escape* it. Refusing here bounds memory
            # without ever weakening a live per-scope bound.
            #
            # There is deliberately no eviction helper in this module. An earlier
            # revision dropped the oldest tracked scope to admit a new one; because
            # a budget lives for the full issuance window, that discarded counters
            # whose window had not expired, and a flood of new scopes could reset
            # existing rate limits. Memory is bounded by pruning only.
            raise ControlPlaneContractError(
                "pairing_issuance_scope_capacity_exhausted",
                "tracked broker pairing issuance scopes exceed the bounded capacity",
            )
        self._issuance_counters[scope] = (window_start, issued + 1)

    def _prune_issuance_counters(self, *, now: datetime) -> None:
        """Drop scopes that have been idle for at least one full window.

        An inactive scope can no longer refuse an issuance, so keeping it would
        only grow the map. This is what stops the abuse guard from becoming an
        unbounded-memory surface of its own.
        """
        stale = [
            scope
            for scope, (window_start, _issued) in self._issuance_counters.items()
            if (now - window_start).total_seconds() >= PAIRING_ISSUANCE_WINDOW_SECONDS
        ]
        for scope in stale:
            del self._issuance_counters[scope]

    @property
    def tracked_issuance_scope_count(self) -> int:
        return len(self._issuance_counters)

    def issuance_rate_state(self, *, account_ref: str, workspace_ref: str) -> dict[str, Any]:
        """Secret-free support evidence about one scope's bounded issuance."""
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = _ref(workspace_ref, "workspace_ref")
        scope = (account_ref, workspace_ref)
        window_start, issued = self._issuance_counters.get(scope, (None, 0))
        return {
            "scope": f"{account_ref}/{workspace_ref}",
            "issued_in_window": issued,
            "rate_limit": self._issuance_rate_limit,
            "rate_bound_active": self._issuance_rate_limit is not None,
            "window_seconds": PAIRING_ISSUANCE_WINDOW_SECONDS,
            "window_started_at": None if window_start is None else window_start.isoformat().replace("+00:00", "Z"),
            "tracked_scopes": len(self._issuance_counters),
            "max_tracked_scopes": MAX_TRACKED_PAIRING_ISSUANCE_SCOPES,
        }

    def issue_challenge(
        self,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> tuple[BrokerPairingChallenge, str]:
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = _ref(workspace_ref, "workspace_ref")
        now = _aware(now, "now")
        ttl_seconds = _positive_int(
            ttl_seconds,
            "ttl_seconds",
            minimum=MIN_PAIRING_TTL_SECONDS,
            maximum=MAX_PAIRING_TTL_SECONDS,
        )
        self._prune(now=now)
        # The global pending-capacity guard keeps its original precedence: it is
        # the coarser condition and reports `pairing_capacity_exhausted`.
        if len(self._pending) >= MAX_PENDING_PAIRING_CHALLENGES:
            raise ControlPlaneContractError(
                "pairing_capacity_exhausted",
                "pending broker pairing challenges exceed the bounded capacity",
            )
        # #3102: refuse a scope that is already minting at its bounded rate.
        # Checked after prune so expired challenges never count against a caller.
        self._enforce_issuance_rate_limit(
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            now=now,
        )
        code_nonce = self._code_nonce_factory()
        if not isinstance(code_nonce, str) or not _CODE_NONCE_RE.fullmatch(code_nonce):
            raise ControlPlaneContractError(
                "invalid_pairing_nonce",
                "pairing nonce factory must return 32 lowercase hexadecimal characters",
            )
        challenge = BrokerPairingChallenge(
            challenge_id=f"pairing.{code_nonce}",
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        if challenge.challenge_id in self._pending:
            raise ControlPlaneContractError(
                "duplicate_pairing_challenge",
                "pairing nonce factory reused an existing challenge identifier",
            )
        self._pending[challenge.challenge_id] = _PendingBrokerPairingChallenge(
            challenge=challenge,
            code_nonce=code_nonce,
        )
        return challenge, self._pairing_code(challenge_id=challenge.challenge_id, code_nonce=code_nonce)

    def redeem(
        self,
        *,
        challenge_id: str,
        device_id: str,
        proof_ref: str,
        now: datetime,
    ) -> tuple[BrokerPairingEnrollment, bytes]:
        challenge_id = _ref(challenge_id, "challenge_id")
        device_id = _ref(device_id, "device_id")
        if not isinstance(proof_ref, str) or not PROOF_REF_RE.fullmatch(proof_ref):
            raise ControlPlaneContractError(
                "invalid_pairing_proof",
                "pairing proof must be a canonical HMAC-SHA256 proof reference",
            )
        now = _aware(now, "now")
        try:
            pending = self._pending[challenge_id]
        except KeyError as exc:
            raise ControlPlaneContractError(
                "pairing_challenge_not_found",
                "broker pairing challenge was not found",
            ) from exc
        if pending.redeemed_at is not None:
            raise ControlPlaneContractError(
                "pairing_challenge_already_redeemed",
                "broker pairing challenge is single-use and was already consumed",
            )
        if now >= pending.challenge.expires_at:
            raise ControlPlaneContractError(
                "pairing_challenge_expired",
                "broker pairing challenge has expired",
            )
        expected = pairing_proof_ref(
            challenge_id=challenge_id,
            device_id=device_id,
            pairing_code=self._pairing_code(challenge_id=challenge_id, code_nonce=pending.code_nonce),
        )
        if not hmac.compare_digest(expected, proof_ref):
            raise ControlPlaneContractError(
                "invalid_pairing_proof",
                "broker pairing proof is invalid",
            )

        digest = hashlib.sha256(f"{challenge_id}:{device_id}".encode("utf-8")).hexdigest()[:32]
        binding_ref = f"pairing-binding.{digest}"
        credential_ref = f"pairing-credential.{digest}"

        # Consume the challenge before any binding mutation. A failure after this
        # point burns the code instead of leaving a replayable challenge behind.
        self._pending[challenge_id] = replace(
            pending,
            redeemed_at=now,
            redeemed_device_id=device_id,
            redeemed_binding_ref=binding_ref,
        )

        credential = self._credential_factory()
        if (
            not isinstance(credential, bytes)
            or not credential
            or len(credential) > MAX_PAIRING_CREDENTIAL_BYTES
        ):
            raise ControlPlaneContractError(
                "invalid_pairing_credential",
                "pairing credential factory must return non-empty bounded bytes",
            )
        binding: BrokerDeviceBinding = self._authority.register_binding(
            binding_ref=binding_ref,
            device_id=device_id,
            account_ref=pending.challenge.account_ref,
            workspace_ref=pending.challenge.workspace_ref,
            credential=credential,
            now=now,
            credential_ttl_seconds=self._credential_ttl_seconds,
        )
        enrollment = BrokerPairingEnrollment(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_ref=credential_ref,
            credential_generation=binding.credential_generation,
            issued_at=now,
            credential_expires_at=binding.credential_expires_at,
            challenge_id=challenge_id,
        )
        return enrollment, credential

    def safe_dict(self) -> dict[str, Any]:
        return {
            "pairing_proof_algorithm": PAIRING_PROOF_ALGORITHM,
            "pairing_proof_transcript": PAIRING_PROOF_TRANSCRIPT,
            "pairing_code_hex_chars": PAIRING_CODE_HEX_CHARS,
            "pairing_code_single_use": True,
            "challenge_ttl_max_seconds": MAX_PAIRING_TTL_SECONDS,
            "pending_challenge_capacity": MAX_PENDING_PAIRING_CHALLENGES,
            "pending_challenge_count": len(self._pending),
            # #3102 bounded issuance, declared for support/activation evidence.
            "issuance_rate_limit": self._issuance_rate_limit,
            "issuance_rate_bound_active": self._issuance_rate_limit is not None,
            "production_pairing_activated": False,
            "issuance_window_seconds": PAIRING_ISSUANCE_WINDOW_SECONDS,
            "issuance_rate_bounded": True,
            "issuance_scope_keyed_by_pair": True,
            "tracked_issuance_scopes": len(self._issuance_counters),
            "max_tracked_issuance_scopes": MAX_TRACKED_PAIRING_ISSUANCE_SCOPES,
            "issuance_scopes_pruned": True,
            "active_issuance_counter_eviction": False,
            "issuance_scope_cap_fails_closed": True,
            "generic_rate_authority": False,
            "server_owned_binding_refs": True,
            "server_owned_credential_digests": True,
            "canonical_broker_binding_authority_reused": True,
            "second_credential_verifier": False,
            "self_asserted_account_workspace_authority": False,
            "raw_pairing_code_persisted": False,
            "raw_device_credential_persisted": False,
            "raw_device_credential_returned_once": True,
            "durable_pairing_store_configured": False,
            "production_ready": False,
        }


BROKER_PAIRING_AUTHORITY = True
PAIRING_PROOF_ALGORITHM = "HMAC-SHA256"
PAIRING_CODE_SINGLE_USE = True
RAW_PAIRING_CODE_PERSISTED = False
RAW_DEVICE_CREDENTIAL_PERSISTED = False
RAW_DEVICE_CREDENTIAL_RETURNED_ONCE = True
SERVER_OWNED_PAIRING_REFS = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
CANONICAL_BROKER_BINDING_AUTHORITY_REUSED = True
SECOND_CREDENTIAL_VERIFIER = False
PUBLIC_INBOUND_PORT_REQUIRED = False
DURABLE_PAIRING_STORE_CONFIGURED = False
IN_MEMORY_COUNTS_AS_DURABLE = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
