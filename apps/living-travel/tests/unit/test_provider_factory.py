"""Tests for provider factory, source governance, and pipeline integration.

All tests are network-free — the OpenAI-compatible provider receives an
injectable stub transport that never opens a real socket.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.ai.factory import create_ai_provider
from app.ai.mock import MockProvider
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.config import reset_settings
from app.domain.enums import CostClass
from app.domain.models import (
    EditionContent,
    EditorialPlan,
    ProviderResult,
)
from app.pipeline.service import GenerationService
from app.pipeline.validators import (
    validate_edition_content,
    validate_information_class_metadata,
    validate_source_references,
)


# ---------------------------------------------------------------------------
# Stub transport for network-free tests
# ---------------------------------------------------------------------------


class _StubTransport:
    def __init__(self) -> None:
        self.requests = []

    def request(self, url, data, headers, timeout):
        self.requests.append((url, data, headers))
        return self._handler(url, data, headers, timeout)


def _ok_transport(payload: dict) -> _StubTransport:
    t = _StubTransport()
    response = {
        "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    t._handler = lambda *a: (200, json.dumps(response).encode("utf-8"))
    return t


def _err_transport(status: int, body_text: str) -> _StubTransport:
    t = _StubTransport()
    t._handler = lambda *a: (status, body_text.encode("utf-8"))
    return t


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_settings():
    reset_settings()
    yield
    reset_settings()


@pytest.fixture()
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    from app.db import apply_migrations
    apply_migrations(db_path)
    # Seed a traveler
    conn.execute(
        "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("traveler-001", "Test", "Seoul", 3, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture()
def _setenv_mock():
    os.environ.setdefault("LT_AI_PROVIDER", "mock")


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactoryMockRegression:
    def test_factory_returns_mock_when_mock_selected(self, _setenv_mock):
        from app.config import get_settings

        s = get_settings()
        conn = MagicMock()
        provider = create_ai_provider(s, conn=conn, traveler_preferences={"destination": "Seoul"})
        assert isinstance(provider, MockProvider)

    def test_mock_first_edition_provider_produces_plan_and_draft(self, _setenv_mock, temp_db):
        from app.config import get_settings

        s = get_settings()
        preferences = {
            "destination": "Seoul",
            "trip_duration_nights": 3,
            "trip_context": "solo",
            "budget_tendency": "moderate",
            "pace_preference": "comfortable",
            "tone_preference": "calm",
            "length_preference": "medium",
        }
        provider = create_ai_provider(s, conn=temp_db, traveler_preferences=preferences)
        assert isinstance(provider, MockProvider)
        # The mock provider should be able to generate a plan
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="test",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="test-mock-1",
        )
        assert result.success is True
        assert result.provider == "mock"

    def test_mock_second_edition_provider_accepts_feedback(self, _setenv_mock, temp_db):
        from app.config import get_settings

        s = get_settings()
        preferences = {"destination": "Busan"}
        class _FakeFeedback:
            def __init__(self, d):
                self.id = d["feedback_id"]
                self.direction_choices = d.get("direction", [])
                self.free_text = d.get("free_text", "")
                self.traveler_id = "traveler-001"
                self.edition_id = "ed-001"
                self.feedback_direction = ""
        feedback = [_FakeFeedback({"feedback_id": "fb-1", "direction": ["quieter_places"], "free_text": "too loud"})]
        prior = {
            "content_version": "1.0",
            "publication_title": "Test",
            "edition_title": "First",
            "destination": "Busan",
            "trip_frame": "3N4D",
            "editorial_opening": "test",
            "sections": [],
        }
        provider = create_ai_provider(
            s,
            conn=temp_db,
            traveler_preferences=preferences,
            feedback_records=feedback,
            prior_content=prior,
        )
        assert isinstance(provider, MockProvider)
        result = provider.generate_structured(
            task_name="edition_draft",
            system_prompt="test",
            user_payload={},
            response_schema=EditionContent,
            request_id="test-mock-2",
        )
        assert result.success is True


class TestFactoryOpenAICompatible:
    def test_factory_returns_openai_compatible(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
            ai_timeout_seconds=30,
            ai_cost_class="free",
        )
        transport = _ok_transport({"central_theme": "test", "sections": []})
        provider = create_ai_provider(s, transport=transport)
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_openai_first_edition_path(self):
        from app.config import Settings

        plan_obj = {
            "plan_version": "1.0",
            "language": "ko",
            "central_theme": "Seoul",
            "sections": [{"section_id": "s1", "title": "t", "description": "d"}],
        }
        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        transport = _ok_transport(plan_obj)
        provider = create_ai_provider(s, transport=transport)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="plan",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="integ-001",
        )
        assert result.success is True
        assert result.payload["central_theme"] == "Seoul"
        assert len(transport.requests) == 1

    def test_openai_second_edition_path_with_prior(self):
        from app.config import Settings

        draft_obj = {
            "content_version": "1.0",
            "publication_title": "Second",
            "edition_title": "Second Edition",
            "destination": "Seoul",
            "trip_frame": "3N4D",
            "editorial_opening": "test",
            "sections": [],
        }
        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        transport = _ok_transport(draft_obj)
        provider = create_ai_provider(
            s,
            transport=transport,
            traveler_preferences={"destination": "Seoul"},
            feedback_records=[],
            prior_content=draft_obj,
        )
        result = provider.generate_structured(
            task_name="edition_draft",
            system_prompt="draft",
            user_payload={},
            response_schema=EditionContent,
            request_id="integ-002",
        )
        assert result.success is True
        assert result.payload["destination"] == "Seoul"

    def test_no_silent_fallback_to_mock(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        transport = _err_transport(500, "Internal Server Error")
        provider = create_ai_provider(s, transport=transport)
        assert isinstance(provider, OpenAICompatibleProvider)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="integ-003",
        )
        assert result.success is False
        assert result.error_category.value == "provider_error"

    def test_first_and_second_use_same_provider_type(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        payload = {"central_theme": "x", "sections": []}
        t1 = _ok_transport(payload)
        t2 = _ok_transport(payload)
        p1 = create_ai_provider(s, transport=t1)
        p2 = create_ai_provider(
            s,
            transport=t2,
            traveler_preferences={},
            feedback_records=[],
            prior_content={},
        )
        assert type(p1) is type(p2) is OpenAICompatibleProvider


class TestFactoryMissingConfig:
    def test_mock_requires_conn_and_preferences(self):
        from app.config import Settings

        s = Settings(environment="testing", ai_provider="mock")
        with pytest.raises(ValueError, match="requires conn"):
            create_ai_provider(s)

    def test_openai_compatible_missing_config_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError, match="requires"):
            Settings(
                environment="testing",
                ai_provider="openai_compatible",
                ai_api_key="sk-key",
            )


# ---------------------------------------------------------------------------
# Source governance tests
# ---------------------------------------------------------------------------


class TestSourceGovernance:
    def test_valid_source_ref_passes(self):
        content = EditionContent(
            publication_title="Test",
            edition_title="T",
            destination="Seoul",
            trip_frame="3N",
            editorial_opening="test",
            sections=[
                {
                    "section_id": "s1",
                    "title": "Section",
                    "narrative": "test",
                    "items": [
                        {
                            "item_id": "item-1",
                            "information_class": "stable_reference",
                            "source_ref": "src-001",
                        }
                    ],
                }
            ],
        )
        errors = validate_edition_content(content, valid_source_ids={"src-001"})
        assert errors == []

    def test_fabricated_source_ref_rejected(self):
        content = EditionContent(
            publication_title="Test",
            edition_title="T",
            destination="Seoul",
            trip_frame="3N",
            editorial_opening="test",
            sections=[
                {
                    "section_id": "s1",
                    "title": "Section",
                    "narrative": "test",
                    "items": [
                        {
                            "item_id": "item-1",
                            "information_class": "stable_reference",
                            "source_ref": "fake-src-999",
                        }
                    ],
                }
            ],
        )
        errors = validate_edition_content(content, valid_source_ids={"src-001", "src-002"})
        assert len(errors) == 1
        assert "Unknown source reference" in errors[0]
        assert "fake-src-999" in errors[0]

    def test_unknown_source_url_not_auto_registered(self):
        content = EditionContent(
            publication_title="Test",
            edition_title="T",
            destination="Seoul",
            trip_frame="3N",
            editorial_opening="test",
            sections=[
                {
                    "section_id": "s1",
                    "title": "Section",
                    "narrative": "test",
                    "items": [
                        {
                            "item_id": "item-1",
                            "information_class": "stable_reference",
                            "source_ref": "https://fabricated-url.example.com",
                        }
                    ],
                }
            ],
        )
        errors = validate_edition_content(content, valid_source_ids={"src-001"})
        assert len(errors) == 1
        assert "Unknown source reference" in errors[0]

    def test_time_sensitive_requires_fields(self):
        content = EditionContent(
            publication_title="Test",
            edition_title="T",
            destination="Seoul",
            trip_frame="3N",
            editorial_opening="test",
            sections=[
                {
                    "section_id": "s1",
                    "title": "Section",
                    "narrative": "test",
                    "items": [
                        {
                            "item_id": "item-ts-1",
                            "information_class": "time_sensitive",
                            "source_ref": "src-001",
                        }
                    ],
                }
            ],
        )
        errors = validate_edition_content(content, valid_source_ids={"src-001"})
        time_errors = [e for e in errors if "time_sensitive" in e]
        assert len(time_errors) > 0
        # Should error on missing as_of_date and verify_before_use

    def test_invalid_generation_not_persisted(self):
        """Simulate a provider failure in the pipeline and verify no content persists."""
        from app.config import Settings
        from app.db import apply_migrations
        from pathlib import Path
        import tempfile

        tmp = tempfile.mkdtemp()
        db_path = str(Path(tmp) / "test.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(db_path)
        conn.execute(
            "INSERT INTO travelers (id, display_name, destination, trip_duration_nights, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("tv-err", "Err", "Seoul", 3, "active", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        )
        conn.commit()

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
            allowed_origins="",
        )
        transport = _err_transport(500, "Server Error")
        provider = create_ai_provider(s, transport=transport)
        service = GenerationService(conn, provider)
        with pytest.raises(Exception):
            service.generate_first_edition(
                traveler_id="tv-err",
                traveler_preferences={"destination": "Seoul"},
                source_items=[],
            )
        from app.edition_repository import get_editions_by_traveler
        editions = get_editions_by_traveler(conn, "tv-err")
        for ed in editions:
            assert ed.generation_status != "pending_review"
        conn.close()


class TestFactoryNoSilentFallback:
    def test_openai_failure_does_not_fallback_to_mock(self):
        from app.config import Settings

        s = Settings(
            environment="testing",
            ai_provider="openai_compatible",
            ai_base_url="https://api.openai.com",
            ai_api_key="sk-test-key",
            ai_model="gpt-4o-mini",
        )
        transport = _err_transport(500, "fail")
        provider = create_ai_provider(s, transport=transport)
        assert isinstance(provider, OpenAICompatibleProvider)
        result = provider.generate_structured(
            task_name="editorial_plan",
            system_prompt="p",
            user_payload={},
            response_schema=EditorialPlan,
            request_id="nsf-001",
        )
        assert result.success is False
        assert result.provider == "openai_compatible"
        assert result.error_category.value == "provider_error"

    def test_mock_always_default(self):
        from app.config import get_settings
        s = get_settings()
        assert s.ai_provider == "mock"
        conn = MagicMock()
        provider = create_ai_provider(s, conn=conn, traveler_preferences={"destination": "x"})
        assert isinstance(provider, MockProvider)
