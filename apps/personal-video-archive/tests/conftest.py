"""Shared test fixtures for Personal Video Archive tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure the app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import apply_migrations, get_connection
from app.providers.fake_language_model import FakeLanguageModelProvider
from app.providers.fake_video_discovery import FakeVideoDiscoveryProvider
from app.repositories import (
    ProposalRepository,
    QuotaLedgerRepository,
    QueryRuleRepository,
    SyncRunRepository,
    TopicRepository,
    TopicVideoRepository,
    VideoRepository,
    ViewingRecordRepository,
)
from app.services import (
    DiscoveryService,
    ProposalService,
    RecordService,
    TopicService,
)


_MIGRATIONS_DIR = str(
    Path(__file__).resolve().parent.parent / "migrations"
)


@pytest.fixture
def conn():
    """In-memory SQLite connection with migrations applied."""
    connection = get_connection(":memory:")
    apply_migrations(connection, _MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture
def repos(conn):
    """All repositories bound to the in-memory connection."""
    return {
        "topic": TopicRepository(conn),
        "rule": QueryRuleRepository(conn),
        "video": VideoRepository(conn),
        "topic_video": TopicVideoRepository(conn),
        "record": ViewingRecordRepository(conn),
        "sync": SyncRunRepository(conn),
        "quota": QuotaLedgerRepository(conn),
        "proposal": ProposalRepository(conn),
    }


@pytest.fixture
def fake_discovery():
    return FakeVideoDiscoveryProvider()


@pytest.fixture
def fake_llm():
    return FakeLanguageModelProvider()


@pytest.fixture
def topic_service(repos, fake_llm):
    return TopicService(
        repos["topic"], repos["rule"], fake_llm
    )


@pytest.fixture
def discovery_service(repos, fake_discovery, fake_llm):
    return DiscoveryService(
        repos["topic"], repos["rule"], repos["video"],
        repos["topic_video"], repos["sync"], repos["quota"],
        fake_discovery, fake_llm,
    )


@pytest.fixture
def record_service(repos, fake_llm):
    return RecordService(
        repos["topic_video"], repos["record"],
        repos["proposal"], fake_llm,
    )


@pytest.fixture
def proposal_service(repos, fake_llm):
    return ProposalService(
        repos["topic"], repos["rule"],
        repos["proposal"], fake_llm,
    )


@pytest.fixture
def created_topic(topic_service):
    """A topic with an accepted query rule, ready for discovery."""
    topic, proposal = topic_service.create_topic(
        name="ChatGPT updates",
        intent="Show me newly published Korean and English videos about "
               "meaningful ChatGPT product updates, excluding Shorts and "
               "low-value reaction content.",
    )
    topic_service.accept_rule_draft(topic.id, proposal)
    return topic
