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
    validate_tags,
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


# Map match levels to deterministic scores
_MATCH_SCORES = {
    "strong": 1.0,
    "possible": 0.5,
    "noise": 0.0,
}


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

            # Batch classify all videos in the page (not one-by-one)
            classifications = self._llm.classify_videos(page.videos, rules)
            cls_by_video = {
                c.video_id: c for c in classifications
            }

            for video in page.videos:
                existing = self._videos.get_by_provider_id(
                    video.provider, video.provider_video_id
                )
                if existing is None:
                    self._videos.upsert(video)
                    videos_added += 1
                else:
                    if existing.title != video.title or existing.view_count != video.view_count:
                        self._videos.upsert(video)
                        videos_updated += 1

                # Link topic-video (deduplication handled by repository)
                tv = self._topic_videos.link(topic_id, video.id)

                # Apply batch classification results
                cls = cls_by_video.get(video.id)
                if cls is not None:
                    score = _MATCH_SCORES.get(cls.match_level, 0.0)
                    self._topic_videos.update_match(
                        tv.id,
                        match_score=score,
                        match_reasons=cls.reasons,
                        is_excluded=cls.is_excluded_candidate,
                    )

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
        state_filter: str | None = None,
    ) -> list[tuple[TopicVideo, DiscoveredVideo, PrivateViewingRecord | None]]:
        """Get topic feed with optional state filtering.

        Returns (TopicVideo, DiscoveredVideo, record_or_none) tuples.
        """
        return self._topic_videos.list_for_topic_with_records(
            topic_id,
            sort=sort,
            exclude_irrelevant=exclude_irrelevant,
            state_filter=state_filter,
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

    def delete_timestamp_ref(self, ts_id: str) -> None:
        self._records.delete_timestamp_ref(ts_id)

    def propose_structure(
        self, record_id: str, rough_notes: str
    ) -> ProposalRecord:
        """Generate an LLM structure proposal from rough notes.

        Validation order:
        1. Record existence check
        2. Input length validation
        3. Provider invocation (only after validation passes)
        4. Result validation as RecordStructureProposal
        5. Persist proposal with validation status
        """
        # 1. Record existence check
        record = self._records.get(record_id)
        if record is None:
            raise ValueError(f"Record not found: {record_id}")

        # 2. Input length validation BEFORE provider call
        if len(rough_notes) > 20000:
            return self._proposals.create(
                proposal_type=ProposalType.RECORD_STRUCTURE,
                proposed_json="{}",
                input_text=rough_notes[:20000],
                record_id=record_id,
                validation_status=ValidationStatus.INVALID,
                validation_error="input notes exceed 20000 characters",
            )

        # 3. Provider invocation (only after validation passes)
        proposal = self._llm.structure_record(rough_notes)

        # 4. Validate result as RecordStructureProposal
        validation_status = ValidationStatus.VALID
        validation_error = ""
        try:
            # Re-validate by constructing the model
            RecordStructureProposal(
                title=proposal.title,
                summary=proposal.summary,
                reflection=proposal.reflection,
                learned_point=proposal.learned_point,
                agreement=proposal.agreement,
                disagreement=proposal.disagreement,
                uncertainty=proposal.uncertainty,
                follow_up_plan=proposal.follow_up_plan,
                tags=proposal.tags,
                timestamp_references=proposal.timestamp_references,
                rating=proposal.rating,
            )
        except Exception as exc:
            validation_status = ValidationStatus.INVALID
            validation_error = str(exc)

        # 5. Persist proposal with validation status
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
        """Accept a structure proposal and apply it to the record.

        All operations are wrapped in a transaction. If any step fails,
        all changes are rolled back.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")
        if proposal.proposal_type != ProposalType.RECORD_STRUCTURE:
            raise ValueError(
                f"Proposal is not a record_structure proposal: "
                f"{proposal.proposal_type}"
            )
        if proposal.validation_status != ValidationStatus.VALID:
            raise ValueError(
                f"Proposal validation failed: {proposal.validation_error}"
            )

        # Revalidate persisted JSON as RecordStructureProposal
        try:
            data = json.loads(proposal.proposed_json)
            RecordStructureProposal(
                title=data.get("title", ""),
                summary=data.get("summary", ""),
                reflection=data.get("reflection", ""),
                learned_point=data.get("learned_point", ""),
                agreement=data.get("agreement", ""),
                disagreement=data.get("disagreement", ""),
                uncertainty=data.get("uncertainty", ""),
                follow_up_plan=data.get("follow_up_plan", ""),
                tags=data.get("tags", []),
                timestamp_references=data.get("timestamp_references", []),
                rating=data.get("rating"),
            )
        except (json.JSONDecodeError, Exception) as exc:
            raise ValueError(f"Proposal JSON is invalid: {exc}")

        record = self._records.get(proposal.record_id)
        if record is None:
            raise ValueError(f"Record not found: {proposal.record_id}")

        # Apply the whole proposal as ONE transaction. Repository methods are
        # called with commit=False so their internal commits cannot make the
        # outer rollback ineffective; a single commit happens only after every
        # step succeeds, and any failure rolls back record, timestamps, and
        # proposal status together.
        conn = self._records._conn

        try:
            # Collect existing timestamp IDs for replacement
            existing_ts = self._records.list_timestamp_refs(record.id)
            existing_ts_ids = [ts.id for ts in existing_ts]

            # Apply structured fields, preserve original free_form_note
            updates = {
                "reflection": data.get("reflection", ""),
                "learned_point": data.get("learned_point", ""),
                "agreement": data.get("agreement", ""),
                "disagreement": data.get("disagreement", ""),
                "uncertainty": data.get("uncertainty", ""),
                "follow_up_plan": data.get("follow_up_plan", ""),
                "tags": data.get("tags", []),
            }

            if data.get("rating") is not None:
                updates["rating"] = data["rating"]

            self._records.update(record.id, commit=False, **updates)

            # Replace timestamps: delete old, add new
            for ts_id in existing_ts_ids:
                self._records.delete_timestamp_ref(ts_id, commit=False)

            for ts_data in data.get("timestamp_references", []):
                self._records.add_timestamp_ref(
                    record.id,
                    ts_data["timestamp_seconds"],
                    ts_data.get("label", ""),
                    commit=False,
                )

            # Mark proposal as accepted
            self._proposals.update_status(
                proposal_id, ProposalStatus.ACCEPTED, commit=False
            )

            conn.commit()
            return self._records.get(record.id)

        except Exception:
            conn.rollback()
            raise

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
        """Accept a rule-change proposal and apply it.

        Revalidates persisted JSON as RuleChangeProposal before applying.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal not found: {proposal_id}")
        if proposal.status != ProposalStatus.PENDING:
            raise ValueError(f"Proposal is not pending: {proposal.status}")

        # Revalidate persisted JSON as RuleChangeProposal
        try:
            data = json.loads(proposal.proposed_json)
            RuleChangeProposal(
                added_excluded_terms=data.get("added_excluded_terms", []),
                added_related_queries=data.get("added_related_queries", []),
                preferred_channels=data.get("preferred_channels", []),
                excluded_channels=data.get("excluded_channels", []),
                exclude_shorts=data.get("exclude_shorts", False),
                date_window_start=data.get("date_window_start"),
                date_window_end=data.get("date_window_end"),
                duration_preference=data.get("duration_preference"),
                rationale=data.get("rationale", ""),
            )
        except (json.JSONDecodeError, Exception) as exc:
            raise ValueError(f"Proposal JSON is invalid: {exc}")

        topic_id = proposal.topic_id
        if topic_id is None:
            raise ValueError("Proposal has no topic_id")

        rules = self._rules.get_active(topic_id)
        if rules is None:
            raise ValueError(f"No active rule for topic: {topic_id}")

        # Build updated rule fields
        updates: dict[str, Any] = {}

        existing_excluded = list(rules.excluded_terms)
        for term in data.get("added_excluded_terms", []):
            if term not in existing_excluded:
                existing_excluded.append(term)
        updates["excluded_terms"] = existing_excluded

        existing_related = list(rules.related_queries)
        for term in data.get("added_related_queries", []):
            if term not in existing_related:
                existing_related.append(term)
        updates["related_queries"] = existing_related

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

        if data.get("exclude_shorts"):
            updates["shorts_preference"] = "exclude"

        if data.get("date_window_start"):
            updates["date_window_start"] = data["date_window_start"]
        if data.get("date_window_end"):
            updates["date_window_end"] = data["date_window_end"]

        if data.get("duration_preference"):
            updates["duration_preference"] = data["duration_preference"]

        # Apply rule update and proposal acceptance as ONE transaction so a
        # failure after the rule write cannot leave the proposal pending while
        # the rule is already changed (or vice versa).
        conn = self._rules._conn
        try:
            result = self._rules.update(rules.id, commit=False, **updates)
            self._proposals.update_status(
                proposal_id, ProposalStatus.ACCEPTED, commit=False
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

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
