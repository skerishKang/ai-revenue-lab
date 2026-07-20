from app.domain.enums import Category, FeedbackAction, SourceState
from app.domain.models import ReaderPreferences
from app.ranking import rank_event_ids, select_top


class _Event:
    def __init__(self, event_id, status, category, canonical_key):
        self.id = event_id
        self.status = status
        self.category = category.value if hasattr(category, "value") else category
        self.canonical_key = canonical_key


def _events():
    return [
        _Event("e1", SourceState.SINGLE_SOURCE, Category.PLACE_CULTURE, "k1"),
        _Event("e2", SourceState.SINGLE_SOURCE, Category.NEIGHBORHOOD, "k2"),
        _Event("e3", SourceState.SINGLE_SOURCE, Category.PROMOTIONAL_ENTERTAINMENT, "k3"),
        _Event("e4", SourceState.SINGLE_SOURCE, Category.OFFICIAL_EVENT, "k4"),
        # Culture item that is NOT already top-ranked (key sorts after promo).
        _Event("e8", SourceState.SINGLE_SOURCE, Category.PLACE_CULTURE, "kz-culture"),
        _Event("e5", SourceState.WITHDRAWN, Category.PLACE_CULTURE, "k5"),
        _Event("e6", SourceState.SUPERSEDED, Category.NEIGHBORHOOD, "k6"),
        _Event("e7", SourceState.CONFLICTING, Category.OFFICIAL_EVENT, "k7"),
    ]


class TestRanking:
    def test_withdrawn_and_superseded_excluded(self):
        ranked = rank_event_ids(_events(), ReaderPreferences(), [])
        assert "e5" not in ranked
        assert "e6" not in ranked

    def test_conflicting_penalized_but_present(self):
        ranked = rank_event_ids(_events(), ReaderPreferences(), [])
        assert "e7" in ranked

    def test_interests_boost(self):
        prefs = ReaderPreferences(
            interests=[Category.PLACE_CULTURE, Category.NEIGHBORHOOD]
        )
        ranked = rank_event_ids(_events(), prefs, [])
        assert ranked[0] == "e1"
        assert ranked[1] == "e2"

    def test_feedback_increases_culture_neighborhood(self):
        prefs = ReaderPreferences()
        base = rank_event_ids(_events(), prefs, [])
        fed = rank_event_ids(
            _events(), prefs, [FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD.value]
        )
        # e8 (culture) starts after the promo event e3; feedback lifts it above.
        assert base.index("e8") > base.index("e3")
        assert fed.index("e8") < fed.index("e3")

    def test_feedback_reduces_promotional_entertainment(self):
        prefs = ReaderPreferences()
        base = rank_event_ids(_events(), prefs, [])
        fed = rank_event_ids(
            _events(), prefs, [FeedbackAction.REDUCE_PROMOTIONAL_ENTERTAINMENT.value]
        )
        assert fed.index("e3") > base.index("e3")

    def test_deterministic_ordering(self):
        prefs = ReaderPreferences(
            interests=[Category.PLACE_CULTURE, Category.NEIGHBORHOOD]
        )
        a = rank_event_ids(_events(), prefs, [])
        b = rank_event_ids(_events(), prefs, [])
        assert a == b

    def test_select_top_limits(self):
        ranked = rank_event_ids(_events(), ReaderPreferences(), [])
        assert select_top(ranked, 3) == ranked[:3]
        assert select_top(ranked, 0) == []
