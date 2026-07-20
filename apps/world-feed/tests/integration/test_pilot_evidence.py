from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import Category, PilotEvidenceType
from app.domain.models import PilotEvidenceInput
from app.repositories import pilot_evidence_repository
from app.service import EvidenceValidationError, WorldFeedService
from tests.conftest import (
    event_id_map,
    event_source_ids_map,
    make_brief_provider,
    make_reader,
    make_source,
)


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


def _seed_with_brief(conn):
    svc = _svc(make_brief_provider([], []))
    svc.ingest_source_card(conn, make_source("s1", "ev-1", Category.PLACE_CULTURE))
    svc.resolve_canonical_events(conn)
    mp = event_id_map(conn)
    sm = event_source_ids_map(conn)
    svc2 = _svc(make_brief_provider(list(mp.values()), list(mp.values()), source_ids_map=sm))
    svc2.create_reader(conn, make_reader("r1"))
    brief = svc2.generate_first_brief(conn, "r1")
    return brief


class TestPilotEvidence:
    def test_records_privacy_safe_evidence(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        brief = _seed_with_brief(conn)
        evidence = PilotEvidenceInput(
            reader_id="r1",
            brief_id=brief.id,
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-9f2c",
            detail="followed Vietnam",
        )
        svc = _svc(make_brief_provider([], []))
        rec = svc.record_pilot_evidence(conn, evidence)
        assert rec.evidence_type == "followed_country"
        assert rec.anonymous_token == "anon-9f2c"
        assert rec.reader_id == "r1"
        cols = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(pilot_evidence)").fetchall()
        ]
        for forbidden in ("name", "email", "phone", "address", "birth"):
            assert forbidden not in cols
        assert pilot_evidence_repository.count_evidence(conn) == 1
        conn.close()

    def test_evidence_nonexistent_reader_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        brief = _seed_with_brief(conn)
        svc = _svc(make_brief_provider([], []))
        evidence = PilotEvidenceInput(
            reader_id="nonexistent",
            brief_id=brief.id,
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-1",
        )
        import pytest
        with pytest.raises(EvidenceValidationError, match="reader not found"):
            svc.record_pilot_evidence(conn, evidence)
        conn.close()

    def test_evidence_nonexistent_brief_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        brief = _seed_with_brief(conn)
        svc = _svc(make_brief_provider([], []))
        evidence = PilotEvidenceInput(
            reader_id="r1",
            brief_id="nonexistent-brief",
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-2",
        )
        import pytest
        with pytest.raises(EvidenceValidationError, match="brief not found"):
            svc.record_pilot_evidence(conn, evidence)
        conn.close()

    def test_evidence_ownership_mismatch_rejected(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        brief = _seed_with_brief(conn)
        svc = _svc(make_brief_provider([], []))
        svc.create_reader(conn, make_reader("r2"))
        evidence = PilotEvidenceInput(
            reader_id="r2",
            brief_id=brief.id,
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-3",
        )
        import pytest
        with pytest.raises(EvidenceValidationError, match="does not belong"):
            svc.record_pilot_evidence(conn, evidence)
        conn.close()

    def test_evidence_detail_redacted(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        brief = _seed_with_brief(conn)
        svc = _svc(make_brief_provider([], []))
        evidence = PilotEvidenceInput(
            reader_id="r1",
            brief_id=brief.id,
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-4",
            detail="Contact me at test@example.com or call +1-555-123-4567",
        )
        rec = svc.record_pilot_evidence(conn, evidence)
        assert "test@example.com" not in rec.detail
        assert "+1-555-123-4567" not in rec.detail
        assert "[redacted]" in rec.detail
        conn.close()
