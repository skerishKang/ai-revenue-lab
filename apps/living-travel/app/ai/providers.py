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

_SUPPORTED_LANGUAGES = {"ko"}

_DIRECTION_TO_SECTION: dict[str, tuple[str, str, str]] = {
    "quieter_places": (
        "sec_quiet",
        "조용한 장소",
        "한적하고 조용한 명소 위주로 구성했습니다.",
    ),
    "slower_pace": (
        "sec_slow_pace",
        "여유로운 일정",
        "이동 시간을 줄이고 여유 있게 즐길 수 있는 일정으로 조정했습니다.",
    ),
    "more_local_food": (
        "sec_local_food",
        "로컬 음식",
        "지역 맛집과 로컬 푸드를 중심으로 음식 정보를 강화했습니다.",
    ),
    "less_walking": (
        "sec_low_effort",
        "적은 이동 코스",
        "도보 거리를 최소화하고 이동이 적은 코스로 재구성했습니다.",
    ),
    "lower_budget": (
        "sec_budget",
        "비용 효율 코스",
        "합리적인 가격대의 선택지를 중심으로 예산 부담을 줄였습니다.",
    ),
    "more_practical": (
        "sec_practical",
        "실용 정보",
        "운영시간·교통·예약 등 실용적인 정보를 추가했습니다.",
    ),
}

_DIRECTION_TO_ACTION: dict[str, str] = {
    "quieter_places": "조용한 장소 위주로 코스를 재구성",
    "slower_pace": "여유로운 일정으로 조정",
    "more_local_food": "로컬 음식 섹션 강화",
    "less_walking": "이동 동선 축소 및 도보 거리 최소화",
    "lower_budget": "비용 효율적 선택지 중심으로 조정",
    "more_practical": "실용 정보 섹션 강화",
}


def _load_fixture(name: str) -> dict:
    path = _FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _destination_hash(destination: str) -> str:
    return hashlib.sha256(destination.encode()).hexdigest()[:8]


def _ensure_source(
    conn: sqlite3.Connection,
    source_id: str,
    destination: str,
    source_data: dict,
) -> None:
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


def _build_source_bundle_for_destination(destination: str) -> list[dict]:
    destination_hash = _destination_hash(destination)
    return [
        {
            "source_id": f"syn_src_{destination_hash}_overview",
            "category": "destination_overview",
            "claims": [f"{destination} 여행 overview", "item_weather_note"],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{destination_hash}_market",
            "category": "market",
            "claims": [
                f"{destination} 전통시장",
                "item_gukje_atmosphere",
                "item_gukje_hours",
                "item_solo_dining",
            ],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{destination_hash}_neighborhood",
            "category": "neighborhood",
            "claims": [
                f"{destination} 로컬 동네",
                "item_haegyeolri_vibe",
                "item_quiet_haegyeolri",
            ],
            "confidence": "approximate",
        },
    ]


def _build_plan_from_draft(draft: dict, prefs: dict) -> dict:
    destination = prefs.get("destination", "")
    return {
        "plan_version": "1.0",
        "language": prefs.get("preferred_language", "ko"),
        "central_theme": f"{destination} 맞춤 여행",
        "sections": [
            {
                "section_id": section.get("section_id", ""),
                "title": section.get("title", ""),
                "description": (
                    section.get("narrative", "")
                    or section.get("title", "")
                    or "맞춤 여행 섹션"
                )[:240],
            }
            for section in draft.get("sections", [])
        ],
    }


def _apply_preferences_to_plan(plan: dict, prefs: dict) -> dict:
    plan = copy.deepcopy(plan)
    destination = prefs.get("destination", "")
    language = prefs.get("preferred_language", "ko")
    plan["central_theme"] = f"{destination} 여행"
    plan["language"] = language

    length = prefs.get("length_preference", "medium")
    max_sections = {"short": 1, "medium": 2, "long": 3}.get(length, 2)
    if len(plan.get("sections", [])) > max_sections:
        plan["sections"] = plan["sections"][:max_sections]

    for section in plan.get("sections", []):
        section["title"] = f"{destination} — {section.get('title', '')}"

    if language not in _SUPPORTED_LANGUAGES:
        plan["sections"] = []
    return plan


def _apply_preferences_to_draft(draft: dict, prefs: dict) -> dict:
    draft = copy.deepcopy(draft)
    destination = prefs.get("destination", "")
    nights = prefs.get("trip_duration_nights", 2)
    pace = prefs.get("pace_preference", "comfortable")
    budget = prefs.get("budget_tendency", "moderate")
    interests = prefs.get("interests", [])
    trip_context = prefs.get("trip_context", "solo")
    tone = prefs.get("tone_preference", "calm")
    length = prefs.get("length_preference", "medium")
    exclusions = prefs.get("exclusions", [])

    draft["destination"] = destination
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"

    context_map = {
        "solo": "혼행",
        "couple": "커플 여행",
        "family": "가족 여행",
        "group": "단체 여행",
    }
    context_label = context_map.get(trip_context, trip_context)
    draft["publication_title"] = f"{destination} {nights}박: 맞춤 {context_label}"
    draft["edition_title"] = f"첫 번째 에디션 — {destination}의 {context_label}"

    pace_description = "천천히" if pace in ("relaxed", "comfortable") else "활기차게"
    budget_description = "합리적인" if budget in ("budget", "moderate") else "여유로운"
    interest_description = ", ".join(interests[:3]) if interests else "로컬 분위기"
    exclusion_description = (
        f" ({', '.join(exclusions[:2])}는 제외)" if exclusions else ""
    )

    opening = f"{destination}는 {interest_description}으로 유명합니다{exclusion_description}. "
    opening += (
        f"이번 에디션은 {context_label}에 적합한 {pace_description} 걷는 "
        f"{budget_description} 코스로 준비했습니다."
    )
    if tone == "calm":
        opening += " 여유롭게 즐겨보세요."
    elif tone == "energetic":
        opening += " 활기차게 즐겨보세요!"
    elif tone == "luxury":
        opening += " 프리미엄 경험을 만끽하세요."

    draft["editorial_opening"] = opening

    max_sections = {"short": 1, "medium": 2, "long": 3}.get(length, 2)
    if len(draft.get("sections", [])) > max_sections:
        draft["sections"] = draft["sections"][:max_sections]

    draft["provenance_note"] = (
        "모든 정보는 합성된 데모 데이터입니다. 실제 검증된 출처가 아닙니다."
    )
    for section in draft.get("sections", []):
        section["title"] = f"{destination} — {section.get('title', '')}"
        section["narrative"] = (
            f"{destination}에서 {pace_description} 걸으며 즐길 수 있는 "
            f"{section.get('title', '').split('—')[-1].strip()} 관련 내용입니다."
        )

    return draft


def _apply_preferences_to_second_draft(
    prior_content: dict,
    prefs: dict,
) -> dict:
    """Use the persisted prior structured content as the second-edition base."""
    if not prior_content:
        raise ValueError("Persisted prior content is required for a second edition")

    draft = copy.deepcopy(prior_content)
    previous_destination = draft.get("destination", "")
    destination = prefs.get("destination", "")
    nights = prefs.get("trip_duration_nights", 2)
    pace = prefs.get("pace_preference", "comfortable")
    budget = prefs.get("budget_tendency", "moderate")
    interests = prefs.get("interests", [])
    trip_context = prefs.get("trip_context", "solo")
    tone = prefs.get("tone_preference", "calm")
    length = prefs.get("length_preference", "medium")
    exclusions = prefs.get("exclusions", [])
    language = prefs.get("preferred_language", "ko")

    if language not in _SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported fixture language")

    context_map = {
        "solo": "혼행",
        "couple": "커플 여행",
        "family": "가족 여행",
        "group": "단체 여행",
    }
    context_label = context_map.get(trip_context, trip_context)
    pace_description = "천천히" if pace in ("relaxed", "comfortable") else "활기차게"
    budget_description = "합리적인" if budget in ("budget", "moderate") else "여유로운"
    interest_description = ", ".join(interests[:3]) if interests else "로컬 분위기"
    exclusion_description = (
        f" ({', '.join(exclusions[:2])}는 제외)" if exclusions else ""
    )
    tone_description = {
        "calm": "차분한",
        "energetic": "활기찬",
        "luxury": "프리미엄",
    }.get(tone, "차분한")

    prior_title = draft.get("publication_title", "이전 에디션")
    prior_opening = draft.get("editorial_opening", "")

    draft["destination"] = destination
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"
    draft["publication_title"] = f"{destination} {nights}박: 연속 {context_label}"
    draft["edition_title"] = f"두 번째 에디션 — {destination} 맞춤 코스"
    draft["editorial_opening"] = (
        f"'{prior_title}'의 흐름을 이어 {destination}{exclusion_description}에서 "
        f"{interest_description}에 집중한 {pace_description} {budget_description} "
        f"{tone_description} {context_label} 일정을 구성했습니다. "
        f"출력 언어는 한국어이며 분량 선호는 {length}입니다. "
        f"{prior_opening}"
    ).strip()
    draft["applied_feedback"] = []
    draft["next_edition_prompt"] = (
        "이전 에디션의 연속성을 유지하면서 다음에 바꿀 부분을 알려주세요."
    )
    draft["provenance_note"] = (
        f"{draft.get('provenance_note', '').strip()} "
        "이 에디션은 persisted prior structured content를 기반으로 한 "
        "network-free synthetic adaptation입니다."
    ).strip()

    if previous_destination and previous_destination != destination:
        for section in draft.get("sections", []):
            section["title"] = section.get("title", "").replace(
                previous_destination, destination
            )
            section["narrative"] = section.get("narrative", "").replace(
                previous_destination, destination
            )

    return draft


def _apply_feedback_to_second_draft(
    draft: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> dict:
    """Modify only exact feedback sections while preserving unrelated prior content."""
    draft = copy.deepcopy(draft)
    destination = draft.get("destination", "")

    direction_changes: set[str] = set()
    section_by_id = {
        section["section_id"]: section
        for section in draft.get("sections", [])
    }
    applied: list[dict] = []

    for feedback in feedback_records:
        affected_ids: list[str] = []
        unfulfilled: list[str] = []

        for direction in feedback.direction_choices:
            direction_changes.add(direction)
            mapping = _DIRECTION_TO_SECTION.get(direction)
            if mapping is None:
                unfulfilled.append(f"{direction}: 알 수 없는 방향")
                continue

            section_id, section_title, section_note = mapping
            section = section_by_id.get(section_id)
            if section is None:
                section = {
                    "section_id": section_id,
                    "title": f"{destination} — {section_title}",
                    "narrative": f"{destination} — {section_note}",
                    "items": [],
                }
                draft.setdefault("sections", []).append(section)
                section_by_id[section_id] = section
            else:
                section["title"] = f"{destination} — {section_title}"
                section["narrative"] = f"{destination} — {section_note}"

            if section_id not in affected_ids:
                affected_ids.append(section_id)

        actual_action = "; ".join(
            _DIRECTION_TO_ACTION.get(direction, direction)
            for direction in feedback.direction_choices
        )
        if unfulfilled:
            actual_action += " (일부 미반영: " + "; ".join(unfulfilled) + ")"

        applied.append(
            {
                "feedback_id": feedback.id,
                "requested_change": ", ".join(feedback.direction_choices),
                "actual_action": actual_action,
                "affected_section_ids": affected_ids,
                "evidence": feedback.free_text[:200] if feedback.free_text else "",
                "unfulfilled_reason": "; ".join(unfulfilled),
            }
        )

    draft["applied_feedback"] = applied

    opening_parts = [f"{destination}에서"]
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
    opening_parts.append("재구성했습니다.")

    draft["editorial_opening"] = (
        draft.get("editorial_opening", "").rstrip()
        + " "
        + " ".join(opening_parts)
    ).strip()
    return draft


def _source_category_for_item(item_id: str) -> str:
    lowered = item_id.lower()
    if any(token in lowered for token in ("gukje", "market", "food", "dining")):
        return "market"
    if any(
        token in lowered
        for token in ("haegyeolri", "neighborhood", "cafe", "quiet")
    ):
        return "neighborhood"
    return "destination_overview"


def _remap_source_refs(
    draft: dict,
    category_to_source: dict[str, str],
) -> dict:
    draft = copy.deepcopy(draft)
    for section in draft.get("sections", []):
        for item in section.get("items", []):
            category = _source_category_for_item(item.get("item_id", ""))
            source_id = category_to_source.get(category, "")
            if source_id:
                item["source_ref"] = source_id
    return draft


def create_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
) -> MockProvider:
    destination = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(destination)
    source_map: dict[str, str] = {}
    for source in source_bundle:
        _ensure_source(conn, source["source_id"], destination, source)
        source_map[source["category"]] = source["source_id"]

    plan = _apply_preferences_to_plan(
        _load_fixture("synthetic_plan.json"),
        traveler_preferences,
    )
    draft = _apply_preferences_to_draft(
        _load_fixture("synthetic_draft.json"),
        traveler_preferences,
    )
    draft = _remap_source_refs(draft, source_map)

    return MockProvider(
        task_payloads={
            "editorial_plan": plan,
            "edition_draft": draft,
        }
    )


def create_second_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> MockProvider:
    if not prior_content:
        raise ValueError("Persisted prior content is required for a second edition")

    destination = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(destination)
    source_map: dict[str, str] = {}
    for source in source_bundle:
        _ensure_source(conn, source["source_id"], destination, source)
        source_map[source["category"]] = source["source_id"]

    draft = _apply_preferences_to_second_draft(
        prior_content,
        traveler_preferences,
    )
    draft = _apply_feedback_to_second_draft(
        draft,
        feedback_records,
        prior_content,
    )
    draft = _remap_source_refs(draft, source_map)
    plan = _build_plan_from_draft(draft, traveler_preferences)

    return MockProvider(
        task_payloads={
            "editorial_plan": plan,
            "edition_draft": draft,
        }
    )


def _build_unsupported_draft(prefs: dict) -> dict:
    destination = prefs.get("destination", "Unknown")
    return {
        "publication_title": f"[Unsupported Language] {destination}",
        "edition_title": f"Unsupported — {destination}",
        "destination": destination,
        "trip_frame": "N/A",
        "editorial_opening": (
            f"This language is not yet supported for {destination}."
        ),
        "sections": [],
        "applied_feedback": [],
        "content_version": "1.0",
        "provenance_note": "Synthetic demonstration.",
    }
