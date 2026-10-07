"""#3611 — `browser.open` product composition and restart-safe one-shot tests.

Hermetic: no browser, no network, no model call, no real profile. The durable
store is a real SQLite file (or `:memory:`), because the point of this suite is
that the one-shot is anchored to a *durable* fact rather than to a process-local
set.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

from kagent.browser_open import (
    BROWSER_OPEN_HOST_REF,
    BROWSER_OPEN_TOOL_ID,
    BrowserOpenOutcome,
    BrowserOpenReceipt,
    BrowserOpenRefusal,
    BrowserOpenRequest,
    browser_open_fingerprint,
    browser_open_host_lease_ref,
    browser_open_target_ref,
)
from kagent.browser_open_authority import (
    BROWSER_CONTROL_IMPLEMENTED,
    BROWSER_OPEN_AUTHORITY_COMPOSED,
    BROWSER_OPEN_USES_EXISTING_P01,
    DURABLE_ONE_SHOT_ANCHOR,
    LOCAL_POLICY_RECOMPUTED_AT_COMPOSITION,
    NEW_APPROVAL_STORE,
    NEW_BROKER_ROUTE,
    P01_EVIDENCE_ROUTE_REUSED,
    RESTART_SAFE_ONE_SHOT,
    SECOND_APPROVAL_AUTHORITY,
    SECOND_BROWSER_AUTHORITY,
    BrowserOpenAuthority,
    BrowserOpenAuthorityEvidence,
    DeterministicBrowserOpenAuthorityEvidencePort,
    P01LoopbackBrowserOpenEvidenceClient,
    P01LocalPermissionBrowserOpenAuthorizationPort,
    UnconfiguredBrowserOpenAuthorityEvidencePort,
    settle_browser_open_command,
)
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_durable_run import (
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
)
from kagent.local_agent_durable_run_store import DurableRunStore
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPolicyMode,
    RootPermissionPolicy,
    default_device_permission_profile,
)
from kagent.local_agent_runtime_assembly import BoundLocalAgentRuntimeAssembly
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import WindowsExecutionReceipt, WindowsExecutionTermination

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
SAFE_URL = "https://example.com/report?id=7#section"
COMMAND_ID = "command.3611.open.1"
FINGERPRINT_SOURCE_BROKER = "broker"


# --- fixtures ----------------------------------------------------------------


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3611",
        workspace_ref="workspace_3611",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root_work", windows_path=r"E:\work"),),
    )


def profile(browser_mode: LocalPolicyMode = LocalPolicyMode.ASK) -> DevicePermissionProfile:
    base = default_device_permission_profile(device=device())
    global_rules = tuple(
        CapabilityRule(LocalCapability.BROWSER_OPEN, browser_mode)
        if rule.capability is LocalCapability.BROWSER_OPEN
        else rule
        for rule in base.global_rules
    )
    return DevicePermissionProfile(
        device_id=base.device_id,
        workspace_ref=base.workspace_ref,
        roots=tuple(RootPermissionPolicy(root.root_ref, root.rules) for root in base.roots),
        global_rules=global_rules,
    )


def request(**overrides: object) -> BrowserOpenRequest:
    values: dict[str, object] = {
        "open_id": "open_1",
        "run_id": "run_3611",
        "device_id": "device_3611",
        "ticket_ref": "ticket_3611",
        "target_url": SAFE_URL,
        "requested_at": NOW,
        "ttl_seconds": 300,
    }
    values.update(overrides)
    return BrowserOpenRequest(**values)  # type: ignore[arg-type]


def admitted_record(**overrides: object) -> DurableRunRecord:
    values: dict[str, object] = {
        "command_id": COMMAND_ID,
        "run_id": "run_3611",
        "tool_request_ref": "tool-request.3611",
        "request_id": "request.3611",
        "revision_ref": "revision.7f3c1a9e",
        "device_id": "device_3611",
        "binding_ref": "pairing-binding." + "a" * 32,
        "session_id": "session.3611",
        "account_ref": "account.3611",
        "workspace_ref": "workspace_3611",
        "sequence": 7,
        "credential_generation": 1,
        "request_fingerprint": browser_open_fingerprint(request()),
        "fingerprint_source": FINGERPRINT_SOURCE_BROKER,
        "command_issued_at": NOW - timedelta(seconds=30),
        "command_expires_at": NOW + timedelta(seconds=300),
        "admitted_at": NOW - timedelta(seconds=20),
        "admission_ref": "admission.3611",
    }
    values.update(overrides)
    return DurableRunRecord(**values)  # type: ignore[arg-type]


def pause(item: BrowserOpenRequest, *, scope: tuple[str, ...] = (BROWSER_OPEN_TOOL_ID,)) -> ApprovalPause:
    return ApprovalPause(
        pause_id="pause_3611",
        run_id=item.run_id,
        agent_runtime_id="runtime_3611",
        tool_id=BROWSER_OPEN_TOOL_ID,
        invocation_sha256=browser_open_fingerprint(item),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=600),
        approval_scope=scope,
    )


def decision(item: BrowserOpenRequest, *, outcome: ApprovalOutcome = ApprovalOutcome.APPROVED) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id="decision_3611",
        pause_id="pause_3611",
        outcome=outcome,
        authority_ref="p01_authority.3611",
        evidence_ref="evidence.p01.3611",
        decided_at=NOW - timedelta(seconds=4),
    )


def evidence(item: BrowserOpenRequest, **overrides: object) -> BrowserOpenAuthorityEvidence:
    from kagent.local_agent_permissions import LocalPermissionRequest

    values: dict[str, object] = {
        "evidence_ref": "evidence.p01.3611",
        "request_fingerprint": browser_open_fingerprint(item),
        "command_id": COMMAND_ID,
        "permission_request": LocalPermissionRequest(
            action_id=f"browser_open_{item.open_id}",
            run_id=item.run_id,
            device_id=item.device_id,
            capability=LocalCapability.BROWSER_OPEN,
            target_ref=browser_open_target_ref(item),
        ),
        "approval_pause": pause(item),
        "approval_decision": decision(item),
        "local_policy_ref": "local:require_p01_approval",
        "admission_ref": "admission.3611",
        "revision_ref": "revision.7f3c1a9e",
        "expires_at": NOW + timedelta(seconds=600),
    }
    values.update(overrides)
    return BrowserOpenAuthorityEvidence(**values)  # type: ignore[arg-type]


class FakeViewPort:
    """Deterministic trusted host double. Creates no browser and no profile."""

    def __init__(self, *, outcome: str = "loaded", raises: Exception | None = None) -> None:
        self.opened: list[str] = []
        self.closed_leases: list[str] = []
        self._outcome = outcome
        self._raises = raises
        self.configured = True

    def open(self, *, request, grant, now):  # type: ignore[no-untyped-def]
        self.opened.append(request.open_id)
        if self._raises is not None:
            raise self._raises
        if self._outcome == "policy_denied":
            raise BrowserOpenRefusal("policy_denied", "host refused the URL")
        return BrowserOpenReceipt(
            open_id=request.open_id,
            run_id=request.run_id,
            device_id=request.device_id,
            host_lease_ref=grant.host_lease_ref,
            requested_url_normalized=request.normalized_url,
            load_outcome=BrowserOpenOutcome(self._outcome),
            redirect_count=0,
            dialogs_suppressed=1,
            opened_at=now,
            closed_at=now + timedelta(milliseconds=5),
            elapsed_ms=5,
            host_ref=BROWSER_OPEN_HOST_REF,
            request_fingerprint=grant.request_fingerprint,
            p01_approval_ref=grant.p01_approval_ref,
            admission_ref="admission.3611",
            revision_ref="revision.7f3c1a9e",
            final_url_normalized=request.normalized_url,
        )


def authority(
    store: DurableRunStore,
    *,
    view: FakeViewPort | None = None,
    item: BrowserOpenRequest | None = None,
    evidence_items: tuple[BrowserOpenAuthorityEvidence, ...] | None = None,
) -> BrowserOpenAuthority:
    item = item or request()
    return BrowserOpenAuthority(
        device=device(),
        permission_profile=profile(),
        store=store,
        host=view or FakeViewPort(),
        evidence_port=DeterministicBrowserOpenAuthorityEvidencePort(
            evidence_items or (evidence(item),)
        ),
    )


# --- hermetic integration ----------------------------------------------------


class CompositionIntegrationTests(unittest.TestCase):
    def test_the_full_chain_runs_once_and_settles_durably(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            view = FakeViewPort()
            composed = authority(store, view=view)

            outcome = composed.open(request=request(), now=NOW)

            self.assertEqual(outcome.load_outcome, BrowserOpenOutcome.LOADED)
            self.assertTrue(outcome.settled)
            self.assertEqual(outcome.command_id, COMMAND_ID)
            self.assertEqual(view.opened, ["open_1"])
            self.assertEqual(outcome.host_lease_ref, browser_open_host_lease_ref(request()))
            # The durable row is the anchor, and it ends terminal.
            settled = store.get(command_id=COMMAND_ID)
            assert settled is not None
            self.assertIs(settled.state, DurableRunState.TERMINAL)
            self.assertIs(settled.termination, DurableRunTermination.EXITED)
            self.assertEqual(settled.evidence.summary, "browser.open loaded")

    def test_the_durable_transition_happens_before_any_view_exists(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            seen: list[DurableRunState] = []
            inner = FakeViewPort()

            class ObservingView(FakeViewPort):
                def open(self, *, request, grant, now):  # type: ignore[no-untyped-def]
                    current = store.get(command_id=COMMAND_ID)
                    assert current is not None
                    seen.append(current.state)
                    return inner.open(request=request, grant=grant, now=now)

            composed = authority(store, view=ObservingView())
            composed.open(request=request(), now=NOW)

            # By the time the host is reached the command is already EXECUTING,
            # so a crash from here on cannot be mistaken for "never started".
            self.assertEqual(seen, [DurableRunState.EXECUTING])

    def test_the_receipt_carries_no_page_derived_material(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            outcome = authority(store).open(request=request(), now=NOW)
            rendered = outcome.safe_dict()
            self.assertFalse(rendered["receipt"]["page_content_included"])
            self.assertFalse(rendered["receipt"]["cookie_included"])
            self.assertFalse(rendered["receipt"]["credential_included"])
            self.assertFalse(rendered["receipt"]["dom_api_exposed"])
            self.assertEqual(rendered["page_derived_bytes"], 0)
            self.assertEqual(rendered["receipt"]["network_scope"], "approved_url_fetch_only")

    def test_a_refusal_after_the_durable_transition_settles_and_stays_refused(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            composed = authority(store, view=FakeViewPort(outcome="policy_denied"))

            with self.assertRaises(BrowserOpenRefusal):
                composed.open(request=request(), now=NOW)

            settled = store.get(command_id=COMMAND_ID)
            assert settled is not None
            self.assertIs(settled.state, DurableRunState.TERMINAL)
            self.assertIs(settled.termination, DurableRunTermination.ABORTED)
            # A settled command is still never replayable.
            self.assertFalse(settled.replayable)


# --- restart / replay --------------------------------------------------------


class RestartReplayTests(unittest.TestCase):
    """The one-shot must survive losing every in-process object."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "durable-runs.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_second_open_after_a_full_restart_is_denied(self) -> None:
        # First process: complete one open.
        with DurableRunStore(self.path) as first:
            first.put(admitted_record())
            first_view = FakeViewPort()
            authority(first, view=first_view).open(request=request(), now=NOW)
            self.assertEqual(first_view.opened, ["open_1"])

        # Restart: brand-new store object, brand-new authority, empty memory.
        with DurableRunStore(self.path) as second:
            second_view = FakeViewPort()
            composed = authority(second, view=second_view)
            with self.assertRaises(BrowserOpenRefusal) as raised:
                composed.open(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "command_already_settled")
            # No second view was ever created.
            self.assertEqual(second_view.opened, [])

    def test_a_second_open_after_a_crash_mid_open_is_denied(self) -> None:
        # First process: the durable transition happens, then the process dies
        # before the host returns and before any settlement.
        with DurableRunStore(self.path) as first:
            first.put(admitted_record())
            port = P01LocalPermissionBrowserOpenAuthorizationPort(
                device=device(),
                permission_profile=profile(),
                store=first,
                evidence_port=DeterministicBrowserOpenAuthorityEvidencePort((evidence(request()),)),
            )
            grant, _ = port.authorize(request=request(), now=NOW)
            started = first.get(command_id=COMMAND_ID)
            assert started is not None
            self.assertIs(started.state, DurableRunState.EXECUTING)
            self.assertEqual(grant.request_fingerprint, browser_open_fingerprint(request()))
            # ... process ends here. Nothing settles the row.

        with DurableRunStore(self.path) as second:
            second_view = FakeViewPort()
            with self.assertRaises(BrowserOpenRefusal) as raised:
                authority(second, view=second_view).open(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "command_already_started")
            self.assertEqual(second_view.opened, [])

    def test_the_in_process_consumed_set_is_not_the_authority(self) -> None:
        """An empty in-memory set must not be enough to open a second time."""

        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
            store.mark_started(command_id=COMMAND_ID, started_at=NOW - timedelta(seconds=1))
            fresh = authority(store)
            # The fresh authority has consumed nothing at all.
            self.assertEqual(fresh.consumed_count, 0)
            with self.assertRaises(BrowserOpenRefusal) as raised:
                fresh.open(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "command_already_started")
            self.assertEqual(fresh.consumed_count, 0)

    def test_the_recovery_report_never_offers_the_open_for_replay(self) -> None:
        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
            store.mark_started(command_id=COMMAND_ID, started_at=NOW - timedelta(seconds=1))

        with DurableRunStore(self.path) as reopened:
            report = reopened.recover(now=NOW)
            self.assertEqual(report.replay_candidates, ())
            self.assertFalse(report.execution_authority_granted)
            self.assertEqual(report.safe_dict()["execution_authority_granted"], False)


class DurableStoreTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "durable-runs.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mark_started_admits_exactly_one_winner(self) -> None:
        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
            self.assertTrue(store.mark_started(command_id=COMMAND_ID, started_at=NOW))
            self.assertFalse(store.mark_started(command_id=COMMAND_ID, started_at=NOW))
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.EXECUTING)
            self.assertEqual(record.started_at, NOW)

    def test_mark_started_refuses_a_missing_or_terminal_command(self) -> None:
        with DurableRunStore(self.path) as store:
            self.assertFalse(store.mark_started(command_id="command.absent", started_at=NOW))
            store.put(admitted_record())
            self.assertTrue(store.mark_started(command_id=COMMAND_ID, started_at=NOW))
            receipt = FakeViewPort().open(
                request=request(), grant=_grant(), now=NOW
            )
            self.assertTrue(
                settle_browser_open_command(
                    store=store, command_id=COMMAND_ID, receipt=receipt, now=NOW
                )
            )
            # Already terminal: never a second local run.
            self.assertFalse(store.mark_started(command_id=COMMAND_ID, started_at=NOW))


def _grant():
    """Build a grant through the canonical path (never by hand)."""

    with DurableRunStore(":memory:") as store:
        store.put(admitted_record())
        port = P01LocalPermissionBrowserOpenAuthorizationPort(
            device=device(),
            permission_profile=profile(),
            store=store,
            evidence_port=DeterministicBrowserOpenAuthorityEvidencePort((evidence(request()),)),
        )
        grant, _ = port.authorize(request=request(), now=NOW)
        return grant


# --- fail-closed and refusals ------------------------------------------------


class AuthorizationRefusalTests(unittest.TestCase):
    def _port(self, store: DurableRunStore, **kwargs: object) -> P01LocalPermissionBrowserOpenAuthorizationPort:
        item = kwargs.pop("item", None) or request()
        items = kwargs.pop("evidence_items", None) or (evidence(item),)
        return P01LocalPermissionBrowserOpenAuthorizationPort(
            device=device(),
            permission_profile=kwargs.pop("permission_profile", None) or profile(),  # type: ignore[arg-type]
            store=store,
            evidence_port=DeterministicBrowserOpenAuthorityEvidencePort(items),  # type: ignore[arg-type]
        )

    def test_an_unadmitted_command_is_refused(self) -> None:
        with DurableRunStore(":memory:") as store:
            with self.assertRaises(BrowserOpenRefusal) as raised:
                self._port(store).authorize(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "command_not_admitted")

    def test_a_passed_hard_deadline_is_refused_before_any_write(self) -> None:
        late = admitted_record(
            command_issued_at=NOW - timedelta(seconds=600),
            command_expires_at=NOW - timedelta(seconds=300),
            admitted_at=NOW - timedelta(seconds=590),
        )
        with DurableRunStore(":memory:") as store:
            store.put(late)
            with self.assertRaises(BrowserOpenRefusal) as raised:
                self._port(store).authorize(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "command_expired")
            # Nothing was written: the row is untouched and still loadable.
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.ADMITTED)
            self.assertIsNone(record.started_at)

    def test_local_policy_deny_wins_over_an_approved_decision(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            port = self._port(store, permission_profile=profile(LocalPolicyMode.DENY))
            with self.assertRaises(BrowserOpenRefusal) as raised:
                port.authorize(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "policy_denied")
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.ADMITTED)

    def test_a_denied_p01_decision_is_refused(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            item = request()
            port = self._port(
                store,
                evidence_items=(
                    evidence(item, approval_decision=decision(item, outcome=ApprovalOutcome.DENIED)),
                ),
            )
            with self.assertRaises(BrowserOpenRefusal) as raised:
                port.authorize(request=item, now=NOW)
            self.assertEqual(raised.exception.code, "grant_rejected")

    def test_an_approval_scope_without_browser_open_is_refused(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            item = request()
            port = self._port(
                store,
                evidence_items=(evidence(item, approval_pause=pause(item, scope=("filesystem.read",))),),
            )
            with self.assertRaises(ContractError):
                port.authorize(request=item, now=NOW)

    def test_unconfigured_evidence_fails_closed(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            port = P01LocalPermissionBrowserOpenAuthorizationPort(
                device=device(),
                permission_profile=profile(),
                store=store,
            )
            self.assertIsInstance(
                port._evidence_port, UnconfiguredBrowserOpenAuthorityEvidencePort
            )
            with self.assertRaises(BrowserOpenRefusal) as raised:
                port.authorize(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "evidence_unavailable")

    def test_an_unconfigured_host_is_refused_without_a_view(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            composed = BrowserOpenAuthority(
                device=device(),
                permission_profile=profile(),
                store=store,
                evidence_port=DeterministicBrowserOpenAuthorityEvidencePort((evidence(request()),)),
            )
            with self.assertRaises(BrowserOpenRefusal) as raised:
                composed.open(request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "host_unavailable")

    def test_malicious_evidence_cannot_repoint_the_open(self) -> None:
        from kagent.local_agent_permissions import LocalPermissionRequest

        # Same action id, different URL: only the target digest differs, so this
        # isolates the binding check from the action check.
        other = request(target_url="https://example.org/elsewhere")
        self.assertNotEqual(browser_open_target_ref(other), browser_open_target_ref(request()))
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            port = self._port(
                store,
                evidence_items=(
                    evidence(
                        request(),
                        permission_request=LocalPermissionRequest(
                            action_id="browser_open_open_1",
                            run_id="run_3611",
                            device_id="device_3611",
                            capability=LocalCapability.BROWSER_OPEN,
                            target_ref=browser_open_target_ref(other),
                        ),
                    ),
                ),
            )
            with self.assertRaises(ContractError):
                port.authorize(request=request(), now=NOW)
            # Fail-closed: the mismatch is refused before any durable write.
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.ADMITTED)


# --- loopback evidence client (existing route) -------------------------------


class LoopbackEvidenceClientTests(unittest.TestCase):
    def _envelope(self) -> dict[str, object]:
        item = request()
        return {
            "envelope": {
                "evidence_ref": "evidence.p01.3611",
                "request_fingerprint": browser_open_fingerprint(item),
                "approval_pause": {
                    "pause_id": "pause_3611",
                    "run_id": "run_3611",
                    "agent_runtime_id": "runtime_3611",
                    "tool_id": BROWSER_OPEN_TOOL_ID,
                    "invocation_sha256": browser_open_fingerprint(item),
                    "requirement": "user_confirmation",
                    "step_index": 1,
                    "created_at": (NOW - timedelta(seconds=5)).isoformat(),
                    "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
                    "approval_scope": [BROWSER_OPEN_TOOL_ID],
                },
                "approval_decision": {
                    "decision_id": "decision_3611",
                    "pause_id": "pause_3611",
                    "outcome": "approved",
                    "authority_ref": "p01_authority.3611",
                    "evidence_ref": "evidence.p01.3611",
                    "decided_at": (NOW - timedelta(seconds=4)).isoformat(),
                },
                "permission_requests": [
                    {
                        "action_id": "browser_open_open_1",
                        "run_id": "run_3611",
                        "device_id": "device_3611",
                        "capability": "browser.open",
                        "target_ref": browser_open_target_ref(item),
                    }
                ],
                "local_policy_ref": "local:require_p01_approval",
                "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
            }
        }

    def test_the_existing_envelope_parses_into_browser_open_evidence(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            sent: list[bytes] = []

            def opener(body: bytes) -> dict[str, object]:
                sent.append(body)
                return self._envelope()

            client = P01LoopbackBrowserOpenEvidenceClient(
                store=store,
                command_id=COMMAND_ID,
                binding_ref="pairing-binding." + "a" * 32,
                request_id="request.3611",
                opener=opener,
            )
            resolved = client.resolve(browser_open_fingerprint(request()))
            self.assertEqual(resolved.request_fingerprint, browser_open_fingerprint(request()))
            self.assertEqual(resolved.command_id, COMMAND_ID)
            self.assertEqual(resolved.admission_ref, "admission.3611")
            self.assertEqual(resolved.revision_ref, "revision.7f3c1a9e")
            self.assertEqual(resolved.approval_pause.tool_id, BROWSER_OPEN_TOOL_ID)
            # The 4 canonical correlation facts are sent unchanged.
            body = json.loads(sent[0].decode("utf-8"))
            self.assertEqual(body["command_id"], COMMAND_ID)
            self.assertEqual(body["request_id"], "request.3611")

    def test_the_client_refuses_without_an_admitted_command(self) -> None:
        with DurableRunStore(":memory:") as store:
            client = P01LoopbackBrowserOpenEvidenceClient(
                store=store,
                command_id=COMMAND_ID,
                binding_ref="pairing-binding." + "a" * 32,
                request_id="request.3611",
                opener=lambda body: self._envelope(),
            )
            with self.assertRaises(BrowserOpenRefusal) as raised:
                client.resolve(browser_open_fingerprint(request()))
            self.assertEqual(raised.exception.code, "command_not_admitted")

    def test_the_client_uses_the_existing_route_and_adds_no_route(self) -> None:
        self.assertEqual(P01_EVIDENCE_ROUTE_REUSED, "/v1/broker/p01-evidence")
        self.assertFalse(NEW_BROKER_ROUTE)


# --- runtime assembly callsite ----------------------------------------------


def binding(*, state: DeviceLifecycle = DeviceLifecycle.ONLINE) -> DeviceBinding:
    return DeviceBinding(
        device_id="device_3611",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.3611",
        workspace_ref="workspace_3611",
        credential_ref="device-credential:generation-1",
        credential_generation=1,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=state,
    )


def session() -> DeviceSession:
    return DeviceSession(
        session_id="session.3611",
        device_id="device_3611",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.3611",
        workspace_ref="workspace_3611",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def pinned(current: DeviceBinding) -> PinnedOutboundBrokerBinding:
    return PinnedOutboundBrokerBinding.from_binding(
        binding=current,
        config=OutboundTransportConfig(
            endpoint=OutboundBrokerEndpoint(
                endpoint_ref="broker_primary",
                url="https://broker.padiem.example/v1/local-agent",
                mode=OutboundTransportMode.HTTPS_LONG_POLL,
            )
        ),
    )


class EmptyReceiptRuntime:
    def execute_with_receipt(self, item, *, now):  # type: ignore[no-untyped-def]
        return WindowsExecutionReceipt(
            result=None,
            termination=WindowsExecutionTermination.EXITED,
            executable_profile_ref="python_profile",
            authorization_ref="windows_grant_1",
        )

    def cancel(self, request_id: str) -> None:
        return None


class AssemblyCallsiteTests(unittest.TestCase):
    def _assembly(self, store: DurableRunStore, *, composed: bool = True, current=None):
        current = current or binding()
        return BoundLocalAgentRuntimeAssembly(
            device=device(),
            binding=current,
            permissions=default_device_permission_profile(device=device()),
            broker_authority=pinned(current),
            runtime=EmptyReceiptRuntime(),
            browser_open=authority(store) if composed else None,
        )

    def test_the_composed_slice_runs_through_the_assembly(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            assembly = self._assembly(store)
            outcome = assembly.open_browser(session=session(), request=request(), now=NOW)
            self.assertEqual(outcome.load_outcome, BrowserOpenOutcome.LOADED)
            self.assertTrue(outcome.settled)

    def test_an_offline_binding_never_reaches_the_slice(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            assembly = self._assembly(store, current=binding(state=DeviceLifecycle.PAIRED_OFFLINE))
            with self.assertRaises(ContractError):
                assembly.open_browser(session=session(), request=request(), now=NOW)
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.ADMITTED)

    def test_an_uncomposed_assembly_refuses_instead_of_borrowing_authority(self) -> None:
        with DurableRunStore(":memory:") as store:
            assembly = self._assembly(store, composed=False)
            self.assertFalse(assembly.browser_open_configured)
            with self.assertRaises(BrowserOpenRefusal) as raised:
                assembly.open_browser(session=session(), request=request(), now=NOW)
            self.assertEqual(raised.exception.code, "host_unavailable")

    def test_a_future_dated_request_is_refused(self) -> None:
        with DurableRunStore(":memory:") as store:
            store.put(admitted_record())
            assembly = self._assembly(store)
            with self.assertRaises(ContractError):
                assembly.open_browser(
                    session=session(),
                    request=request(requested_at=NOW + timedelta(seconds=60)),
                    now=NOW,
                )

    def test_the_assembly_projection_states_the_composition_truthfully(self) -> None:
        with DurableRunStore(":memory:") as store:
            rendered = self._assembly(store).safe_dict(now=NOW)
            self.assertTrue(rendered["browser_open_composed"])
            self.assertFalse(rendered["browser_control_composed"])
            self.assertFalse(rendered["second_browser_authority"])
            self.assertTrue(rendered["p01_authorization_reused"])


class BoundaryFlagTests(unittest.TestCase):
    def test_the_composition_creates_no_second_authority(self) -> None:
        self.assertTrue(BROWSER_OPEN_AUTHORITY_COMPOSED)
        self.assertTrue(BROWSER_OPEN_USES_EXISTING_P01)
        self.assertFalse(SECOND_APPROVAL_AUTHORITY)
        self.assertFalse(SECOND_BROWSER_AUTHORITY)
        self.assertFalse(BROWSER_CONTROL_IMPLEMENTED)
        self.assertFalse(NEW_APPROVAL_STORE)
        self.assertFalse(NEW_BROKER_ROUTE)
        self.assertTrue(RESTART_SAFE_ONE_SHOT)
        self.assertEqual(DURABLE_ONE_SHOT_ANCHOR, "durable_run_store_admitted_to_executing")
        self.assertTrue(LOCAL_POLICY_RECOMPUTED_AT_COMPOSITION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
