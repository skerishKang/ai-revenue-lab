from app.config import settings
from app.db import apply_migrations, get_connection
from app.domain.enums import PilotEvidenceType
from app.domain.models import PilotEvidenceInput
from app.repositories import pilot_evidence_repository
from app.service import WorldFeedService
from tests.conftest import make_brief_provider


def _svc(provider):
    return WorldFeedService(provider=provider, settings=settings)


class TestPilotEvidence:
    def test_records_privacy_safe_evidence(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        evidence = PilotEvidenceInput(
            reader_id="r1",
            brief_id="brief-1",
            evidence_type=PilotEvidenceType.FOLLOWED_COUNTRY,
            anonymous_token="anon-9f2c",
            detail="followed Vietnam",
        )
        rec = svc.record_pilot_evidence(conn, evidence)
        assert rec.evidence_type == "followed_country"
        assert rec.anonymous_token == "anon-9f2c"
        assert rec.reader_id == "r1"
        # No personal identifiers are stored; only an anonymous token.
        cols = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(pilot_evidence)").fetchall()
        ]
        for forbidden in ("name", "email", "phone", "address", "birth"):
            assert forbidden not in cols
        assert pilot_evidence_repository.count_evidence(conn) == 1
        conn.close()

    def test_evidence_is_reader_scoped(self, db_path):
        conn = get_connection(db_path)
        apply_migrations(conn, "migrations")
        svc = _svc(make_brief_provider([], []))
        svc.record_pilot_evidence(
            conn,
            PilotEvidenceInput(
                reader_id="r1",
                brief_id="b1",
                evidence_type=PilotEvidenceType.CLICKED_OFFICIAL_LINK,
                anonymous_token="anon-a",
            ),
        )
        svc.record_pilot_evidence(
            conn,
            PilotEvidenceInput(
                reader_id="r2",
                brief_id="b2",
                evidence_type=PilotEvidenceType.REQUESTED_CONTINUED_EDITIONS,
                anonymous_token="anon-b",
            ),
        )
        r1 = pilot_evidence_repository.list_evidence_for_reader(conn, "r1")
        assert len(r1) == 1
        assert r1[0].reader_id == "r1"
        conn.close()
