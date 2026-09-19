"""Contract tests for provider-neutral sandbox lease reclamation (#1405 / #2803).

Proves that the bounded sweep classifies what it examined, counts only what it
actually transitioned, refuses a provider that cannot be swept instead of reporting
an empty inventory it never earned, keeps unresolved leases out of the reclaimed
count, bounds and truncates its own work, and performs no I/O. A reclamation report
is bookkeeping about reservations: no assertion here lets it read as evidence that a
workload stopped.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import (
    DeterministicFakeSandboxProvider,
    SandboxLeaseError,
    SandboxUnavailableError,
    UnconfiguredSandboxProvider,
)
from kagent.sandbox_reclamation import (
    DEFAULT_RECLAMATION_SCAN,
    LeaseReclamationOutcome,
    LeaseReclamationRecord,
    LeaseReclamationReport,
    MAX_RECLAMATION_SCAN,
    reap_expired_leases,
    unresolved_leases,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "kagent" / "sandbox_reclamation.py"
START = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


def request(run_id: str = "run_reap", *, ttl_seconds: int = 900) -> SandboxLeaseRequest:
    return SandboxLeaseRequest(
        run_id=run_id,
        execution_mode=ExecutionMode.CLOUD,
        repository_ref="skerishKang/example",
        requested_revision="abcdef1234567890abcdef1234567890abcdef12",
        ttl_seconds=ttl_seconds,
    )


def fake_provider() -> DeterministicFakeSandboxProvider:
    return DeterministicFakeSandboxProvider(clock=lambda: START)


def lease(lease_id: str = "lease_a", run_id: str = "run_reap", **overrides) -> SandboxLease:
    values = {
        "lease_id": lease_id,
        "run_id": run_id,
        "execution_mode": ExecutionMode.CLOUD,
        "resource_class": ResourceClass.STANDARD,
        "network_policy": NetworkPolicy.OFF,
        "writable_workspace": False,
        "created_at": START,
        "expires_at": START + timedelta(seconds=900),
        "state": SandboxLeaseState.RESERVED,
    }
    values.update(overrides)
    return SandboxLease(**values)


class StaticProvider:
    """A reclamation port whose behaviour is fixed per lease, with no clock of its own."""

    def __init__(self, inventory=(), *, expire=None) -> None:
        self._inventory = tuple(inventory)
        self._expire = expire
        self.calls: list[str] = []

    def active_leases(self):
        return self._inventory

    def expire(self, lease_id, *, run_id, now):
        self.calls.append(lease_id)
        if self._expire is None:
            raise SandboxLeaseError("injected reclamation refusal")
        return self._expire(lease_id, run_id, now)


class SweepTests(unittest.TestCase):
    def outcomes(self, report: LeaseReclamationReport) -> dict[str, LeaseReclamationOutcome]:
        return {record.lease_id: record.outcome for record in report.records}

    def test_classifies_a_mixed_inventory(self):
        lapsed = lease("lease_lapsed")
        live = lease("lease_live", run_id="run_live", expires_at=START + timedelta(seconds=3_600))
        terminal = lease("lease_terminal", run_id="run_old", state=SandboxLeaseState.RELEASED)

        def expire(lease_id, run_id, now):
            assert lease_id == "lease_lapsed"
            return lapsed.with_state(SandboxLeaseState.EXPIRED)

        provider = StaticProvider((live, terminal, lapsed), expire=expire)
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))

        self.assertEqual(
            self.outcomes(report),
            {
                "lease_lapsed": LeaseReclamationOutcome.RECLAIMED,
                "lease_live": LeaseReclamationOutcome.NOT_YET_LAPSED,
                "lease_terminal": LeaseReclamationOutcome.ALREADY_TERMINAL,
            },
        )
        self.assertEqual(report.examined, 3)
        self.assertEqual(report.reclaimed_count, 1)
        self.assertEqual(report.unresolved_count, 0)
        self.assertTrue(report.fully_reclaimed)
        # a terminal lease is never handed to the provider at all
        self.assertEqual(provider.calls, ["lease_lapsed"])

    def test_examines_in_lease_id_order_not_inventory_order(self):
        inventory = tuple(lease(f"lease_{letter}") for letter in ("z", "a", "m"))
        provider = StaticProvider(
            inventory,
            expire=lambda lease_id, run_id, now: lease(lease_id).with_state(
                SandboxLeaseState.EXPIRED
            ),
        )
        report = reap_expired_leases(
            provider, now=START + timedelta(seconds=901), limit=2
        )
        self.assertEqual([record.lease_id for record in report.records], ["lease_a", "lease_m"])
        self.assertEqual(provider.calls, ["lease_a", "lease_m"])

    def test_limit_truncates_and_says_so(self):
        inventory = tuple(lease(f"lease_{index:02d}") for index in range(9))
        provider = StaticProvider(
            inventory,
            expire=lambda lease_id, run_id, now: lease(lease_id).with_state(
                SandboxLeaseState.EXPIRED
            ),
        )
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901), limit=4)
        self.assertEqual(report.inventory_size, 9)
        self.assertEqual(report.examined, 4)
        self.assertTrue(report.truncated)
        self.assertFalse(report.fully_reclaimed)
        self.assertEqual(report.reclaimed_count, 4)

    def test_default_scan_is_bounded_below_the_maximum(self):
        self.assertLessEqual(DEFAULT_RECLAMATION_SCAN, MAX_RECLAMATION_SCAN)
        inventory = tuple(lease(f"lease_{index:03d}") for index in range(MAX_RECLAMATION_SCAN + 5))
        provider = StaticProvider(inventory)
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(report.examined, DEFAULT_RECLAMATION_SCAN)
        self.assertTrue(report.truncated)

    def test_unresolved_never_counts_as_reclaimed(self):
        lapsed = lease("lease_lapsed")
        provider = StaticProvider((lapsed,))  # expire always refuses
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))

        self.assertEqual(
            self.outcomes(report), {"lease_lapsed": LeaseReclamationOutcome.RECONCILIATION_REQUIRED}
        )
        self.assertEqual(report.reclaimed_count, 0)
        self.assertEqual(report.unresolved_count, 1)
        self.assertFalse(report.fully_reclaimed)
        self.assertEqual(len(unresolved_leases(report)), 1)
        self.assertIn("injected reclamation refusal", unresolved_leases(report)[0].reason)

    def test_a_provider_that_fails_mid_pass_still_reports_the_whole_pass(self):
        # Losing the report would hide the leases that really were reclaimed.
        first = lease("lease_a")
        second = lease("lease_b", run_id="run_b")

        def expire(lease_id, run_id, now):
            if lease_id == "lease_b":
                raise SandboxUnavailableError("provider became unavailable")
            return lease(lease_id).with_state(SandboxLeaseState.EXPIRED)

        provider = StaticProvider((first, second), expire=expire)
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(report.reclaimed_count, 1)
        self.assertEqual(report.unresolved_count, 1)
        self.assertEqual(report.inventory_size, 2)
        self.assertFalse(report.fully_reclaimed)
        self.assertEqual([record.lease_id for record in unresolved_leases(report)], ["lease_b"])
        self.assertIn("became unavailable", unresolved_leases(report)[0].reason)

    def test_a_provider_that_accepts_without_expiring_is_unresolved(self):
        # The dangerous shape: the call succeeds, so a naive sweep would count it.
        lapsed = lease("lease_lapsed")
        provider = StaticProvider(
            (lapsed,),
            expire=lambda lease_id, run_id, now: lease(lease_id),  # still RESERVED
        )
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(report.reclaimed_count, 0)
        self.assertEqual(report.unresolved_count, 1)
        self.assertEqual(
            report.records[0].outcome, LeaseReclamationOutcome.RECONCILIATION_REQUIRED
        )
        self.assertIn("did not drive the lease to EXPIRED", report.records[0].reason)

    def test_missing_capability_is_refused_not_swept_empty(self):
        class LeaseOnly:
            def allocate(self, request):
                raise AssertionError("unused")

            def get(self, lease_id):
                raise AssertionError("unused")

            def renew(self, lease_id, *, run_id, ttl_seconds):
                raise AssertionError("unused")

            def release(self, lease_id, *, run_id):
                raise AssertionError("unused")

        with self.assertRaises(SandboxLeaseError) as caught:
            reap_expired_leases(LeaseOnly(), now=START + timedelta(seconds=901))
        self.assertIn("nothing was reclaimed", str(caught.exception))

    def test_an_unconfigured_provider_refuses_when_asked(self):
        # Distinct from the case above: this provider exposes the operations and says
        # no, so its own error class reaches the caller rather than an empty report.
        with self.assertRaises(SandboxUnavailableError):
            reap_expired_leases(UnconfiguredSandboxProvider(), now=START + timedelta(seconds=901))

    def test_supplied_clock_is_validated_once(self):
        provider = StaticProvider((lease(),))
        for candidate in (
            (START + timedelta(seconds=901)).replace(tzinfo=None),
            "2026-09-02T10:15:00Z",
            None,
        ):
            with self.subTest(now=candidate):
                # a nonsense question is refused by the contract rule, before any
                # provider is reached at all
                with self.assertRaises(ContractError):
                    reap_expired_leases(provider, now=candidate)
        self.assertEqual(provider.calls, [])

    def test_scan_limit_must_be_bounded(self):
        provider = StaticProvider((lease(),))
        for candidate in (0, -1, True, False, "10", MAX_RECLAMATION_SCAN + 1, None):
            with self.subTest(limit=candidate):
                with self.assertRaises(ContractError):
                    reap_expired_leases(
                        provider, now=START + timedelta(seconds=901), limit=candidate
                        )
        self.assertEqual(provider.calls, [])

    def test_the_sweep_never_reclaims_twice_in_one_pass(self):
        inventory = (lease("lease_a"), lease("lease_b", run_id="run_b"))
        seen: list[str] = []

        def expire(lease_id, run_id, now):
            self.assertNotIn(lease_id, seen)
            seen.append(lease_id)
            return lease(lease_id).with_state(SandboxLeaseState.EXPIRED)

        provider = StaticProvider(inventory, expire=expire)
        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(report.reclaimed_count, 2)
        self.assertEqual(sorted(provider.calls), ["lease_a", "lease_b"])


class FakeProviderSweepTests(unittest.TestCase):
    def test_one_pass_reclaims_every_run_that_lapsed_unread(self):
        # The behaviour gap #2803 closes: three reservations lapse and nobody reads
        # them, so before this change they stayed reserved and held their run slots.
        provider = fake_provider()
        ids = {run: provider.allocate(request(run)).lease_id for run in ("run_1", "run_2", "run_3")}
        self.assertEqual(len(provider.active_leases()), 3)

        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(report.inventory_size, 3)
        self.assertEqual(report.reclaimed_count, 3)
        self.assertTrue(report.fully_reclaimed)
        self.assertEqual(provider.active_leases(), ())
        self.assertEqual(report.truncated, False)

        # every reclaimed lease is terminal and cannot be revived
        for lease_id in ids.values():
            self.assertIs(provider.get(lease_id).state, SandboxLeaseState.EXPIRED)
        # and each run may reserve again, so reclamation released rather than locked
        for run in ids:
            self.assertIs(provider.allocate(request(run)).state, SandboxLeaseState.RESERVED)

    def test_a_second_pass_reclaims_nothing_and_claims_nothing(self):
        provider = fake_provider()
        provider.allocate(request("run_1"))
        first = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(first.reclaimed_count, 1)

        second = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        self.assertEqual(second.examined, 0)
        self.assertEqual(second.reclaimed_count, 0)
        self.assertEqual(second.inventory_size, 0)
        self.assertTrue(second.fully_reclaimed)

    def test_only_the_lapsed_part_of_a_mixed_store_is_reclaimed(self):
        provider = fake_provider()
        lapsed = provider.allocate(request("run_lapsed"))
        held = provider.allocate(request("run_held", ttl_seconds=3_600))
        ended = provider.allocate(request("run_released"))
        provider.release(ended.lease_id, run_id="run_released")

        report = reap_expired_leases(provider, now=START + timedelta(seconds=901))
        outcomes = {record.lease_id: record.outcome for record in report.records}
        self.assertEqual(outcomes[lapsed.lease_id], LeaseReclamationOutcome.RECLAIMED)
        self.assertEqual(outcomes[held.lease_id], LeaseReclamationOutcome.NOT_YET_LAPSED)
        self.assertNotIn(ended.lease_id, outcomes)
        self.assertEqual(provider.get(held.lease_id).state, SandboxLeaseState.RESERVED)


class ReportIntegrityTests(unittest.TestCase):
    def report(self, *records: LeaseReclamationRecord, inventory_size: int | None = None, limit: int = 10):
        return LeaseReclamationReport(
            observed_at=START,
            limit=limit,
            inventory_size=len(records) if inventory_size is None else inventory_size,
            records=tuple(records),
        )

    def test_counts_are_derived_from_the_records(self):
        records = (
            LeaseReclamationRecord("lease_a", "run_a", LeaseReclamationOutcome.RECLAIMED),
            LeaseReclamationRecord(
                "lease_b",
                "run_b",
                LeaseReclamationOutcome.RECONCILIATION_REQUIRED,
                reason="provider refused",
            ),
        )
        report = self.report(*records)
        self.assertEqual(report.examined, 2)
        self.assertEqual(report.reclaimed_count, 1)
        self.assertEqual(report.unresolved_count, 1)
        self.assertEqual(
            report.outcome_counts[LeaseReclamationOutcome.RECLAIMED.value], 1
        )

    def test_a_report_cannot_claim_more_reclamation_than_it_observed(self):
        # No reclaimed_count parameter exists, so the only way to state a count is to
        # produce the records behind it.
        fields = set(LeaseReclamationReport.__dataclass_fields__)
        self.assertNotIn("reclaimed_count", fields)
        self.assertNotIn("unresolved_count", fields)
        self.assertNotIn("truncated", fields)
        self.assertNotIn("fully_reclaimed", fields)

    def test_a_report_cannot_describe_a_sweep_that_could_not_have_happened(self):
        record = LeaseReclamationRecord(
            "lease_a", "run_a", LeaseReclamationOutcome.RECONCILIATION_REQUIRED, reason="x"
        )
        with self.assertRaises(ContractError):
            LeaseReclamationReport(
                observed_at=START, limit=1, inventory_size=5, records=(record, record)
            )
        with self.assertRaises(ContractError):
            LeaseReclamationReport(
                observed_at=START, limit=1, inventory_size=0, records=(record,)
            )
        with self.assertRaises(ContractError):
            LeaseReclamationReport(observed_at=START, limit=0, inventory_size=0, records=())
        with self.assertRaises(ContractError):
            LeaseReclamationReport(
                observed_at=START.replace(tzinfo=None), limit=1, inventory_size=0, records=()
            )

    def test_an_unresolved_record_has_to_say_why(self):
        with self.assertRaises(ContractError):
            LeaseReclamationRecord(
                "lease_a", "run_a", LeaseReclamationOutcome.RECONCILIATION_REQUIRED
            )
        # and a reclaimed one does not need a reason
        LeaseReclamationRecord("lease_a", "run_a", LeaseReclamationOutcome.RECLAIMED)

    def test_identifiers_are_bounded_and_outcomes_are_closed(self):
        for bad_id in ("", "lease a", "lease\na", "x" * 600):
            with self.subTest(lease_id=bad_id):
                with self.assertRaises(ContractError):
                    LeaseReclamationRecord(
                        bad_id, "run_a", LeaseReclamationOutcome.RECLAIMED
                    )
        with self.assertRaises(ContractError):
            LeaseReclamationRecord("lease_a", "run_a", "reclaimed_but_not_quite")

    def test_projection_reports_reservation_bookkeeping_only(self):
        report = self.report(
            LeaseReclamationRecord(
                "lease_a",
                "run_a",
                LeaseReclamationOutcome.RECONCILIATION_REQUIRED,
                reason="provider said token=sentinel-lease-secret-must-never-appear",
            ),
            LeaseReclamationRecord(
                "lease_b",
                "run_b",
                LeaseReclamationOutcome.RECONCILIATION_REQUIRED,
                reason="provider refused: lease has not reached its TTL",
            ),
        )
        safe = report.safe_dict()
        self.assertFalse(safe["workload_stop_observed"])
        self.assertFalse(safe["production_claim"])
        self.assertEqual(safe["real_provider_calls"], 0)
        self.assertEqual(safe["reclaimed_count"], 0)
        self.assertEqual(safe["unresolved_count"], 2)
        # A provider's own error text reaches evidence redacted where it has to be
        # and readable where it does not.
        projected = {record["lease_id"]: record["reason"] for record in safe["records"]}
        self.assertNotIn("sentinel-lease-secret-must-never-appear", str(safe["records"]))
        self.assertEqual(projected["lease_a"], "provider said token=[REDACTED]")
        self.assertEqual(projected["lease_b"], "provider refused: lease has not reached its TTL")

    def test_a_long_provider_reason_is_bounded(self):
        record = LeaseReclamationRecord(
            "lease_a",
            "run_a",
            LeaseReclamationOutcome.RECONCILIATION_REQUIRED,
            reason="x" * 5_000,
        )
        self.assertLessEqual(len(record.reason), 512)


class ModulePurityTests(unittest.TestCase):
    """The sweep decides; it must never reach for a clock, a socket or a filesystem."""

    def tree(self) -> ast.Module:
        return ast.parse(MODULE.read_text(encoding="utf-8"))

    def imported_modules(self) -> set[str]:
        modules: set[str] = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".")[0])
        return modules

    def called_names(self) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    names.add(node.func.attr)
        return names

    def test_no_io_capable_import(self):
        for module in ("os", "socket", "subprocess", "threading", "time", "asyncio",
                       "http", "requests", "urllib", "sqlite3", "pathlib"):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imported_modules())

    def test_only_the_lease_layer_is_imported(self):
        self.assertLessEqual(
            self.imported_modules(),
            {"__future__", "dataclasses", "datetime", "enum", "re", "kagent"},
        )

    def test_no_clock_or_environment_read(self):
        for forbidden in ("now", "today", "utcfromtimestamp", "environ", "getenv", "sleep",
                          "allocate", "open"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, self.called_names())

    def test_the_module_never_allocates_a_lease(self):
        # Reclamation only ends reservations; minting one would let a sweep create
        # the work it reports on.
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn(".allocate(", source)
        self.assertNotIn("datetime.now", source)


if __name__ == "__main__":
    unittest.main()
