import asyncio

import pytest

from padiem_ai_core.memory import (
    MemoryContractError,
    MemoryNamespace,
    MemoryProvenance,
    MemoryScope,
    MemoryWriteAuthorization,
    MemoryWriteOrigin,
    MemoryWriteRequest,
    authorize_memory_write,
)
from padiem_ai_core.memory_receipt import (
    MemoryWriteDisposition,
    MemoryWriteReceipt,
    persist_authorized_memory_write,
    validate_memory_write_receipt,
)


def prepared_write():
    namespace = MemoryNamespace(
        app_id="b62",
        scope=MemoryScope.PROJECT,
        subject_id="project.alpha",
    )
    candidate = MemoryWriteRequest(
        memory_id="memory_1",
        namespace=namespace,
        content="The architecture keeps provider routing in B14.",
        origin=MemoryWriteOrigin.USER_EXPLICIT,
        provenance=MemoryProvenance(
            source_type="conversation_turn",
            source_ref="conversation:conv_1:turn_8",
        ),
        idempotency_key="idem_1",
    )
    return authorize_memory_write(
        candidate,
        MemoryWriteAuthorization(
            app_id="b62",
            writable_namespaces=(namespace.key,),
        ),
    )


def receipt_for(request, *, disposition=MemoryWriteDisposition.CREATED):
    return MemoryWriteReceipt(
        memory_id=request.request.memory_id,
        namespace_key=request.request.namespace.key,
        idempotency_scope=request.request.idempotency_scope,
        disposition=disposition,
        adapter_id="product_memory_store",
        storage_ref="private:row:123",
    )


def test_created_receipt_matches_authorized_write() -> None:
    request = prepared_write()
    receipt = receipt_for(request)

    assert validate_memory_write_receipt(request, receipt) is receipt


def test_duplicate_receipt_is_valid_when_identity_is_exact() -> None:
    request = prepared_write()
    receipt = receipt_for(request, disposition=MemoryWriteDisposition.DUPLICATE)

    validated = validate_memory_write_receipt(request, receipt)

    assert validated.disposition is MemoryWriteDisposition.DUPLICATE


def test_receipt_with_wrong_memory_id_fails_closed() -> None:
    request = prepared_write()
    receipt = MemoryWriteReceipt(
        memory_id="memory_other",
        namespace_key=request.request.namespace.key,
        idempotency_scope=request.request.idempotency_scope,
        disposition=MemoryWriteDisposition.CREATED,
        adapter_id="product_memory_store",
    )

    with pytest.raises(MemoryContractError) as exc_info:
        validate_memory_write_receipt(request, receipt)

    assert exc_info.value.code == "memory_receipt_mismatch"


def test_receipt_with_wrong_namespace_fails_closed() -> None:
    request = prepared_write()
    receipt = MemoryWriteReceipt(
        memory_id=request.request.memory_id,
        namespace_key="memory:project:b62:project.other",
        idempotency_scope=request.request.idempotency_scope,
        disposition=MemoryWriteDisposition.CREATED,
        adapter_id="product_memory_store",
    )

    with pytest.raises(MemoryContractError) as exc_info:
        validate_memory_write_receipt(request, receipt)

    assert exc_info.value.code == "memory_receipt_mismatch"


def test_receipt_with_wrong_idempotency_scope_fails_closed() -> None:
    request = prepared_write()
    receipt = MemoryWriteReceipt(
        memory_id=request.request.memory_id,
        namespace_key=request.request.namespace.key,
        idempotency_scope="memory:project:b62:project.alpha:idem_other",
        disposition=MemoryWriteDisposition.DUPLICATE,
        adapter_id="product_memory_store",
    )

    with pytest.raises(MemoryContractError) as exc_info:
        validate_memory_write_receipt(request, receipt)

    assert exc_info.value.code == "memory_receipt_mismatch"


def test_public_receipt_redacts_private_storage_reference() -> None:
    request = prepared_write()
    public = receipt_for(request).to_public_dict()

    assert public == {
        "memory_id": "memory_1",
        "namespace": "memory:project:b62:project.alpha",
        "disposition": "created",
        "adapter_id": "product_memory_store",
    }
    assert "storage_ref" not in public
    assert "idempotency_scope" not in public


def test_persist_helper_validates_adapter_receipt() -> None:
    request = prepared_write()

    class Adapter:
        async def write(self, incoming):
            assert incoming is request
            return receipt_for(incoming)

    receipt = asyncio.run(persist_authorized_memory_write(request, Adapter()))

    assert receipt.disposition is MemoryWriteDisposition.CREATED


def test_persist_helper_rejects_confused_adapter_response() -> None:
    request = prepared_write()

    class Adapter:
        async def write(self, incoming):
            return MemoryWriteReceipt(
                memory_id="memory_other",
                namespace_key=incoming.request.namespace.key,
                idempotency_scope=incoming.request.idempotency_scope,
                disposition=MemoryWriteDisposition.CREATED,
                adapter_id="product_memory_store",
            )

    with pytest.raises(MemoryContractError) as exc_info:
        asyncio.run(persist_authorized_memory_write(request, Adapter()))

    assert exc_info.value.code == "memory_receipt_mismatch"
