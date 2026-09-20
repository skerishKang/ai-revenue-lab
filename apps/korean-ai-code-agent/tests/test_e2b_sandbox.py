"""Contract tests for the E2B Cloud M1 launch adapter prototype (#1405 step C).

Nothing here touches a provider: every transport is a scripted in-memory fake, and the
tests exist to pin four properties.

1. The launch body denies by construction — egress, public traffic, persistence,
   privilege and credentials are each written down, because E2B documents open defaults
   for egress and public URLs.
2. Termination is observed, never assumed. A kill acknowledgement without a terminal
   state observation is a refusal, and no projection can report a physical process-tree
   kill because the evidence record has no field that could carry one.
3. The adapter reuses the repository's canonical contracts instead of restating them:
   the same lease, state, identifier, revision, TTL and reclamation rules, to the point
   that the existing conformance harness and the existing bounded sweep evaluate it.
4. The prototype is not a selection: provider-native claims stay documented-or-unverified
   and adapter-enforced controls are labelled ADAPTER_BORNE.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from inspect import signature
from pathlib import Path
import unittest

from kagent.contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import (
    SandboxLeaseError,
    SandboxUnavailableError,
    supports_lease_reclamation,
    supports_workload_cancellation,
)
from kagent.sandbox_conformance_harness import SandboxProviderConformanceHarness
from kagent.sandbox_reclamation import LeaseReclamationOutcome, reap_expired_leases
from kagent.e2b_sandbox import (
    E2B_CONTROL_PROVENANCE,
    E2B_NEVER_ACCEPTED_KEYS,
    E2B_PAYLOAD_KEYS,
    E2BCloudM1Adapter,
    E2BAdapterError,
    E2BTerminationEvidence,
    REAL_E2B_PROVIDER_SELECTED,
    build_e2b_launch_payload,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "kagent" / "e2b_sandbox.py"
T0 = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
REVISION = "abcdef1234567890abcdef1234567890abcdef12"


def request(run_id: str = "run_1", *, ttl_seconds: int = 900, revision: object = REVISION,
            network_policy: NetworkPolicy = NetworkPolicy.OFF,
            execution_mode: ExecutionMode = ExecutionMode.CLOUD) -> SandboxLeaseRequest:
    return SandboxLeaseRequest(
        run_id=run_id,
        execution_mode=execution_mode,
        repository_ref="skerishKang/ai-revenue-lab",
        requested_revision=revision,
        ttl_seconds=ttl_seconds,
        network_policy=network_policy,
    )


class ScriptedTransport:
    """The only transport these tests run against. It cannot reach a network."""

    def __init__(self, *, terminal_state="killed", reports_running_after_kill=False,
                 pause_instead=False):
        self.payloads: list[dict] = []
        self.killed: list[str] = []
        self.counter = 0
        self.terminal_state = terminal_state
        self.reports_running_after_kill = reports_running_after_kill
        self.pause_instead = pause_instead

    def create(self, payload):
        self.payloads.append(dict(payload))
        self.counter += 1
        return {"sandbox_id": f"e2b-sbx-{self.counter:04d}", "state": "running"}

    def state(self, sandbox_id):
        if sandbox_id not in self.killed:
            return {"state": "running", "running": True}
        if self.pause_instead:
            return {"state": "paused", "running": False}
        if self.reports_running_after_kill:
            return {"state": "running", "running": True}
        return {"state": self.terminal_state, "running": False}

    def kill(self, sandbox_id):
        self.killed.append(sandbox_id)
        return True

    def list_running(self):
        return ()


_UNSET = object()


class AdapterCase(unittest.TestCase):
    def adapter(self, transport=_UNSET, **overrides):
        kwargs = {"template": "claw-m1-base", "clock": lambda: T0}
        kwargs.update(overrides)
        if transport is _UNSET:
            transport = ScriptedTransport()
        return E2BCloudM1Adapter(transport, **kwargs)

    def launched(self, transport=_UNSET, run_id="run_1", **overrides):
        adapter = self.adapter(transport, **overrides)
        lease = adapter.allocate(request(run_id), content_ref="content-rev-0001")
        return adapter, lease


class LaunchShapeTests(AdapterCase):
    def payload(self, **kwargs):
        overrides = {"template": "claw-m1-base", "content_ref": "content-rev-0001", "now": T0}
        overrides.update(kwargs)
        return build_e2b_launch_payload(overrides.pop("request", request()), **overrides)

    def test_egress_is_denied_explicitly_not_by_default(self):
        payload = self.payload()
        self.assertIs(payload["allow_internet_access"], False)
        self.assertEqual(payload["network"], {"deny_out": ["0.0.0.0/0"]})

    def test_public_traffic_is_restricted_explicitly(self):
        payload = self.payload()
        self.assertIs(payload["allow_public_traffic"], False)
        self.assertEqual(payload["public_ports"], ())

    def test_a_network_policy_other_than_off_is_refused(self):
        with self.assertRaises(ContractError):
            self.payload(request=request("run_1", network_policy=NetworkPolicy.RESTRICTED))

    def test_mutable_revisions_are_refused_by_the_canonical_rule(self):
        for revision in ("main", "refs/heads/main", "v1.2.3", "abcdef1", "HEAD", None, ""):
            with self.subTest(revision=revision):
                with self.assertRaises(ContractError):
                    self.payload(request=request("run_1", revision=revision))

    def test_ttl_is_bounded_by_the_existing_contract(self):
        payload = self.payload(request=request("run_1", ttl_seconds=SANDBOX_LEASE_MAX_TTL_SECONDS))
        self.assertEqual(payload["timeout"], 3_600)
        for ttl in (3_601, 59, 0, -1, True, "900"):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ContractError):
                    self.payload(request=request("run_1", ttl_seconds=ttl))

    def test_timeout_is_wired_to_kill_and_pause_is_forbidden(self):
        payload = self.payload()
        self.assertEqual(payload["timeout_action"], "kill")
        self.assertIs(payload["auto_pause"], False)
        self.assertIs(payload["auto_resume"], False)

    def test_snapshot_fork_and_volume_reuse_are_absent(self):
        payload = self.payload()
        self.assertIsNone(payload["snapshot"])
        self.assertIsNone(payload["fork_source"])
        self.assertEqual(payload["volume_mounts"], ())

    def test_privilege_host_mounts_sockets_and_credentials_are_absent(self):
        payload = self.payload()
        self.assertIs(payload["privileged"], False)
        self.assertEqual(payload["host_mounts"], ())
        self.assertIs(payload["runtime_socket"], False)
        self.assertEqual(payload["envs"], {})
        self.assertEqual(payload["secrets"], ())

    def test_no_endpoint_or_credential_key_can_enter_the_payload(self):
        payload = self.payload()
        self.assertEqual(set(payload), set(E2B_PAYLOAD_KEYS))
        self.assertFalse(set(payload).intersection(E2B_NEVER_ACCEPTED_KEYS))

    def test_the_adapter_takes_no_endpoint_and_no_credential(self):
        parameters = signature(E2BCloudM1Adapter.__init__).parameters
        self.assertFalse(any(
            name in parameters for name in ("api_url", "base_url", "domain", "endpoint", "token")
        ))
        self.assertIn("transport", parameters)
        with self.assertRaises(E2BAdapterError):
            self.adapter(transport=None)

    def test_a_url_cannot_be_smuggled_through_an_identifier_field(self):
        # The canonical identifier grammar excludes "/", so a host cannot ride in on a
        # template or content reference. This is reuse of the contract, not a second rule.
        for candidate in ("https://evil.example/base", "bucket/prefix", "a b"):
            with self.subTest(template=candidate):
                with self.assertRaises(E2BAdapterError):
                    self.adapter(template=candidate)

    def test_materialization_is_pre_supplied_content_only(self):
        payload = self.payload()
        self.assertEqual(payload["materialization"]["mode"], "PRE_SUPPLIED_EXACT_REVISION_CONTENT")
        self.assertIs(payload["materialization"]["live_clone"], False)

    def test_the_launch_body_shape_is_closed(self):
        # A new key has to be decided, not drifted in.
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("launch payload shape is closed", source)
        self.assertEqual(len(set(E2B_PAYLOAD_KEYS)), len(E2B_PAYLOAD_KEYS))


class PolicyDelegationTests(AdapterCase):
    """The adapter defers to the canonical Cloud M1 policy, and can be tightened by it."""

    def test_a_tightened_policy_ceiling_is_honoured_not_hardcoded_around(self):
        # The probe packet needs exactly this: an operator-tightened TTL ceiling has to
        # bind the adapter, instead of the adapter silently accepting the default 3600.
        from kagent.sandbox_conformance import SandboxSecurityPolicy

        tight = SandboxSecurityPolicy(max_ttl_seconds=300)
        adapter = self.adapter(template="claw", policy=tight)
        with self.assertRaises(ContractError) as caught:
            adapter.launch_payload(request("run_p", ttl_seconds=900), content_ref="content-p")
        self.assertIn("TTL", str(caught.exception))
        accepted = adapter.launch_payload(request("run_p", ttl_seconds=300), content_ref="content-p")
        self.assertEqual(accepted["timeout"], 300)

    def test_a_non_cloud_request_is_refused_by_the_canonical_validator(self):
        with self.assertRaises(ContractError):
            self.adapter().launch_payload(
                request("run_l", execution_mode=ExecutionMode.LOCAL), content_ref="content-l"
            )


class LifecycleTests(AdapterCase):
    def test_one_active_lease_per_run(self):
        adapter, first = self.launched()
        self.assertIs(first.state, SandboxLeaseState.RESERVED)
        self.assertEqual(first.lease_id, "e2b-sbx-0001")
        with self.assertRaises(SandboxLeaseError):
            adapter.allocate(request("run_1"), content_ref="content-rev-0002")

    def test_lease_identity_and_expiry_come_from_the_canonical_contract(self):
        adapter, lease = self.launched()
        self.assertIsInstance(lease, SandboxLease)
        self.assertEqual(lease.expires_at - lease.created_at, timedelta(seconds=900))
        self.assertIs(lease.network_policy, NetworkPolicy.OFF)
        self.assertIs(lease.execution_mode, ExecutionMode.CLOUD)

    def test_renewal_is_refused_because_the_seam_cannot_back_it(self):
        # E2BSandboxTransport has no timeout update, so an extended expires_at would be a
        # ledger-only claim: the provider still kills at the lifetime it agreed to. Refusing
        # is the fail-closed shape; #2832 found this test previously asserting the opposite.
        transport = ScriptedTransport()
        adapter, lease = self.launched(transport)
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.renew(lease.lease_id, run_id="run_1", ttl_seconds=1_200)
        self.assertIn("lifetime the provider never accepted", str(caught.exception))
        # neither the lease nor its lifetime moved, and the seam was not asked
        self.assertIs(adapter.get(lease.lease_id).state, SandboxLeaseState.RESERVED)
        self.assertEqual(
            adapter.get(lease.lease_id).expires_at, T0 + timedelta(seconds=900)
        )
        self.assertEqual(len(transport.payloads), 1)
        # ownership is still checked first, so a foreign lease fails for the real reason
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.renew(lease.lease_id, run_id="run_intruder", ttl_seconds=1_200)
        self.assertIn("different run", str(caught.exception))

    def test_release_and_cancel_end_the_lease_the_same_way(self):
        for verb in ("release", "cancel"):
            with self.subTest(verb=verb):
                adapter, lease = self.launched(run_id="run_x")
                ended = getattr(adapter, verb)(lease.lease_id, run_id="run_x")
                self.assertIs(ended.state, SandboxLeaseState.RELEASED)
                self.assertEqual(adapter.active_leases(), ())

    def test_wrong_run_cannot_end_or_reclaim_a_lease(self):
        adapter, lease = self.launched()
        with self.assertRaises(SandboxLeaseError):
            adapter.release(lease.lease_id, run_id="run_someone_else")
        with self.assertRaises(SandboxLeaseError):
            adapter.cancel(lease.lease_id, run_id="run_someone_else")
        with self.assertRaises(SandboxLeaseError):
            adapter.expire(lease.lease_id, run_id="run_someone_else", now=T0 + timedelta(seconds=900))
        self.assertIs(adapter.get(lease.lease_id).state, SandboxLeaseState.RESERVED)

    def test_terminal_leases_never_resurrect(self):
        adapter, lease = self.launched(run_id="run_t")
        adapter.cancel(lease.lease_id, run_id="run_t")
        for call in (
            lambda: adapter.cancel(lease.lease_id, run_id="run_t"),
            lambda: adapter.release(lease.lease_id, run_id="run_t"),
            lambda: adapter.renew(lease.lease_id, run_id="run_t", ttl_seconds=900),
            lambda: adapter.expire(lease.lease_id, run_id="run_t", now=T0 + timedelta(seconds=900)),
        ):
            with self.assertRaises(SandboxLeaseError):
                call()

    def test_unknown_lease_is_refused(self):
        adapter = self.adapter()
        with self.assertRaises(SandboxLeaseError):
            adapter.get("e2b-sbx-9999")
        with self.assertRaises(SandboxLeaseError):
            adapter.release("e2b-sbx-9999", run_id="run_1")


class LedgerIntegrityTests(AdapterCase):
    """#2832 readiness findings: identity collision and transport-failure shapes."""

    def test_a_reused_provider_sandbox_id_is_refused_not_recorded(self):
        class ReusingTransport(ScriptedTransport):
            def create(self, payload):
                self.payloads.append(dict(payload))
                return {"sandbox_id": "sbx-same", "state": "running"}

        transport = ReusingTransport()
        adapter = self.adapter(transport=transport)
        first = adapter.allocate(request("run_a"), content_ref="content-a")
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.allocate(request("run_b"), content_ref="content-b")
        self.assertIn("reused sandbox id", str(caught.exception))
        # the original record survives intact, and the refused run holds nothing
        self.assertEqual([entry.lease_id for entry in adapter.active_leases()], [first.lease_id])
        self.assertIs(adapter.get("sbx-same").run_id, "run_a")
        self.assertEqual(adapter._active_by_run.get("run_a"), "sbx-same")
        self.assertNotIn("run_b", adapter._active_by_run)
        self.assertEqual(len(transport.payloads), 2)

    def test_a_transport_failure_is_reported_as_a_refused_lease_operation(self):
        class FailingTransport(ScriptedTransport):
            def state(self, sandbox_id):
                raise ConnectionError("provider unreachable")

        adapter, lease = self.launched(FailingTransport(), run_id="run_flaky")
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.cancel(lease.lease_id, run_id="run_flaky")
        self.assertIn("provider state failed", str(caught.exception))
        self.assertIn("ConnectionError", str(caught.exception))
        # nothing is recorded as ended when the outcome could not be observed
        self.assertIs(adapter.get(lease.lease_id).state, SandboxLeaseState.RESERVED)
        self.assertEqual([entry.lease_id for entry in adapter.active_leases()], [lease.lease_id])

    def test_a_failing_provider_leaves_the_sweep_with_a_report_not_a_crash(self):
        class FailingTransport(ScriptedTransport):
            def state(self, sandbox_id):
                raise ConnectionError("provider unreachable")

        adapter = self.adapter(transport=FailingTransport())
        for run in ("run_a", "run_b"):
            adapter.allocate(request(run), content_ref="content-" + run)
        report = reap_expired_leases(adapter, now=T0 + timedelta(seconds=901))
        self.assertEqual(report.inventory_size, 2)
        self.assertEqual(report.reclaimed_count, 0)
        self.assertEqual(report.unresolved_count, 2)
        self.assertFalse(report.fully_reclaimed)
        for record in report.records:
            self.assertIs(record.outcome, LeaseReclamationOutcome.RECONCILIATION_REQUIRED)
            self.assertIn("provider state failed", record.reason)


class TerminationObservationTests(AdapterCase):
    def test_kill_acknowledgement_alone_does_not_end_a_lease(self):
        transport = ScriptedTransport(reports_running_after_kill=True)
        adapter, lease = self.launched(transport, run_id="run_leak")
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.cancel(lease.lease_id, run_id="run_leak")
        self.assertIn("unresolved", str(caught.exception))
        # the reservation is still held, so no caller can read a clean ending
        self.assertIs(adapter.get(lease.lease_id).state, SandboxLeaseState.RESERVED)
        self.assertEqual([entry.lease_id for entry in adapter.active_leases()], [lease.lease_id])
        self.assertTrue(adapter.termination_evidence(lease.lease_id).unresolved)

    def test_a_paused_sandbox_is_refused_not_treated_as_reclaimed(self):
        # E2B documents no TTL for a paused sandbox, so pause is a persistence channel.
        transport = ScriptedTransport(pause_instead=True)
        adapter, lease = self.launched(transport, run_id="run_pause")
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.release(lease.lease_id, run_id="run_pause")
        self.assertIn("forbids pause/resume", str(caught.exception))
        self.assertIs(adapter.get(lease.lease_id).state, SandboxLeaseState.RESERVED)

    def test_no_path_can_attest_a_physical_process_tree_kill(self):
        fields = set(E2BTerminationEvidence.__dataclass_fields__)
        self.assertFalse(any("process" in name for name in fields))
        self.assertNotIn("process_tree_killed", fields)
        adapter, lease = self.launched(run_id="run_ev")
        adapter.cancel(lease.lease_id, run_id="run_ev")
        evidence = adapter.termination_evidence(lease.lease_id)
        self.assertFalse(evidence.physical_process_tree_kill_attested)
        safe = evidence.safe_dict()
        self.assertTrue(safe["reservation_terminated"])
        self.assertFalse(safe["process_tree_kill_attested"])
        self.assertTrue(safe["physical_kill_claim_prohibited"])
        self.assertEqual(safe["real_provider_calls"], 0)
        # and an outcome cannot be asserted without the observation behind it
        with self.assertRaises(E2BAdapterError):
            E2BTerminationEvidence(
                sandbox_id="e2b-sbx-0001",
                reservation_terminated=True,
                terminal_state_observed=False,
                provider_terminal_state="killed",
                observed_at=T0,
                kill_acknowledged=True,
            )
        with self.assertRaises(TypeError):
            E2BTerminationEvidence(
                "e2b-sbx-0001", True, True, "killed", T0, True, process_tree_killed=True
            )

    def test_termination_requires_a_terminal_provider_state(self):
        with self.assertRaises(E2BAdapterError):
            E2BTerminationEvidence(
                sandbox_id="e2b-sbx-0001",
                reservation_terminated=True,
                terminal_state_observed=True,
                provider_terminal_state="running",
                observed_at=T0,
                kill_acknowledged=True,
            )

    def test_evidence_for_an_unobserved_lease_is_refused(self):
        adapter = self.adapter()
        with self.assertRaises(E2BAdapterError):
            adapter.termination_evidence("e2b-sbx-4242")


class ReclamationIntegrationTests(AdapterCase):
    def test_expire_needs_no_prior_read_and_reclaims_a_lapsed_lease(self):
        adapter, lease = self.launched(run_id="run_reap")
        expired = adapter.expire(lease.lease_id, run_id="run_reap", now=T0 + timedelta(seconds=900))
        self.assertIs(expired.state, SandboxLeaseState.EXPIRED)
        self.assertEqual(adapter.active_leases(), ())
        # the run may reserve again: reclamation released, it did not lock
        again = adapter.allocate(request("run_reap"), content_ref="content-rev-0002")
        self.assertIs(again.state, SandboxLeaseState.RESERVED)

    def test_expire_refuses_before_the_ttl_without_touching_the_lease(self):
        adapter, lease = self.launched(run_id="run_early")
        with self.assertRaises(SandboxLeaseError):
            adapter.expire(lease.lease_id, run_id="run_early", now=T0 + timedelta(seconds=899))
        self.assertEqual(adapter._transport.killed, [])
        self.assertIs(adapter.active_leases()[0].state, SandboxLeaseState.RESERVED)

    def test_the_canonical_sweep_reclaims_through_the_adapter(self):
        adapter = self.adapter()
        for run in ("run_a", "run_b"):
            adapter.allocate(request(run), content_ref=f"content-{run}")
        report = reap_expired_leases(adapter, now=T0 + timedelta(seconds=901))
        self.assertEqual(report.inventory_size, 2)
        self.assertEqual(report.reclaimed_count, 2)
        self.assertEqual(report.unresolved_count, 0)
        self.assertTrue(report.fully_reclaimed)
        self.assertEqual(adapter.active_leases(), ())

    def test_an_unobservable_kill_becomes_reconciliation_not_reclamation(self):
        transport = ScriptedTransport(reports_running_after_kill=True)
        adapter = self.adapter(transport=transport)
        adapter.allocate(request("run_a"), content_ref="content-run_a")
        adapter.allocate(request("run_b"), content_ref="content-run_b")
        report = reap_expired_leases(adapter, now=T0 + timedelta(seconds=901))
        self.assertEqual(report.reclaimed_count, 0)
        self.assertEqual(report.unresolved_count, 2)
        self.assertFalse(report.fully_reclaimed)
        outcomes = {r.lease_id: r.outcome for r in report.records}
        self.assertTrue(all(o is LeaseReclamationOutcome.RECONCILIATION_REQUIRED
                            for o in outcomes.values()))


class CanonicalPortReuseTests(AdapterCase):
    def facade(self, adapter):
        """Supply the pre-materialized content ref so the canonical port shape fits.

        The adapter needs a content reference to launch; the ports do not carry one, so
        this thin forwarder is what proves the adapter satisfies them unchanged. It adds
        no behaviour of its own.
        """
        outer = self

        class Launch:
            allocate_calls = 0

            def allocate(self, req):
                Launch.allocate_calls += 1
                return adapter.allocate(req, content_ref="content-facade")

            def get(self, lease_id):
                return adapter.get(lease_id)

            def renew(self, lease_id, *, run_id, ttl_seconds):
                return adapter.renew(lease_id, run_id=run_id, ttl_seconds=ttl_seconds)

            def release(self, lease_id, *, run_id):
                return adapter.release(lease_id, run_id=run_id)

            def cancel(self, lease_id, *, run_id):
                return adapter.cancel(lease_id, run_id=run_id)

            def active_leases(self):
                return adapter.active_leases()

            def expire(self, lease_id, *, run_id, now):
                return adapter.expire(lease_id, run_id=run_id, now=now)

        return Launch()

    def test_existing_probes_recognise_the_adapter(self):
        adapter = self.adapter()
        self.assertTrue(supports_workload_cancellation(adapter))
        self.assertTrue(supports_lease_reclamation(adapter))

    def test_the_existing_conformance_harness_accepts_the_adapter(self):
        # A fresh adapter per exercise: each step leaves a live reservation behind on
        # purpose, and one run cannot hold two of them.
        harness = SandboxProviderConformanceHarness()
        self.assertTrue(
            harness.evaluate_cancellation(self.facade(self.adapter()), request("run_cancel"))
        )
        self.assertTrue(
            harness.evaluate_reclamation(self.facade(self.adapter()), request("run_reclaim"))
        )
        self.assertTrue(
            harness.evaluate_lease_lifecycle(self.facade(self.adapter()), request("run_full"))
        )

    def test_the_adapter_does_not_restate_the_lease_or_revision_contract(self):
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("re.compile", source)
        self.assertNotIn("class SandboxLease", source)
        self.assertNotIn("class SandboxLeaseState", source)
        for forbidden in ("_SAFE_ID_RE", "EXACT_COMMIT_REVISION_RE", "[0-9a-f]{40}"):
            with self.subTest(symbol=forbidden):
                self.assertNotIn(forbidden, source)
        # the canonical rules are imported and used, not copied
        self.assertIn("_safe_id", source)
        # policy validation is delegated to the one canonical Cloud M1 entry point
        self.assertIn("validate_lease_request_against_cloud_m1_policy", source)
        for restated in ("SandboxProviderConformanceGate()", "NetworkPolicy.OFF"):
            with self.subTest(restated=restated):
                self.assertNotIn(restated, source)


class EvidenceHonestyTests(AdapterCase):
    def test_the_prototype_selects_nothing_and_calls_nothing(self):
        adapter, lease = self.launched(run_id="run_flags")
        self.assertFalse(REAL_E2B_PROVIDER_SELECTED)
        self.assertFalse(adapter.live_execution_ready)
        safe = adapter.safe_dict()
        self.assertFalse(safe["formal_provider_selected"])
        self.assertFalse(safe["live_execution_ready"])
        self.assertEqual(safe["real_provider_calls"], 0)
        self.assertEqual(safe["real_sandbox_allocations"], 0)
        self.assertEqual(safe["provider_sdk_imports"], 0)
        self.assertEqual(safe["credential_material_read"], 0)
        self.assertFalse(safe["production_claim"])
        self.assertEqual(safe["provider_candidate"], "e2b")
        self.assertEqual(safe["isolation_primitive"], "microvm")

    def test_adapter_enforced_controls_are_labelled_adapter_borne(self):
        self.assertEqual(E2B_CONTROL_PROVENANCE["network_deny_by_default"], "adapter_borne")
        self.assertEqual(E2B_CONTROL_PROVENANCE["exact_revision_materialization"], "adapter_borne")
        self.assertEqual(E2B_CONTROL_PROVENANCE["cross_run_reuse_disabled"], "adapter_borne")
        # provider statements stay provider statements
        self.assertEqual(E2B_CONTROL_PROVENANCE["egress_policy_enforced"], "provider_documented")
        self.assertEqual(E2B_CONTROL_PROVENANCE["ttl_enforced"], "provider_documented")
        # and what nobody has observed is not laundered into either bucket
        for control in ("cancellation_kills_workload", "teardown_guaranteed",
                        "provider_metadata_blocked", "checkout_hooks_disabled"):
            with self.subTest(control=control):
                self.assertEqual(E2B_CONTROL_PROVENANCE[control], "unverified_live")

    def test_no_provider_native_guarantee_is_claimed_as_measured(self):
        source = MODULE.read_text(encoding="utf-8")
        # Every control sits in one of three honest buckets, none of them "verified".
        self.assertTrue(
            set(E2B_CONTROL_PROVENANCE.values())
            <= {"provider_documented", "adapter_borne", "unverified_live"}
        )
        for claim in ('"VERIFIED"', '"MEASURED"', "CONFORMANCE_PASS", "process tree killed"):
            with self.subTest(claim=claim):
                self.assertNotIn(claim, source)
        # the only evidence basis the adapter can offer is its own observation
        self.assertIn('"evidence_basis": "ADAPTER_OBSERVATION"', source)

    def test_this_child_projects_no_artifact_or_output_bounds(self):
        # Bounds belong to the canonical artifact contract, not to a provider module that
        # could quietly define a second ceiling.
        source = MODULE.read_text(encoding="utf-8")
        for symbol in ("max_bytes", "MAX_ARTIFACT", "sha256", "ArtifactCandidateCollection",
                       "excerpt"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, source)

    def test_the_unverified_documentation_claims_are_marked_as_such(self):
        import kagent.e2b_sandbox as module

        self.assertEqual(module.E2B_DEFAULT_EGRESS, "ALLOW")
        self.assertEqual(module.E2B_PUBLIC_URL_DEFAULT, "PUBLIC")
        self.assertEqual(module.E2B_PAUSED_SANDBOX_TTL, "NONE")
        self.assertEqual(module.E2B_LINK_LOCAL_169_254_BLOCKED,
                         "CENTRAL_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED")
        self.assertEqual(module.E2B_CONTROL_CHANNEL_EXCEPTION,
                         "CENTRAL_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED")
        self.assertTrue(module.E2B_SECURITY_LIVE_PROBE_WRITTEN_CONSENT_REQUIRED)
        self.assertFalse(module.E2B_ARTIFACT_PROJECTION_IN_THIS_CHILD)


class ModulePurityTests(unittest.TestCase):
    def tree(self) -> ast.Module:
        return ast.parse(MODULE.read_text(encoding="utf-8"))

    def imported_modules(self) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
        return found

    def test_no_provider_sdk_and_no_network_capable_import(self):
        for module in ("e2b", "requests", "httpx", "urllib", "urllib3", "socket", "ssl",
                       "subprocess", "aiohttp", "os", "threading", "time"):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imported_modules())

    def test_only_the_stdlib_and_this_packages_contract_layer_are_imported(self):
        self.assertLessEqual(
            self.imported_modules(),
            {"__future__", "dataclasses", "datetime", "enum", "typing"},
        )

    def test_the_module_never_reads_a_clock_or_the_environment(self):
        names: set[str] = set()
        for node in ast.walk(self.tree()):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    names.add(node.func.attr)
        for forbidden in ("now", "today", "environ", "getenv", "sleep", "open", "print"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, names)
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("http", source.lower().replace("https://docs.e2b.dev", ""))


if __name__ == "__main__":
    unittest.main()
