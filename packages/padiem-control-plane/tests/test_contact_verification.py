from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contact_verification import (
    ContactVerificationReceipt,
    OtpVerificationChallenge,
    SignupContactBinding,
    VerificationChallengeState,
    VerificationChannel,
    VerificationOutcome,
    VerificationRatePolicy,
    VerificationRateSnapshot,
    derive_otp_digest,
    generate_numeric_otp,
    issue_otp_challenge,
    supersede_for_resend,
    verify_otp_challenge,
)
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 3, 6, 30, tzinfo=timezone.utc)
PEPPER = b"test-only-otp-pepper-material-32b"


def binding() -> SignupContactBinding:
    return SignupContactBinding(
        product_id="padiem-claw",
        signup_session_ref="signup.session.1",
        email_contact_ref="email.contact.1",
        phone_contact_ref="phone.contact.1",
        network_ref="network.bucket.1",
    )


def rate() -> VerificationRateSnapshot:
    return VerificationRateSnapshot(window_started_at=NOW - timedelta(minutes=5))


def issue(code: str = "482731"):
    return issue_otp_challenge(
        challenge_id="challenge.1",
        binding=binding(),
        channel=VerificationChannel.KAKAO_SIMULATED,
        now=NOW,
        pepper=PEPPER,
        rate_snapshot=rate(),
        otp_factory=lambda: code,
    )


def test_generated_otp_is_six_decimal_digits() -> None:
    code = generate_numeric_otp()
    assert len(code) == 6
    assert code.isdecimal()


def test_issue_persists_digest_not_raw_code_in_public_projection() -> None:
    result = issue()
    assert result.delivery_code == "482731"
    assert result.challenge.otp_digest != result.delivery_code
    assert len(result.challenge.otp_digest) == 64
    public = result.to_public_dict()
    assert public["delivery_code_exposed"] is False
    challenge_public = public["challenge"]
    assert challenge_public["raw_otp_present"] is False
    assert challenge_public["otp_digest_exposed"] is False
    assert challenge_public["binding"]["raw_email_present"] is False
    assert challenge_public["binding"]["raw_phone_present"] is False


def test_digest_is_bound_to_exact_signup_and_contact_refs() -> None:
    result = issue()
    changed_binding = replace(binding(), phone_contact_ref="phone.contact.2")
    changed = derive_otp_digest(
        pepper=PEPPER,
        challenge_id=result.challenge.challenge_id,
        binding=changed_binding,
        otp_code="482731",
    )
    assert changed != result.challenge.otp_digest


def test_correct_code_verifies_once_and_returns_contact_possession_receipt() -> None:
    result = issue()
    verified = verify_otp_challenge(
        result.challenge,
        submitted_code="482731",
        pepper=PEPPER,
        now=NOW + timedelta(seconds=10),
        receipt_id="receipt.1",
    )
    assert verified.outcome is VerificationOutcome.VERIFIED
    assert verified.challenge.state is VerificationChallengeState.VERIFIED
    assert isinstance(verified.receipt, ContactVerificationReceipt)
    assert verified.receipt.phone_contact_ref == "phone.contact.1"
    public = verified.receipt.to_public_dict()
    assert public["phone_verified"] is True
    assert public["identity_assurance"] == "contact_possession_only"
    assert public["legal_identity_verified"] is False

    with pytest.raises(ControlPlaneContractError) as exc:
        verify_otp_challenge(
            verified.challenge,
            submitted_code="482731",
            pepper=PEPPER,
            now=NOW + timedelta(seconds=20),
            receipt_id="receipt.2",
        )
    assert exc.value.code == "replayed_contact_verification"


def test_wrong_codes_consume_attempt_budget_and_lock() -> None:
    current = issue().challenge
    for attempt in range(1, current.max_attempts + 1):
        checked = verify_otp_challenge(
            current,
            submitted_code="000000",
            pepper=PEPPER,
            now=NOW + timedelta(seconds=attempt),
            receipt_id=f"receipt.bad.{attempt}",
        )
        current = checked.challenge
    assert checked.outcome is VerificationOutcome.LOCKED
    assert current.state is VerificationChallengeState.LOCKED
    assert current.attempts_used == current.max_attempts


def test_expired_code_cannot_verify() -> None:
    result = issue()
    checked = verify_otp_challenge(
        result.challenge,
        submitted_code="482731",
        pepper=PEPPER,
        now=result.challenge.expires_at,
        receipt_id="receipt.expired",
    )
    assert checked.outcome is VerificationOutcome.EXPIRED
    assert checked.challenge.state is VerificationChallengeState.EXPIRED
    assert checked.receipt is None


def test_resend_before_cooldown_is_rejected() -> None:
    result = issue()
    with pytest.raises(ControlPlaneContractError) as exc:
        supersede_for_resend(
            result.challenge,
            new_challenge_id="challenge.2",
            now=NOW + timedelta(seconds=30),
            pepper=PEPPER,
            rate_snapshot=result.rate_snapshot,
            otp_factory=lambda: "555555",
        )
    assert exc.value.code == "contact_verification_resend_cooldown"


def test_resend_supersedes_old_code_and_rotates_generation() -> None:
    result = issue()
    old, resent = supersede_for_resend(
        result.challenge,
        new_challenge_id="challenge.2",
        now=NOW + timedelta(seconds=61),
        pepper=PEPPER,
        rate_snapshot=result.rate_snapshot,
        otp_factory=lambda: "555555",
    )
    assert old.state is VerificationChallengeState.SUPERSEDED
    assert resent.challenge.generation == 2
    assert resent.delivery_code == "555555"
    with pytest.raises(ControlPlaneContractError) as exc:
        verify_otp_challenge(
            old,
            submitted_code="482731",
            pepper=PEPPER,
            now=NOW + timedelta(seconds=62),
            receipt_id="receipt.old",
        )
    assert exc.value.code == "superseded_contact_verification"


def test_rate_budget_enforces_session_phone_network_and_cooldown() -> None:
    policy = VerificationRatePolicy(
        max_session_issues=2,
        max_phone_issues=2,
        max_network_issues=2,
        resend_cooldown_seconds=60,
    )
    snapshot = VerificationRateSnapshot(window_started_at=NOW)
    first = snapshot.after_issue(now=NOW, policy=policy)
    with pytest.raises(ControlPlaneContractError) as exc:
        first.after_issue(now=NOW + timedelta(seconds=30), policy=policy)
    assert exc.value.code == "contact_verification_resend_cooldown"
    second = first.after_issue(now=NOW + timedelta(seconds=61), policy=policy)
    with pytest.raises(ControlPlaneContractError) as exc:
        second.after_issue(now=NOW + timedelta(seconds=122), policy=policy)
    assert exc.value.code == "contact_verification_rate_limited"


def test_rate_window_resets_after_policy_window() -> None:
    policy = VerificationRatePolicy(max_session_issues=1, max_phone_issues=1, max_network_issues=1)
    snapshot = VerificationRateSnapshot(
        window_started_at=NOW - timedelta(hours=2),
        session_issues=99,
        phone_issues=99,
        network_issues=99,
        last_issued_at=NOW - timedelta(hours=2),
    )
    updated = snapshot.after_issue(now=NOW, policy=policy)
    assert updated.session_issues == 1
    assert updated.phone_issues == 1
    assert updated.network_issues == 1


def test_challenge_rejects_lifetime_over_ten_minutes() -> None:
    b = binding()
    digest = derive_otp_digest(
        pepper=PEPPER,
        challenge_id="challenge.long",
        binding=b,
        otp_code="123456",
    )
    with pytest.raises(ControlPlaneContractError):
        OtpVerificationChallenge(
            challenge_id="challenge.long",
            binding=b,
            channel=VerificationChannel.KAKAO_SIMULATED,
            otp_digest=digest,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=11),
            resend_not_before=NOW + timedelta(minutes=1),
        )


def test_pepper_must_be_server_secret_strength() -> None:
    with pytest.raises(ControlPlaneContractError) as exc:
        issue_otp_challenge(
            challenge_id="challenge.weak",
            binding=binding(),
            channel=VerificationChannel.KAKAO_SIMULATED,
            now=NOW,
            pepper=b"short",
            rate_snapshot=rate(),
            otp_factory=lambda: "123456",
        )
    assert exc.value.code == "invalid_contact_verification_pepper"
