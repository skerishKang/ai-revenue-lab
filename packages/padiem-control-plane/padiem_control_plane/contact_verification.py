"""Product-neutral signup contact verification contracts for Padiem Control Plane.

This module owns the trusted lifecycle of a one-time contact-possession challenge.
It intentionally does not own HTTP endpoints, Kakao/SMS credentials, user-facing
UI, persistent storage, or legal identity verification.

Security invariants:
- raw email addresses and phone numbers are resolved to opaque trusted refs before
  entering this contract;
- the persisted challenge carries only an HMAC digest of the OTP, never the OTP;
- the HMAC pepper is supplied by trusted server secret authority and is never
  stored in the challenge;
- OTP challenges are short-lived, single-use and attempt-bounded;
- resend supersedes the prior challenge and is cooldown/rate-budget gated;
- successful verification proves possession of the challenged contact endpoint
  for this signup session only; it does not claim legal/CI identity proof.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import hmac
import re
import secrets
from typing import Callable

from .contracts import ControlPlaneContractError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_OTP_RE = re.compile(r"^[0-9]{6}$")

OTP_DIGITS = 6
DEFAULT_OTP_TTL_SECONDS = 300
DEFAULT_RESEND_COOLDOWN_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RATE_WINDOW_SECONDS = 3600
DEFAULT_MAX_SESSION_ISSUES = 5
DEFAULT_MAX_PHONE_ISSUES = 5
DEFAULT_MAX_NETWORK_ISSUES = 20
MIN_PEPPER_BYTES = 16


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value.strip()):
        raise ControlPlaneContractError(
            "invalid_contact_verification",
            f"{name} must be a bounded safe identifier",
        )
    return value.strip()


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_contact_verification",
            f"{name} must be timezone-aware",
        )
    return value


def _positive_int(name: str, value: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ControlPlaneContractError(
            "invalid_contact_verification",
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def _otp(value: str) -> str:
    if not isinstance(value, str) or not _OTP_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_contact_verification_code",
            "verification code must be exactly six decimal digits",
        )
    return value


def _pepper(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < MIN_PEPPER_BYTES:
        raise ControlPlaneContractError(
            "invalid_contact_verification_pepper",
            f"OTP pepper must contain at least {MIN_PEPPER_BYTES} bytes",
        )
    return value


class VerificationChannel(str, Enum):
    KAKAO_SIMULATED = "kakao_simulated"
    KAKAO_ALIMTALK = "kakao_alimtalk"
    SMS_FALLBACK = "sms_fallback"


class VerificationChallengeState(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"
    LOCKED = "locked"
    SUPERSEDED = "superseded"


class VerificationOutcome(str, Enum):
    VERIFIED = "verified"
    INVALID_CODE = "invalid_code"
    EXPIRED = "expired"
    LOCKED = "locked"


@dataclass(frozen=True, slots=True)
class SignupContactBinding:
    product_id: str
    signup_session_ref: str
    email_contact_ref: str
    phone_contact_ref: str
    network_ref: str

    def __post_init__(self) -> None:
        for field_name in (
            "product_id",
            "signup_session_ref",
            "email_contact_ref",
            "phone_contact_ref",
            "network_ref",
        ):
            object.__setattr__(self, field_name, _identifier(field_name, getattr(self, field_name)))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "signup_session_ref": self.signup_session_ref,
            "email_contact_ref": self.email_contact_ref,
            "phone_contact_ref": self.phone_contact_ref,
            "network_ref": self.network_ref,
            "raw_email_present": False,
            "raw_phone_present": False,
        }


@dataclass(frozen=True, slots=True)
class VerificationRatePolicy:
    window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS
    max_session_issues: int = DEFAULT_MAX_SESSION_ISSUES
    max_phone_issues: int = DEFAULT_MAX_PHONE_ISSUES
    max_network_issues: int = DEFAULT_MAX_NETWORK_ISSUES
    resend_cooldown_seconds: int = DEFAULT_RESEND_COOLDOWN_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_seconds", _positive_int("window_seconds", self.window_seconds, minimum=60, maximum=86400))
        object.__setattr__(self, "max_session_issues", _positive_int("max_session_issues", self.max_session_issues, minimum=1, maximum=100))
        object.__setattr__(self, "max_phone_issues", _positive_int("max_phone_issues", self.max_phone_issues, minimum=1, maximum=100))
        object.__setattr__(self, "max_network_issues", _positive_int("max_network_issues", self.max_network_issues, minimum=1, maximum=1000))
        object.__setattr__(self, "resend_cooldown_seconds", _positive_int("resend_cooldown_seconds", self.resend_cooldown_seconds, minimum=10, maximum=3600))


@dataclass(frozen=True, slots=True)
class VerificationRateSnapshot:
    window_started_at: datetime
    session_issues: int = 0
    phone_issues: int = 0
    network_issues: int = 0
    last_issued_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_started_at", _aware("window_started_at", self.window_started_at))
        for field_name in ("session_issues", "phone_issues", "network_issues"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ControlPlaneContractError(
                    "invalid_contact_verification_rate_snapshot",
                    f"{field_name} must be a non-negative integer",
                )
        if self.last_issued_at is not None:
            object.__setattr__(self, "last_issued_at", _aware("last_issued_at", self.last_issued_at))

    def normalized(self, *, now: datetime, policy: VerificationRatePolicy) -> "VerificationRateSnapshot":
        now = _aware("now", now)
        if now - self.window_started_at >= timedelta(seconds=policy.window_seconds):
            return VerificationRateSnapshot(window_started_at=now)
        return self

    def assert_can_issue(self, *, now: datetime, policy: VerificationRatePolicy) -> None:
        now = _aware("now", now)
        current = self.normalized(now=now, policy=policy)
        if current.session_issues >= policy.max_session_issues:
            raise ControlPlaneContractError("contact_verification_rate_limited", "signup session issue budget exhausted")
        if current.phone_issues >= policy.max_phone_issues:
            raise ControlPlaneContractError("contact_verification_rate_limited", "phone contact issue budget exhausted")
        if current.network_issues >= policy.max_network_issues:
            raise ControlPlaneContractError("contact_verification_rate_limited", "network issue budget exhausted")
        if current.last_issued_at is not None and now < current.last_issued_at + timedelta(seconds=policy.resend_cooldown_seconds):
            raise ControlPlaneContractError("contact_verification_resend_cooldown", "verification resend cooldown is still active")

    def after_issue(self, *, now: datetime, policy: VerificationRatePolicy) -> "VerificationRateSnapshot":
        now = _aware("now", now)
        current = self.normalized(now=now, policy=policy)
        current.assert_can_issue(now=now, policy=policy)
        return VerificationRateSnapshot(
            window_started_at=current.window_started_at,
            session_issues=current.session_issues + 1,
            phone_issues=current.phone_issues + 1,
            network_issues=current.network_issues + 1,
            last_issued_at=now,
        )


def generate_numeric_otp() -> str:
    """Generate a cryptographically strong six-digit decimal OTP."""
    return f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"


def derive_otp_digest(*, pepper: bytes, challenge_id: str, binding: SignupContactBinding, otp_code: str) -> str:
    pepper = _pepper(pepper)
    challenge_id = _identifier("challenge_id", challenge_id)
    otp_code = _otp(otp_code)
    material = "\x1f".join(
        (
            challenge_id,
            binding.product_id,
            binding.signup_session_ref,
            binding.email_contact_ref,
            binding.phone_contact_ref,
            otp_code,
        )
    ).encode("utf-8")
    return hmac.new(pepper, material, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class OtpVerificationChallenge:
    challenge_id: str
    binding: SignupContactBinding
    channel: VerificationChannel
    otp_digest: str
    issued_at: datetime
    expires_at: datetime
    resend_not_before: datetime
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    attempts_used: int = 0
    generation: int = 1
    state: VerificationChallengeState = VerificationChallengeState.PENDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "challenge_id", _identifier("challenge_id", self.challenge_id))
        if not isinstance(self.binding, SignupContactBinding):
            raise ControlPlaneContractError("invalid_contact_verification", "binding must be SignupContactBinding")
        if not isinstance(self.channel, VerificationChannel):
            try:
                object.__setattr__(self, "channel", VerificationChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError("invalid_contact_verification", "invalid verification channel") from exc
        if not isinstance(self.otp_digest, str) or not _DIGEST_RE.fullmatch(self.otp_digest):
            raise ControlPlaneContractError("invalid_contact_verification", "otp_digest must be lowercase SHA-256 HMAC")
        issued = _aware("issued_at", self.issued_at)
        expires = _aware("expires_at", self.expires_at)
        resend = _aware("resend_not_before", self.resend_not_before)
        if expires <= issued or expires - issued > timedelta(minutes=10):
            raise ControlPlaneContractError("invalid_contact_verification", "challenge lifetime must be positive and at most ten minutes")
        if resend < issued or resend > expires:
            raise ControlPlaneContractError("invalid_contact_verification", "resend_not_before must fall inside the challenge lifetime")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "resend_not_before", resend)
        object.__setattr__(self, "max_attempts", _positive_int("max_attempts", self.max_attempts, minimum=1, maximum=10))
        if isinstance(self.attempts_used, bool) or not isinstance(self.attempts_used, int) or not 0 <= self.attempts_used <= self.max_attempts:
            raise ControlPlaneContractError("invalid_contact_verification", "attempts_used must be within the attempt budget")
        object.__setattr__(self, "generation", _positive_int("generation", self.generation, minimum=1, maximum=1000))
        if not isinstance(self.state, VerificationChallengeState):
            try:
                object.__setattr__(self, "state", VerificationChallengeState(self.state))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError("invalid_contact_verification", "invalid challenge state") from exc
        if self.state is VerificationChallengeState.LOCKED and self.attempts_used < self.max_attempts:
            raise ControlPlaneContractError("invalid_contact_verification", "locked challenge must exhaust the attempt budget")

    def effective_state(self, *, now: datetime) -> VerificationChallengeState:
        now = _aware("now", now)
        if self.state is VerificationChallengeState.PENDING and now >= self.expires_at:
            return VerificationChallengeState.EXPIRED
        return self.state

    def to_public_dict(self) -> dict[str, object]:
        return {
            "challenge_id": self.challenge_id,
            "binding": self.binding.to_public_dict(),
            "channel": self.channel.value,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "resend_not_before": self.resend_not_before.isoformat(),
            "attempts_remaining": max(0, self.max_attempts - self.attempts_used),
            "generation": self.generation,
            "state": self.state.value,
            "raw_otp_present": False,
            "otp_digest_exposed": False,
            "legal_identity_verified": False,
        }


@dataclass(frozen=True, slots=True)
class OtpIssueResult:
    challenge: OtpVerificationChallenge
    delivery_code: str
    rate_snapshot: VerificationRateSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.challenge, OtpVerificationChallenge):
            raise ControlPlaneContractError("invalid_contact_verification", "challenge must be OtpVerificationChallenge")
        object.__setattr__(self, "delivery_code", _otp(self.delivery_code))
        if not isinstance(self.rate_snapshot, VerificationRateSnapshot):
            raise ControlPlaneContractError("invalid_contact_verification", "rate_snapshot must be VerificationRateSnapshot")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "challenge": self.challenge.to_public_dict(),
            "delivery_code_exposed": False,
        }


@dataclass(frozen=True, slots=True)
class ContactVerificationReceipt:
    receipt_id: str
    challenge_id: str
    product_id: str
    signup_session_ref: str
    email_contact_ref: str
    phone_contact_ref: str
    channel: VerificationChannel
    verified_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "challenge_id",
            "product_id",
            "signup_session_ref",
            "email_contact_ref",
            "phone_contact_ref",
        ):
            object.__setattr__(self, field_name, _identifier(field_name, getattr(self, field_name)))
        if not isinstance(self.channel, VerificationChannel):
            try:
                object.__setattr__(self, "channel", VerificationChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError("invalid_contact_verification_receipt", "invalid verification channel") from exc
        object.__setattr__(self, "verified_at", _aware("verified_at", self.verified_at))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "challenge_id": self.challenge_id,
            "product_id": self.product_id,
            "signup_session_ref": self.signup_session_ref,
            "email_contact_ref": self.email_contact_ref,
            "phone_contact_ref": self.phone_contact_ref,
            "channel": self.channel.value,
            "verified_at": self.verified_at.isoformat(),
            "phone_verified": True,
            "identity_assurance": "contact_possession_only",
            "legal_identity_verified": False,
        }


@dataclass(frozen=True, slots=True)
class OtpVerificationResult:
    challenge: OtpVerificationChallenge
    outcome: VerificationOutcome
    receipt: ContactVerificationReceipt | None = None


def issue_otp_challenge(
    *,
    challenge_id: str,
    binding: SignupContactBinding,
    channel: VerificationChannel,
    now: datetime,
    pepper: bytes,
    rate_snapshot: VerificationRateSnapshot,
    rate_policy: VerificationRatePolicy = VerificationRatePolicy(),
    ttl_seconds: int = DEFAULT_OTP_TTL_SECONDS,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    generation: int = 1,
    otp_factory: Callable[[], str] = generate_numeric_otp,
) -> OtpIssueResult:
    now = _aware("now", now)
    ttl_seconds = _positive_int("ttl_seconds", ttl_seconds, minimum=60, maximum=600)
    max_attempts = _positive_int("max_attempts", max_attempts, minimum=1, maximum=10)
    if not isinstance(rate_snapshot, VerificationRateSnapshot):
        raise ControlPlaneContractError("invalid_contact_verification", "rate_snapshot must be VerificationRateSnapshot")
    updated_rate = rate_snapshot.after_issue(now=now, policy=rate_policy)
    code = _otp(otp_factory())
    challenge_id = _identifier("challenge_id", challenge_id)
    digest = derive_otp_digest(pepper=pepper, challenge_id=challenge_id, binding=binding, otp_code=code)
    challenge = OtpVerificationChallenge(
        challenge_id=challenge_id,
        binding=binding,
        channel=channel,
        otp_digest=digest,
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        resend_not_before=now + timedelta(seconds=min(rate_policy.resend_cooldown_seconds, ttl_seconds)),
        max_attempts=max_attempts,
        generation=generation,
    )
    return OtpIssueResult(challenge=challenge, delivery_code=code, rate_snapshot=updated_rate)


def supersede_for_resend(
    previous: OtpVerificationChallenge,
    *,
    new_challenge_id: str,
    now: datetime,
    pepper: bytes,
    rate_snapshot: VerificationRateSnapshot,
    rate_policy: VerificationRatePolicy = VerificationRatePolicy(),
    otp_factory: Callable[[], str] = generate_numeric_otp,
) -> tuple[OtpVerificationChallenge, OtpIssueResult]:
    if not isinstance(previous, OtpVerificationChallenge):
        raise ControlPlaneContractError("invalid_contact_verification", "previous must be OtpVerificationChallenge")
    now = _aware("now", now)
    if previous.state is not VerificationChallengeState.PENDING:
        raise ControlPlaneContractError("terminal_contact_verification", "only a pending challenge may be resent")
    if now < previous.resend_not_before:
        raise ControlPlaneContractError("contact_verification_resend_cooldown", "verification resend cooldown is still active")
    superseded = replace(previous, state=VerificationChallengeState.SUPERSEDED)
    issued = issue_otp_challenge(
        challenge_id=new_challenge_id,
        binding=previous.binding,
        channel=previous.channel,
        now=now,
        pepper=pepper,
        rate_snapshot=rate_snapshot,
        rate_policy=rate_policy,
        ttl_seconds=int((previous.expires_at - previous.issued_at).total_seconds()),
        max_attempts=previous.max_attempts,
        generation=previous.generation + 1,
        otp_factory=otp_factory,
    )
    return superseded, issued


def verify_otp_challenge(
    challenge: OtpVerificationChallenge,
    *,
    submitted_code: str,
    pepper: bytes,
    now: datetime,
    receipt_id: str,
) -> OtpVerificationResult:
    if not isinstance(challenge, OtpVerificationChallenge):
        raise ControlPlaneContractError("invalid_contact_verification", "challenge must be OtpVerificationChallenge")
    now = _aware("now", now)
    submitted_code = _otp(submitted_code)

    if challenge.state is VerificationChallengeState.VERIFIED:
        raise ControlPlaneContractError("replayed_contact_verification", "verified challenge cannot be consumed twice")
    if challenge.state is VerificationChallengeState.SUPERSEDED:
        raise ControlPlaneContractError("superseded_contact_verification", "superseded challenge cannot be verified")
    if challenge.state is VerificationChallengeState.LOCKED:
        return OtpVerificationResult(challenge=challenge, outcome=VerificationOutcome.LOCKED)
    if challenge.state is VerificationChallengeState.EXPIRED or now >= challenge.expires_at:
        expired = replace(challenge, state=VerificationChallengeState.EXPIRED)
        return OtpVerificationResult(challenge=expired, outcome=VerificationOutcome.EXPIRED)

    expected = derive_otp_digest(
        pepper=pepper,
        challenge_id=challenge.challenge_id,
        binding=challenge.binding,
        otp_code=submitted_code,
    )
    if not hmac.compare_digest(expected, challenge.otp_digest):
        attempts = challenge.attempts_used + 1
        if attempts >= challenge.max_attempts:
            locked = replace(challenge, attempts_used=attempts, state=VerificationChallengeState.LOCKED)
            return OtpVerificationResult(challenge=locked, outcome=VerificationOutcome.LOCKED)
        current = replace(challenge, attempts_used=attempts)
        return OtpVerificationResult(challenge=current, outcome=VerificationOutcome.INVALID_CODE)

    verified = replace(challenge, state=VerificationChallengeState.VERIFIED)
    receipt = ContactVerificationReceipt(
        receipt_id=receipt_id,
        challenge_id=challenge.challenge_id,
        product_id=challenge.binding.product_id,
        signup_session_ref=challenge.binding.signup_session_ref,
        email_contact_ref=challenge.binding.email_contact_ref,
        phone_contact_ref=challenge.binding.phone_contact_ref,
        channel=challenge.channel,
        verified_at=now,
    )
    return OtpVerificationResult(
        challenge=verified,
        outcome=VerificationOutcome.VERIFIED,
        receipt=receipt,
    )


REAL_CONTACT_VERIFICATION_STORAGE_CONFIGURED = False
REAL_KAKAO_OTP_PROVIDER_CONFIGURED = False
REAL_SMS_OTP_FALLBACK_CONFIGURED = False
LEGAL_IDENTITY_VERIFICATION_SUPPORTED = False
RAW_CONTACT_PII_IN_PUBLIC_CONTRACT = False
RAW_OTP_AT_REST_SUPPORTED = False
