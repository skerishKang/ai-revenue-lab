"""Tests for server-only B66 operator Saved Quote Skill provisioning (#3302)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    B66ProvisioningError,
    B66SavedQuoteSkillProvisioner,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from app.b66_saved_quote_skill_store import canonicalize_approved_artifact
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType


NOW = datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)


def _grant(*actions, issued_at=None, expires_at=None):
    return TrustedB66ProvisioningGrant(
        grant_ref="grant:b66:test",
        operator_subject=CanonicalSubjectRef(SubjectType.USER, "operator_subject"),
        authority_ref="authority:b66:ops",
        allowed_actions=tuple(actions or (B66ProvisioningAction.ASSIGN,)),
        issued_at=issued_at or (NOW - timedelta(minutes=5)),
        expires_at=expires_at or (NOW + timedelta(minutes=30)),
    )


def _target(*, user_id="usr_" + "a" * 32, workspace_id="workspace_one"):
    return ResolvedB66ProvisioningTarget(
        user_id=user_id,
        workspace_id=workspace_id,
        tenant_id="tenant_" + "b" * 32,
        canonical_subject_id="subject_customer",
    )


def _artifact():
    fingerprint = "c" * 64
    payload = {
        "schemaVersion": 1,
        "id": "saved-skill-1",
        "name": "우리 견적서",
        "fixedDefaults": {},
        "variableSchema": {},
        "internalTemplate": {},
        "provenance": {},
        "approval": {
            "schemaVersion": 1,
            "status": "approved",
            "skillFingerprint": fingerprint,
            "approvedBy": "operator:test",
            "approvedAt": "2026-10-01T00:00:00Z",
            "approvalRef": "manual:test",
        },
        "fingerprint": fingerprint,
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
        "createdAt": "2026-10-01T00:00:00Z",
        "updatedAt": "2026-10-01T00:00:00Z",
    }
    return canonicalize_approved_artifact(
        skill_id="saved-skill-1",
        skill_name="우리 견적서",
        fingerprint=fingerprint,
        version=1,
        serialized_json=json.dumps(payload, ensure_ascii=False),
    )


class _Store:
    def __init__(self):
        self.put_calls = []
        self.disable_calls = []
        self.rows = {}

    async def put_approved_skill(self, *, user_id, workspace_id, artifact):
        self.put_calls.append((user_id, workspace_id, artifact))
        saved = "b66skill_" + "d" * 32
        row = {
            "saved_skill_id": saved,
            "workspace_id": workspace_id,
            "skill_id": artifact.skill_id,
            "skill_name": artifact.skill_name,
            "skill_fingerprint": artifact.fingerprint,
            "skill_version": artifact.version,
            "status": "approved",
            "skill": json.loads(artifact.serialized_json),
        }
        self.rows[(user_id, workspace_id, saved)] = row
        return row

    async def disable_skill(self, *, user_id, workspace_id, saved_skill_id):
        self.disable_calls.append((user_id, workspace_id, saved_skill_id))
        return (user_id, workspace_id, saved_skill_id) in self.rows


@pytest.mark.asyncio
async def test_assign_requires_trusted_grant_and_server_resolved_target():
    store = _Store()
    provisioner = B66SavedQuoteSkillProvisioner(store)
    artifact = _artifact()

    stored, receipt = await provisioner.assign(
        grant=_grant(B66ProvisioningAction.ASSIGN),
        target=_target(),
        artifact=artifact,
        now=NOW,
    )

    assert stored["skill_id"] == "saved-skill-1"
    assert len(store.put_calls) == 1
    user_id, workspace_id, passed_artifact = store.put_calls[0]
    assert user_id == "usr_" + "a" * 32
    assert workspace_id == "workspace_one"
    assert passed_artifact is artifact

    safe = receipt.safe_dict()
    assert safe["action"] == "assign"
    assert safe["target_user_id"] == user_id
    assert safe["target_workspace_id"] == workspace_id
    assert safe["target_tenant_id"] == "tenant_" + "b" * 32
    assert safe["skill_id"] == "saved-skill-1"
    assert safe["skill_fingerprint"] == "c" * 64


@pytest.mark.asyncio
async def test_raw_client_shaped_grant_or_target_is_rejected_before_store():
    store = _Store()
    provisioner = B66SavedQuoteSkillProvisioner(store)

    with pytest.raises(B66ProvisioningError, match="trusted operator grant"):
        await provisioner.assign(
            grant={"grant_ref": "client-forged"},  # type: ignore[arg-type]
            target=_target(),
            artifact=_artifact(),
            now=NOW,
        )
    with pytest.raises(B66ProvisioningError, match="server-resolved target"):
        await provisioner.assign(
            grant=_grant(B66ProvisioningAction.ASSIGN),
            target={  # type: ignore[arg-type]
                "user_id": "usr_" + "e" * 32,
                "workspace_id": "evil",
                "tenant_id": "tenant_" + "f" * 32,
            },
            artifact=_artifact(),
            now=NOW,
        )
    assert store.put_calls == []


@pytest.mark.asyncio
async def test_expired_or_wrong_action_grant_cannot_assign():
    store = _Store()
    provisioner = B66SavedQuoteSkillProvisioner(store)
    expired = _grant(
        B66ProvisioningAction.ASSIGN,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
    )
    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.assign(
            grant=expired,
            target=_target(),
            artifact=_artifact(),
            now=NOW,
        )

    disable_only = _grant(B66ProvisioningAction.DISABLE)
    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.assign(
            grant=disable_only,
            target=_target(),
            artifact=_artifact(),
            now=NOW,
        )
    assert store.put_calls == []


@pytest.mark.asyncio
async def test_disable_is_bounded_to_resolved_target_and_requires_disable_action():
    store = _Store()
    provisioner = B66SavedQuoteSkillProvisioner(store)
    target = _target()
    stored, _ = await provisioner.assign(
        grant=_grant(B66ProvisioningAction.ASSIGN),
        target=target,
        artifact=_artifact(),
        now=NOW,
    )
    saved_id = stored["saved_skill_id"]

    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.disable(
            grant=_grant(B66ProvisioningAction.ASSIGN),
            target=target,
            saved_skill_id=saved_id,
            now=NOW,
        )

    foreign_target = _target(user_id="usr_" + "e" * 32, workspace_id="workspace_two")
    missing = await provisioner.disable(
        grant=_grant(B66ProvisioningAction.DISABLE),
        target=foreign_target,
        saved_skill_id=saved_id,
        now=NOW,
    )
    assert missing is None

    receipt = await provisioner.disable(
        grant=_grant(B66ProvisioningAction.DISABLE),
        target=target,
        saved_skill_id=saved_id,
        now=NOW,
    )
    assert receipt is not None
    assert receipt.safe_dict()["action"] == "disable"


def test_target_requires_canonical_tenant_shape():
    with pytest.raises(B66ProvisioningError, match="tenant_id"):
        ResolvedB66ProvisioningTarget(
            user_id="usr_" + "a" * 32,
            workspace_id="workspace_one",
            tenant_id="client-tenant",
            canonical_subject_id="subject_customer",
        )


def test_no_browser_route_or_identity_authority_is_created():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "b66_quote_skill_provisioning.py"
    ).read_text(encoding="utf-8").lower()

    assert "@router" not in source
    assert "request.json" not in source
    assert "request.query" not in source
    assert "create_session" not in source
    assert "mint_tenant" not in source
    assert "insert into users" not in source
