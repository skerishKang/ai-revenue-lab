"""Audit: failing migration, reader deletion, evidence privacy."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.config import settings
from app.db import MigrationError, apply_migrations, get_connection
from app.domain.enums import Category, FeedbackAction, PilotEvidenceType
from app.domain.models import FeedbackInput, PilotEvidenceInput
from app.repositories import (
    brief_repository,
    feedback_repository,
    reader_repository,
)
from app.service import EvidenceValidationError, WorldFeedService
from tests.conftest import (
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.ingest_source_card(conn, make_source("s2", "ev-2", Category.NEIGHBORHOOD))
    svc.resolve_canonical_events(conn)
    return event_id_map(conn), event_source_ids_map(conn)


class TestMigrationFailure:
    def test_real_failing_migration_not_recorded(self, db_path, tmp_path):
        mig = tmp_path / "migrations"
        mig.mkdir()
        shutil.copy(MIGRATIONS / "001_initial.sql", mig / "001_initial.sql")
        conn = get_connection(db_path)
        applied = apply_migrations(conn, str(mig))
        assert applied == ["001_initial.sql"]
        (mig / "002_bad.sql").write_text(
            "-- intentionally broken\nSELECT broken_column FROM nonexistent;\n",
            encoding="utf-8",
        )
        with pytest.raises(MigrationError) as exc:
            apply_migrations(conn, str(mig))
        assert exc.value.filename == "002_bad.sql"
        versions = [
            r["version"]
            for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        assert versions == ["001_initial.sql"]
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "sources" in tables
        conn.close()
        conn2 = get_connection(db_path)
        versions2 = [
            r["version"]
            for r in conn2.execute("SELECT version FROM schema_migrations")
        ]
        assert versions2 == ["001_initial.sql"]
        conn2.close()


class TestReaderDeletion:
    def test_delete_anonymizes_and_is_idempotent(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm)
        )
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        svc.apply_feedback(
            conn,
            FeedbackInput(
                feedback_id="fb-del",
                reader_id="r1",
                prior_brief_id=brief.id,
                idempotency_key="idem-del",
                action=FeedbackAction.INCREASE_CULTURE_NEIGHBORHOOD,
                detail="private preference text",
            ),
        )
        ev = svc.record_pilot_evidence(
            conn,
            PilotEvidenceInput(
                reader_id="r1",
                brief_id=brief.id,
                evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                anonymous_token="anon-del",
                detail="followed Vietnam",
            ),
        )
        source_count = conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"]
        event_count = conn.execute(
            "SELECT COUNT(*) AS n FROM canonical_events"
        ).fetchone()["n"]

        result = svc.delete_reader(conn, "r1")
        assert result["status"] == "deleted"
        assert reader_repository.get_reader_by_id(conn, "r1") is None
        assert brief_repository.list_briefs_for_reader(conn, "r1") == []
        assert feedback_repository.list_feedback_for_reader(conn, "r1") == []
        rows = conn.execute(
            "SELECT reader_id, detail FROM pilot_evidence WHERE id = ?", (ev.id,)
        ).fetchone()
        assert rows["reader_id"].startswith("revoked:")
        assert rows["detail"] == ""
        exported = svc.export_evidence(conn, ev.id)
        assert "r1" not in str(exported)
        assert "reader_id" not in exported
        assert conn.execute("SELECT COUNT(*) AS n FROM sources").fetchone()["n"] == source_count
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM canonical_events").fetchone()["n"]
            == event_count
        )
        assert svc.delete_reader(conn, "r1")["status"] == "already_absent"
        conn.close()
        conn2 = get_connection(db_path)
        assert svc.delete_reader(conn2, "r1")["status"] == "already_absent"
        conn2.close()


class TestEvidencePrivacyExtras:
    def test_payment_claim_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm)
        )
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        with pytest.raises(EvidenceValidationError, match="payment or revenue"):
            svc.record_pilot_evidence(
                conn,
                PilotEvidenceInput(
                    reader_id="r1",
                    brief_id=brief.id,
                    evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                    anonymous_token="anon-pay",
                    detail="user paid revenue settled invoice",
                ),
            )
        conn.close()

    def test_api_key_under_permitted_field_redacted(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, str(MIGRATIONS))
        mp, sm = _seed(conn)
        svc = _svc(
            make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm)
        )
        svc.create_reader(conn, make_reader("r1"))
        brief = svc.generate_first_brief(conn, "r1")
        rec = svc.record_pilot_evidence(
            conn,
            PilotEvidenceInput(
                reader_id="r1",
                brief_id=brief.id,
                evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
                anonymous_token="anon-key",
                detail="note api_key=sk-live-SECRET123 and screenshot/path/private.png",
            ),
        )
        assert "sk-live-SECRET123" not in rec.detail
        assert "screenshot/path/private.png" not in rec.detail
        assert "[redacted]" in rec.detail
        conn.close()
