"""Regression for Chat's shared PC-target transport hint."""
from app.request_contract import _validate_payload


def test_chat_contract_accepts_optional_pc_device_id():
    payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "mode": "auto", "tier": "admin", "skill": "auto",
        "device_id": "device_mock",
    }
    assert isinstance(_validate_payload(payload), tuple)
