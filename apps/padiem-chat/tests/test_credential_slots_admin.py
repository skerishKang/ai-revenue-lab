"""Owner-only credential-slot board: authority, closed failures, no key values.

The B14 side already reports derived metadata only. These tests prove the Chat
edge is not a second path out of that: the existing global-admin check runs
before any upstream call, every failure stays a closed code, and the response
is rebuilt from an allowlist so even a regressed B14 payload cannot carry a
credential into the browser.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.b14_slot_status_source import (
    PROOF_UNCONFIGURED,
    REFUSED,
    SlotStatusUnavailable,
)
from app.config import Settings
from app.main import create_app

BASE = "https://chat.test"
AGNES_KEY = "sk-synthetic-agnes-0123456789-wxyz"
GOOGLE_KEY = "AIza-synthetic-google-abcdefghij-zsug"


class GlobalAdmin:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls: list[str] = []

    async def is_global_model_admin(self, *, user_id: str):
        self.calls.append(user_id)
        return self.allowed


class Source:
    def __init__(self, payload=None, *, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


def _slot(number: int, *, providers=None, configured=False, state="empty",
          length=None, last4=None, extra=None):
    row = {
        "slot": f"PADIEM_B14_CREDENTIAL_{number:02d}",
        "slot_number": number,
        "provider_ids": list(providers or []),
        "configured": configured,
        "state": state,
        "state_detail": "",
        "length": length,
        "last4": last4,
        "file_modified_at": "2026-11-02T09:00:00+09:00" if configured else None,
        "file_modified_source": "secret_file" if configured else "none",
        "last_success_at": "2026-11-02T08:30:00+09:00" if configured else None,
        "recent_error_codes": (
            [{"code": "provider_timeout", "count": 2}] if configured else []
        ),
    }
    if extra:
        row.update(extra)
    return row


def _payload(*, slots=None, ledger=None, registry="loaded", extra=None):
    payload = {
        "slots": slots if slots is not None else [
            _slot(1, providers=["agnes-ai"], configured=True,
                  length=len(AGNES_KEY), last4=AGNES_KEY[-4:]),
            _slot(2, providers=["atria"]),
            _slot(3),
            _slot(4, providers=["experiential"]),
            _slot(5, providers=["google"], configured=True,
                  length=len(GOOGLE_KEY), last4=GOOGLE_KEY[-4:]),
            _slot(6, providers=["inception"]),
            _slot(7),
            _slot(8),
            _slot(9, providers=["kira"]),
            _slot(10, providers=["modelscope"]),
            _slot(11, providers=["opencode-go"]),
            _slot(12, providers=["poolside"]),
            _slot(13, providers=["tokenharbor"]),
            _slot(14, providers=["zanslab"]),
        ],
        "ledger": ledger or {"state": "bound", "error_window_hours": 168},
        "registry": registry,
        "generated_at": "2026-11-02T09:00:00+00:00",
    }
    if extra:
        payload.update(extra)
    return payload


def built_app(*, admin="default", source="absent"):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="credential-slots-admin-test-session-secret",
        session_max_age_seconds=3600,
    )
    if admin == "default":
        admin = GlobalAdmin()
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=admin,
    )
    if source != "absent":
        app.state.b14_slot_status_source = source
    return app, settings


def request(app, settings, path="/api/admin/credential-slots", *, owner="usr_slots_owner"):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if owner is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner))
            return await client.get(path)
    return asyncio.run(inner())


def test_anonymous_is_rejected_before_any_upstream_call():
    source = Source(_payload())
    app, settings = built_app(source=source)
    response = request(app, settings, owner=None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert source.calls == 0


def test_non_owner_is_forbidden_before_any_upstream_call():
    source = Source(_payload())
    app, settings = built_app(admin=GlobalAdmin(False), source=source)
    response = request(app, settings)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "global_model_admin_forbidden"
    assert source.calls == 0


def test_unconfigured_authorizer_is_not_treated_as_owner():
    source = Source(_payload())
    app, settings = built_app(admin=None, source=source)
    response = request(app, settings)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "central_admin_not_configured"
    assert source.calls == 0


def test_missing_source_is_reported_not_empty():
    app, settings = built_app(source="absent")
    response = request(app, settings)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "credential_slots_unavailable"


def test_upstream_failure_keeps_its_closed_code():
    app, settings = built_app(source=Source(error=SlotStatusUnavailable(REFUSED)))
    response = request(app, settings)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == REFUSED


def test_upstream_proof_failure_is_distinct():
    app, settings = built_app(source=Source(error=SlotStatusUnavailable(PROOF_UNCONFIGURED)))
    response = request(app, settings)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == PROOF_UNCONFIGURED


def test_unexpected_source_exception_is_not_echoed():
    app, settings = built_app(source=Source(error=RuntimeError("https://b14.internal leak")))
    response = request(app, settings)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "credential_slots_unavailable"
    assert "b14.internal" not in response.text


@pytest.mark.parametrize("payload", [
    None,
    [],
    {"slots": [], "ledger": {"state": "bound", "error_window_hours": 168}},
    {"slots": [{"slot": "not-a-slot"}], "ledger": {"state": "bound", "error_window_hours": 168}},
])
def test_malformed_upstream_payload_is_rejected(payload):
    app, settings = built_app(source=Source(payload))
    response = request(app, settings)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "credential_slots_invalid_response"


def test_success_shape_and_ledger():
    app, settings = built_app(source=Source(_payload()))
    response = request(app, settings)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    body = response.json()
    assert body["ok"] is True
    assert len(body["slots"]) == 14
    assert [row["slot_number"] for row in body["slots"]] == list(range(1, 15))
    assert [row["provider_ids"] for row in body["slots"]][:5] == [
        ["agnes-ai"], ["atria"], [], ["experiential"], ["google"],
    ]
    assert body["ledger"] == {"state": "bound", "error_window_hours": 168}
    assert body["registry"] == "loaded"
    assert body["generated_at"] == "2026-11-02T09:00:00+00:00"
    first = body["slots"][0]
    assert first["configured"] is True
    assert first["length"] == len(AGNES_KEY)
    assert first["last4"] == AGNES_KEY[-4:]
    assert first["file_modified_source"] == "secret_file"
    assert first["last_success_at"] == "2026-11-02T08:30:00+09:00"
    assert first["recent_error_codes"] == [{"code": "provider_timeout", "count": 2}]


def test_allowlist_strips_extra_fields_from_upstream():
    slots = _payload()["slots"]
    slots[0] = _slot(
        1, providers=["agnes-ai"], configured=True,
        length=len(AGNES_KEY), last4=AGNES_KEY[-4:],
        extra={"key_value": AGNES_KEY, "credential": AGNES_KEY},
    )
    payload = _payload(
        slots=slots,
        extra={"upstream_secret": AGNES_KEY, "raw": {"key": AGNES_KEY}},
    )
    app, settings = built_app(source=Source(payload))
    response = request(app, settings)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "slots", "ledger", "registry", "generated_at"}
    assert set(body["slots"][0]) == {
        "slot", "slot_number", "provider_ids", "configured", "state",
        "state_detail", "length", "last4", "file_modified_at",
        "file_modified_source", "last_success_at", "recent_error_codes",
    }
    assert "key_value" not in response.text
    assert "upstream_secret" not in response.text


@pytest.mark.parametrize("secret", [AGNES_KEY, GOOGLE_KEY])
def test_key_values_never_appear_in_the_response(secret, caplog):
    caplog.set_level("DEBUG")
    app, settings = built_app(source=Source(_payload()))
    response = request(app, settings)
    assert response.status_code == 200
    text = response.text
    for needle in (secret, secret[:-4], secret[:8]):
        assert needle not in text
    for record in caplog.records:
        assert secret not in record.getMessage()
    assert secret[-4:] in text


def test_invalid_state_row_rejects_the_whole_board():
    slots = _payload()["slots"]
    slots[2] = _slot(3, state="secret_value_leaked")
    app, settings = built_app(source=Source(_payload(slots=slots)))
    response = request(app, settings)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "credential_slots_invalid_response"


def test_static_screen_is_a_separate_asset():
    from pathlib import Path

    static = Path(__file__).parents[1] / "static"
    page = (static / "credential-slots.html").read_text(encoding="utf8")
    script = (static / "credential-slots.js").read_text(encoding="utf8")
    assert "./credential-slots.js" in page
    assert "./credential-slots.css" in page
    assert '"/api/admin/credential-slots"' in script
    assert "app.js" not in script


def test_screen_is_served_at_the_static_path():
    app, settings = built_app(source="absent")
    response = request(app, settings, "/credential-slots.html", owner=None)
    assert response.status_code == 200
    assert "키 슬롯 상태" in response.text
    assert "./credential-slots.js" in response.text


def test_existing_admin_pages_link_to_the_screen():
    from pathlib import Path

    static = Path(__file__).parents[1] / "static"
    for name in ("admin.html", "admin-models.html"):
        page = (static / name).read_text(encoding="utf8")
        assert 'href="./credential-slots.html"' in page
