from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .contact_verification import (
    ContactVerificationReceipt,
    OtpVerificationChallenge,
    SignupContactBinding,
    VerificationChallengeState,
    VerificationChannel,
    VerificationRatePolicy,
    VerificationRateSnapshot,
    issue_otp_challenge,
    supersede_for_resend,
    verify_otp_challenge,
)
from .contracts import ControlPlaneContractError


def _dt(value: str) -> datetime:
    if not isinstance(value, str):
        raise ControlPlaneContractError("invalid_contact_verification", "timestamp must be ISO-8601 text")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _binding(value: dict[str, Any]) -> SignupContactBinding:
    return SignupContactBinding(
        product_id=value["product_id"],
        signup_session_ref=value["signup_session_ref"],
        email_contact_ref=value["email_contact_ref"],
        phone_contact_ref=value["phone_contact_ref"],
        network_ref=value["network_ref"],
    )


def _rate_snapshot(value: dict[str, Any]) -> VerificationRateSnapshot:
    last = value.get("last_issued_at")
    return VerificationRateSnapshot(
        window_started_at=_dt(value["window_started_at"]),
        session_issues=int(value.get("session_issues", 0)),
        phone_issues=int(value.get("phone_issues", 0)),
        network_issues=int(value.get("network_issues", 0)),
        last_issued_at=_dt(last) if last else None,
    )


def _rate_policy(value: dict[str, Any] | None) -> VerificationRatePolicy:
    if not value:
        return VerificationRatePolicy()
    return VerificationRatePolicy(
        window_seconds=int(value.get("window_seconds", 3600)),
        max_session_issues=int(value.get("max_session_issues", 5)),
        max_phone_issues=int(value.get("max_phone_issues", 5)),
        max_network_issues=int(value.get("max_network_issues", 20)),
        resend_cooldown_seconds=int(value.get("resend_cooldown_seconds", 60)),
    )


def _challenge(value: dict[str, Any]) -> OtpVerificationChallenge:
    return OtpVerificationChallenge(
        challenge_id=value["challenge_id"],
        binding=_binding(value["binding"]),
        channel=VerificationChannel(value["channel"]),
        otp_digest=value["otp_digest"],
        issued_at=_dt(value["issued_at"]),
        expires_at=_dt(value["expires_at"]),
        resend_not_before=_dt(value["resend_not_before"]),
        max_attempts=int(value["max_attempts"]),
        attempts_used=int(value["attempts_used"]),
        generation=int(value["generation"]),
        state=VerificationChallengeState(value["state"]),
    )


def _challenge_dict(value: OtpVerificationChallenge) -> dict[str, Any]:
    return {
        "challenge_id": value.challenge_id,
        "binding": {
            "product_id": value.binding.product_id,
            "signup_session_ref": value.binding.signup_session_ref,
            "email_contact_ref": value.binding.email_contact_ref,
            "phone_contact_ref": value.binding.phone_contact_ref,
            "network_ref": value.binding.network_ref,
        },
        "channel": value.channel.value,
        "otp_digest": value.otp_digest,
        "issued_at": value.issued_at.isoformat(),
        "expires_at": value.expires_at.isoformat(),
        "resend_not_before": value.resend_not_before.isoformat(),
        "max_attempts": value.max_attempts,
        "attempts_used": value.attempts_used,
        "generation": value.generation,
        "state": value.state.value,
    }


def _rate_dict(value: VerificationRateSnapshot) -> dict[str, Any]:
    return {
        "window_started_at": value.window_started_at.isoformat(),
        "session_issues": value.session_issues,
        "phone_issues": value.phone_issues,
        "network_issues": value.network_issues,
        "last_issued_at": value.last_issued_at.isoformat() if value.last_issued_at else None,
    }


def _receipt_dict(value: ContactVerificationReceipt | None) -> dict[str, Any] | None:
    return value.to_public_dict() if value else None


class ContactVerificationRpcFacade:
    """Structured-clone-safe facade over the canonical contact-verification core.

    This class deliberately contains no OTP algorithm. It only reconstructs the
    canonical dataclasses, calls the canonical functions, and serializes results
    for a same-account Cloudflare Worker RPC caller.
    """

    def __init__(self, *, pepper: bytes) -> None:
        if not isinstance(pepper, bytes) or len(pepper) < 16:
            raise ValueError("contact verification pepper must contain at least 16 bytes")
        self._pepper = pepper

    def _call(self, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": exc.safe_message}}
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_contact_verification_rpc_payload",
                    "message": "contact verification RPC payload is invalid",
                },
            }

    def issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            result = issue_otp_challenge(
                challenge_id=payload["challenge_id"],
                binding=_binding(payload["binding"]),
                channel=VerificationChannel(payload.get("channel", VerificationChannel.KAKAO_SIMULATED.value)),
                now=_dt(payload["now"]),
                pepper=self._pepper,
                rate_snapshot=_rate_snapshot(payload["rate_snapshot"]),
                rate_policy=_rate_policy(payload.get("rate_policy")),
                ttl_seconds=int(payload.get("ttl_seconds", 300)),
                max_attempts=int(payload.get("max_attempts", 5)),
                generation=int(payload.get("generation", 1)),
            )
            return {
                "ok": True,
                "challenge": _challenge_dict(result.challenge),
                "rate_snapshot": _rate_dict(result.rate_snapshot),
                # Trusted caller only. DanjiOn must deliver then discard this value.
                "delivery_code": result.delivery_code,
            }

        return self._call(operation)

    def resend(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            superseded, result = supersede_for_resend(
                _challenge(payload["previous_challenge"]),
                new_challenge_id=payload["new_challenge_id"],
                now=_dt(payload["now"]),
                pepper=self._pepper,
                rate_snapshot=_rate_snapshot(payload["rate_snapshot"]),
                rate_policy=_rate_policy(payload.get("rate_policy")),
            )
            return {
                "ok": True,
                "superseded_challenge": _challenge_dict(superseded),
                "challenge": _challenge_dict(result.challenge),
                "rate_snapshot": _rate_dict(result.rate_snapshot),
                "delivery_code": result.delivery_code,
            }

        return self._call(operation)

    def verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            result = verify_otp_challenge(
                _challenge(payload["challenge"]),
                submitted_code=payload["submitted_code"],
                pepper=self._pepper,
                now=_dt(payload["now"]),
                receipt_id=payload["receipt_id"],
            )
            return {
                "ok": True,
                "challenge": _challenge_dict(result.challenge),
                "outcome": result.outcome.value,
                "receipt": _receipt_dict(result.receipt),
            }

        return self._call(operation)
