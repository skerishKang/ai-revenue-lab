"""Tests for trusted server-only B66 private asset provisioning (#3427)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.b66_quote_asset_provisioning import B66QuoteAssetProvisioner
from app.b66_quote_assets import B66QuoteAssetMetadata
from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    B66ProvisioningError,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType


NOW = datetime(2026, 10, 2, 11, 30, tzinfo=timezone.utc)


def _grant(*actions, issued_at=None, expires_at=None):
    return TrustedB66ProvisioningGrant(
        grant_ref="grant:b66:asset:test",
        operator_subject=CanonicalSubjectRef(
            SubjectType.USER, "operator_asset_subject"
        ),
        authority_ref="authority:b66:ops",
        allowed_actions=tuple(
            actions or (B66ProvisioningAction.PROVISION_ASSET,)
        ),
        issued_at=issued_at or (NOW - timedelta(minutes=5)),
        expires_at=expires_at or (NOW + timedelta(minutes=30)),
    )


def _target():
    return ResolvedB66ProvisioningTarget(
        user_id="usr_" + "a" * 32,
        workspace_id="workspace_asset_owner",
        tenant_id="tenant_" + "b" * 32,
        canonical_subject_id="subject_asset_customer",
    )


class _Store:
    def __init__(self):
        self.calls = []

    async def put_approved_asset(
        self,
        *,
        user_id,
        workspace_id,
        asset_kind,
        media_type,
        body,
    ):
        self.calls.append(
            (user_id, workspace_id, asset_kind, media_type, body)
        )
        return B66QuoteAssetMetadata(
            asset_id="b66asset_" + "c" * 32,
            user_id=user_id,
            workspace_id=workspace_id,
            asset_kind=asset_kind,
            media_type=media_type,
            object_key="b66/quote-assets/" + "c" * 32 + ".png",
            byte_length=len(body),
            sha256="d" * 64,
            status="approved",
            created_at="2026-10-02T11:30:00Z",
            updated_at="2026-10-02T11:30:00Z",
        )


@pytest.mark.asyncio
async def test_provision_uses_server_resolved_owner_and_safe_receipt():
    store = _Store()
    provisioner = B66QuoteAssetProvisioner(store)
    body = b"\x89PNG\r\n\x1a\nsynthetic"

    metadata, receipt = await provisioner.provision(
        grant=_grant(B66ProvisioningAction.PROVISION_ASSET),
        target=_target(),
        asset_kind="logo",
        media_type="image/png",
        body=body,
        now=NOW,
    )

    assert metadata.asset_id == "b66asset_" + "c" * 32
    assert store.calls == [
        (
            "usr_" + "a" * 32,
            "workspace_asset_owner",
            "logo",
            "image/png",
            body,
        )
    ]

    safe = receipt.safe_dict()
    assert safe["action"] == "provision_asset"
    assert safe["target_user_id"] == "usr_" + "a" * 32
    assert safe["target_workspace_id"] == "workspace_asset_owner"
    assert safe["target_tenant_id"] == "tenant_" + "b" * 32
    assert safe["asset_id"] == metadata.asset_id
    assert safe["asset_kind"] == "logo"
    assert safe["media_type"] == "image/png"
    assert safe["byte_length"] == len(body)
    assert safe["sha256"] == "d" * 64
    assert "object_key" not in safe
    assert "body" not in safe


@pytest.mark.asyncio
async def test_raw_grant_or_target_is_rejected_before_store():
    store = _Store()
    provisioner = B66QuoteAssetProvisioner(store)

    with pytest.raises(B66ProvisioningError, match="trusted operator grant"):
        await provisioner.provision(
            grant={"grant_ref": "forged"},  # type: ignore[arg-type]
            target=_target(),
            asset_kind="logo",
            media_type="image/png",
            body=b"x",
            now=NOW,
        )

    with pytest.raises(B66ProvisioningError, match="server-resolved target"):
        await provisioner.provision(
            grant=_grant(B66ProvisioningAction.PROVISION_ASSET),
            target={"user_id": "client"},  # type: ignore[arg-type]
            asset_kind="stamp",
            media_type="image/png",
            body=b"x",
            now=NOW,
        )

    assert store.calls == []


@pytest.mark.asyncio
async def test_expired_or_wrong_action_grant_is_denied():
    store = _Store()
    provisioner = B66QuoteAssetProvisioner(store)

    expired = _grant(
        B66ProvisioningAction.PROVISION_ASSET,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
    )
    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.provision(
            grant=expired,
            target=_target(),
            asset_kind="logo",
            media_type="image/png",
            body=b"x",
            now=NOW,
        )

    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.provision(
            grant=_grant(B66ProvisioningAction.ASSIGN),
            target=_target(),
            asset_kind="logo",
            media_type="image/png",
            body=b"x",
            now=NOW,
        )

    assert store.calls == []


def test_no_browser_route_or_second_identity_authority():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "b66_quote_asset_provisioning.py"
    ).read_text(encoding="utf-8").lower()

    assert "@router" not in source
    assert "request.json" not in source
    assert "request.query" not in source
    assert "route(" not in source
    assert "create_session" not in source
    assert "mint_tenant" not in source
    assert "insert into users" not in source
    assert "object_key" not in source.split("safe_dict", 1)[1].split(
        "def _receipt_ref", 1
    )[0]
