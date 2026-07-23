"""Reader choice submission workflow — idempotent and privacy-safe.

This service owns the full "one canon choice per reader → one personal branch"
workflow so the web route never persists a choice it cannot recover from and
never leaks provider or database internals.

Contracts enforced here (not in the route):

* A reader holds at most ONE choice per canon episode. Migration 008 adds a
  ``UNIQUE(reader_id, canon_episode_id)`` index as the final defense; this
  service resolves any duplicate submission (same choice, different choice, or
  a concurrent race) to the existing row instead of creating a second choice —
  and therefore never a second branch.
* Choice creation and branch generation share one stable idempotency key
  (keyed on the reused ``reader_choice_id`` plus the canon checkpoint). A
  generation failure leaves a retryable ``failed`` generation request that a
  later submission resumes through the Phase 1 CAS state machine — the reader
  is never permanently blocked and no duplicate branch is created.
* Every outcome collapses to a small set of privacy-safe statuses; raw SQLite
  errors, duplicate-key detail, and provider/internal exceptions never reach
  the caller.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from app import choice_repository as choice_repo
from app.ai.base import AIProvider
from app.domain.enums import EpisodeType
from app.pipeline.service import GenerationRequest, generate_personal_branch
from app.utils import new_id


@dataclass(frozen=True)
class ChoiceSubmission:
    """Privacy-safe outcome of a choice submission attempt.

    ``status`` is one of:
      * ``submitted`` — a new personal branch was generated for this choice.
      * ``already_completed`` — the reader already had a choice for this canon
        (applied to a branch, or a completed generation replayed); nothing new
        was created.
      * ``generation_failed`` — the choice is persisted but branch generation
        failed; the same submission can be retried and will resume the failed
        generation request rather than creating a duplicate.
      * ``conflict`` — the reader already submitted a different choice (or a
        different comment) for this canon episode. The first submission wins;
        no provider call, no new choice/branch/episode is created, and the
        existing private comment is never silently overwritten.
    """

    status: str
    branch_episode_id: str | None = None
    choice_id: str | None = None


# build_provider(choice_id, choice_text, comment) -> AIProvider
ProviderBuilder = Callable[[str, str, str | None], AIProvider]


def submit_reader_choice(
    conn: sqlite3.Connection,
    *,
    world,
    world_id: str,
    reader_id: str,
    canon_episode_id: str,
    canon_checkpoint_id: str,
    choice_text: str,
    comment: str | None,
    build_provider: ProviderBuilder,
) -> ChoiceSubmission:
    """Submit (or safely resume) the reader's single choice for a canon episode.

    The caller supplies a ``build_provider`` factory so this service stays
    decoupled from the preview MockProvider construction used by the web layer.
    """
    # 1. Idempotency anchor: resolve the reader's existing choice for this
    #    canon. At most one row can exist (migration 008 unique index).
    choice = choice_repo.get_choice_for_reader_canon(
        conn, reader_id, canon_episode_id
    )
    if choice is None:
        try:
            choice = choice_repo.create_reader_choice(
                conn,
                choice_id=new_id(),
                reader_id=reader_id,
                canon_episode_id=canon_episode_id,
                choice_text=choice_text,
                comment=comment,
            )
        except choice_repo.ChoiceValidationError:
            # Lost a race or a duplicate submit: the unique constraint rejected
            # a second row. Resolve to the existing choice — the reader's first
            # choice wins; no second choice or branch is created.
            choice = choice_repo.get_choice_for_reader_canon(
                conn, reader_id, canon_episode_id
            )
            if choice is None:
                # Constraint fired but no readable row — treat as a duplicate.
                return ChoiceSubmission(status="already_completed")

    # 2. Conflict: the reader already submitted a different choice text or a
    #    different comment for this canon. First submission wins — no provider
    #    call, no new choice/branch/episode, and the existing private comment
    #    is never silently overwritten.
    if choice.choice_text != choice_text or choice.comment != comment:
        return ChoiceSubmission(status="conflict", choice_id=choice.id)

    # 3. Already applied to a branch → idempotent success, nothing to generate.
    if choice.applied_to_branch_id is not None:
        return ChoiceSubmission(
            status="already_completed",
            branch_episode_id=choice.applied_to_branch_id,
            choice_id=choice.id,
        )

    # 4. Generate the personal branch. The idempotency key is derived from the
    #    stable choice.id + canon checkpoint, so a retry after failure reclaims
    #    the failed generation request (CAS failed→pending) instead of creating
    #    a duplicate branch.
    provider = build_provider(choice.id, choice.choice_text, choice.comment)
    gen_request = GenerationRequest(
        world=world,
        episode_type=EpisodeType.PERSONAL_BRANCH,
        reader_id=reader_id,
        reader_choice_id=choice.id,
        reader_choice_text=choice.choice_text,
        reader_comment=choice.comment,
    )
    result = generate_personal_branch(
        conn,
        provider,
        gen_request,
        world_id=world_id,
        canon_checkpoint_id=canon_checkpoint_id,
        prior_episode_id=canon_episode_id,
    )

    if result.succeeded:
        return ChoiceSubmission(
            status="submitted",
            branch_episode_id=result.episode_id,
            choice_id=choice.id,
        )
    return ChoiceSubmission(status="generation_failed", choice_id=choice.id)
