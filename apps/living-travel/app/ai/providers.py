"""Deterministic provider factory for Living Travel production routes.

Loads app-owned synthetic fixtures and creates MockProvider instances
with valid payloads matched to persisted source records.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.ai.mock import MockProvider

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = _FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_source(
    conn: sqlite3.Connection,
    source_id: str,
    destination: str,
    source_data: dict,
) -> None:
    """Ensure a source with the given ID exists in the DB."""
    existing = conn.execute(
        "SELECT id FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    if existing:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        "INSERT INTO sources "
        "(id, source_url, publisher, source_type, original_language, "
        "publication_date, access_date, destination, locality, category, "
        "claims, confidence, state, verification_notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_id,
            f"https://synthetic/{source_id}",
            source_data.get("publisher", "Synthetic"),
            "web",
            "ko",
            "",
            "",
            destination,
            "",
            source_data.get("category", "general"),
            json.dumps(source_data.get("claims", []), ensure_ascii=False),
            source_data.get("confidence", "confirmed"),
            "single_source",
            "",
            now,
        ),
    )
    conn.commit()


_SOURCE_BUNDLE = [
    {
        "source_id": "src_busan_tourism",
        "publisher": "부산관광공사",
        "category": "destination_overview",
        "claims": [
            "부산은 한국 제2의 도시",
            "해운대와 광안리가 대표 해수욕장",
            "item_weather_note",
        ],
        "confidence": "confirmed",
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
        "confidence": "confirmed",
    },
    {
        "source_id": "src_haegyeolri",
        "publisher": "부산남구청",
        "category": "neighborhood",
        "claims": [
            "합성동은 로컬 분위기가 남아있는 동네",
            "조용한 카페와 식당이 있음",
            "item_haegyeolri_vibe",
            "item_quiet_haegyeolri",
        ],
        "confidence": "approximate",
    },
]


def create_mock_provider(conn: sqlite3.Connection, destination: str) -> MockProvider:
    """Create a MockProvider with valid payloads for the given destination.

    Ensures synthetic source records exist in the DB and returns a
    MockProvider pre-configured with deterministic plan/draft fixtures.
    """
    for src in _SOURCE_BUNDLE:
        _ensure_source(conn, src["source_id"], destination, src)

    plan = _load_fixture("synthetic_plan.json")
    draft = _load_fixture("synthetic_draft.json")

    return MockProvider(task_payloads={
        "editorial_plan": plan,
        "edition_draft": draft,
    })


def create_second_mock_provider(conn: sqlite3.Connection, destination: str) -> MockProvider:
    """Create a MockProvider for second-edition generation."""
    for src in _SOURCE_BUNDLE:
        _ensure_source(conn, src["source_id"], destination, src)

    plan = _load_fixture("synthetic_second_plan.json")
    draft = _load_fixture("synthetic_second_draft.json")

    return MockProvider(task_payloads={
        "editorial_plan": plan,
        "edition_draft": draft,
    })
