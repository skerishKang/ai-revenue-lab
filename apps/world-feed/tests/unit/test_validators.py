import pytest

from app.domain.enums import Category, SourceState
from app.domain.models import SourceCard
from app.validators import (
    derive_event_status,
    is_eligible,
    requires_uncertainty,
    summarize_source_states,
)
from tests.conftest import make_source


class TestSourceStateDerivation:
    def test_withdrawn_wins(self):
        assert derive_event_status(
            [SourceState.SINGLE_SOURCE, SourceState.WITHDRAWN]
        ) == SourceState.WITHDRAWN

    def test_superseded_wins_over_conflicting(self):
        assert derive_event_status(
            [SourceState.CONFLICTING, SourceState.SUPERSEDED]
        ) == SourceState.SUPERSEDED

    def test_conflicting_detected(self):
        assert derive_event_status(
            [SourceState.SINGLE_SOURCE, SourceState.CONFLICTING]
        ) == SourceState.CONFLICTING

    def test_multi_source_when_independent(self):
        assert derive_event_status(
            [SourceState.SINGLE_SOURCE, SourceState.SINGLE_SOURCE]
        ) == SourceState.MULTI_SOURCE

    def test_single_source(self):
        assert derive_event_status(
            [SourceState.SINGLE_SOURCE]
        ) == SourceState.SINGLE_SOURCE

    def test_is_eligible(self):
        assert is_eligible(SourceState.SINGLE_SOURCE)
        assert is_eligible(SourceState.MULTI_SOURCE)
        assert is_eligible(SourceState.CONFLICTING)
        assert not is_eligible(SourceState.WITHDRAWN)
        assert not is_eligible(SourceState.SUPERSEDED)

    def test_requires_uncertainty(self):
        assert requires_uncertainty(SourceState.CONFLICTING)
        assert not requires_uncertainty(SourceState.SINGLE_SOURCE)


class TestSummarizeGroup:
    def test_conflicting_group_sets_uncertainty(self):
        sources = [
            make_source("s1", "ev-x", Category.OFFICIAL_EVENT,
                        source_state=SourceState.SINGLE_SOURCE),
            make_source("s2", "ev-x", Category.OFFICIAL_EVENT,
                        source_state=SourceState.CONFLICTING),
        ]
        view = summarize_source_states(sources)
        assert view["status"] == SourceState.CONFLICTING
        assert view["eligible"] is True
        assert view["uncertainty_note"] is not None
        assert set(view["source_ids"]) == {"s1", "s2"}
        assert view["conflicting_source_ids"] == ["s2"]

    def test_withdrawn_group_not_eligible(self):
        sources = [
            make_source("s1", "ev-y", Category.PLACE_CULTURE,
                        source_state=SourceState.SINGLE_SOURCE),
            make_source("s2", "ev-y", Category.PLACE_CULTURE,
                        source_state=SourceState.WITHDRAWN),
        ]
        view = summarize_source_states(sources)
        assert view["status"] == SourceState.WITHDRAWN
        assert view["eligible"] is False
