"""Data access repositories for Personal Video Archive.

Each repository is a thin data-mapper over SQLite rows, returning domain
model objects.  No business logic lives here — that belongs in services.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.domain.enums import (
    DefaultSort,
    DurationPreference,
    ProposalStatus,
    ProposalType,
    Provenance,
    ShortsPreference,
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
    QuotaLedgerEntry,
    RecordStructureProposal,
    RuleChangeProposal,
    SyncRun,
    TimestampReference,
    Topic,
    TopicVideo,
    VideoClassification,
)


def _new_id() -> str:
    return uuid.uuid4().hex[:24]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Topic repository
# ---------------------------------------------------------------------------

class TopicRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, name: str, intent: str) -> Topic:
        topic_id = _new_id()
        now = _now()
        self._conn.execute(
            "INSERT INTO topics (id, name, intent, is_archived, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (topic_id, name.strip(), intent.strip(), now, now),
        )
        self._conn.commit()
        return self.get(topic_id)

    def get(self, topic_id: str) -> Topic | None:
        row = self._conn.execute(
            "SELECT * FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_topic(row)

    def list_active(self) -> list[Topic]:
        rows = self._conn.execute(
            "SELECT * FROM topics WHERE is_archived = 0 ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_topic(r) for r in rows]

    def list_all(self) -> list[Topic]:
        rows = self._conn.execute(
            "SELECT * FROM topics ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_topic(r) for r in rows]

    def update(self, topic_id: str, **fields) -> Topic | None:
        allowed = {"name", "intent", "is_archived"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(topic_id)
        now = _now()
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [topic_id]
        self._conn.execute(
            f"UPDATE topics SET {set_clause} WHERE id = ?", params
        )
        self._conn.commit()
        return self.get(topic_id)

    def delete(self, topic_id: str) -> None:
        self._conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        self._conn.commit()

    @staticmethod
    def _row_to_topic(row: sqlite3.Row) -> Topic:
        return Topic(
            id=row["id"],
            name=row["name"],
            intent=row["intent"],
            is_archived=bool(row["is_archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# QueryRule repository
# ---------------------------------------------------------------------------

class QueryRuleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_from_proposal(
        self, topic_id: str, proposal: QueryRuleProposal
    ) -> QueryRule:
        rule_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO query_rules (
                id, topic_id, primary_query, related_queries,
                required_terms, excluded_terms, preferred_languages,
                included_channels, excluded_channels, duration_preference,
                shorts_preference, date_window_start, date_window_end,
                default_sort, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                rule_id, topic_id, proposal.primary_query,
                _json_dumps(proposal.related_queries),
                _json_dumps(proposal.required_terms),
                _json_dumps(proposal.excluded_terms),
                _json_dumps(proposal.preferred_languages),
                _json_dumps(proposal.included_channels),
                _json_dumps(proposal.excluded_channels),
                proposal.duration_preference.value,
                proposal.shorts_preference.value,
                proposal.date_window_start,
                proposal.date_window_end,
                proposal.default_sort.value,
                now, now,
            ),
        )
        # Deactivate previous rules for this topic
        self._conn.execute(
            "UPDATE query_rules SET is_active = 0 WHERE topic_id = ? AND id != ?",
            (topic_id, rule_id),
        )
        self._conn.commit()
        return self.get(rule_id)

    def create(self, topic_id: str, **fields) -> QueryRule:
        rule_id = _new_id()
        now = _now()
        # Deactivate previous rules
        self._conn.execute(
            "UPDATE query_rules SET is_active = 0 WHERE topic_id = ?",
            (topic_id,),
        )
        cols = ["id", "topic_id", "created_at", "updated_at"]
        vals = [rule_id, topic_id, now, now]
        for key, val in fields.items():
            cols.append(key)
            vals.append(val)
        placeholders = ", ".join("?" for _ in vals)
        self._conn.execute(
            f"INSERT INTO query_rules ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        self._conn.commit()
        return self.get(rule_id)

    def get(self, rule_id: str) -> QueryRule | None:
        row = self._conn.execute(
            "SELECT * FROM query_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_rule(row)

    def get_active(self, topic_id: str) -> QueryRule | None:
        row = self._conn.execute(
            "SELECT * FROM query_rules WHERE topic_id = ? AND is_active = 1 "
            "ORDER BY created_at DESC LIMIT 1",
            (topic_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_rule(row)

    def list_for_topic(self, topic_id: str) -> list[QueryRule]:
        rows = self._conn.execute(
            "SELECT * FROM query_rules WHERE topic_id = ? ORDER BY created_at DESC",
            (topic_id,),
        ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def update(self, rule_id: str, **fields) -> QueryRule | None:
        allowed = {
            "primary_query", "related_queries", "required_terms",
            "excluded_terms", "preferred_languages", "included_channels",
            "excluded_channels", "duration_preference", "shorts_preference",
            "date_window_start", "date_window_end", "default_sort",
            "is_active",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(rule_id)
        now = _now()
        updates["updated_at"] = now

        # Serialize list fields to JSON
        _list_fields = {
            "related_queries", "required_terms", "excluded_terms",
            "preferred_languages", "included_channels", "excluded_channels",
        }
        for key in _list_fields:
            if key in updates and isinstance(updates[key], list):
                updates[key] = _json_dumps(updates[key])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [rule_id]
        self._conn.execute(
            f"UPDATE query_rules SET {set_clause} WHERE id = ?", params
        )
        self._conn.commit()
        return self.get(rule_id)

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> QueryRule:
        return QueryRule(
            id=row["id"],
            topic_id=row["topic_id"],
            primary_query=row["primary_query"],
            related_queries=_json_loads(row["related_queries"]) or [],
            required_terms=_json_loads(row["required_terms"]) or [],
            excluded_terms=_json_loads(row["excluded_terms"]) or [],
            preferred_languages=_json_loads(row["preferred_languages"]) or [],
            included_channels=_json_loads(row["included_channels"]) or [],
            excluded_channels=_json_loads(row["excluded_channels"]) or [],
            duration_preference=DurationPreference(row["duration_preference"]),
            shorts_preference=ShortsPreference(row["shorts_preference"]),
            date_window_start=row["date_window_start"],
            date_window_end=row["date_window_end"],
            default_sort=DefaultSort(row["default_sort"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# Video repository
# ---------------------------------------------------------------------------

class VideoRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, video: DiscoveredVideo) -> DiscoveredVideo:
        """Insert or update a video by (provider, provider_video_id)."""
        existing = self._conn.execute(
            "SELECT id FROM videos WHERE provider = ? AND provider_video_id = ?",
            (video.provider, video.provider_video_id),
        ).fetchone()

        if existing:
            video_id = existing["id"]
            self._conn.execute(
                """UPDATE videos SET
                    canonical_url = ?, title = ?, description = ?,
                    channel_id = ?, channel_title = ?, published_at = ?,
                    duration_seconds = ?, view_count = ?, like_count = ?,
                    thumbnail_url = ?, tags = ?, updated_at = ?
                WHERE id = ?""",
                (
                    video.canonical_url, video.title, video.description,
                    video.channel_id, video.channel_title, video.published_at,
                    video.duration_seconds, video.view_count, video.like_count,
                    video.thumbnail_url, _json_dumps(video.tags),
                    _now(), video_id,
                ),
            )
        else:
            video_id = video.id
            self._conn.execute(
                """INSERT INTO videos (
                    id, provider, provider_video_id, canonical_url,
                    title, description, channel_id, channel_title,
                    published_at, duration_seconds, view_count, like_count,
                    thumbnail_url, tags, provenance, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video_id, video.provider, video.provider_video_id,
                    video.canonical_url, video.title, video.description,
                    video.channel_id, video.channel_title, video.published_at,
                    video.duration_seconds, video.view_count, video.like_count,
                    video.thumbnail_url, _json_dumps(video.tags),
                    video.provenance.value, video.created_at, video.updated_at,
                ),
            )
        self._conn.commit()
        return self.get(video_id)

    def get(self, video_id: str) -> DiscoveredVideo | None:
        row = self._conn.execute(
            "SELECT * FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_video(row)

    def get_by_provider_id(
        self, provider: str, provider_video_id: str
    ) -> DiscoveredVideo | None:
        row = self._conn.execute(
            "SELECT * FROM videos WHERE provider = ? AND provider_video_id = ?",
            (provider, provider_video_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_video(row)

    @staticmethod
    def _row_to_video(row: sqlite3.Row) -> DiscoveredVideo:
        return DiscoveredVideo(
            id=row["id"],
            provider=row["provider"],
            provider_video_id=row["provider_video_id"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            description=row["description"],
            channel_id=row["channel_id"],
            channel_title=row["channel_title"],
            published_at=row["published_at"],
            duration_seconds=row["duration_seconds"],
            view_count=row["view_count"],
            like_count=row["like_count"],
            thumbnail_url=row["thumbnail_url"],
            tags=_json_loads(row["tags"]) or [],
            provenance=Provenance(row["provenance"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# TopicVideo repository
# ---------------------------------------------------------------------------

class TopicVideoRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def link(self, topic_id: str, video_id: str) -> TopicVideo:
        """Create or update a topic-video association (deduplication)."""
        existing = self._conn.execute(
            "SELECT id FROM topic_videos WHERE topic_id = ? AND video_id = ?",
            (topic_id, video_id),
        ).fetchone()

        now = _now()
        if existing:
            tv_id = existing["id"]
            self._conn.execute(
                "UPDATE topic_videos SET last_matched_at = ? WHERE id = ?",
                (now, tv_id),
            )
        else:
            tv_id = _new_id()
            self._conn.execute(
                """INSERT INTO topic_videos (
                    id, topic_id, video_id, first_matched_at,
                    last_matched_at, match_score, match_reasons,
                    is_excluded, provenance, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, '[]', 0, 'application', ?, ?)""",
                (tv_id, topic_id, video_id, now, now, now, now),
            )
        self._conn.commit()
        return self.get(tv_id)

    def get(self, tv_id: str) -> TopicVideo | None:
        row = self._conn.execute(
            "SELECT * FROM topic_videos WHERE id = ?", (tv_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_tv(row)

    def get_by_topic_video(
        self, topic_id: str, video_id: str
    ) -> TopicVideo | None:
        row = self._conn.execute(
            "SELECT * FROM topic_videos WHERE topic_id = ? AND video_id = ?",
            (topic_id, video_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_tv(row)

    def list_for_topic(
        self,
        topic_id: str,
        sort: str = "newest",
        exclude_irrelevant: bool = False,
    ) -> list[tuple[TopicVideo, DiscoveredVideo]]:
        """List topic-videos joined with video metadata, sorted."""
        where = "tv.topic_id = ?"
        params: list = [topic_id]
        if exclude_irrelevant:
            where += " AND tv.is_excluded = 0"

        if sort == "newest":
            order = "v_published DESC"
        elif sort == "view_count":
            order = "COALESCE(v_view_count, 0) DESC"
        elif sort == "relevance":
            order = "COALESCE(tv.match_score, 0) DESC, v_published DESC"
        else:
            order = "v_published DESC"

        rows = self._conn.execute(
            f"""SELECT
                tv.id as tv_id, tv.topic_id as tv_topic_id,
                tv.video_id as tv_video_id, tv.first_matched_at as tv_first,
                tv.last_matched_at as tv_last, tv.match_score as tv_score,
                tv.match_reasons as tv_reasons, tv.is_excluded as tv_excluded,
                tv.provenance as tv_provenance,
                tv.created_at as tv_created, tv.updated_at as tv_updated,
                v.id as v_id, v.provider as v_provider,
                v.provider_video_id as v_provider_id, v.canonical_url as v_url,
                v.title as v_title, v.description as v_desc,
                v.channel_id as v_channel_id, v.channel_title as v_channel_title,
                v.published_at as v_published, v.duration_seconds as v_duration,
                v.view_count as v_view_count, v.like_count as v_likes,
                v.thumbnail_url as v_thumbnail, v.tags as v_tags,
                v.provenance as v_provenance,
                v.created_at as v_created, v.updated_at as v_updated
            FROM topic_videos tv
            JOIN videos v ON tv.video_id = v.id
            WHERE {where}
            ORDER BY {order}""",
            params,
        ).fetchall()

        result = []
        for row in rows:
            tv = TopicVideo(
                id=row["tv_id"],
                topic_id=row["tv_topic_id"],
                video_id=row["tv_video_id"],
                first_matched_at=row["tv_first"],
                last_matched_at=row["tv_last"],
                match_score=row["tv_score"],
                match_reasons=_json_loads(row["tv_reasons"]) or [],
                is_excluded=bool(row["tv_excluded"]),
                provenance=Provenance(row["tv_provenance"]),
                created_at=row["tv_created"],
                updated_at=row["tv_updated"],
            )
            video = DiscoveredVideo(
                id=row["v_id"],
                provider=row["v_provider"],
                provider_video_id=row["v_provider_id"],
                canonical_url=row["v_url"],
                title=row["v_title"],
                description=row["v_desc"],
                channel_id=row["v_channel_id"],
                channel_title=row["v_channel_title"],
                published_at=row["v_published"],
                duration_seconds=row["v_duration"],
                view_count=row["v_view_count"],
                like_count=row["v_likes"],
                thumbnail_url=row["v_thumbnail"],
                tags=_json_loads(row["v_tags"]) or [],
                provenance=Provenance(row["v_provenance"]),
                created_at=row["v_created"],
                updated_at=row["v_updated"],
            )
            result.append((tv, video))
        return result

    def set_excluded(
        self, topic_video_id: str, excluded: bool
    ) -> TopicVideo | None:
        self._conn.execute(
            "UPDATE topic_videos SET is_excluded = ? WHERE id = ?",
            (1 if excluded else 0, topic_video_id),
        )
        self._conn.commit()
        return self.get(topic_video_id)

    @staticmethod
    def _row_to_tv(row: sqlite3.Row) -> TopicVideo:
        return TopicVideo(
            id=row["id"],
            topic_id=row["topic_id"],
            video_id=row["video_id"],
            first_matched_at=row["first_matched_at"],
            last_matched_at=row["last_matched_at"],
            match_score=row["match_score"],
            match_reasons=_json_loads(row["match_reasons"]) or [],
            is_excluded=bool(row["is_excluded"]),
            provenance=Provenance(row["provenance"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# ViewingRecord repository
# ---------------------------------------------------------------------------

class ViewingRecordRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, topic_video_id: str) -> PrivateViewingRecord:
        record_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO viewing_records (
                id, topic_video_id, viewing_state, rating, reflection,
                learned_point, agreement, disagreement, uncertainty,
                follow_up_plan, free_form_note, tags, opened_date,
                completed_date, provenance, created_at, updated_at
            ) VALUES (?, ?, 'unseen', NULL, '', '', '', '', '', '', '',
                      '[]', NULL, NULL, 'user', ?, ?)""",
            (record_id, topic_video_id, now, now),
        )
        self._conn.commit()
        return self.get(record_id)

    def get(self, record_id: str) -> PrivateViewingRecord | None:
        row = self._conn.execute(
            "SELECT * FROM viewing_records WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_topic_video(
        self, topic_video_id: str
    ) -> PrivateViewingRecord | None:
        row = self._conn.execute(
            "SELECT * FROM viewing_records WHERE topic_video_id = ?",
            (topic_video_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update(self, record_id: str, **fields) -> PrivateViewingRecord | None:
        allowed = {
            "viewing_state", "rating", "reflection", "learned_point",
            "agreement", "disagreement", "uncertainty", "follow_up_plan",
            "free_form_note", "tags", "opened_date", "completed_date",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(record_id)
        now = _now()
        updates["updated_at"] = now

        # Serialize list fields to JSON
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = _json_dumps(updates["tags"])

        # Validate state transition
        if "viewing_state" in updates:
            new_state = updates["viewing_state"]
            if isinstance(new_state, str):
                updates["viewing_state"] = new_state
            # Set dates based on state
            if new_state == "opened" and "opened_date" not in updates:
                updates["opened_date"] = _now_date()
            if new_state == "completed" and "completed_date" not in updates:
                updates["completed_date"] = _now_date()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [record_id]
        self._conn.execute(
            f"UPDATE viewing_records SET {set_clause} WHERE id = ?", params
        )
        self._conn.commit()
        return self.get(record_id)

    def add_timestamp_ref(
        self, record_id: str, seconds: int, label: str = ""
    ) -> TimestampReference:
        ts_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO timestamp_references
                (id, record_id, timestamp_seconds, label, created_at)
                VALUES (?, ?, ?, ?, ?)""",
            (ts_id, record_id, seconds, label, now),
        )
        self._conn.commit()
        return TimestampReference(
            id=ts_id,
            record_id=record_id,
            timestamp_seconds=seconds,
            label=label,
            created_at=now,
        )

    def list_timestamp_refs(
        self, record_id: str
    ) -> list[TimestampReference]:
        rows = self._conn.execute(
            "SELECT * FROM timestamp_references WHERE record_id = ? ORDER BY timestamp_seconds",
            (record_id,),
        ).fetchall()
        return [
            TimestampReference(
                id=r["id"], record_id=r["record_id"],
                timestamp_seconds=r["timestamp_seconds"],
                label=r["label"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def search(
        self,
        topic_id: str | None = None,
        state: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
    ) -> list[tuple[PrivateViewingRecord, TopicVideo, DiscoveredVideo]]:
        """Search viewing records with optional filters."""
        where_parts = []
        params: list = []

        if topic_id:
            where_parts.append("tv.topic_id = ?")
            params.append(topic_id)
        if state:
            where_parts.append("vr.viewing_state = ?")
            params.append(state)
        if query:
            where_parts.append(
                "(vr.free_form_note LIKE ? OR vr.reflection LIKE ? "
                "OR vr.follow_up_plan LIKE ? OR v.title LIKE ?)"
            )
            like_pattern = f"%{query}%"
            params.extend([like_pattern, like_pattern, like_pattern, like_pattern])

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        rows = self._conn.execute(
            f"""SELECT
                vr.id as vr_id, vr.topic_video_id as vr_tv_id,
                vr.viewing_state as vr_state, vr.rating as vr_rating,
                vr.reflection as vr_reflection, vr.learned_point as vr_learned,
                vr.agreement as vr_agreement, vr.disagreement as vr_disagree,
                vr.uncertainty as vr_uncertainty, vr.follow_up_plan as vr_plan,
                vr.free_form_note as vr_note, vr.tags as vr_tags,
                vr.opened_date as vr_opened, vr.completed_date as vr_completed,
                vr.provenance as vr_provenance,
                vr.created_at as vr_created, vr.updated_at as vr_updated,
                tv.id as tv_id, tv.topic_id as tv_topic_id,
                tv.video_id as tv_video_id, tv.first_matched_at as tv_first,
                tv.last_matched_at as tv_last, tv.match_score as tv_score,
                tv.match_reasons as tv_reasons, tv.is_excluded as tv_excluded,
                tv.provenance as tv_provenance,
                tv.created_at as tv_created, tv.updated_at as tv_updated,
                v.id as v_id, v.provider as v_provider,
                v.provider_video_id as v_provider_id, v.canonical_url as v_url,
                v.title as v_title, v.description as v_desc,
                v.channel_id as v_channel_id, v.channel_title as v_channel_title,
                v.published_at as v_published, v.duration_seconds as v_duration,
                v.view_count as v_view_count, v.like_count as v_likes,
                v.thumbnail_url as v_thumbnail, v.tags as v_tags,
                v.provenance as v_provenance,
                v.created_at as v_created, v.updated_at as v_updated
            FROM viewing_records vr
            JOIN topic_videos tv ON vr.topic_video_id = tv.id
            JOIN videos v ON tv.video_id = v.id
            WHERE {where_clause}
            ORDER BY vr.updated_at DESC""",
            params,
        ).fetchall()

        result = []
        for row in rows:
            record = PrivateViewingRecord(
                id=row["vr_id"],
                topic_video_id=row["vr_tv_id"],
                viewing_state=ViewingState(row["vr_state"]),
                rating=row["vr_rating"],
                reflection=row["vr_reflection"],
                learned_point=row["vr_learned"],
                agreement=row["vr_agreement"],
                disagreement=row["vr_disagree"],
                uncertainty=row["vr_uncertainty"],
                follow_up_plan=row["vr_plan"],
                free_form_note=row["vr_note"],
                tags=_json_loads(row["vr_tags"]) or [],
                opened_date=row["vr_opened"],
                completed_date=row["vr_completed"],
                provenance=Provenance(row["vr_provenance"]),
                created_at=row["vr_created"],
                updated_at=row["vr_updated"],
            )
            tv = TopicVideo(
                id=row["tv_id"],
                topic_id=row["tv_topic_id"],
                video_id=row["tv_video_id"],
                first_matched_at=row["tv_first"],
                last_matched_at=row["tv_last"],
                match_score=row["tv_score"],
                match_reasons=_json_loads(row["tv_reasons"]) or [],
                is_excluded=bool(row["tv_excluded"]),
                provenance=Provenance(row["tv_provenance"]),
                created_at=row["tv_created"],
                updated_at=row["tv_updated"],
            )
            video = DiscoveredVideo(
                id=row["v_id"],
                provider=row["v_provider"],
                provider_video_id=row["v_provider_id"],
                canonical_url=row["v_url"],
                title=row["v_title"],
                description=row["v_desc"],
                channel_id=row["v_channel_id"],
                channel_title=row["v_channel_title"],
                published_at=row["v_published"],
                duration_seconds=row["v_duration"],
                view_count=row["v_view_count"],
                like_count=row["v_likes"],
                thumbnail_url=row["v_thumbnail"],
                tags=_json_loads(row["v_tags"]) or [],
                provenance=Provenance(row["v_provenance"]),
                created_at=row["v_created"],
                updated_at=row["v_updated"],
            )
            result.append((record, tv, video))

        # Filter by tags (post-filter since tags are JSON)
        if tags:
            filtered = []
            tag_set = set(t.lower() for t in tags)
            for record, tv, video in result:
                record_tags = set(t.lower() for t in record.tags)
                if tag_set & record_tags:
                    filtered.append((record, tv, video))
            result = filtered

        return result

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PrivateViewingRecord:
        return PrivateViewingRecord(
            id=row["id"],
            topic_video_id=row["topic_video_id"],
            viewing_state=ViewingState(row["viewing_state"]),
            rating=row["rating"],
            reflection=row["reflection"],
            learned_point=row["learned_point"],
            agreement=row["agreement"],
            disagreement=row["disagreement"],
            uncertainty=row["uncertainty"],
            follow_up_plan=row["follow_up_plan"],
            free_form_note=row["free_form_note"],
            tags=_json_loads(row["tags"]) or [],
            opened_date=row["opened_date"],
            completed_date=row["completed_date"],
            provenance=Provenance(row["provenance"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# ---------------------------------------------------------------------------
# SyncRun repository
# ---------------------------------------------------------------------------

class SyncRunRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, topic_id: str, provider: str) -> SyncRun:
        run_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO sync_runs
                (id, topic_id, provider, started_at, status)
                VALUES (?, ?, ?, ?, 'running')""",
            (run_id, topic_id, provider, now),
        )
        self._conn.commit()
        return SyncRun(
            id=run_id, topic_id=topic_id, provider=provider,
            started_at=now, status=SyncStatus.RUNNING,
        )

    def complete(
        self, run_id: str, status: SyncStatus,
        videos_found: int = 0, videos_added: int = 0,
        videos_updated: int = 0, quota_cost: int = 0,
        error_message: str = "",
    ) -> SyncRun | None:
        now = _now()
        self._conn.execute(
            """UPDATE sync_runs SET
                completed_at = ?, status = ?, videos_found = ?,
                videos_added = ?, videos_updated = ?, quota_cost = ?,
                error_message = ?
            WHERE id = ?""",
            (now, status.value, videos_found, videos_added, videos_updated,
             quota_cost, error_message, run_id),
        )
        self._conn.commit()
        return self.get(run_id)

    def get(self, run_id: str) -> SyncRun | None:
        row = self._conn.execute(
            "SELECT * FROM sync_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return SyncRun(
            id=row["id"],
            topic_id=row["topic_id"],
            provider=row["provider"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=SyncStatus(row["status"]),
            videos_found=row["videos_found"],
            videos_added=row["videos_added"],
            videos_updated=row["videos_updated"],
            quota_cost=row["quota_cost"],
            error_message=row["error_message"],
        )

    def list_for_topic(self, topic_id: str) -> list[SyncRun]:
        rows = self._conn.execute(
            "SELECT * FROM sync_runs WHERE topic_id = ? ORDER BY started_at DESC",
            (topic_id,),
        ).fetchall()
        return [
            SyncRun(
                id=r["id"], topic_id=r["topic_id"], provider=r["provider"],
                started_at=r["started_at"], completed_at=r["completed_at"],
                status=SyncStatus(r["status"]),
                videos_found=r["videos_found"],
                videos_added=r["videos_added"],
                videos_updated=r["videos_updated"],
                quota_cost=r["quota_cost"],
                error_message=r["error_message"],
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# QuotaLedger repository
# ---------------------------------------------------------------------------

class QuotaLedgerRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def record(
        self, topic_id: str, provider: str, operation: str,
        cost: int, sync_run_id: str | None = None,
    ) -> QuotaLedgerEntry:
        entry_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO quota_ledger
                (id, topic_id, sync_run_id, provider, operation, cost, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, topic_id, sync_run_id, provider, operation, cost, now),
        )
        self._conn.commit()
        return QuotaLedgerEntry(
            id=entry_id, topic_id=topic_id, sync_run_id=sync_run_id,
            provider=provider, operation=operation, cost=cost,
            recorded_at=now,
        )

    def total_cost(self, topic_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost), 0) as total FROM quota_ledger WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return row["total"] if row else 0


# ---------------------------------------------------------------------------
# Proposal repository
# ---------------------------------------------------------------------------

class ProposalRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        proposal_type: ProposalType,
        proposed_json: str,
        input_text: str = "",
        topic_id: str | None = None,
        record_id: str | None = None,
        validation_status: ValidationStatus = ValidationStatus.VALID,
        validation_error: str = "",
    ) -> ProposalRecord:
        prop_id = _new_id()
        now = _now()
        self._conn.execute(
            """INSERT INTO proposals
                (id, topic_id, record_id, proposal_type, status, input_text,
                 proposed_json, validation_status, validation_error, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
            (prop_id, topic_id, record_id, proposal_type.value, input_text,
             proposed_json, validation_status.value, validation_error, now),
        )
        self._conn.commit()
        return ProposalRecord(
            id=prop_id, topic_id=topic_id, record_id=record_id,
            proposal_type=proposal_type, status=ProposalStatus.PENDING,
            input_text=input_text, proposed_json=proposed_json,
            validation_status=validation_status,
            validation_error=validation_error,
            created_at=now,
        )

    def get(self, proposal_id: str) -> ProposalRecord | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def list_pending(
        self, topic_id: str | None = None
    ) -> list[ProposalRecord]:
        where = "1=1"
        params: list = []
        if topic_id:
            where = "topic_id = ?"
            params = [topic_id]
        rows = self._conn.execute(
            f"SELECT * FROM proposals WHERE status = 'pending' AND {where} "
            "ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def update_status(
        self, proposal_id: str, status: ProposalStatus
    ) -> ProposalRecord | None:
        now = _now()
        self._conn.execute(
            "UPDATE proposals SET status = ?, decided_at = ? WHERE id = ?",
            (status.value, now, proposal_id),
        )
        self._conn.commit()
        return self.get(proposal_id)

    @staticmethod
    def _row_to_proposal(row: sqlite3.Row) -> ProposalRecord:
        return ProposalRecord(
            id=row["id"],
            topic_id=row["topic_id"],
            record_id=row["record_id"],
            proposal_type=ProposalType(row["proposal_type"]),
            status=ProposalStatus(row["status"]),
            input_text=row["input_text"],
            proposed_json=row["proposed_json"],
            validation_status=ValidationStatus(row["validation_status"]),
            validation_error=row["validation_error"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )


def _now_date() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
