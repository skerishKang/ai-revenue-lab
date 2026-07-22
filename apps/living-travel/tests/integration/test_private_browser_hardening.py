"""Focused browser acceptance tests for private workflow hardening."""

from __future__ import annotations

import copy
import os
import re
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.config import get_settings, reset_settings
from app.db import get_connection
from app.edition_repository import (
    get_edition_by_id,
    get_editions_by_traveler,
    update_edition_content,
)
from app.factory import create_app
from app.feedback_repository import get_feedback_by_edition
from app.security import reset_login_rate_limiter
from app.traveler_repository import get_traveler_by_id


@pytest.fixture()
def app(tmp_path: Path):
    reset_settings()
    reset_login_rate_limiter()
    os.environ["LT_DATABASE_URL"] = str(tmp_path / "hardening.db")
    os.environ["LT_OPERATOR_SECRET"] = "test-secret-12345"
    reset_settings()
    application = create_app()
    yield application
    reset_settings()
    reset_login_rate_limiter()


def _operator_login(client: TestClient) -> None:
    client.get("/operator/login")
    csrf = client.cookies.get("lt_csrf") or ""
    secret = getattr(get_settings(), "operator_secret", "test-secret-12345")
    response = client.post(
        "/operator/login",
        data={"secret": secret, "csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code in (200, 303)


def _operator_csrf(client: TestClient) -> str:
    response = client.get("/operator/")
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def _create_traveler(client: TestClient, name: str, destination: str) -> str:
    csrf = _operator_csrf(client)
    response = client.post(
        "/operator/travelers/create",
        data={
            "display_name": name,
            "destination": destination,
            "trip_duration_nights": 3,
            "csrf_token": csrf,
        },
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code in (200, 303)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM travelers WHERE display_name = ?",
            (name,),
        ).fetchone()
        assert row is not None
        return row["id"]
    finally:
        conn.close()


def _issue_token(client: TestClient, traveler_id: str) -> str:
    csrf = _operator_csrf(client)
    response = client.post(
        f"/operator/travelers/{traveler_id}/invite",
        data={"csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code == 200
    match = re.search(r'class="token-value">([A-Za-z0-9_-]+)<', response.text)
    assert match is not None
    return match.group(1)


def _traveler_login(client: TestClient, token: str) -> str:
    client.get("/traveler/enter")
    csrf = client.cookies.get("lt_csrf") or ""
    response = client.post(
        "/traveler/enter",
        data={"token": token, "csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code in (200, 303)

    dashboard = client.get("/traveler/")
    assert dashboard.status_code == 200
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', dashboard.text)
    assert match is not None
    return match.group(1)


def _generate_first(client: TestClient, traveler_id: str) -> None:
    csrf = _operator_csrf(client)
    response = client.post(
        f"/operator/travelers/{traveler_id}/generate-first",
        data={"csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code in (200, 303)


def _traveler_preferences_snapshot(traveler) -> tuple:
    return (
        traveler.destination,
        traveler.trip_duration_nights,
        traveler.trip_context,
        traveler.budget_tendency,
        traveler.pace_preference,
        tuple(traveler.interests),
        tuple(traveler.exclusions),
        traveler.tone_preference,
        traveler.length_preference,
        traveler.preferred_language,
    )


def test_operator_preview_renders_nested_item_provenance(app):
    client = TestClient(app, follow_redirects=False)
    _operator_login(client)
    traveler_id = _create_traveler(client, "PreviewHardening", "부산")
    _generate_first(client, traveler_id)

    conn = get_connection()
    try:
        edition = get_editions_by_traveler(conn, traveler_id)[0]
        content = copy.deepcopy(edition.structured_content)
    finally:
        conn.close()

    response = client.get(f"/operator/editions/{edition.id}")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert "Information Class" in response.text
    assert "Source Reference" in response.text
    assert "As Of Date" in response.text
    assert "Confidence" in response.text
    assert "Verify Before Use" in response.text

    for section in content["sections"]:
        assert section["title"] in response.text
        assert section["narrative"] in response.text
        for item in section["items"]:
            assert item["item_id"] in response.text
            assert item["information_class"] in response.text
            assert item["source_ref"] in response.text
            assert item["confidence"] in response.text
            if item["as_of_date"]:
                assert item["as_of_date"] in response.text


def test_preferences_fail_closed_without_partial_save(app):
    client = TestClient(app, follow_redirects=False)
    _operator_login(client)
    traveler_id = _create_traveler(client, "PreferenceHardening", "부산")
    token = _issue_token(client, traveler_id)
    csrf = _traveler_login(client, token)

    valid_payload = {
        "destination": "서울",
        "trip_duration_nights": 4,
        "trip_context": "couple",
        "budget_tendency": "premium",
        "pace_preference": "relaxed",
        "interests": "미술관, 로컬 음식",
        "exclusions": "야간 유흥",
        "tone_preference": "luxury",
        "length_preference": "long",
        "preferred_language": "ko",
        "csrf_token": csrf,
    }
    response = client.post(
        "/traveler/preferences",
        data=valid_payload,
        cookies={"lt_csrf": csrf},
    )
    assert response.status_code == 303

    conn = get_connection()
    try:
        baseline = _traveler_preferences_snapshot(
            get_traveler_by_id(conn, traveler_id)
        )
    finally:
        conn.close()

    invalid_payloads = [
        {**valid_payload, "destination": "변경되면 안 됨", "trip_context": "invalid"},
        {**valid_payload, "destination": "변경되면 안 됨", "trip_duration_nights": 31},
        {**valid_payload, "destination": "<script>alert(1)</script>"},
        {
            **valid_payload,
            "destination": "변경되면 안 됨",
            "interests": ",".join(f"interest-{index}" for index in range(13)),
        },
        {
            **valid_payload,
            "destination": "변경되면 안 됨",
            "exclusions": "x" * 81,
        },
    ]

    for payload in invalid_payloads:
        response = client.post(
            "/traveler/preferences",
            data=payload,
            cookies={"lt_csrf": csrf},
        )
        assert response.status_code == 422
        assert "Preferences not saved" in response.text
        assert "<script>" not in response.text

        conn = get_connection()
        try:
            current = _traveler_preferences_snapshot(
                get_traveler_by_id(conn, traveler_id)
            )
        finally:
            conn.close()
        assert current == baseline


def test_second_edition_starts_from_persisted_prior_content(app):
    client = TestClient(app, follow_redirects=False)
    _operator_login(client)
    traveler_id = _create_traveler(client, "ContinuityHardening", "부산")
    token = _issue_token(client, traveler_id)
    _generate_first(client, traveler_id)

    conn = get_connection()
    try:
        first = get_editions_by_traveler(conn, traveler_id)[0]
        first_content = copy.deepcopy(first.structured_content)
        continuity_section_id = first_content["sections"][0]["section_id"]
        marker = "PERSISTED-CONTINUITY-MARKER-43"
        first_content["sections"][0]["narrative"] += f" {marker}"
        update_edition_content(conn, first.id, first_content)
    finally:
        conn.close()

    csrf = _operator_csrf(client)
    publish_response = client.post(
        f"/operator/editions/{first.id}/publish",
        data={"csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert publish_response.status_code in (200, 303)

    traveler_csrf = _traveler_login(client, token)
    feedback_response = client.post(
        f"/traveler/editions/{first.id}/feedback",
        data={
            "choices": ["lower_budget"],
            "free_text": "예산 섹션만 보강해 주세요.",
            "csrf_token": traveler_csrf,
        },
        cookies={"lt_csrf": traveler_csrf},
    )
    assert feedback_response.status_code in (200, 303)

    csrf = _operator_csrf(client)
    second_response = client.post(
        f"/operator/travelers/{traveler_id}/generate-second",
        data={"csrf_token": csrf},
        cookies={"lt_csrf": csrf},
    )
    assert second_response.status_code in (200, 303)

    conn = get_connection()
    try:
        editions = get_editions_by_traveler(conn, traveler_id)
        assert len(editions) == 2
        persisted_first = get_edition_by_id(conn, first.id)
        second = editions[1]

        prior_sections = {
            section["section_id"]: section
            for section in persisted_first.structured_content["sections"]
        }
        second_sections = {
            section["section_id"]: section
            for section in second.structured_content["sections"]
        }

        assert marker in prior_sections[continuity_section_id]["narrative"]
        assert (
            second_sections[continuity_section_id]["narrative"]
            == prior_sections[continuity_section_id]["narrative"]
        )
        assert "sec_budget" in second_sections
        assert "sec_budget" not in prior_sections

        applied = second.structured_content["applied_feedback"]
        assert len(applied) == 1
        assert applied[0]["affected_section_ids"] == ["sec_budget"]

        feedback = get_feedback_by_edition(conn, first.id)
        assert len(feedback) == 1
        assert feedback[0].applied_to_next_edition is True
    finally:
        conn.close()


def test_deactivation_request_has_database_level_pending_uniqueness(app):
    client = TestClient(app, follow_redirects=False)
    _operator_login(client)
    traveler_id = _create_traveler(client, "DeactivateHardening", "부산")
    token = _issue_token(client, traveler_id)
    csrf = _traveler_login(client, token)

    for _ in range(2):
        response = client.post(
            "/traveler/deactivation-request",
            data={"csrf_token": csrf},
            cookies={"lt_csrf": csrf},
        )
        assert response.status_code == 303

    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM deactivation_requests "
            "WHERE traveler_id = ? AND status = 'pending'",
            (traveler_id,),
        ).fetchone()[0]
        assert count == 1

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO deactivation_requests "
                "(id, traveler_id, status, created_at, updated_at) "
                "VALUES ('dr_duplicate', ?, 'pending', datetime('now'), datetime('now'))",
                (traveler_id,),
            )
        conn.rollback()
    finally:
        conn.close()

    reopened = get_connection()
    try:
        count_after_reopen = reopened.execute(
            "SELECT COUNT(*) FROM deactivation_requests "
            "WHERE traveler_id = ? AND status = 'pending'",
            (traveler_id,),
        ).fetchone()[0]
        assert count_after_reopen == 1
    finally:
        reopened.close()

    dashboard = client.get("/traveler/")
    assert dashboard.status_code == 200
    assert "A pending request is recorded" in dashboard.text
