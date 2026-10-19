"""#3580 Drive WRITE approval port tests.

Hermetic: the canonical P01 approval objects are constructed in-process, the
evidence source is a local static double and the Drive upload transport is the
existing hermetic double. No live approval authority, Google connection or
credential is exercised.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta

import test_google_drive_artifact_upload as drive

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, VerifiedApprovalDecision,
)
from padiem_ai_core.tool_runtime import ToolInvocation

from kagent.artifact_registration import ArtifactLifecycle
from kagent.connector_trust import ConnectorWriteIntent
from kagent.google_drive_artifact_upload import DRIVE_UPLOAD_CAPABILITY
from kagent.google_drive_write_approval import (
    AuthorizedDriveWriteApprovalPort, CLIENT_CLAIM_IS_NOT_APPROVAL,
    DRIVE_WRITE_APPROVAL_ARGUMENT_FIELDS, DRIVE_WRITE_TOOL_ID,
    DriveWriteApprovalError, DriveWriteApprovalEvidence,
    InMemoryDriveWriteApprovalConsumption, NEW_APPROVAL_AUTHORITY,
    NEW_APPROVAL_SCHEMA, NEW_DURABLE_STORE, PRODUCTION_APPROVAL_PORT_COMPOSED,
    READ_APPROVAL_IS_NOT_WRITE_APPROVAL, UnconfiguredDriveWriteApprovalEvidencePort,
    drive_write_approval_arguments, drive_write_approval_fingerprint,
    drive_write_tool_invocation,
)

NOW = drive.NOW
RUN = drive.RUN
PAUSE_ID = "pause_drive_write_1"
DECISION_ID = "decision_drive_write_1"
AUTHORITY_REF = "authority_p01_1"
EVIDENCE_REF = "evidence_drive_write_1"


def fingerprint(*, intent=None, artifact_ref=None, workspace_ref=drive.WORKSPACE,
                run_ref=RUN):
    return drive_write_approval_fingerprint(
        intent=intent if intent is not None else drive.intent(),
        artifact_ref=artifact_ref if artifact_ref is not None else drive.artifact_ref(),
        workspace_ref=workspace_ref, run_ref=run_ref,
    )


def pause(*, invocation_sha256=None, run_id=RUN, tool_id=DRIVE_WRITE_TOOL_ID,
          scope=(DRIVE_UPLOAD_CAPABILITY,), created_at=None, expires_at=None,
          pause_id=PAUSE_ID):
    return ApprovalPause(
        pause_id=pause_id,
        run_id=run_id,
        agent_runtime_id="agent:claw-drive-write@1",
        tool_id=tool_id,
        invocation_sha256=invocation_sha256 or fingerprint(),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=created_at or (NOW - timedelta(minutes=5)),
        expires_at=expires_at or (NOW + timedelta(minutes=15)),
        approval_scope=tuple(scope),
    )


def decision(*, approval_pause=None, outcome=ApprovalOutcome.APPROVED,
             decided_at=None, pause_id=None, evidence_ref=EVIDENCE_REF,
             decision_id=DECISION_ID):
    return VerifiedApprovalDecision(
        decision_id=decision_id,
        pause_id=pause_id or (approval_pause.pause_id if approval_pause else PAUSE_ID),
        outcome=outcome,
        authority_ref=AUTHORITY_REF,
        evidence_ref=evidence_ref,
        decided_at=decided_at or (NOW - timedelta(minutes=4)),
    )


def evidence(*, approval_pause=None, approval_decision=None, expires_at=None,
             request_fingerprint=None, evidence_ref=EVIDENCE_REF):
    the_pause = approval_pause if approval_pause is not None else pause()
    return DriveWriteApprovalEvidence(
        evidence_ref=evidence_ref,
        request_fingerprint=request_fingerprint or fingerprint(),
        approval_pause=the_pause,
        approval_decision=(
            approval_decision if approval_decision is not None
            else decision(approval_pause=the_pause, evidence_ref=evidence_ref)
        ),
        expires_at=expires_at or (NOW + timedelta(minutes=10)),
    )


class StaticEvidence:
    """Hermetic stand-in for the existing canonical P01 evidence boundary."""

    def __init__(self, item=None, error=None):
        self.item = item
        self.error = error
        self.calls = []

    def resolve_drive_write_approval(self, *, request_fingerprint):
        self.calls.append(request_fingerprint)
        if self.error is not None:
            raise self.error
        if self.item is None:
            return None
        if isinstance(self.item, dict):
            return self.item.get(request_fingerprint)
        return self.item


def port(*, item=None, error=None, consumption=None, clock=None):
    source = StaticEvidence(item=item, error=error)
    return (
        AuthorizedDriveWriteApprovalPort(
            evidence_port=source, consumption=consumption,
            clock=clock or (lambda: NOW),
        ),
        source,
    )


def approve(p, *, intent=None, artifact_ref=None, workspace_ref=drive.WORKSPACE,
            run_ref=RUN):
    return p.verify_write_approval(
        intent=intent if intent is not None else drive.intent(),
        artifact_ref=artifact_ref if artifact_ref is not None else drive.artifact_ref(),
        workspace_ref=workspace_ref, run_ref=run_ref,
    )


class DriveWriteApprovalPortTests(unittest.TestCase):
    def test_port_is_a_validator_not_a_new_authority(self):
        self.assertIs(READ_APPROVAL_IS_NOT_WRITE_APPROVAL, True)
        self.assertIs(CLIENT_CLAIM_IS_NOT_APPROVAL, True)
        self.assertIs(NEW_APPROVAL_AUTHORITY, False)
        self.assertIs(NEW_APPROVAL_SCHEMA, False)
        self.assertIs(NEW_DURABLE_STORE, False)
        self.assertIs(PRODUCTION_APPROVAL_PORT_COMPOSED, False)

    def test_construction_requires_a_usable_evidence_port(self):
        with self.assertRaises(DriveWriteApprovalError):
            AuthorizedDriveWriteApprovalPort(evidence_port=object())
        with self.assertRaises(DriveWriteApprovalError):
            AuthorizedDriveWriteApprovalPort(consumption=object())

    def test_unconfigured_evidence_port_fails_closed(self):
        p = AuthorizedDriveWriteApprovalPort(clock=lambda: NOW)
        self.assertIsInstance(
            p._evidence_port, UnconfiguredDriveWriteApprovalEvidencePort
        )
        self.assertFalse(approve(p))

    def test_approved_exact_decision_authorizes_exactly_once(self):
        p, source = port(item=evidence())
        self.assertTrue(approve(p))
        self.assertEqual(source.calls, [fingerprint()])
        # One-shot: the same decision can never authorize a second upload.
        self.assertFalse(approve(p))

    def test_denied_decision_is_refused(self):
        the_pause = pause()
        p, _ = port(item=evidence(
            approval_pause=the_pause,
            approval_decision=decision(
                approval_pause=the_pause, outcome=ApprovalOutcome.DENIED
            ),
        ))
        self.assertFalse(approve(p))

    def test_read_approval_is_not_a_write_approval(self):
        # A READ pause is not a Drive write pause at all.
        with self.assertRaises(DriveWriteApprovalError):
            evidence(approval_pause=pause(tool_id="get_file_metadata"))
        # Even a same-tool pause must carry the WRITE capability in its scope.
        read_scope_pause = pause(scope=("drive.files.get",))
        p, _ = port(item=evidence(approval_pause=read_scope_pause))
        self.assertFalse(approve(p))

    def test_expired_pause_or_evidence_is_refused(self):
        expired_pause = pause(
            created_at=NOW - timedelta(minutes=40),
            expires_at=NOW - timedelta(minutes=1),
        )
        p, _ = port(item=evidence(
            approval_pause=expired_pause,
            approval_decision=decision(
                approval_pause=expired_pause, decided_at=NOW - timedelta(minutes=35)
            ),
            expires_at=NOW - timedelta(minutes=30),
        ))
        self.assertFalse(approve(p))
        # Evidence expiry alone is enough.
        p2, _ = port(item=evidence(expires_at=NOW - timedelta(seconds=1)))
        self.assertFalse(approve(p2))

    def test_foreign_run_or_wrong_fingerprint_is_refused(self):
        p, _ = port(item=evidence(approval_pause=pause(run_id="run_other")))
        self.assertFalse(approve(p))
        p2, _ = port(item=evidence(request_fingerprint="f" * 64))
        self.assertFalse(approve(p2))
        p3, _ = port(item=evidence(approval_pause=pause(invocation_sha256="a" * 64)))
        self.assertFalse(approve(p3))

    def test_decision_for_another_pause_is_refused(self):
        with self.assertRaises(DriveWriteApprovalError):
            evidence(approval_decision=decision(pause_id="pause_other"))
        with self.assertRaises(DriveWriteApprovalError):
            evidence(evidence_ref="evidence_a", approval_decision=decision(
                evidence_ref="evidence_b"
            ))

    def test_foreign_connector_or_overwrite_intent_is_refused(self):
        telegram = ConnectorWriteIntent(
            connector_id="telegram", binding_ref=drive.BINDING, actor_ref=drive.ACTOR,
            tool_name=DRIVE_WRITE_TOOL_ID, target_ref=drive.FOLDER,
            payload_fingerprint=drive.intent().payload_fingerprint,
            idempotency_key="idem_upload_1", approval_ref="approval_1",
            evidence_ref="evidence_1", requested_at=NOW,
        )
        p, source = port(item=evidence())
        self.assertFalse(approve(p, intent=telegram))
        self.assertEqual(source.calls, [])
        versioned = drive.intent(expected_version_ref="drive-version:1")
        self.assertFalse(approve(p, intent=versioned))
        self.assertEqual(source.calls, [])

    def test_evidence_source_error_fails_closed_without_leaking(self):
        p, _ = port(error=RuntimeError("provider approval body leaked"))
        self.assertFalse(approve(p))

    def test_real_port_drives_existing_adapter_to_durable_artifact(self):
        p, source = port(item=evidence())
        adapter, _, folders, _, upload = drive.driver(approval=p)
        result = drive.deliver(adapter)
        self.assertEqual(result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(result.receipt.connector_id, "google-drive")
        self.assertEqual(len(upload.calls), 1)
        self.assertEqual(len(source.calls), 1)
        # The approval was consumed by the real upload, so a second attempt
        # cannot reuse it.
        self.assertFalse(approve(p))

    def test_adapter_refuses_when_approval_port_returns_false(self):
        p, _ = port(item=None)
        adapter, _, _, _, upload = drive.driver(approval=p)
        with self.assertRaises(Exception):
            drive.deliver(adapter)
        self.assertEqual(upload.calls, [])

    def test_invocation_arguments_are_pinned_and_secret_free(self):
        args = drive_write_approval_arguments(
            intent=drive.intent(), artifact_ref=drive.artifact_ref(),
            workspace_ref=drive.WORKSPACE, run_ref=RUN,
        )
        self.assertEqual(tuple(args), DRIVE_WRITE_APPROVAL_ARGUMENT_FIELDS)
        self.assertEqual(args["capability"], DRIVE_UPLOAD_CAPABILITY)
        self.assertIs(args["overwrite_original"], False)
        self.assertIs(args["local_pc_access"], False)
        invocation = drive_write_tool_invocation(
            intent=drive.intent(), artifact_ref=drive.artifact_ref(),
            workspace_ref=drive.WORKSPACE, run_ref=RUN,
        )
        self.assertIsInstance(invocation, ToolInvocation)
        self.assertEqual(invocation.tool_id, DRIVE_WRITE_TOOL_ID)
        rendered = json.dumps(args, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("token", rendered.lower())
        self.assertNotIn("secret", rendered.lower())

    def test_projection_leaks_no_approval_material(self):
        item = evidence()
        rendered = json.dumps(item.safe_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(AUTHORITY_REF, rendered)
        self.assertNotIn(DRIVE_WRITE_TOOL_ID, rendered)
        self.assertIs(item.safe_dict()["raw_approval_material"], False)
        self.assertIs(item.safe_dict()["client_approval_authority"], False)

    def test_consumption_registry_is_one_shot_per_decision(self):
        registry = InMemoryDriveWriteApprovalConsumption()
        self.assertTrue(registry.consume(DECISION_ID))
        self.assertFalse(registry.consume(DECISION_ID))
        self.assertEqual(registry.consumed_decision_ids(), frozenset({DECISION_ID}))
        self.assertFalse(registry.consume(""))
        self.assertFalse(registry.consume(None))


if __name__ == "__main__":
    unittest.main()
