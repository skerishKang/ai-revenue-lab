"""Serialization helpers for API responses."""

from __future__ import annotations


def traveler_to_dict(t) -> dict:
    return {
        "id": t.id,
        "display_name": t.display_name,
        "preferred_language": t.preferred_language,
        "destination": t.destination,
        "trip_duration_nights": t.trip_duration_nights,
        "trip_context": t.trip_context,
        "budget_tendency": t.budget_tendency,
        "pace_preference": t.pace_preference,
        "interests": list(t.interests),
        "exclusions": list(t.exclusions),
        "tone_preference": t.tone_preference,
        "length_preference": t.length_preference,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def traveler_preferences_to_dict(t) -> dict:
    return {
        "destination": t.destination,
        "trip_duration_nights": t.trip_duration_nights,
        "trip_context": t.trip_context,
        "budget_tendency": t.budget_tendency,
        "pace_preference": t.pace_preference,
        "interests": list(t.interests),
        "exclusions": list(t.exclusions),
        "tone_preference": t.tone_preference,
        "length_preference": t.length_preference,
        "preferred_language": t.preferred_language,
    }


def edition_to_dict(ed) -> dict:
    return {
        "id": ed.id,
        "traveler_id": ed.traveler_id,
        "edition_number": ed.edition_number,
        "prior_edition_id": ed.prior_edition_id,
        "generation_status": ed.generation_status,
        "publication_state": ed.publication_state,
        "structured_content": ed.structured_content or {},
        "created_at": ed.created_at,
        "updated_at": ed.updated_at,
    }


def edition_summary_to_dict(ed) -> dict:
    return {
        "id": ed.id,
        "traveler_id": ed.traveler_id,
        "edition_number": ed.edition_number,
        "generation_status": ed.generation_status,
        "publication_state": ed.publication_state,
        "created_at": ed.created_at,
        "updated_at": ed.updated_at,
    }
