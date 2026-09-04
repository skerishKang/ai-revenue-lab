"""Network-free Engine Memory Write + Receipt projection tests (#1748 E3B).

The write half mirrors the E3A read posture: request JSON is never memory
write authority. Callers submit only a bounded candidate (ids, namespace
selector, content, idempotency key, optional proposal reference); origin
classification, provenance, authorization, policy and the idempotent storage
adapter come exclusively from a server-side ``EngineMemoryWriteBinding``.
Core is the only gate (``authorize_memory_write`` ->
``persist_authorized_memory_write`` -> receipt validation) and every adapter
call is counted so fail-closed paths are proven at call count zero.

Conformance fixtures stay product-neutral: ``b61-conformance`` resembles a
story-memory app (user saves a reading note), ``b62-conformance`` a chat app
(user saves project memory) and ``b54-conformance`` an agent-result app
(approved Agent result becomes durable memory). No Product source is imported
and LoveBud is excluded.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from padiem_ai_core.memory import (
    MemoryContractError,
    MemoryNamespace,
    MemoryProvenance,
    MemoryScope,
    MemoryWriteAuthorization,
    MemoryWriteOrigin,
    MemoryWritePolicy,
)
from padiem_ai_core.memory_read import MemoryReadAuthorization
from padiem_ai_core.memory_receipt import (
    MemoryWriteDisposition,
    MemoryWriteReceipt,
)
from padiem_ai_core.retrieval import RetrievedItem

from app.memory_service import (
    EngineMemoryBinding,
    EngineMemoryWriteBinding,
    MEMORY_PATH,
    MEMORY_WRITE_PATH,
    MemoryRetrievalEngineService,
    MemoryWriteClassification,
)

APP_ID = "b61-conformance"


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "app_id": APP_ID,
        "memory_id": "mem-1",
        "namespace": {"scope": "user", "subject_id": "u-1"},
        "content": "remember to review chapter four",
        "idempotency_key": "idem-1",
        "trace_id": "trace-1",
    }
    payload.update(overrides)
    return payload


def _default_classifier(
    origin: MemoryWriteOrigin = MemoryWriteOrigin.USER_EXPLICIT,
) -> Any:
    def classify(candidate: Any) -> MemoryWriteClassification:
        return MemoryWriteClassification(
            origin=origin,
            provenance=MemoryProvenance(
                source_type="attested_action",
                source_ref="private-server-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    return classify


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def write(self, prepared: Any) -> MemoryWriteReceipt:
        self.calls.append(prepared)
        request = prepared.request
        return MemoryWriteReceipt(
            memory_id=request.memory_id,
            namespace_key=request.namespace.key,
            idempotency_scope=request.idempotency_scope,
            disposition=MemoryWriteDisposition.CREATED,
            adapter_id="fixture-store",
            storage_ref="private-storage-1",
        )


def _write_binding(
    app_id: str,
    *,
    adapter: Any = None,
    classifier: Any = None,
    policy: MemoryWritePolicy | None = None,
) -> EngineMemoryWriteBinding:
    namespace = MemoryNamespace(app_id=app_id, scope=MemoryScope.USER, subject_id="u-1")
    return EngineMemoryWriteBinding(
        authorization=MemoryWriteAuthorization(
            app_id=app_id,
            writable_namespaces=(namespace.key,),
            approved_model_proposals=("proposal-1",),
        ),
        adapter=adapter or _FakeAdapter(),
        classifier=classifier or _default_classifier(),
        write_policy=policy if policy is not None else MemoryWritePolicy(),
    )


def _read_binding(app_id: str) -> EngineMemoryBinding:
    namespace = MemoryNamespace(app_id=app_id, scope=MemoryScope.USER, subject_id="u-1")
    return EngineMemoryBinding(
        authorization=MemoryReadAuthorization(
            app_id=app_id, readable_namespaces=(namespace,)
        ),
        provider=_ReadProvider(),
    )


class _ReadProvider:
    async def retrieve(self, request: Any) -> Any:
        return (
            RetrievedItem(
                id="r-1",
                namespace=request.namespaces[0],
                source_type="user_note",
                provider="fixture-store",
                source_ref="private-ref-1",
                content="stored preference",
            ),
        )


def _service(
    *,
    bindings: Any = None,
    write_bindings: Any = None,
) -> MemoryRetrievalEngineService:
    return MemoryRetrievalEngineService(
        bindings=bindings or {},
        write_bindings=write_bindings or {},
    )


def _run(
    service: MemoryRetrievalEngineService,
    payload: Any,
    *,
    path: str = MEMORY_WRITE_PATH,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    return asyncio.run(
        service.handle(method="POST", path=path, content_type="application/json", body=body)
    )


# ── Happy authorized paths ──────────────────────────────────────────────────

def test_authorized_user_explicit_write_returns_created_receipt() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["write"]["origin"] == "user_explicit"
    assert result.body["receipt"]["memory_id"] == "mem-1"
    assert result.body["receipt"]["disposition"] == "created"
    assert result.body["receipt"]["adapter_id"] == "fixture-store"
    assert len(adapter.calls) == 1


def test_authorized_product_derived_write_returns_created_receipt() -> None:
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                classifier=_default_classifier(MemoryWriteOrigin.PRODUCT_DERIVED),
            )
        }
    )

    result = _run(service, _candidate())

    assert result.status_code == 200
    assert result.body["write"]["origin"] == "product_derived"


def test_model_proposed_with_independently_approved_proposal_passes() -> None:
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                classifier=_default_classifier(MemoryWriteOrigin.MODEL_PROPOSED),
            )
        }
    )

    result = _run(service, _candidate(proposal_id="proposal-1"))

    assert result.status_code == 200
    assert result.body["write"]["origin"] == "model_proposed"


# ── Model-proposed approval gate (mandatory) ───────────────────────────────

def test_model_proposed_without_approved_proposal_fails_closed_before_adapter() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                adapter=adapter,
                classifier=_default_classifier(MemoryWriteOrigin.MODEL_PROPOSED),
            )
        }
    )

    result = _run(service, _candidate(proposal_id="proposal-unknown"))

    assert result.status_code == 403
    assert result.body["error"]["code"] == "model_memory_approval_required"
    assert len(adapter.calls) == 0


def test_model_proposed_without_proposal_id_fails_closed_before_adapter() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                adapter=adapter,
                classifier=_default_classifier(MemoryWriteOrigin.MODEL_PROPOSED),
            )
        }
    )

    result = _run(service, _candidate(proposal_id=None))

    assert result.status_code == 400
    assert len(adapter.calls) == 0


def test_no_policy_flag_turns_model_text_into_durable_memory() -> None:
    # There is deliberately no write policy that auto-approves model text:
    # even a fully permissive policy cannot write an unapproved proposal.
    adapter = _FakeAdapter()
    permissive = MemoryWritePolicy(
        allowed_scopes=(MemoryScope.PRODUCT, MemoryScope.USER, MemoryScope.PROJECT, MemoryScope.CONVERSATION),
        allowed_origins=(
            MemoryWriteOrigin.USER_EXPLICIT,
            MemoryWriteOrigin.PRODUCT_DERIVED,
            MemoryWriteOrigin.MODEL_PROPOSED,
            MemoryWriteOrigin.IMPORTED,
        ),
    )
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                adapter=adapter,
                classifier=_default_classifier(MemoryWriteOrigin.MODEL_PROPOSED),
                policy=permissive,
            )
        }
    )

    result = _run(service, _candidate(proposal_id=None))

    assert result.status_code == 400
    assert len(adapter.calls) == 0


# ── Caller authority injection is rejected on the wire ─────────────────────

def test_caller_cannot_self_approve_proposal() -> None:
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                classifier=_default_classifier(MemoryWriteOrigin.MODEL_PROPOSED),
            )
        }
    )

    result = _run(
        service,
        _candidate(proposal_id="proposal-1", approved=True),
    )

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


def test_caller_cannot_self_select_trusted_origin() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(service, _candidate(origin="user_explicit"))

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


@pytest.mark.parametrize(
    "field",
    [
        "authorization",
        "allowed_scopes",
        "approved",
        "approved_model_proposals",
        "adapter",
        "adapter_id",
        "storage_ref",
        "storage_url",
        "endpoint",
        "database",
        "provider",
        "credential",
        "source_ref",
        "policy",
        "writable_namespaces",
        "provenance",
        "memory_write_origin",
    ],
)
def test_caller_cannot_inject_authority_field(field: str) -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate(**{field: "anything"}))

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"
    assert len(adapter.calls) == 0


def test_namespace_object_rejects_authority_fields() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(
        service,
        _candidate(namespace={"scope": "user", "subject_id": "u-1", "adapter": "x"}),
    )

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


# ── App / subject / namespace authority ────────────────────────────────────

def test_cross_app_write_rejected_before_adapter() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate(app_id="b62-conformance"))

    assert result.status_code == 503
    assert result.body["error"]["code"] == "memory_write_binding_unavailable"
    assert len(adapter.calls) == 0


def test_cross_subject_write_rejected_before_adapter() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(
        service,
        _candidate(namespace={"scope": "user", "subject_id": "u-2"}),
    )

    assert result.status_code == 403
    assert result.body["error"]["code"] == "memory_namespace_not_authorized"
    assert len(adapter.calls) == 0


def test_product_scope_with_wrong_subject_rejected() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(
        service,
        _candidate(namespace={"scope": "product", "subject_id": "u-1"}),
    )

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


def test_invalid_scope_string_rejected() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(
        service,
        _candidate(namespace={"scope": "global", "subject_id": "u-1"}),
    )

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


def test_policy_disallowed_scope_rejected_before_adapter() -> None:
    adapter = _FakeAdapter()
    policy = MemoryWritePolicy(allowed_scopes=(MemoryScope.PROJECT,))
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter, policy=policy)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 403
    assert result.body["error"]["code"] == "memory_scope_not_allowed"
    assert len(adapter.calls) == 0


def test_policy_disallowed_origin_rejected_before_adapter() -> None:
    adapter = _FakeAdapter()
    policy = MemoryWritePolicy(allowed_origins=(MemoryWriteOrigin.USER_EXPLICIT,))
    service = _service(
        write_bindings={
            APP_ID: _write_binding(
                APP_ID,
                adapter=adapter,
                classifier=_default_classifier(MemoryWriteOrigin.PRODUCT_DERIVED),
                policy=policy,
            )
        }
    )

    result = _run(service, _candidate())

    assert result.status_code == 403
    assert result.body["error"]["code"] == "memory_origin_not_allowed"
    assert len(adapter.calls) == 0


def test_namespace_widening_rejected() -> None:
    # Authorization owns exact writable_namespaces; a different namespace key
    # on the wire is a reject, never a widen.
    adapter = _FakeAdapter()
    binding = EngineMemoryWriteBinding(
        authorization=MemoryWriteAuthorization(
            app_id=APP_ID,
            writable_namespaces=("memory:user:b61-conformance:u-1",),
        ),
        adapter=adapter,
        classifier=_default_classifier(),
    )
    service = _service(write_bindings={APP_ID: binding})

    result = _run(
        service,
        _candidate(namespace={"scope": "project", "subject_id": "p-1"}),
    )

    assert result.status_code == 403
    assert result.body["error"]["code"] == "memory_namespace_not_authorized"
    assert len(adapter.calls) == 0


# ── Budgets / wire bounds ──────────────────────────────────────────────────

def test_oversized_content_rejected_before_adapter() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate(content="x" * 20_000))

    assert result.status_code == 422
    assert result.body["error"]["code"] == "memory_budget_exceeded"
    assert len(adapter.calls) == 0


def test_oversized_body_rejected() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(service, _candidate(content="x" * 40_000))

    assert result.status_code == 413
    assert result.body["error"]["code"] == "request_too_large"


def test_missing_required_write_field_rejected() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(service, _candidate(memory_id=None))

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_memory_write_request"


# ── Adapter faults and receipt validation ──────────────────────────────────

def test_adapter_exception_fails_closed() -> None:
    adapter = _FakeAdapter()

    async def failing_write(prepared: Any) -> MemoryWriteReceipt:
        adapter.calls.append(prepared)
        raise RuntimeError("store offline")

    adapter.write = failing_write  # type: ignore[method-assign]
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 503
    assert result.body["error"]["code"] == "memory_write_provider_unavailable"
    assert result.body["error"]["retryable"] is True


def test_bad_receipt_wrong_memory_id_fails_closed() -> None:
    adapter = _FakeAdapter()

    async def wrong_id(prepared: Any) -> MemoryWriteReceipt:
        adapter.calls.append(prepared)
        request = prepared.request
        return MemoryWriteReceipt(
            memory_id="other-memory",
            namespace_key=request.namespace.key,
            idempotency_scope=request.idempotency_scope,
            disposition=MemoryWriteDisposition.CREATED,
            adapter_id="fixture-store",
        )

    adapter.write = wrong_id  # type: ignore[method-assign]
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 502
    assert result.body["error"]["code"] == "memory_receipt_mismatch"


def test_bad_receipt_wrong_namespace_fails_closed() -> None:
    adapter = _FakeAdapter()

    async def wrong_namespace(prepared: Any) -> MemoryWriteReceipt:
        adapter.calls.append(prepared)
        request = prepared.request
        return MemoryWriteReceipt(
            memory_id=request.memory_id,
            namespace_key="memory:user:other-app:u-1",
            idempotency_scope=request.idempotency_scope,
            disposition=MemoryWriteDisposition.CREATED,
            adapter_id="fixture-store",
        )

    adapter.write = wrong_namespace  # type: ignore[method-assign]
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 502
    assert result.body["error"]["code"] == "memory_receipt_mismatch"


def test_bad_receipt_wrong_idempotency_scope_fails_closed() -> None:
    adapter = _FakeAdapter()

    async def wrong_scope(prepared: Any) -> MemoryWriteReceipt:
        adapter.calls.append(prepared)
        request = prepared.request
        return MemoryWriteReceipt(
            memory_id=request.memory_id,
            namespace_key=request.namespace.key,
            idempotency_scope="memory:user:b61-conformance:u-1:other-key",
            disposition=MemoryWriteDisposition.CREATED,
            adapter_id="fixture-store",
        )

    adapter.write = wrong_scope  # type: ignore[method-assign]
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 502
    assert result.body["error"]["code"] == "memory_receipt_mismatch"


def test_receipt_wrong_type_fails_closed() -> None:
    adapter = _FakeAdapter()

    async def not_a_receipt(prepared: Any) -> Any:
        adapter.calls.append(prepared)
        return "not a receipt"

    adapter.write = not_a_receipt  # type: ignore[method-assign]
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 502
    assert result.body["error"]["code"] == "invalid_memory_receipt"


# ── Idempotency ────────────────────────────────────────────────────────────

def test_duplicate_write_returns_safe_duplicate_receipt() -> None:
    class _DedupAdapter:
        def __init__(self) -> None:
            self.calls: list[Any] = []
            self.seen: set[str] = set()

        async def write(self, prepared: Any) -> MemoryWriteReceipt:
            self.calls.append(prepared)
            request = prepared.request
            if request.idempotency_scope in self.seen:
                disposition = MemoryWriteDisposition.DUPLICATE
            else:
                self.seen.add(request.idempotency_scope)
                disposition = MemoryWriteDisposition.CREATED
            return MemoryWriteReceipt(
                memory_id=request.memory_id,
                namespace_key=request.namespace.key,
                idempotency_scope=request.idempotency_scope,
                disposition=disposition,
                adapter_id="fixture-store",
                storage_ref="private-storage-1",
            )

    adapter = _DedupAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    first = _run(service, _candidate())
    second = _run(service, _candidate())

    assert first.status_code == 200
    assert first.body["receipt"]["disposition"] == "created"
    assert second.status_code == 200
    assert second.body["receipt"]["disposition"] == "duplicate"
    # The Engine never double-persists on its own; it relies on the Core
    # idempotency contract and projects the adapter's safe duplicate verdict.
    assert len(adapter.calls) == 2


# ── Provenance privacy ─────────────────────────────────────────────────────

def test_private_provenance_source_ref_and_storage_ref_never_projected() -> None:
    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter)}
    )

    result = _run(service, _candidate())

    assert result.status_code == 200
    assert adapter.calls[0].request.provenance.source_ref == "private-server-ref-1"
    serialized = json.dumps(result.body)
    assert "private-server-ref-1" not in serialized
    assert "private-storage-1" not in serialized
    assert "chapter four" not in serialized
    assert set(result.body["receipt"]) == {"memory_id", "namespace", "disposition", "adapter_id"}


# ── Read / write authority separation ──────────────────────────────────────

def test_read_only_binding_cannot_write() -> None:
    service = _service(bindings={APP_ID: _read_binding(APP_ID)})

    result = _run(service, _candidate())

    assert result.status_code == 503
    assert result.body["error"]["code"] == "memory_write_binding_unavailable"


def test_write_binding_does_not_widen_read_authorization() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = _run(
        service,
        {"app_id": APP_ID, "query": "preferences?", "namespaces": [{"scope": "user", "subject_id": "u-1"}]},
        path=MEMORY_PATH,
    )

    assert result.status_code == 503
    assert result.body["error"]["code"] == "memory_binding_unavailable"


def test_no_binding_write_route_fails_closed() -> None:
    result = _run(_service(), _candidate())

    assert result.status_code == 503
    assert result.body["error"]["code"] == "memory_write_binding_unavailable"


def test_read_regression_with_write_bound_service() -> None:
    service = _service(
        bindings={APP_ID: _read_binding(APP_ID)},
        write_bindings={APP_ID: _write_binding(APP_ID)},
    )

    read = _run(
        service,
        {"app_id": APP_ID, "query": "preferences?", "namespaces": [{"scope": "user", "subject_id": "u-1"}]},
        path=MEMORY_PATH,
    )
    write = _run(service, _candidate())

    assert read.status_code == 200
    assert read.body["retrieval"]["item_count"] == 1
    assert "stored preference" not in json.dumps(read.body)
    assert write.status_code == 200
    assert write.body["write"]["origin"] == "user_explicit"


# ── Trusted origin classification (wire never picks origin) ────────────────

def test_trusted_classifier_attests_origin_from_server_state() -> None:
    def classify(candidate: Any) -> MemoryWriteClassification:
        if candidate.idempotency_key.startswith("attest-user:"):
            origin = MemoryWriteOrigin.USER_EXPLICIT
        elif candidate.idempotency_key.startswith("attest-product:"):
            origin = MemoryWriteOrigin.PRODUCT_DERIVED
        elif candidate.idempotency_key.startswith("attest-model:") and candidate.proposal_id == "proposal-1":
            origin = MemoryWriteOrigin.MODEL_PROPOSED
        else:
            raise MemoryContractError(
                "user_action_not_attested",
                "the write action is not attested by trusted server state",
            )
        return MemoryWriteClassification(
            origin=origin,
            provenance=MemoryProvenance(
                source_type="attested_action",
                source_ref="private-server-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    adapter = _FakeAdapter()
    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, adapter=adapter, classifier=classify)}
    )

    explicit = _run(service, _candidate(idempotency_key="attest-user:1"))
    derived = _run(service, _candidate(idempotency_key="attest-product:1"))
    proposed = _run(
        service,
        _candidate(idempotency_key="attest-model:1", proposal_id="proposal-1"),
    )
    unattested = _run(service, _candidate(idempotency_key="random-key"))

    assert explicit.body["write"]["origin"] == "user_explicit"
    assert derived.body["write"]["origin"] == "product_derived"
    assert proposed.body["write"]["origin"] == "model_proposed"
    assert unattested.status_code == 400
    assert unattested.body["error"]["code"] == "user_action_not_attested"
    assert len(adapter.calls) == 3


# ── Reference conformance fixtures (§19) ───────────────────────────────────

def test_b61_conformance_fixture_user_saves_reading_note() -> None:
    def classify(candidate: Any) -> MemoryWriteClassification:
        return MemoryWriteClassification(
            origin=MemoryWriteOrigin.USER_EXPLICIT,
            provenance=MemoryProvenance(
                source_type="saved_reading_note",
                source_ref="private-note-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, classifier=classify)}
    )

    result = _run(service, _candidate(memory_id="note-1", idempotency_key="save-note:1"))

    assert result.status_code == 200
    assert result.body["write"]["origin"] == "user_explicit"
    assert result.body["write"]["provenance"]["source_type"] == "saved_reading_note"
    assert "private-note-ref-1" not in json.dumps(result.body)


def test_b62_conformance_fixture_user_saves_project_memory() -> None:
    def classify(candidate: Any) -> MemoryWriteClassification:
        return MemoryWriteClassification(
            origin=MemoryWriteOrigin.USER_EXPLICIT,
            provenance=MemoryProvenance(
                source_type="saved_project_memory",
                source_ref="private-project-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, classifier=classify)}
    )

    result = _run(service, _candidate(memory_id="proj-mem-1", idempotency_key="save-project:1"))

    assert result.status_code == 200
    assert result.body["write"]["origin"] == "user_explicit"
    assert result.body["write"]["provenance"]["source_type"] == "saved_project_memory"
    assert "private-project-ref-1" not in json.dumps(result.body)


def test_b54_conformance_fixture_approved_agent_result_becomes_memory() -> None:
    def classify(candidate: Any) -> MemoryWriteClassification:
        return MemoryWriteClassification(
            origin=MemoryWriteOrigin.MODEL_PROPOSED,
            provenance=MemoryProvenance(
                source_type="agent_result_workspace_memory",
                source_ref="private-workspace-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    service = _service(
        write_bindings={APP_ID: _write_binding(APP_ID, classifier=classify)}
    )

    result = _run(
        service,
        _candidate(memory_id="agent-mem-1", idempotency_key="agent-result:1", proposal_id="proposal-1"),
    )

    assert result.status_code == 200
    assert result.body["write"]["origin"] == "model_proposed"
    assert result.body["write"]["provenance"]["source_type"] == "agent_result_workspace_memory"


# ── Binding registry guards ────────────────────────────────────────────────

def test_write_binding_must_be_registered_under_its_own_authorized_app() -> None:
    namespace = MemoryNamespace(app_id="b62-conformance", scope=MemoryScope.USER, subject_id="u-1")
    wrong = EngineMemoryWriteBinding(
        authorization=MemoryWriteAuthorization(
            app_id="b62-conformance",
            writable_namespaces=(namespace.key,),
        ),
        adapter=_FakeAdapter(),
        classifier=_default_classifier(),
    )

    with pytest.raises(MemoryContractError) as excinfo:
        _service(write_bindings={APP_ID: wrong})

    assert excinfo.value.code == "memory_app_mismatch"


# ── HTTP envelope ──────────────────────────────────────────────────────────

def test_write_route_rejects_non_post_method() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = asyncio.run(
        service.handle(method="GET", path=MEMORY_WRITE_PATH, content_type="application/json", body=b"{}")
    )

    assert result.status_code == 405
    assert result.body["error"]["code"] == "method_not_allowed"


def test_write_route_rejects_non_json_content_type() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = asyncio.run(
        service.handle(method="POST", path=MEMORY_WRITE_PATH, content_type="text/plain", body=b"{}")
    )

    assert result.status_code == 415
    assert result.body["error"]["code"] == "unsupported_media_type"


def test_write_route_rejects_invalid_json() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = asyncio.run(
        service.handle(method="POST", path=MEMORY_WRITE_PATH, content_type="application/json", body=b"{")
    )

    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_json"


def test_write_route_unknown_path_is_not_found() -> None:
    service = _service(write_bindings={APP_ID: _write_binding(APP_ID)})

    result = asyncio.run(
        service.handle(method="POST", path="/internal/v1/memory/other", content_type="application/json", body=b"{}")
    )

    assert result.status_code == 404
    assert result.body["error"]["code"] == "not_found"
