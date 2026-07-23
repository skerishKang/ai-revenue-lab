"""Pydantic request schemas for the JSON API (bounded payloads)."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_SHORT_TEXT = 200
MAX_FREE_TEXT = 2000
MAX_LIST_ITEMS = 50


class ClaimRequest(BaseModel):
    invitation_code: str = Field(min_length=1, max_length=256)


class PreferencesUpdate(BaseModel):
    destination: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    trip_duration_nights: int | None = Field(default=None, ge=1, le=60)
    trip_context: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    budget_tendency: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    pace_preference: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    tone_preference: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    length_preference: str | None = Field(default=None, max_length=MAX_SHORT_TEXT)
    preferred_language: str | None = Field(default=None, max_length=10)
    interests: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    exclusions: list[str] | None = Field(default=None, max_length=MAX_LIST_ITEMS)


class FeedbackRequest(BaseModel):
    edition_id: str = Field(min_length=1, max_length=128)
    direction_choices: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    selected_section_id: str = Field(default="", max_length=128)
    free_text: str = Field(default="", max_length=MAX_FREE_TEXT)


class CreateTravelerRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=MAX_SHORT_TEXT)
    destination: str = Field(min_length=1, max_length=MAX_SHORT_TEXT)
    trip_duration_nights: int = Field(default=2, ge=1, le=60)
