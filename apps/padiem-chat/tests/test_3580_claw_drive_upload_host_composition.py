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
    READ_SCOPE_IS_NOT_WRITE, build_claw_drive_artifact_uploader,
    build_claw_drive_upload_host_state, drive_write_grant_present,
)
from app.app_factory import create_app
from app.config import Settings
from kagent.connector_trust import ConnectorBindingProjection, ConnectorBindingState
from kagent.google_drive_artifact_upload import (
    DRIVE_UPLOAD_CAPABILITY, GoogleDriveArtifactUploadAdapter,
)
from kagent.google_drive_scope import DriveScopeProjection
from kagent.google_drive_upload_composition import (
    GoogleDriveUploadComposition, build_google_drive_upload_composition,
)

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
