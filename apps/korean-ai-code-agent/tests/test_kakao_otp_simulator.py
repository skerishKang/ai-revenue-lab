from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.kakao_otp_simulator import (
    CHANNEL_NEUTRAL_SIGNUP_UI,
    KAKAO_OTP_TEMPLATE_REF,
    PRIMARY_SIMULATED_TRANSPORT,
    PRODUCTION_FAKE_INBOX_SUPPORTED,
    RAW_OTP_LOGGING_SUPPORTED,
    RAW_PHONE_IN_MODEL_SAFE_STATE,
    REAL_KAKAO_ALIMTALK_CONFIGURED,
    REAL_KAKAO_OTP_SEND,
    REAL_PROVIDER_COST,
    SIGNUP_UI_FIELDS,
    SMS_SPECIFIC_UI_PRESENT,
    FakeKakaoOtpInbox,
)


NOW = datetime(2026, 9, 3, 6, 30, tzinfo=timezone.utc)


class KakaoOtpSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.inbox = FakeKakaoOtpInbox(test_mode=True)

    def test_signup_ui_is_channel_neutral_and_has_no_sms_specific_surface(self):
        self.assertEqual(SIGNUP_UI_FIELDS, ("email", "phone", "verification_code"))
        self.assertTrue(CHANNEL_NEUTRAL_SIGNUP_UI)
        self.assertEqual(PRIMARY_SIMULATED_TRANSPORT, "kakao")
        self.assertFalse(SMS_SPECIFIC_UI_PRESENT)

    def test_fake_inbox_requires_explicit_test_mode(self):
        with self.assertRaises(ContractError):
            FakeKakaoOtpInbox(test_mode=False)
        self.assertFalse(PRODUCTION_FAKE_INBOX_SUPPORTED)

    def test_delivery_keeps_raw_otp_out_of_safe_projection(self):
        receipt = self.inbox.deliver(
            delivery_ref="delivery.1",
            challenge_id="challenge.1",
            phone_contact_ref="phone.contact.1",
            otp_code="482731",
            delivered_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        safe = receipt.safe_dict()
        self.assertEqual(safe["template_ref"], KAKAO_OTP_TEMPLATE_REF)
        self.assertEqual(safe["transport"], "kakao_simulated")
        self.assertFalse(safe["raw_phone_present"])
        self.assertFalse(safe["raw_otp_present"])
        self.assertFalse(safe["real_provider_send"])
        self.assertNotIn("482731", repr(safe))

    def test_test_fixture_can_simulate_what_user_saw_in_kakao(self):
        self.inbox.deliver(
            delivery_ref="delivery.1",
            challenge_id="challenge.1",
            phone_contact_ref="phone.contact.1",
            otp_code="482731",
            delivered_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        self.assertEqual(
            self.inbox.read_code_for_test(challenge_id="challenge.1"),
            "482731",
        )

    def test_duplicate_delivery_for_same_challenge_is_refused(self):
        kwargs = dict(
            delivery_ref="delivery.1",
            challenge_id="challenge.1",
            phone_contact_ref="phone.contact.1",
            otp_code="482731",
            delivered_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        self.inbox.deliver(**kwargs)
        with self.assertRaises(ContractError):
            self.inbox.deliver(**kwargs)

    def test_raw_phone_number_cannot_be_used_as_phone_contact_ref(self):
        with self.assertRaises(ContractError):
            self.inbox.deliver(
                delivery_ref="delivery.1",
                challenge_id="challenge.1",
                phone_contact_ref="01012345678",
                otp_code="482731",
                delivered_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )

    def test_invalid_otp_format_is_refused(self):
        with self.assertRaises(ContractError):
            self.inbox.deliver(
                delivery_ref="delivery.1",
                challenge_id="challenge.1",
                phone_contact_ref="phone.contact.1",
                otp_code="12345",
                delivered_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )

    def test_expiry_must_follow_delivery(self):
        with self.assertRaises(ContractError):
            self.inbox.deliver(
                delivery_ref="delivery.1",
                challenge_id="challenge.1",
                phone_contact_ref="phone.contact.1",
                otp_code="482731",
                delivered_at=NOW,
                expires_at=NOW,
            )

    def test_discard_removes_test_only_secret(self):
        self.inbox.deliver(
            delivery_ref="delivery.1",
            challenge_id="challenge.1",
            phone_contact_ref="phone.contact.1",
            otp_code="482731",
            delivered_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
        self.inbox.discard(challenge_id="challenge.1")
        with self.assertRaises(ContractError):
            self.inbox.read_code_for_test(challenge_id="challenge.1")

    def test_repository_slice_claims_no_real_provider_or_cost(self):
        self.assertFalse(REAL_KAKAO_ALIMTALK_CONFIGURED)
        self.assertFalse(REAL_KAKAO_OTP_SEND)
        self.assertFalse(REAL_PROVIDER_COST)
        self.assertFalse(RAW_PHONE_IN_MODEL_SAFE_STATE)
        self.assertFalse(RAW_OTP_LOGGING_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
