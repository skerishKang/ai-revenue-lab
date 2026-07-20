"""Deterministic, personalized ranking of eligible canonical events.

The ranking is a pure function of (eligible events, reader preferences,
applied feedback). It never uses randomness, so the same reader and the same
corpus always produce the same ordered selection, and feedback produces a
reproducible, materially different selection.
"""

from app.domain.enums import Category, FeedbackAction, SourceState
from app.domain.models import ReaderPreferences


def _base_score(category: Category, prefs: ReaderPreferences) -> float:
    score = 0.0
    if category in prefs.interests:
        score += 1.0
    if category in prefs.desired_coverage:
        score += 0.8
    if category in prefs.excluded_categories:
        score -= 2.0
    if prefs.detail_level == "short" and category == Category.OFFICIAL_EVENT:
        score -= 0.1
    return score


def _feedback_adjustment(category: Category, actions) -> float:
    score = 0.0
    action_values = {a.value if hasattr(a, "value") else a for a in actions}
    if (
        FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD.value in action_values
        and category
        in (Category.PLACE_CULTURE, Category.NEIGHBORHOOD)
    ):
        score += 0.8
    if (
        FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT.value in action_values
        and category == Category.PROMOTIONAL_ENTERTAINMENT
    ):
        score -= 1.0
    if FeedbackAction.MORE_PRACTICAL.value in action_values:
        score += 0.2
    return score


def rank_event_ids(
    events,
    prefs: ReaderPreferences,
    feedback_actions: list = None,
) -> list[str]:
    """Return event ids ordered by personalized score (highest first).

    ``events`` may be any objects exposing ``status``, ``category``,
    ``canonical_key`` and ``id``. Withdrawn/superseded events are excluded.
    Conflicting events receive a penalty. Ties are broken deterministically
    by ``canonical_key`` so the ordering is fully reproducible.
    """
    feedback_actions = feedback_actions or []
    scored = []
    for event in events:
        status = event.status
        if status in (SourceState.WITHDRAWN, SourceState.SUPERSEDED):
            continue
        try:
            category = Category(event.category)
        except ValueError:
            category = Category.OTHER
        score = _base_score(category, prefs)
        if status == SourceState.CONFLICTING:
            score -= 0.5
        score += _feedback_adjustment(category, feedback_actions)
        # Negative score for ascending sort; stable tie-break on key.
        scored.append((-score, event.canonical_key, event.id))
    scored.sort()
    return [event_id for _, _, event_id in scored]


def select_top(event_ids: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    return list(event_ids[:limit])
