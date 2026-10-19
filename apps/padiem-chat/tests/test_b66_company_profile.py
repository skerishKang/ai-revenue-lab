"""Network-free contracts for canonical B66 CompanyProfile (#3406)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_company_profile import CompanyProfileError, canonicalize_company_profile
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="company-profile.apps.googleusercontent.com",
        google_client_secret="company-profile-google-secret",
        session_secret="company-profile-session-secret-not-real",
        live_enabled="false",
    )
class _ProfileStore:
    def __init__(self):
        self.rows = {}
        self.calls = []

    async def get_profile(self, *, user_id, workspace_id):
        self.calls.append(("get", user_id, workspace_id))
        row = self.rows.get((user_id, workspace_id))
        return dict(row) if row else None

    async def put_profile(self, *, user_id, workspace_id, profile):
        self.calls.append(("put", user_id, workspace_id))
        row = dict(profile)
        row["updatedAt"] = "2026-10-03T00:00:00+00:00"
        self.rows[(user_id, workspace_id)] = row
        return dict(row)


def _client(store, *, user_id=USER_A, signed_in=True):
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_company_profile_store=store,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
    return client
def test_partial_profile_keeps_unreviewed_fields_missing() -> None:
    profile = canonicalize_company_profile({
        "company": "Example Company",
        "representative": "Kim",
        "businessNumber": "000-00-00000",
    })
    assert profile["company"] == "Example Company"
    assert profile["representative"] == "Kim"
    assert profile["businessNumber"] == "000-00-00000"
    assert profile["contactPerson"] is None
    assert profile["address"] is None
    assert profile["phone"] is None
    assert profile["email"] is None
    assert profile["defaultValidityDays"] is None
    assert profile["defaultTaxMode"] is None


def test_profile_never_invents_7_or_30_day_default() -> None:
    profile = canonicalize_company_profile({"company": "Example Company"})
    assert profile["defaultValidityDays"] is None
    source = (ROOT / "app" / "b66_company_profile.py").read_text(encoding="utf-8")
    assert '"defaultValidityDays": 7' not in source
    assert '"defaultValidityDays": 30' not in source


@pytest.mark.parametrize("payload", [
    {},
    {"company": "Example", "workspace_id": "tenant_x"},
    {"company": "Example", "defaultValidityDays": -1},
    {"company": "Example", "defaultTaxMode": "UNKNOWN"},
])
def test_invalid_or_owner_supplied_profile_fails_closed(payload) -> None:
    with pytest.raises(CompanyProfileError):
        canonicalize_company_profile(payload)
def test_routes_are_authenticated_and_truthfully_missing() -> None:
    store = _ProfileStore()
    anonymous = _client(store, signed_in=False)
    assert anonymous.get("/api/b66/company-profile").status_code == 401
    assert anonymous.put("/api/b66/company-profile", json={"company": "X"}).status_code == 401

    owner = _client(store)
    response = owner.get("/api/b66/company-profile")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "state": "missing",
        "company_profile": None,
    }


def test_owner_can_save_partial_profile_and_foreign_owner_cannot_read_it() -> None:
    store = _ProfileStore()
    owner = _client(store, user_id=USER_A)
    response = owner.put(
        "/api/b66/company-profile",
        json={
            "company": "Example Company",
            "representative": "Kim",
            "phone": "010-0000-0000",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["company_profile"]["company"] == "Example Company"
    assert body["company_profile"]["defaultValidityDays"] is None

    readback = owner.get("/api/b66/company-profile")
    assert readback.json()["company_profile"]["phone"] == "010-0000-0000"

    other = _client(store, user_id=USER_B)
    foreign = other.get("/api/b66/company-profile")
    assert foreign.status_code == 200
    assert foreign.json()["state"] == "missing"
    assert foreign.json()["company_profile"] is None
def test_client_cannot_choose_user_or_workspace_authority() -> None:
    store = _ProfileStore()
    client = _client(store)
    for forbidden in (
        {"user_id": USER_B},
        {"workspace_id": "tenant_" + "c" * 32},
        {"tenant_id": "tenant_" + "d" * 32},
    ):
        response = client.put(
            "/api/b66/company-profile",
            json={"company": "Example Company", **forbidden},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "forbidden_owner_field"
    assert store.rows == {}


def test_migration_023_is_additive_partial_profile_schema() -> None:
    sql = (ROOT / "migrations" / "023_b66_company_profile.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_company_profile" in sql
    assert "PRIMARY KEY (user_id, workspace_id)" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "default_validity_days INTEGER" in sql
    assert "default_tax_mode TEXT" in sql
    assert "DEFAULT 7" not in sql.upper()
    assert "DEFAULT 30" not in sql.upper()
    assert "DROP TABLE" not in sql.upper()
    assert "ALTER TABLE" not in sql.upper()


def test_chat_runtime_overlays_canonical_profile_without_browser_storage_authority() -> None:
    source = (ROOT / "static" / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "companyProfileForRender" in source
    assert "interpreted.data.company_profile" in source
    assert "!Number.isInteger(profile.defaultValidityDays)" in source
    assert "companyProfile: profileResult.profile" in source
    assert "skill: effectiveSkill" not in source
    assert "copy.fixedDefaults.sender" not in source
    assert "copy.fixedDefaults.validDays" not in source
    assert "localStorage" not in source


def test_new_session_readback_same_account_and_foreign_isolation() -> None:
    """CROSS_DEVICE_COMPANY_PROFILE / FOREIGN_ACCOUNT_COMPANY_PROFILE_ACCESS=0 (#3406).

    Same canonical account, brand-new client session (device simulation):
    write via one session -> read the same profile via a fresh session.
    A foreign account gets truthful missing and cannot touch the row.
    """
    store = _ProfileStore()
    writer = _client(store, user_id=USER_A, signed_in=True)
    saved = writer.put(
        "/api/b66/company-profile",
        json={"company": "스냅샷상사", "address": "테스트시 테스트구", "phone": "02-0000-0000"},
    )
    assert saved.status_code == 200
    assert saved.json()["state"] == "ready"

    # brand-new client/session, same authenticated account
    fresh_session_reader = _client(store, user_id=USER_A, signed_in=True)
    read = fresh_session_reader.get("/api/b66/company-profile")
    assert read.status_code == 200
    payload = read.json()
    assert payload["state"] == "ready"
    assert payload["company_profile"]["company"] == "스냅샷상사"
    assert payload["company_profile"]["address"] == "테스트시 테스트구"

    # foreign account: separate session, its own workspace -> truthful missing
    foreign = _client(store, user_id=USER_B, signed_in=True)
    foreign_read = foreign.get("/api/b66/company-profile")
    assert foreign_read.status_code == 200
    assert foreign_read.json()["state"] == "missing"
    assert foreign_read.json()["company_profile"] is None

    # foreign write lands only in the foreign account's own row
    foreign_write = foreign.put(
        "/api/b66/company-profile", json={"company": "다른계정상사"}
    )
    assert foreign_write.status_code == 200
    read_again = fresh_session_reader.get("/api/b66/company-profile")
    assert read_again.json()["company_profile"]["company"] == "스냅샷상사"
    assert read_again.json()["company_profile"].get("phone") == "02-0000-0000"
