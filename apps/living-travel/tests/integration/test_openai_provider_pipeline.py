"""Integration tests for generation pipeline using OpenAICompatibleProvider.

All tests are network-free — a sequence stub transport replaces the real HTTP
client so no socket is ever opened.  The stub returns pre-configured responses
in order; the last response repeats indefinitely to support the service's retry
loop.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.openai_compatible import OpenAICompatibleProvider
from app.db import apply_migrations, get_connection
from app.domain.enums import EditionGenerationStatus
from app.edition_repository import get_edition_by_id, get_editions_by_traveler
from app.feedback_repository import create_feedback
from app.generation_run_repository import count_generation_runs_by_edition
from app.pipeline.errors import PipelineError
from app.pipeline.service import GenerationService
from app.source_repository import create_source
from app.traveler_repository import create_traveler

# The OpenAICompatibleProvider has attempt_limit=1, so the service makes exactly
# ONE outbound transport call per task (plan or draft).  The stub sequences below
# reflect this — one response per task, with the last response repeating if the
# service loop needed more (but with attempt_limit=1 it never does).

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIRST_PLAN = {
    "plan_version": "1.0",
    "language": "ko",
    "central_theme": "부산 동네 산책",
    "sections": [
        {"section_id": "sec_morning_gukje", "title": "국제시장 근처", "description": "아침 산책"},
        {"section_id": "sec_haegyeolri", "title": "합성동", "description": "로컬 카페"},
        {"section_id": "sec_practical", "title": "실용 정보", "description": "날씨와 이동"},
    ],
}

SECOND_PLAN = {
    "plan_version": "1.0",
    "language": "ko",
    "central_theme": "부산 조용한 로컬",
    "sections": [
        {"section_id": "sec_quiet_morning", "title": "조용한 아침", "description": "아침 산책"},
        {"section_id": "sec_local_food", "title": "로컬 밥상", "description": "음식"},
        {"section_id": "sec_low_effort", "title": "적은 이동", "description": "코스"},
    ],
}


class _SequenceStub:
    """Stub transport that returns pre-configured responses in sequence.

    Each call advances one step.  The last response repeats indefinitely so
    the service retry loop always gets a consistent answer.  ``requests``
    captures every call for post-hoc assertions.
    """

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self._responses = list(responses)
        self.call_count: int = 0
        self.requests: list[tuple[str, bytes, dict[str, str]]] = []

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        self.requests.append((url, data, headers))
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        status, body = self._responses[idx]
        if isinstance(body, dict):
            envelope = {
                "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 100},
            }
            return (status, json.dumps(envelope).encode("utf-8"))
        raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
        return (status, raw)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def _make_provider(
    stub: _SequenceStub,
    **overrides: object,
) -> OpenAICompatibleProvider:
    kwargs: dict = {
        "base_url": "http://localhost:11434/v1/chat/completions",
        "api_key": "sk-test-placeholder",
        "model": "gpt-4o-mini",
        "timeout_seconds": 30,
        "transport": stub,
        "environment": "testing",
    }
    kwargs.update(overrides)
    return OpenAICompatibleProvider(**kwargs)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


@pytest.fixture
def busan_sources(conn):
    sources = []
    for src in _load_fixture("busan_solo_traveler.json")["sources"]:
        s = create_source(
            conn,
            source_url=src["source_url"],
            publisher=src["publisher"],
            source_type=src["source_type"],
            destination=src["destination"],
            locality=src.get("locality", ""),
            category=src["category"],
            claims=src.get("claims", []),
            confidence=src.get("confidence", "approximate"),
            publication_date=src.get("publication_date", ""),
            access_date=src.get("access_date", ""),
        )
        sources.append(s)
    return sources


@pytest.fixture
def traveler(conn):
    prefs = _load_fixture("busan_solo_traveler.json")["traveler"]
    prefs["display_name"] = "Busan Solo Tester"
    return create_traveler(conn, **prefs)


@pytest.fixture
def source_dicts():
    return [
        {
            "source_id": "src_busan_tourism",
            "publisher": "부산관광공사",
            "category": "destination_overview",
            "claims": [
                "부산은 한국 제2의 도시",
                "해운대와 광안리가 대표 해수욕장",
                "item_weather_note",
            ],
        },
        {
            "source_id": "src_gukje_market",
            "publisher": "부산 중구청",
            "category": "market",
            "claims": [
                "국제시장은 1950년대 전후부터 형성된 시장",
                "원조 식당가가 있음",
                "item_gukje_atmosphere",
                "item_gukje_hours",
                "item_solo_dining",
            ],
        },
        {
            "source_id": "src_haegyeolri",
            "publisher": "부산남구청",
            "category": "neighborhood",
            "claims": [
                "합성동은 로컬 분위기가 남아있는 동네",
                "조용한 카페와 식당이 있음",
                "item_haegyeolri_vibe",
            ],
        },
    ]


# ---------------------------------------------------------------------------
# First-edition pipeline
# ---------------------------------------------------------------------------


class TestFirstEditionWithOpenAIProvider:
    def test_generates_pending_review(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        draft_fixture = _load_fixture("source_bundle.json")["first_edition_fixture"]
        stub = _SequenceStub([
            (200, FIRST_PLAN),
            (200, draft_fixture),
        ])
        provider = _make_provider(stub)
        service = GenerationService(conn, provider)

        content = service.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산", "interests": ["food"]},
            source_items=source_dicts,
        )

        assert content.publication_title
        assert len(content.sections) == 3

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 1
        assert editions[0].generation_status == EditionGenerationStatus.pending_review

        runs = count_generation_runs_by_edition(conn, editions[0].id)
        assert runs == 2

    def test_plan_failure_exhausts_attempts(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        stub = _SequenceStub([
            (500, "internal server error"),
        ])
        provider = _make_provider(stub)
        service = GenerationService(conn, provider)

        with pytest.raises(PipelineError, match="Plan generation failed"):
            service.generate_first_edition(
                traveler_id=traveler.id,
                input_id=None,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

        assert stub.call_count == 1

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 0

        runs = count_generation_runs_by_edition(conn, "")
        assert runs == 1

    def test_draft_failure_exhausts_attempts(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        stub = _SequenceStub([
            (200, FIRST_PLAN),
            (500, "internal error"),
        ])
        provider = _make_provider(stub)
        service = GenerationService(conn, provider)

        with pytest.raises(PipelineError, match="Draft generation failed"):
            service.generate_first_edition(
                traveler_id=traveler.id,
                input_id=None,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

        assert stub.call_count == 2

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 0


# ---------------------------------------------------------------------------
# Second-edition pipeline
# ---------------------------------------------------------------------------


class TestSecondEditionWithOpenAIProvider:
    def test_feedback_drives_change(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        first_draft = _load_fixture("source_bundle.json")["first_edition_fixture"]
        second_draft = _load_fixture("source_bundle.json")["second_edition_fixture"]

        stub1 = _SequenceStub([
            (200, FIRST_PLAN),
            (200, first_draft),
        ])
        provider1 = _make_provider(stub1)
        service1 = GenerationService(conn, provider1)
        service1.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산"},
            source_items=source_dicts,
        )

        ed1 = get_editions_by_traveler(conn, traveler.id)[0]
        create_feedback(
            conn,
            traveler_id=traveler.id,
            edition_id=ed1.id,
            direction_choices=["quieter_places", "slower_pace", "more_local_food"],
            free_text="더 조용하고 느린 코스로",
        )

        stub2 = _SequenceStub([
            (200, SECOND_PLAN),
            (200, second_draft),
        ])
        provider2 = _make_provider(stub2)
        service2 = GenerationService(conn, provider2)
        second_content = service2.generate_second_edition(
            traveler_id=traveler.id,
            prior_edition_id=ed1.id,
            traveler_preferences={"destination": "부산", "pace": "slow"},
            source_items=source_dicts,
        )

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 2

        from app.feedback_repository import get_unapplied_feedback_for_traveler
        unapplied = get_unapplied_feedback_for_traveler(conn, traveler.id)
        assert len(unapplied) == 0


# ---------------------------------------------------------------------------
# Validation and rollback
# ---------------------------------------------------------------------------


class TestValidationAndRollback:
    def test_fabricated_source_ref_rolls_back(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        bad_draft = dict(_load_fixture("source_bundle.json")["first_edition_fixture"])
        # All plan sections present to pass validate_draft_against_plan, but
        # one item references a source not in the validated set.
        bad_draft["sections"] = [
            {
                "section_id": "sec_morning_gukje",
                "title": "국제시장 근처 아침 산책",
                "narrative": "Fake source included",
                "items": [
                    {
                        "item_id": "item_gukje_atmosphere",
                        "information_class": "stable_reference",
                        "as_of_date": "2025-06-01",
                        "source_ref": "src_fabricated_999",
                        "confidence": "confirmed",
                    },
                ],
            },
            {
                "section_id": "sec_haegyeolri",
                "title": "합성동 로컬 카페 거리",
                "narrative": "Normal section",
                "items": [],
            },
            {
                "section_id": "sec_practical",
                "title": "실용 정보",
                "narrative": "Practical info",
                "items": [],
            },
        ]
        stub = _SequenceStub([
            (200, FIRST_PLAN),
            (200, bad_draft),
        ])
        provider = _make_provider(stub)
        service = GenerationService(conn, provider)

        with pytest.raises(PipelineError, match="Validation failed"):
            service.generate_first_edition(
                traveler_id=traveler.id,
                input_id=None,
                traveler_preferences={"destination": "부산"},
                source_items=source_dicts,
            )

        editions = get_editions_by_traveler(conn, traveler.id)
        assert len(editions) == 0

    def test_privacy_sentinels_no_leak_in_transport(
        self,
        conn,
        traveler,
        source_dicts,
    ):
        """Provider must not leak private data through transport headers.

        Verifies that:
        - Authorization uses Bearer scheme (API key never in body)
        - X-Request-ID is opaque (hex hash, not raw request_id)
        - No user-payload content appears in transport headers
        """
        draft_fixture = _load_fixture("source_bundle.json")["first_edition_fixture"]
        stub = _SequenceStub([
            (200, FIRST_PLAN),
            (200, draft_fixture),
        ])
        provider = _make_provider(stub)
        service = GenerationService(conn, provider)
        service.generate_first_edition(
            traveler_id=traveler.id,
            input_id=None,
            traveler_preferences={"destination": "부산", "pace": "comfortable"},
            source_items=source_dicts,
        )

        for _url, data, headers in stub.requests:
            body_str = data.decode("utf-8", errors="replace")

            auth = headers.get("Authorization", "")
            assert auth.startswith("Bearer "), "Authorization must use Bearer scheme"
            assert "sk-test-placeholder" in auth, "API key must be in Authorization header"

            api_key_in_body = (
                "sk-test-placeholder" in body_str
                or "Bearer" in body_str
            )
            assert not api_key_in_body, "API key must not appear in request body"

            req_id = headers.get("X-Request-ID", "")
            assert len(req_id) == 32, "X-Request-ID must be 32 hex chars"
            assert all(c in "0123456789abcdef" for c in req_id), (
                "X-Request-ID must be opaque hex"
            )
            assert req_id not in body_str, "X-Request-ID must not appear in body"

            for hdr_key, hdr_val in headers.items():
                assert "부산" not in hdr_val, (
                    f"User content ('부산') leaked in header {hdr_key}"
                )
                assert "comfortable" not in hdr_val, (
                    f"User preference leaked in header {hdr_key}"
                )
