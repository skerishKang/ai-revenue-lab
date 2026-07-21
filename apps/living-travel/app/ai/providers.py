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

_DIRECTION_TO_SECTION: dict[str, tuple[str, str, str, list[str]]] = {
    "quieter_places": (
        "sec_quiet",
        "조용한 장소",
        "한적하고 조용한 명소 위주로 구성했습니다.",
        ["sec_quiet"],
    ),
    "slower_pace": (
        "sec_slow_pace",
        "여유로운 일정",
        "이동 시간을 줄이고 여유 있게 즐길 수 있는 일정으로 조정했습니다.",
        ["sec_slow_pace"],
    ),
    "more_local_food": (
        "sec_local_food",
        "로컬 음식",
        "지역 맛집과 로컬 푸드를 중심으로 음식 정보를 강화했습니다.",
        ["sec_local_food"],
    ),
    "less_walking": (
        "sec_low_effort",
        "적은 이동 코스",
        "도보 거리를 최소화하고 이동이 적은 코스로 재구성했습니다.",
        ["sec_low_effort"],
    ),
    "lower_budget": (
        "sec_budget",
        "비용 효율 코스",
        "합리적인 가격대의 선택지를 중심으로 예산 부담을 줄였습니다.",
        ["sec_budget"],
    ),
    "more_practical": (
        "sec_practical",
        "실용 정보",
        "운영시간·교통·예약 등 실용적인 정보를 추가했습니다.",
        ["sec_practical"],
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
    dhash = _destination_hash(destination)
    return [
        {
            "source_id": f"syn_src_{dhash}_overview",
            "category": "destination_overview",
            "claims": [f"{destination} 여행 overview", "item_weather_note"],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{dhash}_market",
            "category": "market",
            "claims": [f"{destination} 전통시장", "item_gukje_atmosphere", "item_gukje_hours", "item_solo_dining"],
            "confidence": "confirmed",
        },
        {
            "source_id": f"syn_src_{dhash}_neighborhood",
            "category": "neighborhood",
            "claims": [f"{destination} 로컬 동네", "item_haegyeolri_vibe", "item_quiet_haegyeolri"],
            "confidence": "approximate",
        },
    ]


def _apply_preferences_to_plan(plan: dict, prefs: dict) -> dict:
    plan = copy.deepcopy(plan)
    dest = prefs.get("destination", "")
    lang = prefs.get("preferred_language", "ko")
    plan["central_theme"] = f"{dest} 여행"
    length = prefs.get("length_preference", "medium")
    length_factor = {"short": 1, "medium": 2, "long": 3}
    max_sections = length_factor.get(length, 2)
    if len(plan.get("sections", [])) > max_sections:
        plan["sections"] = plan["sections"][:max_sections]
    for sec in plan.get("sections", []):
        sec["title"] = f"{dest} — {sec.get('title', '')}"
    if lang not in _SUPPORTED_LANGUAGES:
        plan["sections"] = []
    return plan


def _apply_preferences_to_draft(draft: dict, prefs: dict) -> dict:
    draft = copy.deepcopy(draft)
    dest = prefs.get("destination", "")
    nights = prefs.get("trip_duration_nights", 2)
    pace = prefs.get("pace_preference", "comfortable")
    budget = prefs.get("budget_tendency", "moderate")
    interests = prefs.get("interests", [])
    trip_context = prefs.get("trip_context", "solo")
    tone = prefs.get("tone_preference", "calm")
    length = prefs.get("length_preference", "medium")
    lang = prefs.get("preferred_language", "ko")
    exclusions = prefs.get("exclusions", [])

    draft["destination"] = dest
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"

    context_map = {"solo": "혼행", "couple": "커플 여행", "family": "가족 여행", "group": "단체 여행"}
    ctx_label = context_map.get(trip_context, trip_context)
    draft["publication_title"] = f"{dest} {nights}박: 맞춤 {ctx_label}"
    draft["edition_title"] = f"첫 번째 에디션 — {dest}의 {ctx_label}"

    pace_desc = "천천히" if pace in ("relaxed", "comfortable") else "활기차게"
    budget_desc = "합리적인" if budget in ("budget", "moderate") else "여유로운"
    interest_desc = ", ".join(interests[:3]) if interests else "로컬 분위기"
    exclus = f" ({', '.join(exclusions[:2])}는 제외)" if exclusions else ""

    opening = f"{dest}는 {interest_desc}으로 유명합니다{exclus}. "
    opening += f"이번 에디션은 {ctx_label}에 적합한 {pace_desc} 걷는 {budget_desc} 코스로 준비했습니다."

    if tone == "calm":
        opening += " 여유롭게 즐겨보세요."
    elif tone == "energetic":
        opening += " 활기차게 즐겨보세요!"
    elif tone == "luxury":
        opening += " 프리미엄 경험을 만끽하세요."

    draft["editorial_opening"] = opening

    length_factor = {"short": 1, "medium": 2, "long": 3}
    max_sections = length_factor.get(length, 2)
    if len(draft.get("sections", [])) > max_sections:
        draft["sections"] = draft["sections"][:max_sections]

    draft["provenance_note"] = (
        "모든 정보는 합성된 데모 데이터입니다. 실제 검증된 출처가 아닙니다."
    )
    for sec in draft.get("sections", []):
        sec["title"] = f"{dest} — {sec.get('title', '')}"
        sec["narrative"] = (
            f"{dest}에서 {pace_desc} 걸으며 즐길 수 있는 "
            f"{sec.get('title', '').split('—')[-1].strip()} 관련 내용입니다."
        )

    return draft


def _apply_preferences_to_second_draft(draft: dict, prefs: dict) -> dict:
    """Apply traveler preferences to second edition draft FIRST, before feedback."""
    draft = copy.deepcopy(draft)
    dest = prefs.get("destination", "")
    nights = prefs.get("trip_duration_nights", 2)
    pace = prefs.get("pace_preference", "comfortable")
    trip_context = prefs.get("trip_context", "solo")
    tone = prefs.get("tone_preference", "calm")
    length = prefs.get("length_preference", "medium")
    exclusions = prefs.get("exclusions", [])

    draft["destination"] = dest
    draft["trip_frame"] = f"{nights}박 {nights + 1}일"

    context_map = {"solo": "혼행", "couple": "커플 여행", "family": "가족 여행", "group": "단체 여행"}
    ctx_label = context_map.get(trip_context, trip_context)
    draft["publication_title"] = f"{dest} {nights}박: 피드백 반영 {ctx_label}"
    draft["edition_title"] = f"두 번째 에디션 — {dest} 맞춤 코스"

    pace_desc = "천천히" if pace in ("relaxed", "comfortable") else "활기차게"
    exclus = f" ({', '.join(exclusions[:2])}는 제외)" if exclusions else ""

    opening = f"피드백을 반영하여 {dest}{exclus} 코스를 재구성했습니다. "
    opening += f"{ctx_label}에 적합한 {pace_desc} 일정으로 준비했습니다."

    if tone == "calm":
        opening += " 여유롭게 즐겨보세요."
    elif tone == "energetic":
        opening += " 활기차게 즐겨보세요!"
    elif tone == "luxury":
        opening += " 프리미엄 경험을 만끽하세요."

    draft["editorial_opening"] = opening

    length_factor = {"short": 1, "medium": 2, "long": 3}
    max_sections = length_factor.get(length, 2)
    if len(draft.get("sections", [])) > max_sections:
        draft["sections"] = draft["sections"][:max_sections]

    for sec in draft.get("sections", []):
        sec["title"] = f"{dest} — {sec.get('title', '')}"
        sec["narrative"] = (
            f"피드백을 반영하여 {dest}에서 "
            f"{sec.get('title', '').split('—')[-1].strip()}를 "
            f"{pace_desc} 재구성했습니다."
        )

    return draft


def _apply_feedback_to_second_draft(
    draft: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> dict:
    """Apply exact feedback to the already-personalized second draft."""
    draft = copy.deepcopy(draft)
    dest = draft.get("destination", "")

    direction_changes: set[str] = set()
    for fb in feedback_records:
        for d in fb.direction_choices:
            direction_changes.add(d)

    all_section_ids = {s["section_id"] for s in draft.get("sections", [])}

    applied = []
    added_sections: list[dict] = []
    modified_section_ids: set[str] = set()

    for fb in feedback_records:
        fb_affected_ids: list[str] = []
        fb_unfulfilled: list[str] = []

        for d in fb.direction_choices:
            if d not in _DIRECTION_TO_SECTION:
                fb_unfulfilled.append(f"{d}: 알 수 없는 방향")
                continue
            sec_id, sec_title, sec_note, expected_ids = _DIRECTION_TO_SECTION[d]

            if sec_id in all_section_ids:
                fb_affected_ids.append(sec_id)
                modified_section_ids.add(sec_id)
                for existing_sec in draft.get("sections", []):
                    if existing_sec["section_id"] == sec_id:
                        existing_sec["narrative"] = f"{dest} — {sec_note}"
                        existing_sec["title"] = f"{dest} — {sec_title}"
            else:
                new_sec = {
                    "section_id": sec_id,
                    "title": f"{dest} — {sec_title}",
                    "narrative": f"{dest} — {sec_note}",
                    "items": [],
                }
                added_sections.append(new_sec)
                fb_affected_ids.append(sec_id)
                modified_section_ids.add(sec_id)

        actual_action = "; ".join(_DIRECTION_TO_ACTION.get(d, d) for d in fb.direction_choices)
        if fb_unfulfilled:
            actual_action += " (일부 미반영: " + "; ".join(fb_unfulfilled) + ")"

        applied.append({
            "feedback_id": fb.id,
            "requested_change": ", ".join(fb.direction_choices),
            "actual_action": actual_action,
            "affected_section_ids": fb_affected_ids,
            "evidence": fb.free_text[:200] if fb.free_text else "",
            "unfulfilled_reason": "; ".join(fb_unfulfilled),
        })

    if added_sections:
        draft["sections"] = draft.get("sections", []) + added_sections

    draft["applied_feedback"] = applied

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
    opening_parts.append("재구성했습니다.")

    existing_opening = draft.get("editorial_opening", "").split(". ")
    base = existing_opening[0] if len(existing_opening) > 1 else f"피드백을 반영하여 {dest} 코스를"
    draft["editorial_opening"] = base + ". " + " ".join(opening_parts)

    return draft


def _remap_source_refs(draft: dict, source_map: dict[str, str]) -> dict:
    draft = copy.deepcopy(draft)
    for sec in draft.get("sections", []):
        for item in sec.get("items", []):
            old_ref = item.get("source_ref", "")
            if old_ref in source_map:
                item["source_ref"] = source_map[old_ref]
    return draft


# --- Public API ---

def create_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
) -> MockProvider:
    lang = traveler_preferences.get("preferred_language", "ko")
    if lang not in _SUPPORTED_LANGUAGES:
        return MockProvider(task_payloads={
            "editorial_plan": {"central_theme": traveler_preferences.get("destination", "Unknown"),
                               "sections": []},
            "edition_draft": _build_unsupported_draft(traveler_preferences),
        })

    dest = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(dest)
    source_map = {}
    for src in source_bundle:
        _ensure_source(conn, src["source_id"], dest, src)
        source_map[src["category"]] = src["source_id"]

    plan = _apply_preferences_to_plan(_load_fixture("synthetic_plan.json"), traveler_preferences)
    draft = _apply_preferences_to_draft(_load_fixture("synthetic_draft.json"), traveler_preferences)

    legacy_to_new = {
        "src_busan_tourism": source_map.get("destination_overview", ""),
        "src_gukje_market": source_map.get("market", ""),
        "src_haegyeolri": source_map.get("neighborhood", ""),
    }
    draft = _remap_source_refs(draft, legacy_to_new)

    return MockProvider(task_payloads={"editorial_plan": plan, "edition_draft": draft})


def create_second_mock_provider(
    conn: sqlite3.Connection,
    traveler_preferences: dict,
    feedback_records: list,
    prior_content: dict | None = None,
) -> MockProvider:
    lang = traveler_preferences.get("preferred_language", "ko")
    if lang not in _SUPPORTED_LANGUAGES:
        return MockProvider(task_payloads={
            "editorial_plan": {"central_theme": traveler_preferences.get("destination", "Unknown"),
                               "sections": []},
            "edition_draft": _build_unsupported_draft(traveler_preferences),
        })

    dest = traveler_preferences.get("destination", "")
    source_bundle = _build_source_bundle_for_destination(dest)
    source_map = {}
    for src in source_bundle:
        _ensure_source(conn, src["source_id"], dest, src)
        source_map[src["category"]] = src["source_id"]

    plan = _apply_preferences_to_plan(_load_fixture("synthetic_second_plan.json"), traveler_preferences)

    # Apply preferences FIRST, then feedback
    draft = _apply_preferences_to_second_draft(
        _load_fixture("synthetic_second_draft.json"), traveler_preferences
    )
    draft = _apply_feedback_to_second_draft(draft, feedback_records, prior_content)

    legacy_to_new = {
        "src_busan_tourism": source_map.get("destination_overview", ""),
        "src_gukje_market": source_map.get("market", ""),
        "src_haegyeolri": source_map.get("neighborhood", ""),
    }
    draft = _remap_source_refs(draft, legacy_to_new)

    return MockProvider(task_payloads={"editorial_plan": plan, "edition_draft": draft})


def _build_unsupported_draft(prefs: dict) -> dict:
    dest = prefs.get("destination", "Unknown")
    return {
        "publication_title": f"[Unsupported Language] {dest}",
        "edition_title": f"Unsupported — {dest}",
        "destination": dest,
        "trip_frame": "",
        "editorial_opening": f"This destination ({dest}) is not yet supported.",
        "sections": [],
        "applied_feedback": [],
        "content_version": "1.0",
        "provenance_note": "Synthetic demonstration.",
    }
