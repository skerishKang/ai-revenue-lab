"""Network-free tests for durable account-bound B66 quotation history (#3405 Slice A).

Covers the server-authority contract: owner/workspace scoping, non-disclosing
cross-account behaviour, server-minted ids, bounded listing, snapshot
normalization (no raw source bytes, no persisted total authority), QuoteCore
recalculation markers and the D1 migration/store regression.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_history_store import (
    MAX_QUOTE_HISTORY_LIMIT,
    MAX_SNAPSHOT_JSON_BYTES,
    QuoteHistoryStoreError,
    normalize_quote_draft_snapshot,
    validate_row_id,
    _public_projection,
)
from app.config import Settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
WORKSPACE_A = f"owner:{USER_A}"
WORKSPACE_B = f"owner:{USER_B}"

MIGRATION = (Path(__file__).resolve().parents[1]
             / "migrations" / "025_b66_quote_history.sql")

SNAPSHOT = {
    "schema": "b66.quote-draft.v1",
    "recipient": "목포대학교",
    "projectName": "체육관 통신공사",
    "quotationNo": "CGI-2-20220621-07",
    "issueDate": "2022-06-21",
    "vatRate": 0.1,
    "items": [{"name": "통신공사", "qty": 1, "unitPrice": 88200000}],
    "sender": {"company": "(주) 시지아이", "representative": "김범신"},
}


class MemoryQuoteHistoryStore:
    """In-memory implementation of the QuoteHistoryStore protocol."""

    def __init__(self):
        self.rows: dict[tuple[str, str, str], dict] = {}
        self.calls: list[tuple] = []
        self.fail = False

    async def save_quote(self, *, user_id, workspace_id, snapshot):
        self.calls.append(("save", user_id, workspace_id))
        if self.fail:
            raise QuoteHistoryStoreError("synthetic failure")
        row_id = "b66quote_" + f"{len(self.rows):032x}"
        row = {
            "id": row_id, "user_id": user_id, "workspace_id": workspace_id,
            "quote_no": snapshot.quote_no, "issue_date": snapshot.issue_date,
            "saved_skill_id": snapshot.saved_skill_id,
            "skill_fingerprint": snapshot.skill_fingerprint,
            "snapshot_json": snapshot.serialized_json,
            "sender_json": snapshot.sender_json,
            "created_at": "2026-10-07T00:00:00.000Z",
            "updated_at": "2026-10-07T00:00:00.000Z",
        }
        self.rows[(user_id, workspace_id, row_id)] = row
        return _projection(row, include_snapshot=True)

    async def list_quotes(self, *, user_id, workspace_id, limit=MAX_QUOTE_HISTORY_LIMIT):
        self.calls.append(("list", user_id, workspace_id))
        if self.fail:
            raise QuoteHistoryStoreError("synthetic failure")
        bounded = max(1, min(int(limit), MAX_QUOTE_HISTORY_LIMIT))
        owned = [r for (u, w, _), r in self.rows.items()
                 if (u, w) == (user_id, workspace_id)]
        owned.sort(key=lambda r: r["updated_at"], reverse=True)
        return [_projection(r, include_snapshot=False) for r in owned[:bounded]]

    async def get_quote(self, *, user_id, workspace_id, quote_history_id):
        self.calls.append(("get", user_id, workspace_id))
        if self.fail:
            raise QuoteHistoryStoreError("synthetic failure")
        row = self.rows.get((user_id, workspace_id, quote_history_id))
        return _projection(row, include_snapshot=True) if row else None

    async def delete_quote(self, *, user_id, workspace_id, quote_history_id):
        self.calls.append(("delete", user_id, workspace_id))
        if self.fail:
            raise QuoteHistoryStoreError("synthetic failure")
        if (user_id, workspace_id, quote_history_id) not in self.rows:
            return False
        del self.rows[(user_id, workspace_id, quote_history_id)]
        return True


def _projection(row, *, include_snapshot):
    projected = {
        "quote_history_id": row["id"],
        "quote_no": row["quote_no"],
        "issue_date": row["issue_date"],
        "saved_skill_id": row["saved_skill_id"],
        "skill_fingerprint": row["skill_fingerprint"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "totals_authority": "quote-core",
        "quote_core_recalculation_required": True,
    }
    if include_snapshot:
        projected["snapshot"] = json.loads(row["snapshot_json"])
        if row["sender_json"]:
            projected["sender"] = json.loads(row["sender_json"])
    return projected


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="hist.apps.googleusercontent.com",
        google_client_secret="hist-google-secret",
        session_secret="hist-session-secret-not-real-000000",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _client(*, user_id=USER_A, signed_in=True, store=None):
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_quote_history_store=store or MemoryQuoteHistoryStore(),
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


# ── snapshot normalization ──────────────────────────────────────────────

def test_snapshot_normalization_is_deterministic_and_server_minted():
    first = normalize_quote_draft_snapshot(SNAPSHOT)
    second = normalize_quote_draft_snapshot(dict(reversed(list(SNAPSHOT.items()))))
    assert first.serialized_json == second.serialized_json
    assert first.quote_no == "CGI-2-20220621-07"
    assert first.sender_json is not None
    # sender snapshot is preserved for historical stability
    assert json.loads(first.sender_json)["company"] == "(주) 시지아이"


def test_computed_totals_are_never_persisted_as_authority():
    payload = dict(SNAPSHOT)
    payload.update({"subtotal": 88200000, "vat": 8820000, "grandTotal": 97020000,
                    "total": 97020000})
    normalized = normalize_quote_draft_snapshot(payload)
    stored = json.loads(normalized.serialized_json)
    for key in ("subtotal", "vat", "grandTotal", "total"):
        assert key not in stored
    # the record itself declares QuoteCore as the only total authority
    assert _projection({"id": "b66quote_" + "0" * 32, "quote_no": None,
                        "issue_date": None, "saved_skill_id": None,
                        "skill_fingerprint": None,
                        "snapshot_json": normalized.serialized_json,
                        "sender_json": normalized.sender_json,
                        "created_at": "", "updated_at": ""},
                       include_snapshot=True)["totals_authority"] == "quote-core"


@pytest.mark.parametrize("key", ["xlsx", "pdfBytes", "sourceFile", "rawBytes",
                                 "rendererHtml", "modelPayload", "apiKey",
                                 "credentials", "base64"])
def test_raw_source_and_secret_payloads_are_rejected(key):
    payload = dict(SNAPSHOT)
    payload[key] = "QUJD"
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(payload)


def test_malformed_snapshot_rejected():
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(["not", "an", "object"])
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot({"items": "not-a-list"})
    huge = dict(SNAPSHOT)
    huge["memo"] = "가" * (MAX_SNAPSHOT_JSON_BYTES)
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(huge)


def test_row_id_shape_is_bounded():
    assert validate_row_id("b66quote_" + "a" * 32).startswith("b66quote_")
    for bad in ("", "b66quote_short", "b66asset_" + "a" * 32, None, 12):
        with pytest.raises(QuoteHistoryStoreError):
            validate_row_id(bad)


# ── routes ──────────────────────────────────────────────────────────────

def test_route_requires_login():
    anonymous = _client(signed_in=False)
    assert anonymous.get("/api/b66/quotes").status_code == 401
    assert anonymous.post("/api/b66/quotes", json=SNAPSHOT).status_code == 401
    assert anonymous.get("/api/b66/quotes/b66quote_" + "a" * 32).status_code == 401
    assert anonymous.delete("/api/b66/quotes/b66quote_" + "a" * 32).status_code == 401


def test_own_quote_round_trip_is_server_minted_and_scoped():
    store = MemoryQuoteHistoryStore()
    client = _client(store=store)

    created = client.post("/api/b66/quotes", json=SNAPSHOT)
    assert created.status_code == 201
    quote = created.json()["quote"]
    row_id = quote["quote_history_id"]
    assert row_id.startswith("b66quote_")
    assert quote["quote_core_recalculation_required"] is True
    assert quote["totals_authority"] == "quote-core"
    # server-minted: the client never supplies the id
    assert "quote_history_id" not in SNAPSHOT

    listed = client.get("/api/b66/quotes?limit=5")
    assert listed.status_code == 200
    assert [q["quote_history_id"] for q in listed.json()["quotes"]] == [row_id]

    got = client.get(f"/api/b66/quotes/{row_id}")
    assert got.status_code == 200
    assert got.json()["quote"]["snapshot"]["recipient"] == "목포대학교"

    deleted = client.delete(f"/api/b66/quotes/{row_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/b66/quotes/{row_id}").status_code == 404


def test_foreign_account_and_workspace_are_non_disclosing():
    store = MemoryQuoteHistoryStore()
    owner = _client(store=store)
    row_id = owner.post("/api/b66/quotes", json=SNAPSHOT).json()["quote"]["quote_history_id"]

    # another account on the same browser
    other = _client(user_id=USER_B, store=store)
    assert other.get("/api/b66/quotes").json()["quotes"] == []
    assert other.get(f"/api/b66/quotes/{row_id}").status_code == 404
    assert other.delete(f"/api/b66/quotes/{row_id}").status_code == 404
    # the owner's record survives the foreign delete attempt
    assert owner.get(f"/api/b66/quotes/{row_id}").status_code == 200

    # the same account with a different workspace is equally non-disclosing
    assert store.rows.get((USER_A, WORKSPACE_A, row_id)) is not None
    assert store.rows.get((USER_A, WORKSPACE_B, row_id)) is None


def test_client_supplied_owner_is_rejected():
    store = MemoryQuoteHistoryStore()
    client = _client(store=store)
    for key in ("userId", "user_id", "owner", "workspace_id", "workspaceId", "tenant"):
        payload = dict(SNAPSHOT)
        payload[key] = USER_B
        response = client.post("/api/b66/quotes", json=payload)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "client_owner_not_allowed"
    assert not [c for c in store.calls if c[0] == "save"]


def test_list_limit_is_bounded():
    store = MemoryQuoteHistoryStore()
    client = _client(store=store)
    for _ in range(3):
        client.post("/api/b66/quotes", json=SNAPSHOT)

    assert len(client.get("/api/b66/quotes?limit=2").json()["quotes"]) == 2
    huge = client.get("/api/b66/quotes?limit=100000")
    assert huge.status_code == 200
    assert huge.json()["limit"] == MAX_QUOTE_HISTORY_LIMIT
    assert client.get("/api/b66/quotes?limit=not-a-number").json()["limit"] == \
        MAX_QUOTE_HISTORY_LIMIT


def test_store_failure_is_reported_without_disclosure():
    store = MemoryQuoteHistoryStore()
    store.fail = True
    client = _client(store=store)
    response = client.get("/api/b66/quotes")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "quote_history_read_failed"


# ── previously persisted malformed detail cannot trigger Worker 1101 ──────

@pytest.mark.parametrize("snapshot_json,sender_json", [
    ('{"items":[],"unitPrice":NaN}', None),
    ('{"items":[],"note":"\\ud800"}', None),
    ('{"items":[]}', '{"company":Infinity}'),
    ('{"items":[]}', 'not-json'),
    ('["not-a-quote"]', None),
])
def test_malformed_persisted_detail_returns_bounded_error(snapshot_json, sender_json):
    """A poisoned historical row must not escape JSONResponse as an unhandled 500.

    No live D1 mutation, no customer data read, no accidental other-owner response.
    """
    row_id = "b66quote_" + "d" * 32

    class MalformedDetailStore(MemoryQuoteHistoryStore):
        async def get_quote(self, *, user_id, workspace_id, quote_history_id):
            if user_id != USER_A or workspace_id != WORKSPACE_A or quote_history_id != row_id:
                return None
            return _public_projection({
                "id": row_id, "quote_no": "SYNTHETIC", "issue_date": "2026-10-09",
                "saved_skill_id": None, "skill_fingerprint": None,
                "created_at": "2026-10-09T00:00:00Z", "updated_at": "2026-10-09T00:00:00Z",
                "snapshot_json": snapshot_json, "sender_json": sender_json,
            }, include_snapshot=True)

    client = _client(store=MalformedDetailStore())
    result = client.get(f"/api/b66/quotes/{row_id}")
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "quote_history_read_failed"
    assert "SYNTHETIC" not in result.text


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "\ud800"])
def test_new_snapshot_cannot_persist_non_json_number_or_invalid_unicode(value):
    unsafe = dict(SNAPSHOT)
    unsafe["memo"] = value
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(unsafe)

    unsafe_sender = dict(SNAPSHOT)
    unsafe_sender["sender"] = {"company": value}
    with pytest.raises(QuoteHistoryStoreError):
        normalize_quote_draft_snapshot(unsafe_sender)


# ── migration regression ────────────────────────────────────────────────

def test_migration_declares_owner_scoped_table_without_total_columns():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_quote_history" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "user_id TEXT NOT NULL" in sql
    assert "workspace_id TEXT NOT NULL" in sql
    assert "snapshot_json TEXT NOT NULL" in sql
    assert "idx_b66_quote_history_owner_workspace_updated" in sql
    # a stored record must not carry a computed total column
    columns = re.findall(r"^\s{4}([a-z_]+) ", sql, flags=re.MULTILINE)
    for forbidden in ("subtotal", "vat", "grand_total", "total"):
        assert forbidden not in columns
    # no DDL beyond the bounded table/index pair
    assert sql.count("CREATE TABLE") == 1
    assert sql.count("CREATE INDEX") == 1
