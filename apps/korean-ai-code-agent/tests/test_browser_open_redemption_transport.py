"""#3611 — Desktop redemption transport over the existing supervised resident pipe.

Two claims are under test here:

1. the existing single stdin reader became a **closed two-kind dispatcher** — no
   second reader thread, no generic command dispatch, unknown kinds fail closed,
   and the redemption request carries only bounded correlation; and
2. the durable ``ADMITTED -> EXECUTING`` transition has **exactly one owner**, so
   two real processes racing for the same open produce exactly one success.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

from kagent.browser_open import (
    BROWSER_OPEN_TOOL_ID,
    BrowserOpenRefusal,
    BrowserOpenRequest,
    browser_open_fingerprint,
    browser_open_target_ref,
)
from kagent.browser_open_authority import (
    ADMITTED_TO_EXECUTING_OWNER,
    AUTHORIZE_PERFORMS_DURABLE_WRITE,
    DURABLE_TRANSITION_COUNT_MAX,
    BrowserOpenAuthorityEvidence,
    DeterministicBrowserOpenAuthorityEvidencePort,
    P01LocalPermissionBrowserOpenAuthorizationPort,
)
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_durable_run import DurableRunRecord, DurableRunState
from kagent.local_agent_durable_run_store import DurableRunStore
from kagent.local_agent_desktop_material import (
    DESKTOP_REQUEST_KIND_COUNT,
    DESKTOP_REQUEST_KINDS,
    GENERIC_COMMAND_DISPATCH,
    MATERIAL_REQUEST_KIND,
    REDEMPTION_REQUEST_CONTRACT_VERSION,
    REDEMPTION_REQUEST_KIND,
    SECOND_STDIN_READER_THREAD,
    UNKNOWN_REQUEST_KIND_FAILS_CLOSED,
    ResidentDesktopMaterialResponder,
    parse_desktop_request,
)
from kagent.local_agent_permissions import (
    LocalPermissionRequest,
    LocalPolicyMode,
    default_device_permission_profile,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
SAFE_URL = "https://example.com/report?id=7#section"
COMMAND_ID = "command.3611.open.1"
TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent
REPO_ROOT = APP_DIR.parents[1]
RACE_CHILD = TESTS_DIR / "_browser_open_race_child.py"


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3611",
        workspace_ref="workspace_3611",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root_work", windows_path=r"E:\work"),),
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
        "fingerprint_source": "broker",
        "command_issued_at": NOW - timedelta(seconds=30),
        "command_expires_at": NOW + timedelta(seconds=300),
        "admitted_at": NOW - timedelta(seconds=20),
        "admission_ref": "admission.3611",
    }
    values.update(overrides)
    return DurableRunRecord(**values)  # type: ignore[arg-type]


def evidence(item: BrowserOpenRequest) -> BrowserOpenAuthorityEvidence:
    pause = ApprovalPause(
        pause_id="pause_3611",
        run_id=item.run_id,
        agent_runtime_id="runtime_3611",
        tool_id=BROWSER_OPEN_TOOL_ID,
        invocation_sha256=browser_open_fingerprint(item),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=600),
        approval_scope=(BROWSER_OPEN_TOOL_ID,),
    )
    return BrowserOpenAuthorityEvidence(
        evidence_ref="evidence.p01.3611",
        request_fingerprint=browser_open_fingerprint(item),
        command_id=COMMAND_ID,
        permission_request=LocalPermissionRequest(
            action_id=f"browser_open_{item.open_id}",
            run_id=item.run_id,
            device_id=item.device_id,
            capability=item.capability,
            target_ref=browser_open_target_ref(item),
        ),
        approval_pause=pause,
        approval_decision=VerifiedApprovalDecision(
            decision_id="decision_3611",
            pause_id="pause_3611",
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority.3611",
            evidence_ref="evidence.p01.3611",
            decided_at=NOW - timedelta(seconds=4),
        ),
        local_policy_ref="local:require_p01_approval",
        admission_ref="admission.3611",
        revision_ref="revision.7f3c1a9e",
        expires_at=NOW + timedelta(seconds=600),
    )


def redemption_request_line(**overrides: object) -> str:
    grant_fingerprint = browser_open_fingerprint(request())
    fields: dict[str, object] = {
        "contract_version": REDEMPTION_REQUEST_CONTRACT_VERSION,
        "request": REDEMPTION_REQUEST_KIND,
        "redemptionRef": COMMAND_ID,
        "requestFingerprint": grant_fingerprint,
        "openId": "open_1",
        "runRef": "run_3611",
    }
    fields.update(overrides)
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


# --- the closed dispatcher ---------------------------------------------------


class ClosedDispatcherTests(unittest.TestCase):
    def _responder(self, *, redemption=None, projection=None) -> ResidentDesktopMaterialResponder:
        return ResidentDesktopMaterialResponder(
            material_projection=projection or (lambda: {"ok": True}),
            redemption=redemption,
            reader=None,
            emit=lambda line: None,
        )

    def test_exactly_five_request_kinds_are_accepted(self) -> None:
        # #3782 adds one private, Broker-authenticated browser command take
        # to the original four kinds; nothing is a wildcard or generic RPC.
        self.assertEqual(len(DESKTOP_REQUEST_KINDS), 5)
        self.assertEqual(DESKTOP_REQUEST_KIND_COUNT, 5)
        self.assertEqual(
            DESKTOP_REQUEST_KINDS,
            frozenset(
                {
                    MATERIAL_REQUEST_KIND,
                    REDEMPTION_REQUEST_KIND,
                    "browser_control_lease_resolve",
                    "browser_control_lease_consume",
                    "browser_control_command_take",
                }
            ),
        )
        self.assertFalse(GENERIC_COMMAND_DISPATCH)
        self.assertEqual(SECOND_STDIN_READER_THREAD, 0)
        self.assertTrue(UNKNOWN_REQUEST_KIND_FAILS_CLOSED)

    def test_an_unknown_kind_is_refused_without_dispatch(self) -> None:
        called: list[str] = []
        responder = self._responder(redemption=lambda **kw: called.append("redeem"))
        line = responder.respond(
            json.dumps({"contract_version": "x", "request": "execute_anything"})
        )
        parsed = json.loads(line)
        self.assertIs(parsed["ok"], False)
        self.assertEqual(called, [])

    def test_a_known_kind_but_extra_field_is_refused(self) -> None:
        called: list[str] = []
        responder = self._responder(redemption=lambda **kw: called.append("redeem"))
        raw = redemption_request_line()
        payload = json.loads(raw)
        payload["rawUrl"] = SAFE_URL
        line = responder.respond(json.dumps(payload, sort_keys=True))
        parsed = json.loads(line)
        self.assertIs(parsed["ok"], False)
        self.assertEqual(called, [])

    def test_the_redemption_request_carries_only_bounded_correlation(self) -> None:
        parsed = parse_desktop_request(redemption_request_line())
        self.assertEqual(parsed["kind"], REDEMPTION_REQUEST_KIND)
        self.assertEqual(
            sorted(parsed["payload"]),
            sorted(["redemptionRef", "requestFingerprint", "openId", "runRef"]),
        )
        # None of the things the transport must never carry are representable.
        for forbidden in ("url", "targetUrl", "normalizedUrl", "pause", "decision", "credential", "cookies"):
            self.assertNotIn(forbidden, parsed["payload"])

    def test_a_missing_correlation_field_is_refused(self) -> None:
        payload = json.loads(redemption_request_line())
        del payload["openId"]
        with self.assertRaises(Exception):
            parse_desktop_request(json.dumps(payload))
        responder = self._responder(redemption=lambda **kw: None)
        self.assertIs(json.loads(responder.respond(json.dumps(payload)))["ok"], False)

    def test_an_unconfigured_redemption_fails_closed(self) -> None:
        responder = self._responder(redemption=None)
        parsed = json.loads(responder.respond(redemption_request_line()))
        self.assertIs(parsed["ok"], False)
        self.assertEqual(parsed["reason"], "redemption_unavailable")

    def test_the_material_kind_still_works_unchanged(self) -> None:
        responder = self._responder(projection=lambda: {"ok": True, "session_id": "s"})
        line = responder.respond(
            json.dumps(
                {
                    "contract_version": "claw-desktop-session-material-request.v1",
                    "request": MATERIAL_REQUEST_KIND,
                }
            )
        )
        parsed = json.loads(line)
        self.assertIs(parsed["ok"], True)
        self.assertEqual(parsed["event"], MATERIAL_REQUEST_KIND)


class RedemptionDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "durable-runs.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _authority(self, store: DurableRunStore):
        from kagent.browser_open_authority import BrowserOpenAuthority

        return BrowserOpenAuthority(
            device=device(),
            permission_profile=default_device_permission_profile(device=device()),
            store=store,
            evidence_port=DeterministicBrowserOpenAuthorityEvidencePort((evidence(request()),)),
            clock=lambda: NOW,
        )

    def test_the_dispatcher_redeems_through_the_composition(self) -> None:
        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
            composed = self._authority(store)
            responder = ResidentDesktopMaterialResponder(
                material_projection=lambda: {"ok": True},
                redemption=composed.redeem_transport,
                emit=lambda line: None,
            )
            # Authorize through the composition, then redeem over the wire shape.
            grant = composed.authorize(request=request(), now=NOW)
            line = responder.respond(
                redemption_request_line(
                    requestFingerprint=grant.request_fingerprint,
                    openId=grant.open_id,
                    runRef=grant.run_id,
                )
            )
            parsed = json.loads(line)
            self.assertIs(parsed["ok"], True, parsed)
            self.assertEqual(parsed["redemption_ref"], COMMAND_ID)
            self.assertEqual(parsed["request_fingerprint"], grant.request_fingerprint)
            self.assertEqual(parsed["event"], REDEMPTION_REQUEST_KIND)
            # No content of any kind on the answer.
            self.assertEqual(
                sorted(parsed),
                sorted(
                    [
                        "contract_version",
                        "event",
                        "ok",
                        "redemption_ref",
                        "request_fingerprint",
                    ]
                ),
            )
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            self.assertIs(record.state, DurableRunState.EXECUTING)

    def test_a_second_redemption_through_the_dispatcher_is_refused(self) -> None:
        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
            composed = self._authority(store)
            grant = composed.authorize(request=request(), now=NOW)
            responder = ResidentDesktopMaterialResponder(
                material_projection=lambda: {"ok": True},
                redemption=composed.redeem_transport,
                emit=lambda line: None,
            )
            payload = dict(
                requestFingerprint=grant.request_fingerprint,
                openId=grant.open_id,
                runRef=grant.run_id,
            )
            first = json.loads(responder.respond(redemption_request_line(**payload)))
            self.assertIs(first["ok"], True)
            second = json.loads(responder.respond(redemption_request_line(**payload)))
            self.assertIs(second["ok"], False)
            self.assertEqual(second["reason"], "command_already_started")


# --- the real multi-process race --------------------------------------------


class MultiProcessRedemptionRaceTests(unittest.TestCase):
    """Two real processes, one real SQLite file, one durable transition."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "durable-runs.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _race(self) -> tuple[list[str], DurableRunState]:
        with DurableRunStore(self.path) as store:
            store.put(admitted_record())
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(APP_DIR / "src"),
                str(REPO_ROOT / "packages" / "padiem-ai-core"),
                str(REPO_ROOT / "packages" / "padiem-control-plane"),
                str(REPO_ROOT / "packages" / "padiem-embedded-runtime"),
                env.get("PYTHONPATH", ""),
            ]
        )
        procs = [
            subprocess.Popen(  # noqa: S603 - fixed interpreter, local script
                [
                    sys.executable,
                    str(RACE_CHILD),
                    self.path,
                    COMMAND_ID,
                    "run_3611",
                    NOW.isoformat(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(APP_DIR),
                env=env,
                text=True,
            )
            for _ in range(2)
        ]
        outcomes: list[str] = []
        for proc in procs:
            out, err = proc.communicate(timeout=180)
            self.assertEqual(proc.returncode, 0, f"racer failed: {err}")
            payload = json.loads(out.strip().splitlines()[-1])
            outcomes.append(payload["outcome"])
        with DurableRunStore(self.path) as store:
            record = store.get(command_id=COMMAND_ID)
            assert record is not None
            return outcomes, record.state

    def test_exactly_one_of_two_concurrent_processes_wins(self) -> None:
        outcomes, state = self._race()
        self.assertEqual(sorted(outcomes), ["command_already_started", "ok"])
        self.assertEqual(outcomes.count("ok"), 1)
        # Exactly one durable transition happened, and the row is loadable.
        self.assertIs(state, DurableRunState.EXECUTING)

    def test_the_loser_result_is_the_canonical_refusal_code(self) -> None:
        outcomes, _ = self._race()
        losers = [item for item in outcomes if item != "ok"]
        self.assertEqual(losers, ["command_already_started"])
        # The losing process raised before any host was reachable, so no view
        # could have been created by it; this suite composes no host at all.
        self.assertEqual(outcomes.count("ok"), 1)

    def test_the_transition_owner_is_single_and_authorize_writes_nothing(self) -> None:
        self.assertEqual(ADMITTED_TO_EXECUTING_OWNER, "CANONICAL_BROWSER_OPEN_REDEMPTION")
        self.assertEqual(DURABLE_TRANSITION_COUNT_MAX, 1)
        self.assertFalse(AUTHORIZE_PERFORMS_DURABLE_WRITE)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
