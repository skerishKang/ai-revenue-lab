"""Deterministic provider factory for Living Travel production routes.

Loads app-owned synthetic fixtures and creates MockProvider instances
with valid payloads personalized to traveler preferences and matched
to persisted source records.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path

from app.ai.mock import MockProvider

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

_SYNTHETIC_PUBLISHER = "Living Travel Synthetic Fixture"
_SYNTHETIC_URL_PREFIX = "https://synthetic.example.com/living-travel"
_SYNTHETIC_VERIFICATION = (
    "Synthetic, network-free demonstration record. "
    "Not a current factual source."
)

_DIRECTION_TO_ACTION = {
    "quieter_places": "더 조용한 장소 위주로 코스를 구성",
    "slower_pace": "일정과 이동량을 완화하여 여유로운 코스로 조정",
    "more_local_food": "로컬 음식 관련 섹션을 강화하고 구체적인 식당 정보 포함",
    "less_walking": "이동 동선을 축소하고 도보 거리를 최소화",
    "lower_budget": "비용 효율적인 선택지 중심으로 코스를 조정",
    "more_practical": "실용 정보 섹션을 강화하여 구체적인 운영시간·예약정보 포함",
}


def _load_fixture(name: str) -> dict:
    path = _FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _destination_hash(destination: str) -> str:
    """Short deterministic hash for destination-specific IDs."""
    return hashlib.sha256(destination.encode()).hexdigest()[:8]


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
            f"{_SYNTHETIC_URL_PREFIX}/{_destination_hash(destination)}/{source_data.get('category', 'general')}",
            _SYNTHETIC_PUBLISHER,
            "synthetic_fixture",
            "ko",
            "",
            "",
            destination,
            "",
            source_data.get("category", "general"),
            json.dumps(source_data.get("claims", []), ensure_ascii=False),
            source_data.get("confidence", "confirmed"),
            "single_source",
            _SYNTHETIC_VERIFICATION,
            now,
        ),
    )
    conn.commit()


def _build_source_bundle_for_destination(
    destination: str,
) -> list[dict]:
    """Build destination-specific source records with deterministic IDs."""
    dhash = _destination_hash(destination)
    return [
        {
            "source_id": f"syn_src_{dhash}_overview",
            "category": "destination_overview",
            "claims": [
                f"{destination}는 여행지 overview 항목",
                f"{destination} 대표 관광지 항목",
                "item_weather_note",
            ],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{dhash}_market",
            "category": "market",
            "claims": [
                f"{destination} 전통시장 관련 항목",
                f"{destination} 식당가 항목",
                "item_gukje_atmosphere",
                "item_gukje_hours",
                "item_solo_dining",
            ],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{dhash}_neighborhood",
            "category": "neighborhood",
            "claims": [
                f"{destination} 로컬 동네 항목",
                f"{destination} 카페·식당 항목",
                "item_haegyeolri_vibe",
                "item_quiet_haegyeolri",
            ],
            "confidence": "approximate",
        },
    ]


def _apply_preferences_to_plan(plan: dict, prefs: dict) -> dict:
    """Deep copy plan and apply traveler preferences."""
    plan = copy.deepcopy(plan)
    dest = prefs.get("destination", plan.get("central_theme", ""))
    plan["central_theme"] = f"{dest} 동네 산책"
    for sec in plan.get("sections", []):
        sec["title"] = f"{dest} — {sec.get('title', '')}"
    return plan


def _apply_preferences_to_draft(draft: dict, prefs: dict) -> dict:
    """Deep copy draft and apply traveler preferences."""
    draft = copy.deepcopy(draft)
    dest = prefs.get("destination", "")
    nights = prefs.get("trip_duration_nights", 2)
    pace = prefs.get("pace_preference", "comfortable")
    budget = prefs.get("budget_tendency", "moderate")
    interests = prefs.get("interests", [])

    draft["destination"] = dest
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"
    draft["publication_title"] = f"{dest} {nights}박: 동네와 로컬 음식의 아침"
    draft["edition_title"] = f"첫 번째 에디션 — {dest}의 동네 산책"

    pace_desc = "천천히" if pace in ("relaxed", "comfortable") else "활기차게"
    budget_desc = "합리적인" if budget in ("budget", "moderate") else "여유로운"
    interest_desc = ", ".join(interests[:3]) if interests else "로컬 분위기"
    draft["editorial_opening"] = (
        f"{dest}는 {interest_desc}으로 유명하지만, "
        f"진짜 맛은 조용한 동네 아침에 있습니다. "
        f"이번 에디션은 {pace_desc} 걸으며 {budget_desc} 선택지 위주로 소개합니다."
    )
    draft["provenance_note"] = (
        "모든 정보는 합성된 데모 데이터입니다. "
        "실제 검증된 출처가 아닙니다."
    )
    for sec in draft.get("sections", []):
        sec["title"] = f"{dest} — {sec.get('title', '')}"
        sec["narrative"] = (
            f"{dest}에서 {pace_desc} 걸으며 즐길 수 있는 "
            f"{sec.get('title', '').split('—')[-1].strip()} 관련 내용입니다."
        )
    return draft


def _apply_feedback_to_second_draft(
    draft: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> dict:
    """Deep copy draft and apply exact feedback records."""
    draft = copy.deepcopy(draft)

    applied = []
    direction_changes = set()
    for fb in feedback_records:
        for d in fb.direction_choices:
            direction_changes.add(d)
        applied.append({
            "feedback_id": fb.id,
            "requested_change": ", ".join(fb.direction_choices),
            "actual_action": "; ".join(
                _DIRECTION_TO_ACTION.get(d, d) for d in fb.direction_choices
            ),
            "affected_section_ids": [s["section_id"] for s in draft.get("sections", [])[:2]],
            "evidence": fb.free_text[:200] if fb.free_text else "",
            "unfulfilled_reason": "",
        })

    draft["applied_feedback"] = applied

    dest = draft.get("destination", "")
    opening_parts = [f"{dest}에서"]
    if "quieter_places" in direction_changes or "less_walking" in direction_changes:
        opening_parts.append("더 조용하고 이동량을 줄인 코스로")
    if "more_local_food" in direction_changes:
        opening_parts.append("로컬 음식에 집중하여")
    if "slower_pace" in direction_changes:
        opening_parts.append("여유로운 일정으로")
    if "lower_budget" in direction_changes:
        opening_parts.append("비용 효율적으로")
    if "more_practical" in direction_changes:
        opening_parts.append("실용 정보를 강화하여")
    opening_parts.append("구성했습니다.")
    draft["editorial_opening"] = " ".join(opening_parts)

    draft["publication_title"] = f"{dest} {draft.get('trip_frame', '').split()[0] if draft.get('trip_frame') else ''}: 맞춤 코스"
    draft["edition_title"] = f"두 번째 에디션 — 피드백 반영 {dest}"

    for sec in draft.get("sections", []):
        sec["narrative"] = (
            f"피드백을 반영하여 {dest}에서 "
            f"{sec.get('title', '').split('—')[-1].strip()}를 "
            f"재구성한 섹션입니다."
        )

    return draft


# --- Public API ---

def _remap_source_refs(draft: dict, source_map: dict[str, str]) -> dict:
    """Remap source_ref values in draft sections using source_map."""
    draft = copy.deepcopy(draft)
    for sec in draft.get("sections", []):
        for item in sec.get("items", []):
            old_ref = item.get("source_ref", "")
            if old_ref in source_map:
                item["source_ref"] = source_map[old_ref]
    return draft


def create_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
) -> MockProvider:
    """Create a MockProvider with personalized payloads for the traveler.

    Deep-copies base fixtures and adjusts content to match traveler
    preferences. Ensures destination-specific source records exist.
    """
    dest = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(dest)
    source_map = {}
    for src in source_bundle:
        _ensure_source(conn, src["source_id"], dest, src)
        source_map[src["category"]] = src["source_id"]

    plan = _apply_preferences_to_plan(
        _load_fixture("synthetic_plan.json"), traveler_preferences
    )
    draft = _apply_preferences_to_draft(
        _load_fixture("synthetic_draft.json"), traveler_preferences
    )

    legacy_to_new = {
        "src_busan_tourism": source_map.get("destination_overview", ""),
        "src_gukje_market": source_map.get("market", ""),
        "src_haegyeolri": source_map.get("neighborhood", ""),
    }
    draft = _remap_source_refs(draft, legacy_to_new)

    return MockProvider(task_payloads={
        "editorial_plan": plan,
        "edition_draft": draft,
    })


def create_second_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> MockProvider:
    """Create a MockProvider for second-edition generation with exact feedback."""
    dest = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(dest)
    source_map = {}
    for src in source_bundle:
        _ensure_source(conn, src["source_id"], dest, src)
        source_map[src["category"]] = src["source_id"]

    plan = _apply_preferences_to_plan(
        _load_fixture("synthetic_second_plan.json"), traveler_preferences
    )
    draft = _apply_feedback_to_second_draft(
        _load_fixture("synthetic_second_draft.json"),
        feedback_records,
        prior_content,
    )
    draft["destination"] = dest
    nights = traveler_preferences.get("trip_duration_nights", 2)
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"

    legacy_to_new = {
        "src_busan_tourism": source_map.get("destination_overview", ""),
        "src_gukje_market": source_map.get("market", ""),
        "src_haegyeolri": source_map.get("neighborhood", ""),
    }
    draft = _remap_source_refs(draft, legacy_to_new)

    return MockProvider(task_payloads={
        "editorial_plan": plan,
        "edition_draft": draft,
    })
