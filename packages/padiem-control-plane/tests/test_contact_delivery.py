from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from padiem_control_plane.contact_delivery import (
    ContactDeliveryError,
    SolapiAlimTalkConfig,
    build_solapi_alimtalk_body,
    parse_delivery_command,
    safe_solapi_delivery_result,
    solapi_authorization,
    solapi_signature,
)


NOW = datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)


def payload(**overrides):
    base = {
        "productId": "danjion",
        "signupSessionRef": "signup.11111111-1111-4111-8111-111111111111",
        "challengeId": "challenge.22222222-2222-4222-8222-222222222222",
        "phoneContactRef": "phone.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "channel": "kakao_alimtalk",
        "recipientPhone": "+82 10-1234-5678",
        "deliveryCode": "123456",
        "expiresAt": (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    }
    base.update(overrides)
    return base


def config():
    return SolapiAlimTalkConfig(
        api_key="test-api-key",
        api_secret="test-api-secret",
        pf_id="PF_TEST",
        template_id="TPL_TEST",
        sender_number="0212345678",
    )


def test_delivery_command_requires_ephemeral_phone_and_exact_channel():
    command = parse_delivery_command(payload(), now=NOW)
    assert command.recipient_phone == "01012345678"
    assert command.delivery_code == "123456"
    assert command.channel == "kakao_alimtalk"

    with pytest.raises(ContactDeliveryError) as exc:
        parse_delivery_command(payload(channel="kakao_simulated"), now=NOW)
    assert exc.value.code == "delivery_channel_not_allowed"

    with pytest.raises(ContactDeliveryError):
        parse_delivery_command(payload(recipientPhone="010-12"), now=NOW)


def test_expired_or_unbounded_codes_fail_closed():
    with pytest.raises(ContactDeliveryError) as expired:
        parse_delivery_command(
            payload(expiresAt=(NOW - timedelta(seconds=1)).isoformat()),
            now=NOW,
        )
    assert expired.value.code == "delivery_code_expired"

    with pytest.raises(ContactDeliveryError):
        parse_delivery_command(
            payload(expiresAt=(NOW + timedelta(minutes=16)).isoformat()),
            now=NOW,
        )


def test_solapi_hmac_is_deterministic_and_secret_not_in_header():
    signature = solapi_signature("secret", "2026-09-03T13:00:00Z", "salt-12345678")
    assert len(signature) == 64
    header = solapi_authorization("key", "secret", "2026-09-03T13:00:00Z", "salt-12345678")
    assert header.startswith("HMAC-SHA256 apiKey=key, date=2026-09-03T13:00:00Z, salt=salt-12345678, signature=")
    assert "secret" not in header


def test_alimtalk_body_disables_sms_fallback_and_keeps_pii_transient():
    command = parse_delivery_command(payload(), now=NOW)
    body = build_solapi_alimtalk_body(command, config())
    message = body["messages"][0]
    assert message["to"] == "01012345678"
    assert message["from"] == "0212345678"
    assert message["kakaoOptions"]["disableSms"] is True
    assert message["kakaoOptions"]["variables"] == {"#{인증번호}": "123456"}
    assert body["strict"] is True
    assert body["allowDuplicates"] is False
    assert body["showMessageList"] is True


def test_provider_response_is_reduced_to_safe_receipt_only():
    result = safe_solapi_delivery_result(
        {
            "groupInfo": {"groupId": "G4V_SAFE_GROUP", "accountId": "provider-account"},
            "messageList": [
                {
                    "messageId": "M4V_SAFE_MESSAGE",
                    "statusCode": "2000",
                    "to": "01012345678",
                    "text": "인증번호 123456",
                }
            ],
        }
    )
    assert result == {
        "ok": True,
        "deliveryRef": "M4V_SAFE_MESSAGE",
        "providerStatusCode": "2000",
    }
    serialized = repr(result)
    assert "01012345678" not in serialized
    assert "123456" not in serialized

    failed = safe_solapi_delivery_result(
        {"failedMessageList": [{"to": "01012345678", "statusMessage": "raw provider detail"}]}
    )
    assert failed == {"ok": False, "errorCode": "PROVIDER_REJECTED"}


def test_worker_configs_are_private_and_log_free():
    package_root = Path(__file__).resolve().parents[1]
    worker = (package_root / "contact_delivery_worker.py").read_text(encoding="utf-8")
    delivery_configs = list(package_root.glob("*contact-delivery.jsonc"))
    verification_configs = list(package_root.glob("*contact-verification.jsonc"))
    assert len(delivery_configs) == 1
    assert len(verification_configs) == 1
    config_text = delivery_configs[0].read_text(encoding="utf-8")
    verification_config = verification_configs[0].read_text(encoding="utf-8")

    assert 'status=404' in worker
    assert "print(" not in worker
    assert "console.log" not in worker
    assert '"workers_dev": false' in config_text
    assert '"preview_urls": false' in config_text
    assert '"python_workers"' in config_text
    assert '"disable_python_external_sdk"' in config_text
    assert '"disable_python_external_sdk"' in verification_config
