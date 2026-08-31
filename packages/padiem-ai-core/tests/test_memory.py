import pytest

from padiem_ai_core.memory import (
    MemoryContractError,
    MemoryNamespace,
    MemoryProvenance,
    MemoryScope,
    MemoryWriteAuthorization,
    MemoryWriteOrigin,
    MemoryWritePolicy,
    MemoryWriteRequest,
    authorize_memory_write,
)


APP_ID = "b62"


def namespace(
    scope: MemoryScope = MemoryScope.PROJECT,
    subject_id: str = "project.alpha",
    *,
    app_id: str = APP_ID,
) -> MemoryNamespace:
    return MemoryNamespace(app_id=app_id, scope=scope, subject_id=subject_id)


def provenance() -> MemoryProvenance:
    return MemoryProvenance(
        source_type="conversation_turn",
        source_ref="conversation:conv_1:turn_8",
        trace_id="trace_1",
        derived_from=("turn_8",),
    )


def request(
    ns: MemoryNamespace | None = None,
    *,
    origin: MemoryWriteOrigin = MemoryWriteOrigin.USER_EXPLICIT,
    content: str = "The project decided to keep the provider boundary in B14.",
    proposal_id: str | None = None,
) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        memory_id="memory_1",
        namespace=ns or namespace(),
        content=content,
        origin=origin,
        provenance=provenance(),
        idempotency_key="idem_1",
        proposal_id=proposal_id,
    )


def authorization(
    ns: MemoryNamespace | None = None,
    *,
    app_id: str = APP_ID,
    approved_model_proposals: tuple[str, ...] = (),
) -> MemoryWriteAuthorization:
    active_namespace = ns or namespace()
    return MemoryWriteAuthorization(
        app_id=app_id,
        writable_namespaces=(active_namespace.key,),
        approved_model_proposals=approved_model_proposals,
    )


def test_namespace_is_canonical_and_product_partitioned() -> None:
    ns = namespace()

    assert ns.key == "memory:project:b62:project.alpha"
    assert ns.to_public_dict() == {
        "app_id": "b62",
        "scope": "project",
        "namespace": "memory:project:b62:project.alpha",
    }


def test_product_scope_has_one_canonical_subject() -> None:
    with pytest.raises(MemoryContractError) as exc_info:
        MemoryNamespace(
            app_id="b62",
            scope=MemoryScope.PRODUCT,
            subject_id="other",
        )

    assert exc_info.value.code == "invalid_memory_namespace"


def test_user_project_and_conversation_namespaces_remain_distinct() -> None:
    namespaces = {
        namespace(MemoryScope.USER, "user_1").key,
        namespace(MemoryScope.PROJECT, "project_1").key,
        namespace(MemoryScope.CONVERSATION, "conversation_1").key,
    }

    assert len(namespaces) == 3


def test_authorized_explicit_write_is_prepared_without_storage_side_effect() -> None:
    ns = namespace()
    prepared = authorize_memory_write(request(ns), authorization(ns))

    assert prepared.request.namespace == ns
    assert prepared.request.content.startswith("The project decided")
    assert prepared.request.idempotency_scope == f"{ns.key}:idem_1"


def test_cross_app_write_fails_closed() -> None:
    ns = namespace(app_id="b62")

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_write(
            request(ns),
            authorization(ns, app_id="storymemory"),
        )

    assert exc_info.value.code == "memory_app_mismatch"


def test_ungranted_namespace_write_fails_closed() -> None:
    allowed = namespace(MemoryScope.PROJECT, "project.allowed")
    other = namespace(MemoryScope.PROJECT, "project.other")

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_write(request(other), authorization(allowed))

    assert exc_info.value.code == "memory_namespace_not_authorized"


def test_policy_can_narrow_scope_but_not_widen_authorization() -> None:
    ns = namespace(MemoryScope.PROJECT, "project.alpha")
    policy = MemoryWritePolicy(allowed_scopes=(MemoryScope.USER,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_write(request(ns), authorization(ns), policy=policy)

    assert exc_info.value.code == "memory_scope_not_allowed"


def test_model_proposal_cannot_be_constructed_without_proposal_id() -> None:
    with pytest.raises(MemoryContractError) as exc_info:
        request(origin=MemoryWriteOrigin.MODEL_PROPOSED)

    assert exc_info.value.code == "model_memory_requires_proposal_id"


def test_model_proposal_requires_independent_trusted_approval() -> None:
    ns = namespace()
    candidate = request(
        ns,
        origin=MemoryWriteOrigin.MODEL_PROPOSED,
        proposal_id="proposal_1",
    )

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_write(candidate, authorization(ns))

    assert exc_info.value.code == "model_memory_approval_required"


def test_model_proposal_can_be_written_only_when_approval_matches() -> None:
    ns = namespace()
    candidate = request(
        ns,
        origin=MemoryWriteOrigin.MODEL_PROPOSED,
        proposal_id="proposal_1",
    )
    prepared = authorize_memory_write(
        candidate,
        authorization(ns, approved_model_proposals=("proposal_1",)),
    )

    assert prepared.request.proposal_id == "proposal_1"
    assert prepared.request.origin is MemoryWriteOrigin.MODEL_PROPOSED


def test_non_model_write_rejects_proposal_id_to_avoid_confused_authority() -> None:
    with pytest.raises(MemoryContractError) as exc_info:
        request(
            origin=MemoryWriteOrigin.USER_EXPLICIT,
            proposal_id="proposal_1",
        )

    assert exc_info.value.code == "invalid_memory_contract"


def test_active_policy_can_narrow_content_budget() -> None:
    ns = namespace()
    candidate = request(ns, content="123456")

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_write(
            candidate,
            authorization(ns),
            policy=MemoryWritePolicy(max_content_chars=5),
        )

    assert exc_info.value.code == "memory_budget_exceeded"


def test_public_projection_redacts_memory_content_and_private_source_ref() -> None:
    ns = namespace()
    prepared = authorize_memory_write(request(ns), authorization(ns))
    public = prepared.to_public_dict()

    assert public["memory_id"] == "memory_1"
    assert public["content_chars"] == len(prepared.request.content)
    assert "content" not in public
    assert "source_ref" not in public["provenance"]
    assert public["provenance"]["source_type"] == "conversation_turn"


def test_authorization_rejects_duplicate_namespaces_and_proposal_ids() -> None:
    ns = namespace()

    with pytest.raises(MemoryContractError):
        MemoryWriteAuthorization(
            app_id=APP_ID,
            writable_namespaces=(ns.key, ns.key),
        )

    with pytest.raises(MemoryContractError):
        MemoryWriteAuthorization(
            app_id=APP_ID,
            writable_namespaces=(ns.key,),
            approved_model_proposals=("proposal_1", "proposal_1"),
        )


def test_provenance_public_projection_keeps_shape_without_private_reference() -> None:
    item = provenance()

    assert item.to_public_dict() == {
        "source_type": "conversation_turn",
        "trace_id": "trace_1",
        "derived_from_count": 1,
    }
