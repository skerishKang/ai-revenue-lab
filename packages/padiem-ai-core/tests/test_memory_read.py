import pytest

from padiem_ai_core.memory import MemoryContractError, MemoryNamespace, MemoryScope
from padiem_ai_core.memory_read import (
    MemoryReadAuthorization,
    MemoryReadPolicy,
    authorize_memory_retrieval,
)
from padiem_ai_core.retrieval import RetrievalContractError


APP_ID = "b62"


def ns(scope: MemoryScope, subject_id: str, *, app_id: str = APP_ID) -> MemoryNamespace:
    return MemoryNamespace(app_id=app_id, scope=scope, subject_id=subject_id)


def test_authorized_memory_read_builds_canonical_retrieval_request() -> None:
    project = ns(MemoryScope.PROJECT, "project.alpha")
    conversation = ns(MemoryScope.CONVERSATION, "conv_1")
    auth = MemoryReadAuthorization(
        app_id=APP_ID,
        readable_namespaces=(project, conversation),
    )

    request = authorize_memory_retrieval(
        query="What did we decide?",
        namespaces=(project, conversation),
        authorization=auth,
        max_results=6,
    )

    assert request.namespaces == (project.key, conversation.key)
    assert request.max_results == 6
    assert request.query == "What did we decide?"


def test_ungranted_memory_namespace_fails_closed_before_retrieval() -> None:
    allowed = ns(MemoryScope.PROJECT, "project.allowed")
    other = ns(MemoryScope.PROJECT, "project.other")
    auth = MemoryReadAuthorization(app_id=APP_ID, readable_namespaces=(allowed,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(other,),
            authorization=auth,
        )

    assert exc_info.value.code == "memory_namespace_not_authorized"


def test_cross_app_memory_read_fails_closed() -> None:
    allowed = ns(MemoryScope.USER, "user_1")
    foreign = ns(MemoryScope.USER, "user_1", app_id="storymemory")
    auth = MemoryReadAuthorization(app_id=APP_ID, readable_namespaces=(allowed,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(foreign,),
            authorization=auth,
        )

    assert exc_info.value.code == "memory_app_mismatch"


def test_authorization_itself_cannot_mix_apps() -> None:
    local = ns(MemoryScope.USER, "user_1")
    foreign = ns(MemoryScope.PROJECT, "project_1", app_id="storymemory")

    with pytest.raises(MemoryContractError) as exc_info:
        MemoryReadAuthorization(
            app_id=APP_ID,
            readable_namespaces=(local, foreign),
        )

    assert exc_info.value.code == "memory_app_mismatch"


def test_read_policy_can_narrow_scopes() -> None:
    user = ns(MemoryScope.USER, "user_1")
    project = ns(MemoryScope.PROJECT, "project_1")
    auth = MemoryReadAuthorization(
        app_id=APP_ID,
        readable_namespaces=(user, project),
    )
    policy = MemoryReadPolicy(allowed_scopes=(MemoryScope.USER,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(project,),
            authorization=auth,
            policy=policy,
        )

    assert exc_info.value.code == "memory_scope_not_allowed"


def test_read_policy_caps_requested_namespace_count() -> None:
    user = ns(MemoryScope.USER, "user_1")
    project = ns(MemoryScope.PROJECT, "project_1")
    auth = MemoryReadAuthorization(
        app_id=APP_ID,
        readable_namespaces=(user, project),
    )

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(user, project),
            authorization=auth,
            policy=MemoryReadPolicy(max_namespaces=1),
        )

    assert exc_info.value.code == "memory_read_budget_exceeded"


def test_read_policy_caps_retrieval_result_count() -> None:
    project = ns(MemoryScope.PROJECT, "project_1")
    auth = MemoryReadAuthorization(app_id=APP_ID, readable_namespaces=(project,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(project,),
            authorization=auth,
            max_results=5,
            policy=MemoryReadPolicy(max_results=4),
        )

    assert exc_info.value.code == "memory_read_budget_exceeded"


def test_duplicate_requested_namespace_fails_closed() -> None:
    project = ns(MemoryScope.PROJECT, "project_1")
    auth = MemoryReadAuthorization(app_id=APP_ID, readable_namespaces=(project,))

    with pytest.raises(MemoryContractError) as exc_info:
        authorize_memory_retrieval(
            query="query",
            namespaces=(project, project),
            authorization=auth,
        )

    assert exc_info.value.code == "invalid_memory_read_request"


def test_underlying_retrieval_contract_still_validates_query() -> None:
    project = ns(MemoryScope.PROJECT, "project_1")
    auth = MemoryReadAuthorization(app_id=APP_ID, readable_namespaces=(project,))

    with pytest.raises(RetrievalContractError) as exc_info:
        authorize_memory_retrieval(
            query="",
            namespaces=(project,),
            authorization=auth,
        )

    assert exc_info.value.code == "invalid_retrieval_contract"
