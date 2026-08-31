"""Idempotent storage receipt contract for authorized P01 memory writes.

The Memory/RAG layer carries an idempotency key, but Core does not own the
persistence backend that enforces it. This module defines the evidence a trusted
storage adapter must return so Core/product adapters can detect mismatched or
confused-deputy responses without exposing private storage references.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol

from .memory import MemoryContractError, PreparedMemoryWrite


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_STORAGE_REF_CHARS = 512


class MemoryWriteDisposition(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise MemoryContractError(
            "invalid_memory_receipt",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _bounded_optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryContractError(
            "invalid_memory_receipt",
            "storage_ref must be a non-empty string or None",
        )
    result = value.strip()
    if len(result) > MAX_STORAGE_REF_CHARS:
        raise MemoryContractError(
            "invalid_memory_receipt",
            "storage_ref exceeds the bounded receipt limit",
        )
    return result


@dataclass(frozen=True, slots=True)
class MemoryWriteReceipt:
    """Adapter assertion about one idempotently persisted memory write."""

    memory_id: str
    namespace_key: str
    idempotency_scope: str
    disposition: MemoryWriteDisposition
    adapter_id: str
    storage_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_id", _identifier("memory_id", self.memory_id))
        object.__setattr__(
            self,
            "namespace_key",
            _identifier("namespace_key", self.namespace_key),
        )
        if not self.namespace_key.startswith("memory:"):
            raise MemoryContractError(
                "invalid_memory_receipt",
                "namespace_key must be a canonical memory namespace",
            )
        if not isinstance(self.idempotency_scope, str) or not self.idempotency_scope:
            raise MemoryContractError(
                "invalid_memory_receipt",
                "idempotency_scope must be a non-empty string",
            )
        if len(self.idempotency_scope) > 320:
            raise MemoryContractError(
                "invalid_memory_receipt",
                "idempotency_scope exceeds the bounded receipt limit",
            )
        if not isinstance(self.disposition, MemoryWriteDisposition):
            raise MemoryContractError(
                "invalid_memory_receipt",
                "disposition must be MemoryWriteDisposition",
            )
        object.__setattr__(self, "adapter_id", _identifier("adapter_id", self.adapter_id))
        object.__setattr__(self, "storage_ref", _bounded_optional_ref(self.storage_ref))

    def to_public_dict(self) -> dict[str, str]:
        """Return non-sensitive receipt metadata; storage_ref stays private."""

        return {
            "memory_id": self.memory_id,
            "namespace": self.namespace_key,
            "disposition": self.disposition.value,
            "adapter_id": self.adapter_id,
        }


class IdempotentMemoryWriteAdapter(Protocol):
    """Product-owned adapter that proves idempotent persistence with a receipt."""

    async def write(self, request: PreparedMemoryWrite) -> MemoryWriteReceipt: ...


def validate_memory_write_receipt(
    request: PreparedMemoryWrite,
    receipt: MemoryWriteReceipt,
) -> MemoryWriteReceipt:
    """Fail closed if storage evidence does not correspond to the authorized write."""

    if not isinstance(request, PreparedMemoryWrite):
        raise MemoryContractError(
            "invalid_memory_contract",
            "request must be PreparedMemoryWrite",
        )
    if not isinstance(receipt, MemoryWriteReceipt):
        raise MemoryContractError(
            "invalid_memory_receipt",
            "receipt must be MemoryWriteReceipt",
        )

    expected = request.request
    if receipt.memory_id != expected.memory_id:
        raise MemoryContractError(
            "memory_receipt_mismatch",
            "receipt memory_id does not match the authorized write",
        )
    if receipt.namespace_key != expected.namespace.key:
        raise MemoryContractError(
            "memory_receipt_mismatch",
            "receipt namespace does not match the authorized write",
        )
    if receipt.idempotency_scope != expected.idempotency_scope:
        raise MemoryContractError(
            "memory_receipt_mismatch",
            "receipt idempotency scope does not match the authorized write",
        )

    return receipt


async def persist_authorized_memory_write(
    request: PreparedMemoryWrite,
    adapter: IdempotentMemoryWriteAdapter,
) -> MemoryWriteReceipt:
    """Persist through a product-owned adapter and verify its receipt."""

    if not isinstance(request, PreparedMemoryWrite):
        raise MemoryContractError(
            "invalid_memory_contract",
            "request must be PreparedMemoryWrite",
        )
    receipt = await adapter.write(request)
    return validate_memory_write_receipt(request, receipt)
