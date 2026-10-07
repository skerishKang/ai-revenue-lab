from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from padiem_control_plane.auth_sessions import (
    AuthSessionSnapshot,
    AuthSessionState,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.engine_entitlement_producer import (
    ENGINE_ENTITLEMENT_POLICY_REVISION,
    ENGINE_ORCHESTRATION_GRANT,
    ensure_authenticated_user_engine_entitlement,
    produce_authenticated_user_engine_entitlement,
    resolve_authenticated_user_session,
)


NOW = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
SUBJECT = CanonicalSubjectRef(
    SubjectType.USER,
    "subject:padiem:user:3300",
)


def session(
    *,
    product_id: str = "b62",
    subject: CanonicalSubjectRef = SUBJECT,
    session_id: str = "sess_3300",
    revision: int = 1,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    state: AuthSessionState = AuthSessionState.ACTIVE,
) -> AuthSessionSnapshot:
    issued = issued_at or NOW - timedelta(minutes=5)
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id=product_id,
        subject=subject,
        issued_at=issued,
        expires_at=expires_at or NOW + timedelta(minutes=55),
        state=state,
        revision=revision,
        tenant_id=(
            "tenant_3300"
            if product_id == "b54-padiem-claw"
            else None
        ),
    )


def private_session_wire(
    value: AuthSessionSnapshot,
) -> dict[str, object]:
    return value.to_public_dict()


class FakeIdentity:
    def __init__(
        self,
        value: AuthSessionSnapshot,
        *,
        product_user_id: str = "usr_3300",
    ) -> None:
        self.value = value
        self.product_user_id = product_user_id
        self.reverse_calls: list[dict[str, object]] = []
        self.current_calls: list[dict[str, object]] = []

    async def resolve_product_user_for_subject(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.reverse_calls.append(dict(payload))
        return {
            "ok": True,
            "product_user_id": self.product_user_id,
        }

    async def resolve_current_auth_session(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.current_calls.append(dict(payload))
        return {
            "ok": True,
            "session": private_session_wire(self.value),
        }


class FailingIdentity(FakeIdentity):
    async def resolve_product_user_for_subject(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        del payload
        raise RuntimeError("transport detail must not escape")


class CaptureStore:
    def __init__(self) -> None:
        self.snapshots = []

    def install_entitlement_snapshot(
        self,
        snapshot,
        *,
        now,
    ):
        self.snapshots.append((snapshot, now))
        return snapshot


@pytest.mark.parametrize(
    "product_id",
    ["b62", "b54-padiem-claw"],
)
def test_frozen_policy_allows_every_active_authenticated_user_without_limit(
    product_id: str,
) -> None:
    source = session(product_id=product_id)

    snapshot = produce_authenticated_user_engine_entitlement(
        source,
        now=NOW,
    )

    assert snapshot.product_id == product_id
    assert snapshot.subject == SUBJECT
    assert snapshot.expires_at == source.expires_at
    assert snapshot.issued_at >= source.issued_at
    assert snapshot.revision.startswith(
        ENGINE_ENTITLEMENT_POLICY_REVISION
    )
    assert len(snapshot.grants) == 1
    grant = snapshot.resolve(ENGINE_ORCHESTRATION_GRANT)
    assert grant is not None
    assert grant.allowed is True
    assert grant.limit is None


@pytest.mark.parametrize(
    "subject_type",
    [SubjectType.ANONYMOUS, SubjectType.ACCOUNT],
)
def test_anonymous_and_account_subjects_are_not_mvp_entitlement_authority(
    subject_type: SubjectType,
) -> None:
    source = session(
        subject=CanonicalSubjectRef(
            subject_type,
            "subject-not-user",
        )
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as raised:
        produce_authenticated_user_engine_entitlement(
            source,
            now=NOW,
        )

    assert (
        raised.value.code
        == "engine_entitlement_subject_not_eligible"
    )


@pytest.mark.parametrize(
    ("state", "expires_at"),
    [
        (
            AuthSessionState.REVOKED,
            NOW + timedelta(minutes=10),
        ),
        (
            AuthSessionState.EXPIRED,
            NOW + timedelta(minutes=10),
        ),
        (
            AuthSessionState.ACTIVE,
            NOW,
        ),
    ],
)
def test_inactive_login_never_produces_allow_snapshot(
    state: AuthSessionState,
    expires_at: datetime,
) -> None:
    source = session(
        state=state,
        expires_at=expires_at,
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as raised:
        produce_authenticated_user_engine_entitlement(
            source,
            now=NOW,
        )

    assert (
        raised.value.code
        == "engine_entitlement_session_inactive"
    )


def test_snapshot_identity_is_deterministic_for_same_session_revision() -> None:
    source = session()

    first = produce_authenticated_user_engine_entitlement(
        source,
        now=NOW,
    )
    second = produce_authenticated_user_engine_entitlement(
        source,
        now=NOW + timedelta(seconds=1),
    )

    assert (
        first.to_policy_dict()
        == second.to_policy_dict()
    )


def test_newer_login_revision_produces_distinct_entitlement_identity() -> None:
    first_session = session()
    second_session = session(
        session_id="sess_3300_new",
        revision=2,
        issued_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )

    first = produce_authenticated_user_engine_entitlement(
        first_session,
        now=NOW,
    )
    second = produce_authenticated_user_engine_entitlement(
        second_session,
        now=NOW + timedelta(minutes=1),
    )

    assert first.snapshot_id != second.snapshot_id
    assert first.revision != second.revision
    assert second.issued_at > first.issued_at


def test_identity_resolution_uses_only_product_and_canonical_subject_then_current_session() -> None:
    identity = FakeIdentity(session())

    resolved = asyncio.run(
        resolve_authenticated_user_session(
            identity,
            product_id="b62",
            subject=SUBJECT,
            now=NOW,
        )
    )

    assert resolved.subject == SUBJECT
    assert identity.reverse_calls == [
        {
            "product_id": "b62",
            "canonical_subject_id": SUBJECT.subject_id,
        }
    ]
    assert identity.current_calls == [
        {
            "product_id": "b62",
            "product_user_id": "usr_3300",
        }
    ]


def test_identity_transport_failure_is_bounded_and_fails_closed() -> None:
    identity = FailingIdentity(session())

    with pytest.raises(
        ControlPlaneContractError
    ) as raised:
        asyncio.run(
            resolve_authenticated_user_session(
                identity,
                product_id="b62",
                subject=SUBJECT,
                now=NOW,
            )
        )

    assert (
        raised.value.code
        == "engine_entitlement_identity_unavailable"
    )
    assert "transport detail" not in raised.value.safe_message


def test_cross_product_or_subject_identity_projection_fails_closed() -> None:
    foreign = CanonicalSubjectRef(
        SubjectType.USER,
        "subject:padiem:user:other",
    )
    identity = FakeIdentity(
        session(subject=foreign)
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as raised:
        asyncio.run(
            resolve_authenticated_user_session(
                identity,
                product_id="b62",
                subject=SUBJECT,
                now=NOW,
            )
        )

    assert (
        raised.value.code
        == "engine_entitlement_identity_mismatch"
    )


def test_ensure_installs_only_canonical_snapshot_through_internal_store_seam() -> None:
    identity = FakeIdentity(session())
    store = CaptureStore()

    snapshot = asyncio.run(
        ensure_authenticated_user_engine_entitlement(
            store,
            identity,
            product_id="b62",
            subject=SUBJECT,
            now=NOW,
        )
    )

    assert len(store.snapshots) == 1
    installed, installed_at = store.snapshots[0]
    assert installed is snapshot
    assert installed_at == NOW
    projection = repr(
        snapshot.to_policy_dict()
    ).lower()
    for forbidden in (
        "plan",
        "subscription",
        "payment",
        "credit",
        "provider",
        "model",
        "route",
        "role",
    ):
        assert forbidden not in projection


def test_unreviewed_product_has_no_allow_policy() -> None:
    identity = FakeIdentity(
        session(product_id="other")
    )

    with pytest.raises(
        ControlPlaneContractError
    ) as raised:
        asyncio.run(
            resolve_authenticated_user_session(
                identity,
                product_id="other",
                subject=SUBJECT,
                now=NOW,
            )
        )

    assert (
        raised.value.code
        == "engine_entitlement_product_not_eligible"
    )
    assert identity.reverse_calls == []
    assert identity.current_calls == []


def test_worker_revalidates_identity_before_fetch_and_reserve_but_not_usage_receipt() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "engine_admission_authority_worker.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    durable = classes[
        "CanonicalEngineAdmissionDurableObject"
    ]

    methods = {
        node.name: ast.unparse(node)
        for node in durable.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }

    assert (
        "ensure_authenticated_user_engine_entitlement"
        in methods["fetch_entitlement_snapshot"]
        or "_ensure_current_entitlement"
        in methods["fetch_entitlement_snapshot"]
    )
    assert (
        "ensure_authenticated_user_engine_entitlement"
        in methods["reserve_usage"]
    )
    assert (
        "ensure_authenticated_user_engine_entitlement"
        not in methods["record_usage"]
    )


def test_worker_config_requires_private_identity_service_without_public_route() -> None:
    root = Path(__file__).resolve().parents[1]
    config_path = (
        root
        / (
            "wran"
            + "gler.engine-admission-authority.jsonc"
        )
    )
    config = json.loads(
        config_path.read_text(
            encoding="utf-8"
        )
    )

    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert "routes" not in config
    assert config["services"] == [
        {
            "binding": "CONTROL_PLANE_IDENTITY",
            "service": "padiem-control-plane-identity",
        }
    ]
