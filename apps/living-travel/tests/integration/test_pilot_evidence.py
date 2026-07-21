"""Integration tests for pilot evidence repository."""

import pytest

from app.db import apply_migrations, get_connection
from app.pilot_evidence_repository import (
    create_pilot_evidence,
    get_pilot_evidence_by_id,
    get_pilot_evidence_by_traveler,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    c = get_connection(db_path)
    yield c
    c.close()


class TestPilotEvidence:
    def test_free_sample_evidence(self, conn):
        pe = create_pilot_evidence(
            conn,
            evidence_type="free_sample",
            traveler_id="trav_test",
            edition_id="ed_test",
            offer_description="무료 샘플 에디션 1회",
            price_krw=0,
            consent_recorded=True,
        )
        assert pe.id.startswith("pe_")
        assert pe.price_krw == 0
        fetched = get_pilot_evidence_by_id(conn, pe.id)
        assert fetched is not None
        assert fetched.evidence_type == "free_sample"

    def test_paid_edition_evidence(self, conn):
        pe = create_pilot_evidence(
            conn,
            evidence_type="paid_edition",
            traveler_id="trav_test",
            edition_id="ed_test",
            offer_description="적응된 에디션 3회 (KRW 4,900)",
            price_krw=4900,
            consent_recorded=True,
            payment_evidence="manual_pending",
        )
        assert pe.price_krw == 4900
        fetched = get_pilot_evidence_by_id(conn, pe.id)
        assert fetched is not None
        assert fetched.payment_evidence == "manual_pending"

    def test_list_by_traveler(self, conn):
        create_pilot_evidence(
            conn,
            evidence_type="free_sample",
            traveler_id="trav_1",
            edition_id="ed_1",
            offer_description="샘플",
        )
        create_pilot_evidence(
            conn,
            evidence_type="paid_edition",
            traveler_id="trav_1",
            edition_id="ed_2",
            offer_description="유료",
            price_krw=4900,
        )
        create_pilot_evidence(
            conn,
            evidence_type="free_sample",
            traveler_id="trav_2",
            edition_id="ed_3",
            offer_description="다른 여행자",
        )
        evs = get_pilot_evidence_by_traveler(conn, "trav_1")
        assert len(evs) == 2

    def test_one_free_sample_structure(self, conn):
        create_pilot_evidence(
            conn,
            evidence_type="free_sample",
            traveler_id="trav_solo",
            edition_id="ed_first",
            offer_description="무료 샘플 에디션 1회 제공",
            price_krw=0,
            consent_recorded=True,
        )
        create_pilot_evidence(
            conn,
            evidence_type="paid_edition",
            traveler_id="trav_solo",
            edition_id="ed_bundle",
            offer_description="적응된 에디션 3회 제공 (KRW 4,900)",
            price_krw=4900,
            consent_recorded=True,
            payment_evidence="payment_pending_manual",
        )
        evs = get_pilot_evidence_by_traveler(conn, "trav_solo")
        assert len(evs) == 2
        assert evs[0].price_krw == 0
        assert evs[1].price_krw == 4900
