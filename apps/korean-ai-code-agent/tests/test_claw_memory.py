from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import inspect
import unittest

from kagent.claw_memory import (
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawItemKind,
    ClawItemMemory,
    ClawMemoryCandidate,
    ClawMemoryError,
    ClawMemoryKind,
    ClawMemorySourceRef,
    ClawMemoryStore,
    ClawPartyMemory,
    ClawPartyRole,
    ClawPriceMemory,
    ClawProposalState,
    ClawSourceOrigin,
    ClawTaskStatus,
    InMemoryClawMemoryStore,
    durable_record_from_proposal,
    proposal_from_candidate,
    sha256_text,
    with_decision,
)

T0 = datetime(2026, 9, 7, 9, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 7, 11, 0, 0, tzinfo=timezone.utc)

RAW_BODY = "삼성상사 견적 요청: 스테인리스 30A 100개 단가 5,000원 납기 9월 20일"


def make_source(workspace_id: str = "ws-a", source_id: str = "src-001") -> ClawMemorySourceRef:
    return ClawMemorySourceRef(
        source_id=source_id,
        workspace_id=workspace_id,
        origin=ClawSourceOrigin.PASTE,
        body_sha256=sha256_text(RAW_BODY),
        created_at=T0,
        raw_excerpt=RAW_BODY,
    )


def make_party_candidate(workspace_id: str = "ws-a") -> ClawMemoryCandidate:
    return ClawMemoryCandidate(
        candidate_id="cand-party-1",
        workspace_id=workspace_id,
        kind=ClawMemoryKind.PARTY,
        payload={
            "name": "삼성상사",
            "role": "customer",
            "preferred_contact_method": "kakao",
            "delivery_preference": "평일 오전 납품",
            "unresolved_request": "9월 정기발주 견적",
        },
        source=make_source(workspace_id),
        created_at=T0,
    )


class ClawMemoryContractTests(unittest.TestCase):
    def test_long_raw_excerpt_and_business_text_are_not_rejected(self):
        source = ClawMemorySourceRef(
            source_id="src-long", workspace_id="ws-a", origin=ClawSourceOrigin.PASTE,
            body_sha256=sha256_text("a" * 9000), created_at=T0,
            raw_excerpt="a" * 9000,
        )
        self.assertEqual(len(source.raw_excerpt), 9000)
        candidate = ClawMemoryCandidate(
            candidate_id="cand-long", workspace_id="ws-a", kind=ClawMemoryKind.PARTY,
            payload={"name": "b" * 6000, "role": "customer"},
            source=source, created_at=T0,
        )
        self.assertEqual(candidate.payload["name"], "b" * 6000)


    def test_party_item_price_records_are_workspace_scoped(self):
        party = ClawPartyMemory(
            memory_id="mem-p1",
            workspace_id="ws-a",
            name="삼성상사",
            role=ClawPartyRole.CUSTOMER,
            source_id="src-001",
            updated_at=T1,
        )
        item = ClawItemMemory(
            memory_id="mem-i1",
            workspace_id="ws-a",
            item_name="스테인리스 30A",
            item_kind=ClawItemKind.PRODUCT,
            source_id="src-001",
            updated_at=T1,
            sku="SS-30A",
            unit="개",
        )
        price = ClawPriceMemory(
            memory_id="mem-r1",
            workspace_id="ws-a",
            item_memory_id="mem-i1",
            unit_price=Decimal("5000"),
            currency="KRW",
            quoted_at=date(2026, 9, 1),
            source_id="src-001",
            updated_at=T1,
        )
        self.assertEqual(party.workspace_id, "ws-a")
        self.assertEqual(item.safe_dict()["sku"], "SS-30A")
        self.assertEqual(price.safe_dict()["unit_price"], "5000")
        store = InMemoryClawMemoryStore()
        store._parties["mem-p1"] = party
        store._parties["mem-p-other"] = ClawPartyMemory(
            memory_id="mem-p-other",
            workspace_id="ws-b",
            name="다른거래처",
            role=ClawPartyRole.SUPPLIER,
            source_id="src-002",
            updated_at=T1,
        )
        listed = store.list_parties("ws-a")
        self.assertEqual([r.memory_id for r in listed], ["mem-p1"])

    def test_durable_records_require_source_ref(self):
        with self.assertRaises(ClawMemoryError):
            ClawPartyMemory(
                memory_id="mem-p1",
                workspace_id="ws-a",
                name="삼성상사",
                role=ClawPartyRole.CUSTOMER,
                source_id="",
                updated_at=T1,
            )

    def test_untrusted_inbound_text_never_becomes_durable_record(self):
        candidate = make_party_candidate()
        self.assertFalse(hasattr(candidate, "apply"))
        self.assertFalse(hasattr(candidate, "to_record"))
        self.assertIsInstance(candidate, ClawMemoryCandidate)
        self.assertNotIsInstance(candidate, ClawPartyMemory)

    def test_candidate_creates_proposal_not_record(self):
        proposal = proposal_from_candidate(make_party_candidate(), proposal_id="prop-1")
        self.assertIs(proposal.state, ClawProposalState.PENDING_REVIEW)
        self.assertEqual(proposal.candidate_id, "cand-party-1")
        self.assertFalse(proposal.applicable)

    def test_pending_proposal_cannot_be_applied(self):
        proposal = proposal_from_candidate(make_party_candidate(), proposal_id="prop-1")
        with self.assertRaises(ClawMemoryError):
            durable_record_from_proposal(proposal, memory_id="mem-1", applied_at=T2)

    def test_approved_proposal_creates_durable_record_with_source_ref(self):
        store = InMemoryClawMemoryStore()
        proposal = store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
        store.decide_proposal(
            "prop-1",
            ClawProposalState.APPROVED,
            workspace_id="ws-a",
            decided_by="owner-1",
            decided_at=T1,
        )
        record = store.apply_proposal("prop-1", workspace_id="ws-a", memory_id="mem-p1", applied_at=T2)
        self.assertIsInstance(record, ClawPartyMemory)
        self.assertEqual(record.name, "삼성상사")
        self.assertEqual(record.source_id, "src-001")
        self.assertEqual(store.list_parties("ws-a")[0].memory_id, "mem-p1")

    def test_rejected_and_suppressed_proposals_cannot_create_records(self):
        for state in (ClawProposalState.REJECTED, ClawProposalState.SUPPRESSED):
            with self.subTest(state=state):
                store = InMemoryClawMemoryStore()
                store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
                store.decide_proposal(
                    "prop-1",
                    state,
                    workspace_id="ws-a",
                    decided_by="owner-1",
                    decided_at=T1,
                )
                with self.assertRaises(ClawMemoryError):
                    store.apply_proposal("prop-1", workspace_id="ws-a", memory_id="mem-p1", applied_at=T2)
                self.assertEqual(store.list_parties("ws-a"), ())

    def test_edited_approval_preserves_source_ref_and_shows_both_payloads(self):
        store = InMemoryClawMemoryStore()
        store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
        decided = store.decide_proposal(
            "prop-1",
            ClawProposalState.EDITED,
            workspace_id="ws-a",
            decided_by="owner-1",
            decided_at=T1,
            edited_payload={"name": "삼성물산(정정)", "role": "customer"},
        )
        self.assertEqual(decided.payload["name"], "삼성상사")
        self.assertEqual(decided.edited_payload["name"], "삼성물산(정정)")
        record = store.apply_proposal("prop-1", workspace_id="ws-a", memory_id="mem-p1", applied_at=T2)
        self.assertEqual(record.name, "삼성물산(정정)")
        self.assertEqual(record.source_id, "src-001")
        applied = store._proposals["prop-1"]
        self.assertIs(applied.state, ClawProposalState.APPLIED)
        self.assertEqual(applied.source.body_sha256, sha256_text(RAW_BODY))

    def test_decided_proposal_cannot_be_re_decided(self):
        store = InMemoryClawMemoryStore()
        store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
        store.decide_proposal(
            "prop-1",
            ClawProposalState.APPROVED,
            workspace_id="ws-a",
            decided_by="owner-1",
            decided_at=T1,
        )
        with self.assertRaises(ClawMemoryError):
            store.decide_proposal(
                "prop-1",
                ClawProposalState.REJECTED,
                workspace_id="ws-a",
                decided_by="owner-1",
                decided_at=T2,
            )

    def test_followup_task_supports_due_date_status_source_workspace_member(self):
        task = ClawFollowupTask(
            task_id="task-1",
            workspace_id="ws-a",
            member_id="member-1",
            title="삼성상사 9월 발주 확인",
            status=ClawTaskStatus.OPEN,
            created_at=T0,
            due_date=date(2026, 9, 20),
            source_id="src-001",
            linked_ref="mem-p1",
        )
        reopened = task.with_status(ClawTaskStatus.DONE, at=T1).with_status(ClawTaskStatus.OPEN, at=T2)
        self.assertIs(reopened.status, ClawTaskStatus.OPEN)
        self.assertEqual(reopened.safe_dict()["due_date"], "2026-09-20")
        store = InMemoryClawMemoryStore()
        store.add_task(task)
        self.assertEqual([t.task_id for t in store.list_tasks("ws-a", member_id="member-1")], ["task-1"])
        self.assertEqual(store.list_tasks("ws-b", member_id="member-1"), ())
        with self.assertRaises(ClawMemoryError):
            store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-b", member_id="member-1", at=T2)

    def test_alert_supports_kind_severity_visibility_and_linked_refs(self):
        alert = ClawAlert(
            alert_id="alert-1",
            workspace_id="ws-a",
            kind=ClawAlertKind.FOLLOWUP_DUE,
            severity=ClawAlertSeverity.WARN,
            title="발주 확인 마감 임박",
            created_at=T0,
            visible_to_members=("member-1",),
            linked_refs=("task-1", "mem-p1"),
        )
        self.assertTrue(alert.is_visible_to("member-1"))
        self.assertFalse(alert.is_visible_to("member-2"))
        self.assertFalse(alert.is_visible_to(None))
        dismissed = alert.with_status(ClawAlertStatus.DISMISSED, at=T1)
        self.assertIs(dismissed.with_status(ClawAlertStatus.ACTIVE, at=T2).status, ClawAlertStatus.ACTIVE)
        store = InMemoryClawMemoryStore()
        store.add_alert(alert)
        store.add_alert(
            ClawAlert(
                alert_id="alert-2",
                workspace_id="ws-a",
                kind=ClawAlertKind.MEMORY_PROPOSAL,
                severity=ClawAlertSeverity.INFO,
                title="메모리 제안 검토 필요",
                created_at=T0,
            )
        )
        self.assertEqual([a.alert_id for a in store.list_alerts("ws-a", member_id="member-2")], ["alert-2"])
        self.assertEqual(len(store.list_alerts("ws-a", member_id="member-1")), 2)

    def test_6324_same_tenant_tenant_mate_tasks_are_invisible_to_the_store(self):
        """#6324: A/B in one tenant — the store read itself carries the owner."""
        store = InMemoryClawMemoryStore()
        store.add_task(
            ClawFollowupTask(
                task_id="task-a1",
                workspace_id="ws-a",
                member_id="member-1",
                title="A의 발주 확인",
                status=ClawTaskStatus.OPEN,
                created_at=T0,
            )
        )
        self.assertEqual(store.list_tasks("ws-a", member_id="member-2"), ())
        self.assertEqual([t.task_id for t in store.list_tasks("ws-a", member_id="member-1")], ["task-a1"])
        self.assertIsNone(store.get_task("task-a1", workspace_id="ws-a", member_id="member-2"))
        self.assertIsNotNone(store.get_task("task-a1", workspace_id="ws-a", member_id="member-1"))

    def test_6324_tenant_mate_cannot_change_my_task_status(self):
        store = InMemoryClawMemoryStore()
        store.add_task(
            ClawFollowupTask(
                task_id="task-a1",
                workspace_id="ws-a",
                member_id="member-1",
                title="A의 발주 확인",
                status=ClawTaskStatus.OPEN,
                created_at=T0,
            )
        )
        with self.assertRaises(ClawMemoryError):
            store.set_task_status(
                "task-a1", ClawTaskStatus.DONE, workspace_id="ws-a", member_id="member-2", at=T2
            )
        mine = store.get_task("task-a1", workspace_id="ws-a", member_id="member-1")
        self.assertIsNotNone(mine)
        self.assertIs(mine.status, ClawTaskStatus.OPEN)

    def test_6324_shared_alert_stays_company_visible_while_private_stays_owned(self):
        store = InMemoryClawMemoryStore()
        store.add_alert(
            ClawAlert(
                alert_id="alert-shared",
                workspace_id="ws-a",
                kind=ClawAlertKind.MEMORY_PROPOSAL,
                severity=ClawAlertSeverity.INFO,
                title="회사 공유 알림",
                created_at=T0,
            )
        )
        store.add_alert(
            ClawAlert(
                alert_id="alert-private",
                workspace_id="ws-a",
                kind=ClawAlertKind.FOLLOWUP_DUE,
                severity=ClawAlertSeverity.WARN,
                title="A 전용 알림",
                created_at=T0,
                visible_to_members=("member-1",),
            )
        )
        self.assertEqual(
            [a.alert_id for a in store.list_alerts("ws-a", member_id="member-2")],
            ["alert-shared"],
        )
        self.assertEqual(len(store.list_alerts("ws-a", member_id="member-1")), 2)
        self.assertIsNotNone(store.get_alert("alert-shared", workspace_id="ws-a", member_id="member-2"))
        self.assertIsNone(store.get_alert("alert-private", workspace_id="ws-a", member_id="member-2"))
        with self.assertRaises(ClawMemoryError):
            store.set_alert_status(
                "alert-private", ClawAlertStatus.DISMISSED, workspace_id="ws-a", member_id="member-2", at=T2
            )

    def test_6324_owner_less_reads_and_status_changes_cannot_be_expressed(self):
        """#6324: no default member_id anywhere — an owner-less call is a TypeError."""
        store = InMemoryClawMemoryStore()
        with self.assertRaises(TypeError):
            store.list_tasks("ws-a")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.list_alerts("ws-a")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.get_task("task-1", workspace_id="ws-a")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.get_alert("alert-1", workspace_id="ws-a")  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.set_task_status("task-1", ClawTaskStatus.DONE, workspace_id="ws-a", at=T0)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.set_alert_status("alert-1", ClawAlertStatus.DISMISSED, workspace_id="ws-a", at=T0)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            store.projection("ws-a")  # type: ignore[call-arg]

    def test_6324_protocol_declares_member_id_required_on_every_read(self):
        """The contract itself forbids a loose re-implementation."""
        for name in (
            "get_task",
            "list_tasks",
            "set_task_status",
            "get_alert",
            "list_alerts",
            "set_alert_status",
            "projection",
        ):
            parameter = inspect.signature(getattr(ClawMemoryStore, name)).parameters["member_id"]
            self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY, name)
            self.assertIs(parameter.default, inspect.Parameter.empty, name)

    def test_owner_projection_carries_the_original_body_and_diagnostics_omit_it(self):
        """#5360: the owner reads their own original business text in full.

        A diagnostic or log projection keeps the body digest and drops the
        owner's original text, so the text never reaches a log.
        """
        store = InMemoryClawMemoryStore()
        store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
        projection = store.projection("ws-a", member_id="member-1")
        rendered = repr(projection)
        self.assertIn(RAW_BODY, rendered)
        self.assertIn(sha256_text(RAW_BODY), rendered)
        diagnostic = store.projection("ws-a", member_id="member-1", include_raw=False)
        self.assertNotIn(RAW_BODY, repr(diagnostic))
        self.assertIn(sha256_text(RAW_BODY), repr(diagnostic))
        source = make_source()
        self.assertEqual(source.safe_dict()["raw_excerpt"], RAW_BODY)
        self.assertEqual(source.safe_dict(include_raw=True)["raw_excerpt"], RAW_BODY)
        self.assertEqual(source.safe_dict(include_raw=False).get("raw_excerpt"), None)

    def test_cross_workspace_candidate_and_access_fail_closed(self):
        with self.assertRaises(ClawMemoryError):
            ClawMemoryCandidate(
                candidate_id="cand-x",
                workspace_id="ws-a",
                kind=ClawMemoryKind.PARTY,
                payload={"name": "삼성상사", "role": "customer"},
                source=make_source("ws-b"),
                created_at=T0,
            )
        store = InMemoryClawMemoryStore()
        store.submit_candidate(make_party_candidate(), proposal_id="prop-1")
        with self.assertRaises(ClawMemoryError):
            store.decide_proposal(
                "prop-1",
                ClawProposalState.APPROVED,
                workspace_id="ws-b",
                decided_by="owner-1",
                decided_at=T1,
            )

    def test_price_proposal_flow_creates_durable_price_history(self):
        store = InMemoryClawMemoryStore()
        candidate = ClawMemoryCandidate(
            candidate_id="cand-price-1",
            workspace_id="ws-a",
            kind=ClawMemoryKind.PRICE,
            payload={
                "item_memory_id": "mem-i1",
                "unit_price": "5000",
                "currency": "KRW",
                "quoted_at": "2026-09-01",
            },
            source=make_source(),
            created_at=T0,
        )
        store.submit_candidate(candidate, proposal_id="prop-price")
        store.decide_proposal(
            "prop-price",
            ClawProposalState.APPROVED,
            workspace_id="ws-a",
            decided_by="owner-1",
            decided_at=T1,
        )
        record = store.apply_proposal("prop-price", workspace_id="ws-a", memory_id="mem-r1", applied_at=T2)
        self.assertIsInstance(record, ClawPriceMemory)
        self.assertEqual(record.unit_price, Decimal("5000"))
        self.assertEqual(record.quoted_at, date(2026, 9, 1))
        self.assertEqual(record.source_id, "src-001")

    def test_no_generic_rag_or_provider_surface_in_module(self):
        import kagent.claw_memory as claw_memory

        for banned in (
            "embed",
            "vector",
            "openai",
            "anthropic",
            "httpx",
            "requests",
            "sqlite",
            "psycopg",
            "boto",
            "neon",
            "wrangler",
        ):
            self.assertNotIn(banned, dir(claw_memory))
        source = open(claw_memory.__file__, encoding="utf-8").read()
        for banned in ("import httpx", "import requests", "import sqlite3", "fetch(", "urllib"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
