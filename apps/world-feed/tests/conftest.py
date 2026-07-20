from pathlib import Path

import pytest

from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, Language, SourceState, SourceTier
from app.domain.models import ReaderProfileInput, SourceCard
from app.service import WorldFeedService

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "world-feed.db")


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    apply_migrations(connection, str(MIGRATIONS_DIR))
    yield connection
    connection.close()


@pytest.fixture
def provider():
    return MockProvider(model=settings.ai_model)


@pytest.fixture
def service(provider):
    return WorldFeedService(provider=provider, settings=settings)


def make_source(
    source_id,
    canonical_key,
    category: Category,
    *,
    source_state: SourceState = SourceState.SINGLE_SOURCE,
    country: str = "Vietnam",
    locality: str = "Hanoi",
    title: str = "Synthetic title",
    text_extract: str = "Synthetic extract with no unsafe markup.",
    conflict_penalty: float = 0.0,
    checksum: str | None = None,
):
    return SourceCard(
        source_id=source_id,
        country=country,
        locality=locality,
        original_language=Language.KO,
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        publisher_name="Synthetic Publisher",
        organization_type="tourism_authority",
        canonical_url=f"https://example.invalid/{source_id}",
        publication_timestamp="2026-01-01T00:00:00Z",
        access_timestamp="2026-01-02T00:00:00Z",
        title=title,
        text_extract=text_extract,
        category=category,
        media_rights_state="clear",
        source_state=source_state,
        conflict_penalty=conflict_penalty,
        canonical_key=canonical_key,
        checksum=checksum or f"cs-{source_id}",
        synthetic_flag=True,
    )


def make_reader(
    reader_id: str = "reader-001",
    *,
    language: Language = Language.KO,
    interests=None,
    excluded=None,
    desired=None,
    active: bool = True,
):
    return ReaderProfileInput(
        reader_id=reader_id,
        display_name="Synthetic Reader",
        language=language,
        preferences={
            "interests": [c.value for c in (interests or [])],
            "excluded_categories": [c.value for c in (excluded or [])],
            "desired_coverage": [c.value for c in (desired or [])],
            "detail_level": "standard",
            "language": language.value,
        },
        active=active,
    )


def brief_payload(event_ids, *, title="Brief", feedback_note=None, uncertainty_notes=None, source_ids_map=None):
    items = []
    for eid in event_ids:
        sids = source_ids_map.get(eid, ["src-1"]) if source_ids_map else ["src-1"]
        items.append({
            "event_id": eid,
            "headline": f"Headline for {eid}",
            "explanation": f"Explanation for {eid}.",
            "source_ids": sids,
        })
    return {
        "brief_title": title,
        "deck": "Synthetic deck.",
        "items": items,
        "uncertainty_notes": uncertainty_notes or [],
        "feedback_note": feedback_note,
    }


def make_brief_provider(first_ids, second_ids, *, source_ids_map=None, first_title="First", second_title="Second", feedback_note="applied feedback"):
    return MockProvider(
        model=settings.ai_model,
        task_payloads={
            "generate_first_microbrief": brief_payload(
                first_ids, title=first_title, source_ids_map=source_ids_map
            ),
            "generate_second_microbrief": brief_payload(
                second_ids, title=second_title, feedback_note=feedback_note,
                source_ids_map=source_ids_map,
            ),
        },
    )


def event_id_map(conn):
    from app.repositories import canonical_event_repository

    return {e.canonical_key: e.id for e in canonical_event_repository.list_events(conn)}


def event_source_ids_map(conn):
    from app.repositories import canonical_event_repository

    return {e.id: e.source_ids for e in canonical_event_repository.list_events(conn)}
