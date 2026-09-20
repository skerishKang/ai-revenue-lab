"""#2830 Phase A B62 connector status projection contract.

Two axes must stay separated:

- platform READ support truth, derived from the Core capability snapshots;
- per-workspace connected/authorized truth, which B62 cannot verify today,
  so every row is exactly ``workspace_state="unverified"`` with the single
  fixed reason code. Neither ``connected`` nor ``disconnected`` may be guessed.

The projection must never serialize scopes, grants, tokens, raw account or
workspace identifiers, authorization material, or SEND/WRITE tool identity.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest

from app.connector_status_projection import (
    PROJECTION_VERSION,
    WORKSPACE_REASON_NO_TRUSTED_AUTHORITY,
    WORKSPACE_STATE_UNVERIFIED,
    build_connector_status_projection,
    connectors_status,
)
from app.config import Settings
from app.main import create_app

STATUS_PATH = "/api/connectors/status"
BASE_URL = "https://chat.example.test"

TOP_LEVEL_KEYS = {
    "projection_version",
    "static_support_vs_workspace_state_separated",
    "send_write_authorized",
    "workspace_state_authority",
    "connectors",
}

ROW_KEYS = {
    "connector_id",
    "contract_version",
    "supported",
    "read_availability",
    "workspace_state",
    "workspace_reason",
    "deferred_reason",
}

# Accepted facts from the #2830 issue body.
EXPECTED_ROWS = {
    "connector:google:drive@1": ("complete", None),
    "connector:google:gmail@1": ("complete", None),
    "connector:telegram:bot@1": ("complete", None),
    "connector:slack:workspace@1": ("deferred", "slack_live_deferred"),
    "connector:google:calendar@1": ("source_ready", "calendar_source_ready_live_deferred"),
}

FORBIDDEN_TEXT = (
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "credential",
    "scope",
    "binding",
    "ticket",
    "oauth",
    "authorize",
    "client_id",
    "client_secret",
    "password",
    "bearer",
    "subject",
    "email",
    "https://",
    "connected",
    "disconnected",
)


def _client() -> httpx.AsyncClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE_URL,
        google_client_id="connector-status-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret="connector-status-session-secret-not-real-0000",
        session_max_age_seconds=3600,
    )
    app = create_app(settings)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)


def projection() -> dict[str, Any]:
    return build_connector_status_projection()


def rows_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["connector_id"]: row for row in document["connectors"]}


def test_exact_top_level_key_set():
    assert set(projection()) == TOP_LEVEL_KEYS


def test_projection_uses_core_contract_versions_not_literables():
    from padiem_ai_core.drive_capability import drive_capability_snapshot

    document = projection()
    assert document["connectors"][0]["contract_version"] == (drive_capability_snapshot()["contract_version"])


def test_exact_connector_row_shape():
    document = projection()
    assert [row["connector_id"] for row in document["connectors"]] == list(EXPECTED_ROWS)
    for row in document["connectors"]:
        assert set(row) == ROW_KEYS
        assert row["supported"] == ["read"]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY


def test_accepted_read_truth_per_connector():
    rows = rows_by_id(projection())
    for connector_id, (availability, deferred_reason) in EXPECTED_ROWS.items():
        assert rows[connector_id]["read_availability"] == availability, connector_id
        assert rows[connector_id]["deferred_reason"] == deferred_reason, connector_id


def test_workspace_axis_is_unverified_and_separated_from_support():
    document = projection()
    assert document["workspace_state_authority"] is False
    assert document["static_support_vs_workspace_state_separated"] is True
    assert all(row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED for row in document["connectors"])
    # Support truth still says Drive/Gmail/Telegram READ are complete while
    # the workspace axis remains unverified — the two axes cannot be merged.
    rows = rows_by_id(document)
    assert rows["connector:google:drive@1"]["read_availability"] == "complete"
    assert rows["connector:google:drive@1"]["workspace_state"] == "unverified"


def test_send_write_never_authorized():
    document = projection()
    assert document["send_write_authorized"] is False
    assert json.dumps(document) and "read" in json.dumps(document)
    for row in document["connectors"]:
        assert row["supported"] == ["read"]


def test_secret_raw_id_and_oauth_material_never_appear():
    serialized = json.dumps(projection()).lower()
    # The one closed-contract envelope key that names authority is itself the
    # false assertion; strip only that literal key name before the scan.
    serialized = serialized.replace("send_write_authorized", "")
    assert serialized.count('"connector:') >= 5  # canonical ids only
    for needle in FORBIDDEN_TEXT:
        assert needle not in serialized, needle


def test_repeated_builds_are_deterministic():
    first = json.dumps(build_connector_status_projection(), sort_keys=True)
    second = json.dumps(build_connector_status_projection(), sort_keys=True)
    assert first == second


def test_builder_fails_closed_when_core_read_contract_disappears(monkeypatch):
    import app.connector_status_projection as module

    broken = module.gmail_capability_snapshot()
    broken.pop("capabilities")
    monkeypatch.setattr(module, "gmail_capability_snapshot", lambda: broken)
    with pytest.raises(RuntimeError):
        build_connector_status_projection()


def test_handler_consumes_no_request_state():
    source = inspect.getsource(connectors_status)
    for needle in ("request.app", "session", "cookie", "store", "httpx", "fetch", "authorize", "scope"):
        assert needle not in source, needle
    assert "build_connector_status_projection" in source


@pytest.mark.asyncio
async def test_public_get_returns_separated_projection():
    async with _client() as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == projection()


@pytest.mark.asyncio
async def test_status_route_is_get_only_and_anonymous():
    async with _client() as client:
        post = await client.post(STATUS_PATH, json={})
        other = await client.get("/api/connectors/status/unknown")
    assert post.status_code == 405
    assert other.status_code == 404
    assert "authorization_url" not in post.text.lower()


def test_projection_version_contract():
    assert PROJECTION_VERSION == "b62-connector-status-projection.v1"
    assert projection()["projection_version"] == PROJECTION_VERSION
