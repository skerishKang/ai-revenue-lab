"""Narrow provider factory used by first- and second-edition generation paths."""

from __future__ import annotations

import sqlite3

from app.ai.base import AIProvider
from app.ai.mock import MockProvider
from app.ai.openai_compatible import OpenAICompatibleProvider, Transport
from app.config import Settings
from app.domain.enums import CostClass


def create_ai_provider(
    settings: Settings,
    *,
    conn: sqlite3.Connection | None = None,
    traveler_preferences: dict | None = None,
    feedback_records: list | None = None,
    prior_content: dict | None = None,
    transport: Transport | None = None,
) -> AIProvider:
    """Create the selected AI provider.

    ``conn`` and ``traveler_preferences`` are required for the ``mock``
    provider (MockProvider loads synthetic fixtures via ``create_mock_provider``
    or ``create_second_mock_provider``).  They are ignored by the
    ``openai_compatible`` provider — the network provider receives only
    normalized prompt data sent by the pipeline.

    ``feedback_records`` and ``prior_content`` are used only when constructing
    a second-edition ``MockProvider`` (``create_second_mock_provider``).  They
    are ignored by the ``openai_compatible`` provider.

    Raises ``ValueError`` on missing or invalid configuration (fail-closed).
    No silent fallback: the caller explicitly requested a network provider, and
    an error is raised rather than falling back to ``MockProvider``.
    """
    if settings.ai_provider == "mock":
        if conn is None or traveler_preferences is None:
            raise ValueError(
                "mock provider requires conn and traveler_preferences"
            )
        if prior_content is not None:
            return _build_mock_second(conn, traveler_preferences, feedback_records, prior_content)
        return _build_mock(conn, traveler_preferences)

    if settings.ai_provider == "openai_compatible":
        return _build_openai_compatible(settings, transport)

    raise ValueError(f"unsupported provider: {settings.ai_provider}")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _build_mock(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
) -> MockProvider:
    """Build a deterministic MockProvider for first-edition fixtures."""
    from app.ai.providers import create_mock_provider

    return create_mock_provider(
        conn,
        traveler_preferences,
    )


def _build_mock_second(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
    feedback_records: list | None = None,
    prior_content: dict | None = None,
) -> MockProvider:
    """Build a deterministic MockProvider for second-edition fixtures."""
    from app.ai.providers import create_second_mock_provider

    return create_second_mock_provider(
        conn,
        traveler_preferences,
        feedback_records or [],
        prior_content,
    )


def _build_openai_compatible(
    settings: Settings,
    transport: Transport | None = None,
) -> OpenAICompatibleProvider:
    cost_map = {
        "free": CostClass.free,
        "paid": CostClass.paid,
        "local": CostClass.local,
        "unknown": CostClass.unknown,
    }
    return OpenAICompatibleProvider(
        base_url=settings.ai_chat_completions_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
        cost_class=cost_map.get(settings.ai_cost_class, CostClass.free),
        transport=transport,
    )
