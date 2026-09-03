from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import ContractError

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_PHONE_SHAPED_RE = re.compile(r"^\+?[0-9][0-9 -]{7,20}$")
_OTP_RE = re.compile(r"^[0-9]{6}$")

SIGNUP_UI_FIELDS = ("email", "phone", "verification_code")
PRIMARY_SIMULATED_TRANSPORT = "kakao"
SMS_SPECIFIC_UI_PRESENT = False
KAKAO_OTP_TEMPLATE_REF = "padiem.signup.otp.v1"


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be text")
    value = value.strip()
    if not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if field_name == "phone_contact_ref" and _PHONE_SHAPED_RE.fullmatch(value):
        raise ContractError("phone_contact_ref must be opaque and must not contain the raw phone number")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _otp(value: str) -> str:
    if not isinstance(value, str) or not _OTP_RE.fullmatch(value):
        raise ContractError("simulated Kakao OTP must be exactly six decimal digits")
    return value


@dataclass(frozen=True, slots=True)
class KakaoOtpDeliveryReceipt:
    delivery_ref: str
    challenge_id: str
    phone_contact_ref: str
    template_ref: str
    delivered_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("delivery_ref", "challenge_id", "phone_contact_ref", "template_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        delivered = _aware(self.delivered_at, "delivered_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= delivered:
            raise ContractError("OTP delivery must expire after delivery")
        object.__setattr__(self, "delivered_at", delivered)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-kakao-otp-delivery.v1",
            "delivery_ref": self.delivery_ref,
            "challenge_id": self.challenge_id,
            "phone_contact_ref": self.phone_contact_ref,
            "template_ref": self.template_ref,
            "delivered_at": self.delivered_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "transport": "kakao_simulated",
            "raw_phone_present": False,
            "raw_otp_present": False,
            "real_provider_send": False,
        }


@dataclass(frozen=True, slots=True)
class _TestInboxEntry:
    receipt: KakaoOtpDeliveryReceipt
    otp_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, KakaoOtpDeliveryReceipt):
            raise ContractError("receipt must be KakaoOtpDeliveryReceipt")
        object.__setattr__(self, "otp_code", _otp(self.otp_code))


class FakeKakaoOtpInbox:
    """Network-free Kakao OTP transport for deterministic development/tests only.

    Raw OTPs exist only in this in-memory fixture so a test can simulate what a
    user would see in KakaoTalk. They are never returned by safe projections,
    written to logs, persisted, or exposed through a Production endpoint.
    """

    def __init__(self, *, test_mode: bool) -> None:
        if test_mode is not True:
            raise ContractError("FakeKakaoOtpInbox is available only in explicit test mode")
        self._entries: dict[str, _TestInboxEntry] = {}

    def deliver(
        self,
        *,
        delivery_ref: str,
        challenge_id: str,
        phone_contact_ref: str,
        otp_code: str,
        delivered_at: datetime,
        expires_at: datetime,
        template_ref: str = KAKAO_OTP_TEMPLATE_REF,
    ) -> KakaoOtpDeliveryReceipt:
        challenge_id = _ref(challenge_id, "challenge_id")
        if challenge_id in self._entries:
            raise ContractError("simulated Kakao OTP challenge has already been delivered")
        receipt = KakaoOtpDeliveryReceipt(
            delivery_ref=delivery_ref,
            challenge_id=challenge_id,
            phone_contact_ref=phone_contact_ref,
            template_ref=template_ref,
            delivered_at=delivered_at,
            expires_at=expires_at,
        )
        self._entries[challenge_id] = _TestInboxEntry(receipt=receipt, otp_code=otp_code)
        return receipt

    def read_code_for_test(self, *, challenge_id: str) -> str:
        challenge_id = _ref(challenge_id, "challenge_id")
        try:
            return self._entries[challenge_id].otp_code
        except KeyError as exc:
            raise ContractError("no simulated Kakao OTP exists for this challenge") from exc

    def safe_delivery(self, *, challenge_id: str) -> dict[str, Any]:
        challenge_id = _ref(challenge_id, "challenge_id")
        try:
            return self._entries[challenge_id].receipt.safe_dict()
        except KeyError as exc:
            raise ContractError("no simulated Kakao OTP exists for this challenge") from exc

    def discard(self, *, challenge_id: str) -> None:
        challenge_id = _ref(challenge_id, "challenge_id")
        self._entries.pop(challenge_id, None)

    def clear(self) -> None:
        self._entries.clear()


CHANNEL_NEUTRAL_SIGNUP_UI = True
REAL_KAKAO_ALIMTALK_CONFIGURED = False
REAL_KAKAO_OTP_SEND = False
REAL_PROVIDER_COST = False
RAW_PHONE_IN_MODEL_SAFE_STATE = False
RAW_OTP_LOGGING_SUPPORTED = False
PRODUCTION_FAKE_INBOX_SUPPORTED = False
