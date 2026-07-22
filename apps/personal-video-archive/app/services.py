"""Business logic services for Personal Video Archive.

Services orchestrate repositories and providers to implement the user
workflows described in the product contract.  No I/O or HTTP coupling.
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.enums import (
    DefaultSort,
    ProposalStatus,
    ProposalType,
    Provenance,
    SyncStatus,
    ValidationStatus,
    ViewingState,
)
from app.domain.models import (
    DiscoveredVideo,
    PrivateViewingRecord,
    ProposalRecord,
    QueryRule,
    QueryRuleProposal,
    RecordStructureProposal,
    RuleChangeProposal,
    SyncRun,
    TimestampReference,
    Topic,
    TopicVideo,
    VideoClassification,
)
from app.providers import (
    LanguageModelProvider,
    VideoDiscoveryProvider,
)
from app.repositories import (
    ProposalRepository,
    QuotaLedgerRepository,
    QueryRuleRepository,
    SyncRunRepository,
    TopicRepository,
    TopicVideoRepository,
    VideoRepository,
    ViewingRecordRepository,
)


class TopicService:
    """Manages topic lifecycle and query-rule creation."""

    def __init__(
        self,
        topic_repo: TopicRepository,
        rule_repo: QueryRuleRepository,
        llm: LanguageModelProvider,
    ):
        self._topics = topic_repo
        self._rules = rule_repo
        self._llm = llm

    def create_topic(
        self, name: str, intent: str
    ) -> tuple[Topic, QueryRuleProposal]:
        """Create a topic and get an LLM-proposed rule draft."""
        topic = self._topics.create(name=name, intent=intent)
        proposal = self._llm.propose_query_rules(intent)
        return topic, proposal

    def accept_rule_draft(
        self, topic_id: str, proposal: QueryRuleProposal
    ) -> QueryRule:
        """Persist a user-accepted query rule draft as the active rule."""
        return self._rules.create_from_proposal(topic_id, proposal)

    def get_topic(self, topic_id: str) -> Topic | None:
        return self._topics.get(topic_id)

    def list_topics(self, include_archived: bool = False) -> list[Topic]:
        if include_archived:
            return self._topics.list_all()
        return self._topics.list_active()

    def archive_topic(self, topic_id: str) -> Topic | None:
        return self._topics.update(topic_id, is_archived=True)

    def get_active_rule(self, topic_id: str) -> QueryRule | None:
        return self._rules.get_active(topic_id)

    def update_rule(
        self, rule_id: str, **fields
    ) -> QueryRule | None:
        return self._rules.update(rule_id, **fields)


class DiscoveryService:
    """Runs discovery sync and manages deduplication."""

    def __init__(
        self,
        topic_repo: TopicRepository,
        rule_repo: QueryRuleRepository,
        video_repo: VideoRepository,
        topic_video_repo: TopicVideoRepository,
        sync_repo: SyncRunRepository,
        quota_repo: QuotaLedgerRepository,
        discovery: VideoDiscoveryProvider,
        llm: LanguageModelProvider,
    ):
        self._topics = topic_repo
        self._rules = rule_repo
        self._videos = video_repo
        self._topic_videos = topic_video_repo
        self._sync = sync_repo
        self._quota = quota_repo
        self._discovery = discovery
        self._llm = llm

    def sync_topic(
        self, topic_id: str, cursor: str | None = None
    ) -> tuple[SyncRun, list[tuple[TopicVideo, DiscoveredVideo]]]:
        """Run a discovery sync for a topic and return results."""
        topic = self._topics.get(topic_id)
        if topic is None:
            raise ValueError(f"Topic not found: {topic_id}")

        rules = self._rules.get_active(topic_id)
        if rules is None:
            raise ValueError(f"No active rule for topic: {topic_id}")

        run = self._sync.create(topic_id, self._discovery.__class__.__name__)

        try:
            page = self._discovery.search_videos(rules, cursor)
            videos_found = len(page.videos)
            videos_added = 0
            videos_updated = 0

            for video in page.videos:
                existing = self._videos.get_by_provider_id(
                    video.provider, video.provider_video_id
                )
                if existing is None:
                    self._videos.upsert(video)
                    videos_added += 1
                else:
                    # Update metadata if changed
                    if existing.title != video.title or existing.view_count != video.view_count:
                        self._videos.upsert(video)
                        videos_updated += 1

                # Link topic-video (deduplication handled by repository)
                tv = self._topic_videos.link(topic_id, video.id)

                # Apply LLM classification if available
                # (in Phase 1, we use the fake provider)
                classifications = self._llm.classify_videos([video], rules)
                if classifications:
                    cls = classifications[0]
                    if cls.is_excluded_candidate:
                        self._topic_videos.set_excluded(tv.id, True)

            # Record quota
            self._quota.record(
                topic_id=topic_id,
                provider=self._discovery.__class__.__name__,
                operation="search",
                cost=page.quota_cost,
                sync_run_id=run.id,
            )

            run = self._sync.complete(
                run.id,
                SyncStatus.COMPLETED,
                videos_found=videos_found,
                videos_added=videos_added,
                videos_updated=videos_updated,
                quota_cost=page.quota_cost,
            )

            results = self._topic_videos.list_for_topic(
                topic_id, sort=rules.default_sort.value
            )
            return run, results

        except Exception as exc:
            self._sync.complete(
                run.id,
                SyncStatus.FAILED,
                error_message=str(exc),
            )
            raise

    def get_topic_feed(
        self,
        topic_id: str,
        sort: str = "newest",
        exclude_irrelevant: bool = True,
    ) -> list[tuple[TopicVideo, DiscoveredVideo]]:
        return self._topic_videos.list_for_topic(
            topic_id, sort=sort, exclude_irrelevant=exclude_irrelevant
        )

    def get_video_classifications(
        self, topic_id: str
    ) -> list[VideoClassification]:
        """Get LLM classifications for all videos in a topic feed."""
        rules = self._rules.get_active(topic_id)
        if rules is None:
            return []
        feed = self._topic_videos.list_for_topic(topic_id, exclude_irrelevant=False)
        videos = [v for _, v in feed]
        return self._llm.classify_videos(videos, rules)


class RecordService:
    """Manages private viewing records and LLM structure proposals."""

    def __init__(
        self,
        topic_video_repo: TopicVideoRepository,
        record_repo: ViewingRecordRepository,
        proposal_repo: ProposalRepository,
        llm: LanguageModelProvider,
    ):
        self._topic_videos = topic_video_repo
        self._records = record_repo
        self._proposals = proposal_repo
        self._llm = llm

    def get_or_create_record(
        self, topic_video_id: str
    ) -> PrivateViewingRecord:
        record = self._records.get_by_topic_video(topic_video_id)
        if record is None:
            record = self._records.create(topic_video_id)
        return record

    def update_record(
        self, record_id: str, **fields
    ) -> PrivateViewingRecord | None:
        return self._records.update(record_id, **fields)

    def add_timestamp_ref(
        self, record_id: str, seconds: int, label: str = ""
    ) -> TimestampReference:
        return self._records.add_timestamp_ref(record_id, seconds, label)

    def propose_structure(
        self, record_id: str, rough_notes: str
    ) -> ProposalRecord:
        """Generate an LLM structure proposal from rough notes."""
        proposal = self._llm.structure_record(rough_notes)

        # Validate the proposal
        validation_status = ValidationStatus.VALID
        validation_error = ""

        # Check for excessive length
        if len(rough_notes) > 20000:
            validation_status = ValidationStatus.INVALID
            validation_error = "input notes exceed 20000 characters"

        # Validate tags
        for tag in proposal.tags:
            if len(tag) > 40 or not tag[0].isalnum():
                validation_status = ValidationStatus.INVALID
                validation_error = f"invalid tag: {tag!r}"
                break

        proposed_json = json.dumps(
            proposal.model_dump(mode="json"), ensure_ascii=False
        )

        return self._proposals.create(
            proposal_type=ProposalType.RECORD_STRUCTURE,
            proposed_json=proposed_json,
            input_text=rough_notes,
            record_id=record_id,
            validation_status=validation_status,
            validation_error=validation_error,
        )

    def accept_structure_proposal(
        self, proposal_id: str
    ) -> PrivateViewingRecord | None:
        """Accept a structure proposal and apply it to the record."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")

        data = json.loads(proposal.proposed_json)
        record = self._records.get(proposal.record_id)
        if record is None:
            raise ValueError(f"Record not found: {proposal.record_id}")

        # Apply structured fields, but preserve original free_form_note
        updates = {
            "reflection": data.get("reflection", ""),
            "learned_point": data.get("learned_point", ""),
            "agreement": data.get("agreement", ""),
            "disagreement": data.get("disagreement", ""),
            "uncertainty": data.get("uncertainty", ""),
            "follow_up_plan": data.get("follow_up_plan", ""),
            "tags": data.get("tags", []),
        }

        # Apply timestamp references
        for ts_data in data.get("timestamp_references", []):
            self._records.add_timestamp_ref(
                record.id,
                ts_data["timestamp_seconds"],
                ts_data.get("label", ""),
            )

        # Apply rating if provided
        if data.get("rating") is not None:
            updates["rating"] = data["rating"]

        result = self._records.update(record.id, **updates)

        # Mark proposal as accepted
        self._proposals.update_status(
            proposal_id, ProposalStatus.ACCEPTED
        )

        return result

    def reject_structure_proposal(
        self, proposal_id: str
    ) -> ProposalRecord:
        """Reject a structure proposal (original text is preserved)."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")

        return self._proposals.update_status(
            proposal_id, ProposalStatus.REJECTED
        )

    def search_records(
        self,
        topic_id: str | None = None,
        state: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
    ) -> list[tuple[PrivateViewingRecord, TopicVideo, DiscoveredVideo]]:
        return self._records.search(
            topic_id=topic_id, state=state, tags=tags, query=query
        )


class ProposalService:
    """Manages LLM proposals for query rules and rule changes."""

    def __init__(
        self,
        topic_repo: TopicRepository,
        rule_repo: QueryRuleRepository,
        proposal_repo: ProposalRepository,
        llm: LanguageModelProvider,
    ):
        self._topics = topic_repo
        self._rules = rule_repo
        self._proposals = proposal_repo
        self._llm = llm

    def propose_rule_change(
        self,
        topic_id: str,
        feedback: list[tuple[str, bool]],
    ) -> ProposalRecord:
        """Generate a rule-change proposal from user feedback."""
        rules = self._rules.get_active(topic_id)
        if rules is None:
            raise ValueError(f"No active rule for topic: {topic_id}")

        proposal = self._llm.suggest_rule_changes(feedback, rules)
        proposed_json = json.dumps(
            proposal.model_dump(mode="json"), ensure_ascii=False
        )

        return self._proposals.create(
            proposal_type=ProposalType.RULE_CHANGE,
            proposed_json=proposed_json,
            input_text=f"feedback: {len(feedback)} items",
            topic_id=topic_id,
        )

    def accept_rule_change(
        self, proposal_id: str
    ) -> QueryRule | None:
        """Accept a rule-change proposal and apply it."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")

        data = json.loads(proposal.proposed_json)
        topic_id = proposal.topic_id
        if topic_id is None:
            raise ValueError("Proposal has no topic_id")

        rules = self._rules.get_active(topic_id)
        if rules is None:
            raise ValueError(f"No active rule for topic: {topic_id}")

        # Build updated rule fields
        updates: dict[str, Any] = {}

        # Add excluded terms
        existing_excluded = list(rules.excluded_terms)
        for term in data.get("added_excluded_terms", []):
            if term not in existing_excluded:
                existing_excluded.append(term)
        updates["excluded_terms"] = existing_excluded

        # Add related queries
        existing_related = list(rules.related_queries)
        for term in data.get("added_related_queries", []):
            if term not in existing_related:
                existing_related.append(term)
        updates["related_queries"] = existing_related

        # Update channels
        if data.get("preferred_channels"):
            existing_included = list(rules.included_channels)
            for ch in data["preferred_channels"]:
                if ch not in existing_included:
                    existing_included.append(ch)
            updates["included_channels"] = existing_included

        if data.get("excluded_channels"):
            existing_excluded_ch = list(rules.excluded_channels)
            for ch in data["excluded_channels"]:
                if ch not in existing_excluded_ch:
                    existing_excluded_ch.append(ch)
            updates["excluded_channels"] = existing_excluded_ch

        # Shorts
        if data.get("exclude_shorts"):
            updates["shorts_preference"] = "exclude"

        # Date window
        if data.get("date_window_start"):
            updates["date_window_start"] = data["date_window_start"]
        if data.get("date_window_end"):
            updates["date_window_end"] = data["date_window_end"]

        # Duration
        if data.get("duration_preference"):
            updates["duration_preference"] = data["duration_preference"]

        result = self._rules.update(rules.id, **updates)

        self._proposals.update_status(
            proposal_id, ProposalStatus.ACCEPTED
        )

        return result

    def reject_rule_change(self, proposal_id: str) -> ProposalRecord:
        """Reject a rule-change proposal."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")

        return self._proposals.update_status(
            proposal_id, ProposalStatus.REJECTED
        )
