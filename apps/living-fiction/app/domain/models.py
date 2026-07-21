"""Pydantic domain models for Living Fiction.

These models define the structured contract for world state, episodes,
continuity deltas, and reader choices. They are used by validators and the
MockProvider to ensure deterministic, schema-validated generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.domain.enums import (
    ContentClassification,
    EpisodeType,
    ProviderErrorCategory,
    CostClass,
    ReviewState,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PatternStr = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+$")]


# ── World State ──────────────────────────────────────────────────────────


class WorldRule(BaseModel):
    rule_id: PatternStr
    description: NonEmptyStr


class CharacterRef(BaseModel):
    character_id: PatternStr
    canonical_name: NonEmptyStr
    role: NonEmptyStr
    location_id: str | None = None
    status: str = "active"
    knowledge: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    possessions: list[str] = Field(default_factory=list)
    injuries: list[str] = Field(default_factory=list)


class LocationRef(BaseModel):
    location_id: PatternStr
    name: NonEmptyStr
    current_state: str = ""
    connected_locations: list[str] = Field(default_factory=list)


class ClueRef(BaseModel):
    clue_id: PatternStr
    description: NonEmptyStr
    resolved: bool = False


class WorldState(BaseModel):
    world_id: PatternStr
    version: str = Field(min_length=1)
    premise: NonEmptyStr
    genre: str = "urban_mystery"
    world_rules: list[WorldRule] = Field(default_factory=list)
    characters: list[CharacterRef] = Field(default_factory=list, min_length=1)
    locations: list[LocationRef] = Field(default_factory=list, min_length=1)
    clues: list[ClueRef] = Field(default_factory=list)
    canonical_timeline: list[str] = Field(default_factory=list)
    unresolved_global_questions: list[str] = Field(default_factory=list)
    current_canon_episode: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_unique_ids(self):
        char_ids = [c.character_id for c in self.characters]
        if len(char_ids) != len(set(char_ids)):
            raise ValueError("duplicate character_id")
        loc_ids = [l.location_id for l in self.locations]
        if len(loc_ids) != len(set(loc_ids)):
            raise ValueError("duplicate location_id")
        clue_ids = [c.clue_id for c in self.clues]
        if len(clue_ids) != len(set(clue_ids)):
            raise ValueError("duplicate clue_id")
        return self


# ── Episode Plan ─────────────────────────────────────────────────────────


class ScenePlan(BaseModel):
    scene_id: PatternStr
    title: NonEmptyStr
    purpose: NonEmptyStr
    participating_character_ids: list[PatternStr] = Field(default_factory=list)
    location_id: str | None = None


class EpisodePlan(BaseModel):
    plan_version: str = Field(min_length=1)
    world_id: PatternStr
    world_version: str = Field(min_length=1)
    episode_type: EpisodeType
    episode_number: int = Field(ge=1)
    title: NonEmptyStr
    synopsis: NonEmptyStr
    canon_checkpoint_id: str | None = None
    prior_episode_id: str | None = None
    scenes: list[ScenePlan] = Field(min_length=1)
    participating_character_ids: list[PatternStr] = Field(default_factory=list)
    location_ids: list[PatternStr] = Field(default_factory=list)
    clue_refs: list[PatternStr] = Field(default_factory=list)
    next_choice_options: list[NonEmptyStr] = Field(default_factory=list)
    content_classification: ContentClassification = ContentClassification.ADULT

    @model_validator(mode="after")
    def check_unique_scene_ids(self):
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scene_id")
        return self


# ── Episode Content ───────────────────────────────────────────────────────


class ProseBeat(BaseModel):
    scene_id: PatternStr
    paragraphs: list[NonEmptyStr] = Field(min_length=1)


class ContinuityDelta(BaseModel):
    """Explicit, validated world-state changes applied by an episode.

    Every removal or alteration requires an explicit structural entry
    with a source/explanation. Silent disappearance is forbidden.
    """

    character_knowledge_added: dict[str, list[str]] = Field(default_factory=dict)
    character_knowledge_sources: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Source/scene for each knowledge addition per character",
    )
    character_location_changed: dict[str, str] = Field(default_factory=dict)
    character_movement_explanations: dict[str, str] = Field(
        default_factory=dict,
        description="Why a character moved: character_id -> explanation",
    )
    character_injuries_added: dict[str, list[str]] = Field(default_factory=dict)
    character_injuries_removed: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Injuries explicitly healed or removed, per character",
    )
    character_possessions_added: dict[str, list[str]] = Field(default_factory=dict)
    character_possessions_removed: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Possessions explicitly lost, given away, or destroyed",
    )
    character_relationship_changes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Relationship state changes per character",
    )
    clues_introduced: list[ClueRef] = Field(default_factory=list)
    clues_resolved: list[PatternStr] = Field(default_factory=list)
    canon_clue_resolution_explanations: dict[str, str] = Field(
        default_factory=dict,
        description="clue_id -> explanation for each canon clue resolved",
    )
    unresolved_threads: list[NonEmptyStr] = Field(default_factory=list)
    thread_resolutions: dict[str, str] = Field(
        default_factory=dict,
        description="thread_text -> resolution for threads that are explicitly resolved",
    )
    branch_only_facts: list[str] = Field(default_factory=list)


class AppliedReaderInput(BaseModel):
    """Records that a reader choice/comment was visibly applied to a branch."""

    reader_choice_id: str = Field(min_length=1)
    choice_text: NonEmptyStr
    comment: str | None = None
    applied_evidence: NonEmptyStr


class EpisodeContent(BaseModel):
    content_version: str = Field(min_length=1)
    world_id: PatternStr
    episode_type: EpisodeType
    episode_number: int = Field(ge=1)
    title: NonEmptyStr
    synopsis: NonEmptyStr
    canon_snapshot_id: str | None = None
    canon_checkpoint_id: str | None = None
    prior_episode_id: str | None = None
    reader_id: str | None = None
    scenes: list[ScenePlan] = Field(min_length=1)
    prose: list[ProseBeat] = Field(min_length=1)
    clue_refs: list[PatternStr] = Field(default_factory=list)
    world_state_delta: ContinuityDelta = Field(default_factory=ContinuityDelta)
    applied_reader_input: AppliedReaderInput | None = None
    unresolved_threads: list[NonEmptyStr] = Field(default_factory=list)
    next_choice_options: list[NonEmptyStr] = Field(default_factory=list)
    content_classification: ContentClassification = ContentClassification.ADULT
    review_state: ReviewState = ReviewState.PENDING_REVIEW

    @model_validator(mode="after")
    def check_scene_prose_consistency(self):
        scene_ids = {s.scene_id for s in self.scenes}
        for beat in self.prose:
            if beat.scene_id not in scene_ids:
                raise ValueError(
                    f"prose references unknown scene_id: {beat.scene_id}"
                )
        return self

    @model_validator(mode="after")
    def check_first_canon_no_applied_input(self):
        if (
            self.episode_type == EpisodeType.CANON
            and self.episode_number == 1
            and self.applied_reader_input is not None
        ):
            raise ValueError(
                "first canon episode must not have applied reader input"
            )
        return self

    @model_validator(mode="after")
    def check_branch_has_applied_input(self):
        if (
            self.episode_type == EpisodeType.PERSONAL_BRANCH
            and self.applied_reader_input is None
        ):
            raise ValueError(
                "personal branch episode must have applied reader input"
            )
        return self


# ── Reader Choice ────────────────────────────────────────────────────────


class ReaderChoice(BaseModel):
    reader_id: str = Field(min_length=1)
    canon_episode_id: str = Field(min_length=1)
    choice_text: NonEmptyStr
    comment: str | None = Field(default=None, max_length=2000)
    submitted_at: datetime


# ── Provider Result ───────────────────────────────────────────────────────


class ProviderUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(BaseModel):
    provider: str
    advertised_model: str
    cost_class: CostClass = CostClass.FREE
    latency_seconds: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    payload: dict[str, Any] | None = None
    request_id: str | None = None
    error_category: ProviderErrorCategory | None = None
    error_message: str | None = None
    success: bool = False


# ── Pilot Evidence Validation Models ─────────────────────────────────────


class PilotEvidenceRequest(BaseModel):
    """Validated request for creating pilot evidence."""

    evidence_category: str = Field(min_length=1)
    canon_episode_id: str | None = None
    branch_episode_id: str | None = None
    reader_id: str | None = None
    evidence_data: dict[str, Any] = Field(default_factory=dict)
    max_text_length: int = Field(default=2000, ge=1, le=10000)


# ── Rejoin Request Models ─────────────────────────────────────────────────


class RejoinExplanation(BaseModel):
    """Explanation for a single unresolved consequence during rejoin."""

    consequence: NonEmptyStr
    explanation: NonEmptyStr
