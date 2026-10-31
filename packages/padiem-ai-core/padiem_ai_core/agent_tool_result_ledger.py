"""#4379: tool results are owned by a ledger, not accumulated by the runtime.

The Agent runtime used to keep every settled tool result in one list and hand a
fresh copy of the whole list to the next step. With the step ceiling removed
that became an unbounded in-process retention plus a repeated full copy per
step.

The runtime now keeps only a small, authorized reference per result. The
payload lives in the ledger: a durable, server-owned store in production and a
process-local store for hosts that have no durable store yet. Nothing is
dropped, truncated or kept only partially: a reference resolves to the exact
original result, including after a resume.

The reference is bound to the run, the step, the ordinal and the tool, and it
carries the payload digest, so a stale or foreign reference can never be
resolved into another run's result.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Protocol

from .contracts import RunStatus, ToolEvent
from .tool_runtime import ToolExecutionResult


@dataclass(frozen=True, slots=True)
class ToolResultRef:
    """An authorized reference to one settled tool result.

    The reference carries no payload. It is the only thing the runtime keeps
    between steps, so the retained memory of a long run scales with the number
    of calls, not with the size of their outputs.
    """

    run_id: str
    step_index: int
    ordinal: int
    tool_id: str
    digest: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_index": self.step_index,
            "ordinal": self.ordinal,
            "tool_id": self.tool_id,
            "digest": self.digest,
        }


class ToolResultLedgerError(RuntimeError):
    """A tool result reference could not be resolved."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def tool_result_digest(result: ToolExecutionResult) -> str:
    """Digest of one settled result, so a reference cannot be swapped."""
    canonical = json.dumps(
        {
            "tool_id": result.tool_id,
            "output": result.output_copy(),
            "event": result.event.to_public_dict(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def encode_tool_result(result: ToolExecutionResult) -> str:
    """Canonical, round-trippable encoding of one settled result."""
    return json.dumps(
        {
            "tool_id": result.tool_id,
            "output": result.output_copy(),
            "event": result.event.to_public_dict(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def decode_tool_result(encoded: str) -> ToolExecutionResult:
    """Rebuild one settled result from its canonical encoding."""
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ToolResultLedgerError(
            "tool_result_payload_invalid", "Stored tool result is unreadable."
        ) from exc
    if not isinstance(payload, dict):
        raise ToolResultLedgerError(
            "tool_result_payload_invalid", "Stored tool result is unreadable."
        )
    event = payload.get("event")
    if not isinstance(event, dict):
        raise ToolResultLedgerError(
            "tool_result_payload_invalid", "Stored tool result is unreadable."
        )
    status = event.get("status")
    try:
        run_status = RunStatus(status)
    except ValueError as exc:
        raise ToolResultLedgerError(
            "tool_result_payload_invalid", "Stored tool result is unreadable."
        ) from exc
    error_class = event.get("error_class")
    return ToolExecutionResult(
        tool_id=str(payload.get("tool_id") or ""),
        output=payload.get("output"),
        event=ToolEvent(
            tool_id=str(payload.get("tool_id") or ""),
            status=run_status,
            duration_ms=event.get("duration_ms"),
            error_class=error_class,
            error_code=event.get("error_code"),
        ),
    )


class ToolResultLedger(Protocol):
    """Durable owner of settled tool results.

    A ledger implementation is server-owned. It never widens who may read a
    result: the reference is bound to one run, and the host decides whether
    that run's owner may resolve it.
    """

    async def append(
        self,
        *,
        run_id: str,
        step_index: int,
        ordinal: int,
        result: ToolExecutionResult,
    ) -> ToolResultRef: ...

    async def resolve(self, ref: ToolResultRef) -> ToolExecutionResult: ...


class InMemoryToolResultLedger:
    """Process-local ledger for hosts that have no durable store yet.

    This is the fallback contract, not the production answer: a durable
    implementation (the Engine's D1 ledger) is what keeps a long run's payload
    out of the Worker. Here the payloads are retained for the lifetime of the
    ledger, and the runtime still keeps only references.
    """

    def __init__(self) -> None:
        self._results: dict[ToolResultRef, str] = {}

    async def append(
        self,
        *,
        run_id: str,
        step_index: int,
        ordinal: int,
        result: ToolExecutionResult,
    ) -> ToolResultRef:
        ref = ToolResultRef(
            run_id=run_id,
            step_index=step_index,
            ordinal=ordinal,
            tool_id=result.tool_id,
            digest=tool_result_digest(result),
        )
        self._results[ref] = encode_tool_result(result)
        return ref

    async def resolve(self, ref: ToolResultRef) -> ToolExecutionResult:
        encoded = self._results.get(ref)
        if encoded is None:
            raise ToolResultLedgerError(
                "tool_result_not_found", "Tool result is not available."
            )
        return decode_tool_result(encoded)

    def adopt(
        self,
        *,
        run_id: str,
        step_index: int,
        results: "tuple[ToolExecutionResult, ...]",
    ) -> tuple[ToolResultRef, ...]:
        """Seed already-known results into this process-local ledger.

        A host that already holds the results (a resumed run restoring its
        history) can adopt them without a durable round trip.
        """
        refs: list[ToolResultRef] = []
        for ordinal, result in enumerate(results):
            ref = ToolResultRef(
                run_id=run_id,
                step_index=step_index,
                ordinal=ordinal,
                tool_id=result.tool_id,
                digest=tool_result_digest(result),
            )
            self._results[ref] = encode_tool_result(result)
            refs.append(ref)
        return tuple(refs)


async def seed_tool_result_refs(
    ledger: ToolResultLedger,
    *,
    run_id: str,
    step_index: int,
    results: "tuple[ToolExecutionResult, ...]",
) -> tuple[ToolResultRef, ...]:
    """Store already-known results in the ledger and return their references."""
    refs: list[ToolResultRef] = []
    for ordinal, result in enumerate(results):
        refs.append(
            await ledger.append(
                run_id=run_id, step_index=step_index, ordinal=ordinal, result=result,
            )
        )
    return tuple(refs)


__all__ = [
    "InMemoryToolResultLedger",
    "seed_tool_result_refs",
    "ToolResultLedger",
    "ToolResultLedgerError",
    "ToolResultRef",
    "decode_tool_result",
    "encode_tool_result",
    "tool_result_digest",
]
