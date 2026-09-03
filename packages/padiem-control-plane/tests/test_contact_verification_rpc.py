from __future__ import annotations

from datetime import datetime, timedelta, timezone

from padiem_control_plane.contact_verification_rpc import ContactVerificationRpcFacade


NOW = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)
PEPPER = b"padiem-test-contact-verification-pepper"


def base_payload() -> dict:
    return {
        "challenge_id": "challenge.1",
        "binding": {
            "product_id": "danjion",
            "signup_session_ref": "signup.1",
            "email_contact_ref": "email.1",
            "phone_contact_ref": "phone.1",
            "network_ref": "network.1",
        },
        "channel": "kakao_simulated",
        "now": NOW.isoformat(),
        "rate_snapshot": {
            "window_started_at": NOW.isoformat(),
            "session_issues": 0,
            "phone_issues": 0,
            "network_issues": 0,
            "last_issued_at": None,
        },
    }


def test_rpc_issue_and_verify_round_trip_uses_canonical_core():
    rpc = ContactVerificationRpcFacade(pepper=PEPPER)
    issued = rpc.issue(base_payload())

    assert issued["ok"] is True
    code = issued["delivery_code"]
    assert len(code) == 6 and code.isdecimal()
    assert code not in repr(issued["challenge"])
    assert issued["challenge"]["binding"]["product_id"] == "danjion"
    assert issued["challenge"]["state"] == "pending"
    assert issued["rate_snapshot"]["session_issues"] == 1

    verified = rpc.verify({
        "challenge": issued["challenge"],
        "submitted_code": code,
        "pepper": "must-not-be-used-by-caller",
        "now": (NOW + timedelta(seconds=10)).isoformat(),
        "receipt_id": "receipt.1",
    })

    assert verified["ok"] is True
    assert verified["outcome"] == "verified"
    assert verified["challenge"]["state"] == "verified"
    assert verified["receipt"]["phone_verified"] is True
    assert verified["receipt"]["identity_assurance"] == "contact_possession_only"
    assert verified["receipt"]["legal_identity_verified"] is False


def test_rpc_replay_fails_closed():
    rpc = ContactVerificationRpcFacade(pepper=PEPPER)
    issued = rpc.issue(base_payload())
    first = rpc.verify({
        "challenge": issued["challenge"],
        "submitted_code": issued["delivery_code"],
        "now": (NOW + timedelta(seconds=10)).isoformat(),
        "receipt_id": "receipt.1",
    })
    replay = rpc.verify({
        "challenge": first["challenge"],
        "submitted_code": issued["delivery_code"],
        "now": (NOW + timedelta(seconds=20)).isoformat(),
        "receipt_id": "receipt.2",
    })

    assert replay == {
        "ok": False,
        "error": {
            "code": "replayed_contact_verification",
            "message": "verified challenge cannot be consumed twice",
        },
    }


def test_rpc_invalid_attempts_persist_and_lock():
    rpc = ContactVerificationRpcFacade(pepper=PEPPER)
    issued = rpc.issue(base_payload())
    challenge = issued["challenge"]

    for attempt in range(1, 6):
        result = rpc.verify({
            "challenge": challenge,
            "submitted_code": "000000" if issued["delivery_code"] != "000000" else "999999",
            "now": (NOW + timedelta(seconds=attempt)).isoformat(),
            "receipt_id": f"receipt.bad.{attempt}",
        })
        assert result["ok"] is True
        challenge = result["challenge"]

    assert result["outcome"] == "locked"
    assert challenge["state"] == "locked"
    assert challenge["attempts_used"] == 5
    assert result["receipt"] is None


def test_rpc_expiry_and_resend_use_canonical_state_transitions():
    rpc = ContactVerificationRpcFacade(pepper=PEPPER)
    issued = rpc.issue(base_payload())

    expired = rpc.verify({
        "challenge": issued["challenge"],
        "submitted_code": issued["delivery_code"],
        "now": (NOW + timedelta(minutes=6)).isoformat(),
        "receipt_id": "receipt.expired",
    })
    assert expired["ok"] is True
    assert expired["outcome"] == "expired"
    assert expired["challenge"]["state"] == "expired"

    resend_payload = {
        "previous_challenge": issued["challenge"],
        "new_challenge_id": "challenge.2",
        "now": (NOW + timedelta(seconds=61)).isoformat(),
        "rate_snapshot": issued["rate_snapshot"],
    }
    resent = rpc.resend(resend_payload)
    assert resent["ok"] is True
    assert resent["superseded_challenge"]["state"] == "superseded"
    assert resent["challenge"]["generation"] == 2
    assert resent["challenge"]["challenge_id"] == "challenge.2"
    assert resent["rate_snapshot"]["session_issues"] == 2


def test_rpc_rate_limit_error_is_safe_and_deterministic():
    rpc = ContactVerificationRpcFacade(pepper=PEPPER)
    payload = base_payload()
    payload["rate_snapshot"] = {
        "window_started_at": NOW.isoformat(),
        "session_issues": 5,
        "phone_issues": 0,
        "network_issues": 0,
        "last_issued_at": None,
    }
    result = rpc.issue(payload)
    assert result["ok"] is False
    assert result["error"]["code"] == "contact_verification_rate_limited"
    assert "delivery_code" not in result
