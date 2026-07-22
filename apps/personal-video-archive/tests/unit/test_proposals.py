"""Unit tests for LLM proposal validation and safety."""

from __future__ import annotations

import json

import pytest

from app.domain.enums import (
    ProposalStatus,
    ProposalType,
    ValidationStatus,
)
from app.domain.models import (
    QueryRuleProposal,
    RecordStructureProposal,
    RuleChangeProposal,
)
from app.providers.fake_language_model import FakeLanguageModelProvider


class TestProposalValidation:
    def test_query_rule_proposal_valid(self, fake_llm):
        proposal = fake_llm.propose_query_rules(
            "ChatGPT updates excluding Shorts"
        )
        assert len(proposal.primary_query) > 0
        assert proposal.default_sort.value == "newest"

    def test_record_structure_proposal_valid(self, fake_llm):
        proposal = fake_llm.structure_record(
            "reflection: Great video\nplan: Try this\nrating: 5"
        )
        assert proposal.rating == 5
        assert len(proposal.reflection) > 0

    def test_malformed_input_handled(self, fake_llm):
        """Empty or malformed input should not crash."""
        proposal = fake_llm.structure_record("")
        assert proposal.reflection == ""

    def test_excessive_input_handled(self, fake_llm):
        """Very long input should be handled gracefully."""
        long_text = "x" * 50000
        proposal = fake_llm.structure_record(long_text)
        assert proposal.reflection == long_text[:5000]


class TestProposalLifecycle:
    def test_proposal_pending_by_default(self, repos, fake_llm):
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json='{"title": "test"}',
            input_text="test input",
        )
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.validation_status == ValidationStatus.VALID

    def test_proposal_accept(self, repos):
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json='{"reflection": "test"}',
        )
        updated = repos["proposal"].update_status(
            proposal.id, ProposalStatus.ACCEPTED
        )
        assert updated.status == ProposalStatus.ACCEPTED
        assert updated.decided_at is not None

    def test_proposal_reject(self, repos):
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json='{"reflection": "test"}',
        )
        updated = repos["proposal"].update_status(
            proposal.id, ProposalStatus.REJECTED
        )
        assert updated.status == ProposalStatus.REJECTED

    def test_double_accept_rejected(self, repos, record_service):
        """Cannot accept/reject a proposal twice."""
        proposal = repos["proposal"].create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json='{"reflection": "test"}',
        )
        repos["proposal"].update_status(
            proposal.id, ProposalStatus.ACCEPTED
        )
        with pytest.raises(ValueError, match="not pending"):
            record_service.accept_structure_proposal(proposal.id)


class TestOriginalTextPreservation:
    def test_free_form_note_preserved_on_accept(self, repos, fake_llm, record_service):
        """Accepting a structure proposal must not overwrite free_form_note."""
        # Create a topic-video-record chain
        topic = repos["topic"].create("Test", "intent")
        rule = repos["rule"].create_from_proposal(topic.id, QueryRuleProposal(
            primary_query="test",
        ))
        video = repos["video"].upsert(
            __import__("app.domain.models", fromlist=["DiscoveredVideo"]).DiscoveredVideo(
                id="v1", provider="youtube",
                provider_video_id="dQw4w9WgXcQ",
                canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                title="Test",
                published_at="2026-07-15T10:00:00Z",
            )
        )
        tv = repos["topic_video"].link(topic.id, video.id)
        record = repos["record"].create(tv.id)

        # Set original note
        original_note = "My original rough note that must be preserved."
        repos["record"].update(record.id, free_form_note=original_note)

        # Create and accept a structure proposal
        proposal = record_service.propose_structure(record.id, original_note)
        record_service.accept_structure_proposal(proposal.id)

        # Verify original note is preserved
        updated = repos["record"].get(record.id)
        assert updated.free_form_note == original_note
