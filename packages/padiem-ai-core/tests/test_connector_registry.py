import pytest

from padiem_ai_core.connector_registry import (
    ConnectorAuthorizationReference,
    ConnectorAuthorizationStatus,
    ConnectorDescriptor,
    ConnectorRegistryError,
    ConnectorRegistrySnapshot,
    resolve_connector_access,
    validate_connector_tools,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot


TOOL_ID = "tool:padiem:drive_read@1"
CONNECTOR_ID = "connector:google:drive@1"


def tool_registry() -> ToolRegistrySnapshot:
    spec = ToolSpec(
        id="drive.read",
        title="Drive Read",
        description="Read an already-authorized Drive resource.",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={"type": "object"},
    )
    return ToolRegistrySnapshot.from_entries(
        (
            RegisteredTool.from_spec(
                canonical_tool_id=TOOL_ID,
                runtime_spec=spec,
            ),
        )
    )


def descriptor(**overrides) -> ConnectorDescriptor:
    values = {
        "connector_id": CONNECTOR_ID,
        "title": "Google Drive",
        "canonical_tool_ids": (TOOL_ID,),
        "requires_authorization": True,
    }
    values.update(overrides)
    return ConnectorDescriptor(**values)


def auth(**overrides) -> ConnectorAuthorizationReference:
    values = {
        "connector_id": CONNECTOR_ID,
        "app_id": "b62",
        "subject_id": "user_1",
        "authorization_ref": "authref:drive:user_1:primary",
        "status": ConnectorAuthorizationStatus.AUTHORIZED,
    }
    values.update(overrides)
    return ConnectorAuthorizationReference(**values)


def test_connector_descriptor_references_registered_canonical_tools() -> None:
    active = descriptor()

    assert validate_connector_tools(active, tool_registry()) is active


def test_connector_with_unknown_tool_fails_closed() -> None:
    active = descriptor(canonical_tool_ids=("tool:padiem:missing@1",))

    with pytest.raises(ConnectorRegistryError) as exc_info:
        validate_connector_tools(active, tool_registry())

    assert exc_info.value.code == "connector_tool_not_registered"


def test_connector_registry_is_deterministic_and_versioned() -> None:
    second = descriptor(
        connector_id="connector:padiem:public_web@1",
        title="Public Web",
        requires_authorization=False,
    )
    registry = ConnectorRegistrySnapshot.from_connectors((second, descriptor()))

    assert tuple(item.connector_id for item in registry.connectors) == (
        "connector:google:drive@1",
        "connector:padiem:public_web@1",
    )


def test_private_connector_requires_opaque_authorization_reference() -> None:
    with pytest.raises(ConnectorRegistryError) as exc_info:
        resolve_connector_access(
            descriptor=descriptor(),
            app_id="b62",
            subject_id="user_1",
        )

    assert exc_info.value.code == "connector_authorization_required"


def test_authorized_private_connector_resolves_without_exposing_secret_reference() -> None:
    access = resolve_connector_access(
        descriptor=descriptor(),
        app_id="b62",
        subject_id="user_1",
        authorization=auth(),
    )

    assert access.authorization_ref == "authref:drive:user_1:primary"
    assert access.to_public_dict() == {
        "connector_id": CONNECTOR_ID,
        "app_id": "b62",
        "subject_id": "user_1",
    }
    assert "authorization_ref" not in access.to_public_dict()


def test_authorization_reference_public_projection_redacts_opaque_reference() -> None:
    public = auth().to_public_dict()

    assert public == {
        "connector_id": CONNECTOR_ID,
        "app_id": "b62",
        "subject_id": "user_1",
        "status": "authorized",
    }
    assert "authorization_ref" not in public


def test_revoked_or_unavailable_authorization_fails_closed() -> None:
    for status in (
        ConnectorAuthorizationStatus.REVOKED,
        ConnectorAuthorizationStatus.UNAVAILABLE,
    ):
        with pytest.raises(ConnectorRegistryError) as exc_info:
            resolve_connector_access(
                descriptor=descriptor(),
                app_id="b62",
                subject_id="user_1",
                authorization=auth(status=status),
            )
        assert exc_info.value.code == "connector_not_authorized"


def test_authorization_cannot_cross_product_or_subject_boundary() -> None:
    for changed in (
        {"app_id": "storymemory"},
        {"subject_id": "user_2"},
        {"connector_id": "connector:google:gmail@1"},
    ):
        with pytest.raises(ConnectorRegistryError) as exc_info:
            resolve_connector_access(
                descriptor=descriptor(),
                app_id="b62",
                subject_id="user_1",
                authorization=auth(**changed),
            )
        assert exc_info.value.code == "connector_authorization_mismatch"


def test_public_connector_requires_no_authorization_reference() -> None:
    public_connector = descriptor(
        connector_id="connector:padiem:public_web@1",
        title="Public Web",
        requires_authorization=False,
    )

    access = resolve_connector_access(
        descriptor=public_connector,
        app_id="b62",
        subject_id="user_1",
    )

    assert access.authorization_ref is None


def test_connector_access_is_not_tool_permission_or_oauth_token() -> None:
    access = resolve_connector_access(
        descriptor=descriptor(),
        app_id="b62",
        subject_id="user_1",
        authorization=auth(),
    )

    for forbidden in (
        "granted_tools",
        "auth_scopes",
        "access_token",
        "refresh_token",
        "client_secret",
        "approved_tools",
    ):
        assert not hasattr(access, forbidden)


def test_descriptor_does_not_duplicate_b49_b50_governance_schema() -> None:
    active = descriptor()

    for forbidden in (
        "source_authority",
        "source_schema",
        "license",
        "transformation_rules",
        "oauth_flow",
        "credentials",
        "private_data_policy",
    ):
        assert not hasattr(active, forbidden)
