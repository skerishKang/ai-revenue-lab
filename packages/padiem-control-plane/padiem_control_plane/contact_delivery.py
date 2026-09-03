from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Any, Mapping


_SAFE_REF = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_KOREAN_MOBILE = re.compile(r"^01[016789]\d{7,8}$")
_OTP = re.compile(r"^\d{6}$")
_SOLAPI_REF = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class ContactDeliveryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SolapiAlimTalkConfig:
    api_key: str
    api_secret: str
    pf_id: str
    template_id: str
    sender_number: str
    otp_variable: str = "#{인증번호}"

    def __post_init__(self) -> None:
        for value, field in (
            (self.api_key, "api_key"),
            (self.api_secret, "api_secret"),
            (self.pf_id, "pf_id"),
            (self.template_id, "template_id"),
            (self.sender_number, "sender_number"),
            (self.otp_variable, "otp_variable"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContactDeliveryError("delivery_not_configured", f"{field} is required")
        if not re.fullmatch(r"\d{8,20}", _digits(self.sender_number)):
            raise ContactDeliveryError("delivery_not_configured", "sender_number is invalid")
        if len(self.otp_variable) > 80:
            raise ContactDeliveryError("delivery_not_configured", "otp_variable is invalid")


@dataclass(frozen=True)
class ContactDeliveryCommand:
    product_id: str
    signup_session_ref: str
    challenge_id: str
    phone_contact_ref: str
    channel: str
    recipient_phone: str
    delivery_code: str
    expires_at: str


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def normalize_korean_mobile(value: str) -> str:
    digits = _digits(value)
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def _require_string(payload: Mapping[str, Any], key: str, max_length: int = 320) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ContactDeliveryError("delivery_payload_invalid", f"{key} is required")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise ContactDeliveryError("delivery_payload_invalid", f"{key} is invalid")
    return normalized


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContactDeliveryError("delivery_payload_invalid", "expiresAt is invalid") from exc
    if parsed.tzinfo is None:
        raise ContactDeliveryError("delivery_payload_invalid", "expiresAt must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def parse_delivery_command(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> ContactDeliveryCommand:
    if not isinstance(payload, Mapping):
        raise ContactDeliveryError("delivery_payload_invalid", "payload must be an object")

    product_id = _require_string(payload, "productId", 40)
    if product_id != "danjion":
        raise ContactDeliveryError("delivery_product_not_allowed", "product is not allowed")

    signup_session_ref = _require_string(payload, "signupSessionRef", 128)
    challenge_id = _require_string(payload, "challengeId", 128)
    phone_contact_ref = _require_string(payload, "phoneContactRef", 128)
    for value in (signup_session_ref, challenge_id, phone_contact_ref):
        if not _SAFE_REF.fullmatch(value):
            raise ContactDeliveryError("delivery_payload_invalid", "opaque reference is invalid")

    channel = _require_string(payload, "channel", 40)
    if channel != "kakao_alimtalk":
        raise ContactDeliveryError("delivery_channel_not_allowed", "delivery channel is not allowed")

    recipient_phone = normalize_korean_mobile(_require_string(payload, "recipientPhone", 40))
    if not _KOREAN_MOBILE.fullmatch(recipient_phone):
        raise ContactDeliveryError("delivery_payload_invalid", "recipient phone is invalid")

    delivery_code = _require_string(payload, "deliveryCode", 6)
    if not _OTP.fullmatch(delivery_code):
        raise ContactDeliveryError("delivery_payload_invalid", "delivery code is invalid")

    expires_at = _require_string(payload, "expiresAt", 64)
    expiry = _parse_expiry(expires_at)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expiry <= current:
        raise ContactDeliveryError("delivery_code_expired", "delivery code is expired")
    if (expiry - current).total_seconds() > 15 * 60:
        raise ContactDeliveryError("delivery_payload_invalid", "delivery expiry is outside the allowed bound")

    return ContactDeliveryCommand(
        product_id=product_id,
        signup_session_ref=signup_session_ref,
        challenge_id=challenge_id,
        phone_contact_ref=phone_contact_ref,
        channel=channel,
        recipient_phone=recipient_phone,
        delivery_code=delivery_code,
        expires_at=expiry.isoformat().replace("+00:00", "Z"),
    )


def solapi_signature(api_secret: str, date_time: str, salt: str) -> str:
    return hmac.new(
        api_secret.encode("utf-8"),
        f"{date_time}{salt}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def solapi_authorization(api_key: str, api_secret: str, date_time: str, salt: str) -> str:
    if not api_key or not api_secret or not date_time or not salt:
        raise ContactDeliveryError("delivery_not_configured", "SOLAPI authentication is not configured")
    signature = solapi_signature(api_secret, date_time, salt)
    return f"HMAC-SHA256 apiKey={api_key}, date={date_time}, salt={salt}, signature={signature}"


def build_solapi_alimtalk_body(
    command: ContactDeliveryCommand,
    config: SolapiAlimTalkConfig,
) -> dict[str, Any]:
    # `recipient_phone` and `delivery_code` exist only in this transient provider
    # request. They must never be persisted or copied into safe evidence/logs.
    return {
        "messages": [
            {
                "to": command.recipient_phone,
                "from": _digits(config.sender_number),
                "kakaoOptions": {
                    "pfId": config.pf_id,
                    "templateId": config.template_id,
                    "variables": {config.otp_variable: command.delivery_code},
                    "disableSms": True,
                },
            }
        ],
        "strict": True,
        "allowDuplicates": False,
        "showMessageList": True,
    }


def safe_solapi_delivery_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"ok": False, "errorCode": "PROVIDER_RESPONSE_INVALID"}

    failed = payload.get("failedMessageList")
    if isinstance(failed, list) and failed:
        return {"ok": False, "errorCode": "PROVIDER_REJECTED"}

    message_list = payload.get("messageList")
    if isinstance(message_list, list) and message_list:
        first = message_list[0]
        if isinstance(first, Mapping):
            message_id = first.get("messageId")
            status_code = first.get("statusCode")
            if isinstance(message_id, str) and _SOLAPI_REF.fullmatch(message_id):
                result: dict[str, Any] = {"ok": True, "deliveryRef": message_id}
                if isinstance(status_code, str) and len(status_code) <= 20:
                    result["providerStatusCode"] = status_code
                return result

    group_info = payload.get("groupInfo")
    if isinstance(group_info, Mapping):
        group_id = group_info.get("groupId")
        if isinstance(group_id, str) and _SOLAPI_REF.fullmatch(group_id):
            return {"ok": True, "deliveryRef": group_id}

    return {"ok": False, "errorCode": "PROVIDER_RESPONSE_INVALID"}
