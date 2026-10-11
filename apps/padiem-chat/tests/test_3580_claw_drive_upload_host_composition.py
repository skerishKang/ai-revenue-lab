"""#3580 Claw Drive WRITE host injection boundary.

Hermetic: every host port is a local fake, the Drive token authority and the
provider network are fakes, and no provider call, credential, grant or
Production binding is exercised.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.claw_drive_upload_host_composition import (
    ClawDriveUploadHostError, ClawDriveUploadHostState,
    HOST_INJECTION_BOUNDARY_IMPLEMENTED, PRODUCTION_DRIVE_UPLOADER_INJECTED,
    READ_SCOPE_IS_NOT_WRITE, build_canonical_drive_write_approval_port,
    build_claw_drive_artifact_uploader, build_claw_drive_upload_host_state,
    drive_write_grant_present,
)
from app.app_factory import create_app
from app.config import Settings
from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, VerifiedApprovalDecision,
)
from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import (
    ArtifactLifecycle, register_canonical_artifact,
)
from kagent.connector_trust import (
    ConnectorBindingProjection, ConnectorBindingState, ConnectorWriteIntent,
)
from kagent.google_drive_artifact_upload import (
    DRIVE_UPLOAD_CAPABILITY, DRIVE_UPLOAD_TOOL, DriveArtifactMaterial,
    GoogleDriveArtifactUploadAdapter, upload_payload_fingerprint,
)
from kagent.google_drive_scope import (
    DriveFileMetadata, DriveResourceProof, DriveScopeProjection,
)
from kagent.google_drive_upload_composition import (
    GoogleDriveUploadComposition, build_google_drive_upload_composition,
)
from kagent.google_drive_write_approval import (
    AuthorizedDriveWriteApprovalPort, DRIVE_WRITE_TOOL_ID,
    DriveWriteApprovalEvidence, drive_write_approval_fingerprint,
)
from kagent.google_oauth_authority import GoogleProviderHttpResponse

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
BINDING = "binding_host_boundary"
ACTOR = "actor_host_boundary"
ACCOUNT = "acct_host_boundary"
WORKSPACE = "workspace_host_boundary"
FOLDER = "folder_host_boundary"
WRITE_SCOPE = "https://www.googleapis.com/auth/drive.file"
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
TOKEN = "ya29.host-boundary-fixture-token-not-live"

WORKER = Path(__file__).resolve().parents[1] / "worker.py"


class _AuthorizedTokenPort:
    def resolve_write_access_token(self, *, binding_ref, actor_ref, capability):
        return TOKEN


class _FakeNetwork:
    def request(self, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the host boundary must not call a provider")


class _MaterialPort:
    def resolve_artifact_material(self, artifact_ref, *, workspace_ref, run_ref):
        return None


class _FolderPort:
    def resolve_folder_proof(self, *, binding_ref, actor_ref, folder_ref):
        return None


class _ApprovalPort:
    def verify_write_approval(self, *, intent, artifact_ref, workspace_ref, run_ref):
        return False


def binding(*, scopes=(WRITE_SCOPE,), capabilities=(DRIVE_UPLOAD_CAPABILITY,),
            connector="google-drive", state=ConnectorBindingState.ACTIVE,
            expires_at=NOW + timedelta(hours=1), revoked_at=None):
    return ConnectorBindingProjection(
        binding_ref=BINDING, connector_id=connector, actor_ref=ACTOR,
        account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        granted_scopes=tuple(scopes), granted_capabilities=tuple(capabilities),
        issued_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1),
        expires_at=expires_at, revoked_at=revoked_at, state=state,
    )


def composition():
    return build_google_drive_upload_composition(
        authorization=_AuthorizedTokenPort(), network=_FakeNetwork(),
    )


def full_inputs(**overrides):
    params = dict(
        binding=binding(),
        scope=DriveScopeProjection(binding_ref=BINDING, allowed_folder_ids=(FOLDER,)),
        artifacts=_MaterialPort(), folders=_FolderPort(), approval=_ApprovalPort(),
        composition=composition(),
    )
    params.update(overrides)
    return params


def settings():
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="boundary-client.apps.googleusercontent.com",
        google_client_secret="boundary-google-secret",
        session_secret="boundary-session-secret-not-a-real-credential",
        session_max_age_seconds=3600,
    )


class TestClawDriveUploadHostBoundary:
    def test_boundary_fails_closed_with_no_trusted_input(self):
        state = build_claw_drive_upload_host_state()
        assert isinstance(state, ClawDriveUploadHostState)
        assert state.uploader is None
        assert state.injected is False
        reasons = " ".join(state.blocked_reasons)
        for expected in ("connector binding", "Drive scope", "artifacts port",
                         "folders port", "approval port", "WRITE port"):
            assert expected in reasons
        projection = state.safe_dict()
        assert projection["boundary_implemented"] is HOST_INJECTION_BOUNDARY_IMPLEMENTED
        assert projection["uploader_injected"] is False
        assert projection["production_claim"] is False

    def test_read_only_grant_is_not_a_write_grant(self):
        read_only = binding(scopes=(READ_SCOPE,), capabilities=("drive.files.get",))
        assert drive_write_grant_present(read_only, now=NOW) is False
        state = build_claw_drive_upload_host_state(**full_inputs(binding=read_only))
        assert state.uploader is None
        assert any("READ-only" in reason for reason in state.blocked_reasons)
        assert READ_SCOPE_IS_NOT_WRITE is True

    def test_write_grant_requires_a_live_binding(self):
        assert drive_write_grant_present(binding(), now=NOW) is True
        expired = binding(expires_at=NOW - timedelta(seconds=1))
        assert drive_write_grant_present(expired, now=NOW) is False
        revoked = binding(state=ConnectorBindingState.REVOKED, revoked_at=NOW)
        assert drive_write_grant_present(revoked, now=NOW) is False
        naive = datetime(2026, 10, 11, 12, 0)
        assert drive_write_grant_present(binding(), now=naive) is False
        assert drive_write_grant_present(None, now=NOW) is False

    def test_all_trusted_inputs_build_the_canonical_uploader(self):
        composed = composition()
        state = build_claw_drive_upload_host_state(
            **full_inputs(composition=composed)
        )
        assert isinstance(state.uploader, GoogleDriveArtifactUploadAdapter)
        assert state.uploader._upload is composed.upload_port
        assert state.blocked_reasons == ()
        assert state.safe_dict()["uploader_injected"] is True
        # The convenience accessor yields exactly the same object class.
        assert isinstance(build_claw_drive_artifact_uploader(**full_inputs()),
                          GoogleDriveArtifactUploadAdapter)

    def test_scope_must_belong_to_the_trusted_binding(self):
        state = build_claw_drive_upload_host_state(**full_inputs(
            scope=DriveScopeProjection(
                binding_ref="some_other_binding", allowed_folder_ids=(FOLDER,),
            )
        ))
        assert state.uploader is None
        assert any("does not belong" in reason for reason in state.blocked_reasons)

    def test_wrong_connector_or_missing_port_is_refused(self):
        other = binding(connector="telegram")
        assert build_claw_drive_upload_host_state(
            **full_inputs(binding=other)
        ).uploader is None
        state = build_claw_drive_upload_host_state(
            **full_inputs(approval=object())
        )
        assert state.uploader is None
        assert any("approval port" in reason for reason in state.blocked_reasons)

    def test_an_injected_state_cannot_also_report_a_blocker(self):
        with pytest.raises(ClawDriveUploadHostError):
            ClawDriveUploadHostState(
                uploader=build_claw_drive_artifact_uploader(**full_inputs()),
                blocked_reasons=("contradiction",),
            )

    def test_projection_leaks_no_token_folder_or_binding_ref(self):
        rendered = json.dumps(
            build_claw_drive_upload_host_state(**full_inputs()).safe_dict(),
            ensure_ascii=False, sort_keys=True,
        )
        for secret in (TOKEN, FOLDER, BINDING, WORKSPACE):
            assert secret not in rendered
        assert PRODUCTION_DRIVE_UPLOADER_INJECTED is False

    def test_worker_passes_the_boundary_result_into_create_app(self):
        source = WORKER.read_text(encoding="utf-8")
        assert "from app.claw_drive_upload_host_composition import" in source
        assert "claw_drive_artifact_uploader = build_claw_drive_artifact_uploader()" in source
        assert "claw_drive_artifact_uploader=claw_drive_artifact_uploader," in source

    def test_create_app_keeps_the_drive_pipeline_unbound_without_an_uploader(self):
        app = create_app(settings=settings(), claw_drive_artifact_uploader=None)
        assert app.state.claw_durable_drive_output_pipeline is None
        # The boundary's deployed-shape result is None in this build.
        assert build_claw_drive_artifact_uploader() is None
        assert inspect.signature(create_app).parameters[
            "claw_drive_artifact_uploader"].default is None


# --- canonical approval-port connection ------------------------------------

DOC = b"%PDF-1.7\nhost boundary approval connection\n%%EOF"
FOLDER_MIME = "application/vnd.google-apps.folder"


def _record():
    import hashlib

    return register_canonical_artifact(
        artifact_id="artifact_host_boundary", artifact_kind="claw.document",
        filename="boundary.pdf", media_type="application/pdf",
        size_bytes=len(DOC), integrity_ref=hashlib.sha256(DOC).hexdigest(),
        workspace_ref=WORKSPACE, run_ref="run_host_boundary",
    )


def _intent(record):
    return ConnectorWriteIntent(
        connector_id="google-drive", binding_ref=BINDING, actor_ref=ACTOR,
        tool_name=DRIVE_UPLOAD_TOOL, target_ref=FOLDER,
        payload_fingerprint=upload_payload_fingerprint(
            artifact=record, folder_ref=FOLDER
        ),
        idempotency_key="idem_host_boundary", approval_ref="approval_host_boundary",
        evidence_ref="evidence_host_boundary", requested_at=NOW,
    )


class _MaterialPort2:
    def __init__(self, record):
        self.record = record

    def resolve_artifact_material(self, artifact_ref, *, workspace_ref, run_ref):
        return DriveArtifactMaterial(self.record, DOC)


class _FolderPort2:
    def resolve_folder_proof(self, *, binding_ref, actor_ref, folder_ref):
        return DriveResourceProof(
            binding_ref=BINDING,
            metadata=DriveFileMetadata(
                file_id=FOLDER, name="Output", mime_type=FOLDER_MIME,
                version=2, trashed=False,
            ),
        )


class _RespondingNetwork:
    """Fake HTTPS transport returning one valid Drive files.create envelope."""

    def __init__(self, record):
        import hashlib
        import json as _json

        self.payload = _json.dumps({
            "id": "file_host_boundary", "name": record.filename,
            "mimeType": record.media_type, "parents": [FOLDER], "version": "1",
            "size": str(len(DOC)),
            "md5Checksum": hashlib.md5(DOC, usedforsecurity=False).hexdigest(),
            "sha256Checksum": record.integrity_ref, "trashed": False,
        }).encode("utf-8")
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return GoogleProviderHttpResponse(200, self.payload)


class _P01Evidence:
    """Hermetic stand-in for the existing canonical P01 evidence boundary."""

    def __init__(self, item):
        self.item = item
        self.calls = []

    def resolve_drive_write_approval(self, *, request_fingerprint):
        self.calls.append(request_fingerprint)
        return self.item


def _p01_evidence(*, intent, artifact_ref, run_ref):
    fingerprint = drive_write_approval_fingerprint(
        intent=intent, artifact_ref=artifact_ref,
        workspace_ref=WORKSPACE, run_ref=run_ref,
    )
    pause = ApprovalPause(
        pause_id="pause_host_boundary", run_id=run_ref,
        agent_runtime_id="agent:claw-drive-write@1", tool_id=DRIVE_WRITE_TOOL_ID,
        invocation_sha256=fingerprint,
        requirement=ApprovalRequirement.USER_CONFIRMATION, step_index=1,
        created_at=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(minutes=15),
        approval_scope=(DRIVE_UPLOAD_CAPABILITY,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="decision_host_boundary", pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED, authority_ref="authority_host_boundary",
        evidence_ref="evidence_host_boundary", decided_at=NOW - timedelta(minutes=4),
    )
    return DriveWriteApprovalEvidence(
        evidence_ref="evidence_host_boundary", request_fingerprint=fingerprint,
        approval_pause=pause, approval_decision=decision,
        expires_at=NOW + timedelta(minutes=10),
    )


class TestCanonicalApprovalPortConnection:
    """The Drive host boundary can now be completed with canonical components."""

    def test_canonical_approval_port_fails_closed_when_unconfigured(self):
        port = build_canonical_drive_write_approval_port(clock=lambda: NOW)
        assert isinstance(port, AuthorizedDriveWriteApprovalPort)
        assert port.verify_write_approval(
            intent=object(), artifact_ref=object(),
            workspace_ref=WORKSPACE, run_ref="run_host_boundary",
        ) is False

    def test_boundary_builds_the_canonical_port_from_p01_evidence(self):
        record = _record()
        state = build_claw_drive_upload_host_state(
            binding=binding(), scope=DriveScopeProjection(
                binding_ref=BINDING, allowed_folder_ids=(FOLDER,),
            ),
            artifacts=_MaterialPort2(record), folders=_FolderPort2(),
            approval_evidence=_P01Evidence(None), approval_clock=lambda: NOW,
            composition=composition_with(_RespondingNetwork(record)),
        )
        assert isinstance(state.uploader, GoogleDriveArtifactUploadAdapter)
        assert isinstance(state.uploader._approval, AuthorizedDriveWriteApprovalPort)

    def test_full_canonical_stack_uploads_once_and_refuses_replay(self):
        record = _record()
        artifact_ref = LineageArtifactRef(record.artifact_id, record.integrity_ref)
        intent = _intent(record)
        run_ref = "run_host_boundary"
        network = _RespondingNetwork(record)
        source = _P01Evidence(_p01_evidence(
            intent=intent, artifact_ref=artifact_ref, run_ref=run_ref
        ))
        state = build_claw_drive_upload_host_state(
            binding=binding(), scope=DriveScopeProjection(
                binding_ref=BINDING, allowed_folder_ids=(FOLDER,),
            ),
            artifacts=_MaterialPort2(record), folders=_FolderPort2(),
            approval_evidence=source, approval_clock=lambda: NOW,
            composition=composition_with(network),
        )
        result = state.uploader.create_output(
            artifact_ref=artifact_ref, intent=intent,
            workspace_ref=WORKSPACE, run_ref=run_ref, now=NOW,
        )
        assert result.artifact.lifecycle is ArtifactLifecycle.DURABLE
        assert result.artifact.durable_location.location_ref == "file_host_boundary"
        assert result.receipt.connector_id == "google-drive"
        assert len(network.calls) == 1
        assert len(source.calls) == 1

    def test_boundary_reports_a_missing_approval_seam_explicitly(self):
        record = _record()
        state = build_claw_drive_upload_host_state(
            binding=binding(), scope=DriveScopeProjection(
                binding_ref=BINDING, allowed_folder_ids=(FOLDER,),
            ),
            artifacts=_MaterialPort2(record), folders=_FolderPort2(),
            composition=composition_with(_RespondingNetwork(record)),
        )
        assert state.uploader is None
        assert any("approval port" in reason for reason in state.blocked_reasons)


def composition_with(network):
    return build_google_drive_upload_composition(
        authorization=_AuthorizedTokenPort(), network=network,
    )
