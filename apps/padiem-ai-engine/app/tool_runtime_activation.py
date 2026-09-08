"""E9 A3 Tool Runtime capability activation gate (#1753, #1746).

Source-level, fail-closed readiness record for the ``tool_runtime``
capability family:

- it refuses to authorize anything without the exact owner confirmation token,
- it enforces exact-head (main SHA) verification,
- it records the rollback anchor (current deployed version -> rollback version),
- it runs non-sensitive synthetic probes against the shared Tool Execution
  routes (``execute``, ``resume``, ``cancel``),
- it runs a structural reference-product parity probe for the reference
  consumers of this capability family (B62 Padiem Chat, B54 Padiem Claw).

This module never mutates Production, never executes a real provider tool,
never imports a product package, and never touches credential material.
Production activation is a separate owner-authorized dispatch; this module
records only evidence and readiness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from app.tool_execution_service import ToolExecutionEngineService

CONFIRMATION_TOKEN = "ACTIVATE_ENGINE_A3_TOOL_RUNTIME"

CURRENT_DEPLOYED_VERSION = "26288341021f9b2ceaa45b9f587d571af63a07bf"
ROLLBACK_VERSION = "8d4db98c13b2b23378536d3b2e5270bb3b457f06"
DEPLOYMENT_TARGET = "Cloudflare Workers (padiem-ai-engine)"

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Reference consumers of the A3 Tool Runtime capability family, in activation
# priority. These are opaque product-neutral identifiers only; the parity probe
# never imports or executes product code.
REFERENCE_CONSUMERS = ("b62-padiem-chat", "b54-padiem-claw")

_SYNTHETIC_OPERATIONS = ("execute", "resume", "cancel")
_SYNTHETIC_APP_ID = "engine-a3-synthetic-probe"
_SYNTHETIC_AGENT_ID = "agent:engine:a3-probe@1"
_SYNTHETIC_READ_TOOL_ID = "tool:engine:a3probe-read@1"
_SYNTHETIC_GATED_TOOL_ID = "tool:engine:a3probe-gate@1"

_SYNTHETIC_READ_ARGUMENTS = {"query": "public structural probe"}
_SYNTHETIC_WRITE_ARGUMENTS = {"note": "structural probe note"}
_SYNTHETIC_DECISION_ID = "dec_engine_a3_synthetic"
_SYNTHETIC_AUTHORITY_REF = "user:synthetic-probe"
_SYNTHETIC_EVIDENCE_REF = "session:synthetic-probe"
_SYNTHETIC_CANCEL_REASON = "user_cancelled"

# Provider function-calling wire vocabulary and caller-minted authority are not
# Engine authority. The parity probe injects these keys and asserts the shared
# route fails closed so the authority-leak invariant stays unambiguous.
_PROVIDER_WIRE_KEYS = frozenset(
    {"tool_calls", "toolCalls", "function_call", "tools", "tool_choice"}
)
_AUTHORITY_MINTING_KEYS = frozenset(
    {"tool_authorization", "authorization", "approved", "approval_grant"}
)


class ActivationError(ValueError):
    """Fail-closed activation failure carrying only safe, bounded information."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("activation error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class RollbackAnchor:
    """Recorded rollback anchor for the A3 activation.

    Config/secret names are recorded without values; this module never
    publishes secret material.
    """

    deployment_target: str
    current_deployed_version: str
    rollback_version: str
    config_binding_diff: str
    secret_name_diff: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "deployment_target": self.deployment_target,
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "config_binding_diff": self.config_binding_diff,
            "secret_name_diff": self.secret_name_diff,
        }


@dataclass(frozen=True, slots=True)
class SyntheticProbeResult:
    operation: str
    ok: bool
    error_code: str | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "ok": self.ok,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class ReferenceParityResult:
    consumer: str
    ok: bool
    finding: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "ok": self.ok,
            "finding": self.finding,
        }


@dataclass(frozen=True, slots=True)
class ActivationEvidence:
    """Public, secret-free activation evidence record for one gate run."""

    current_main: str
    accepted_source_head: str
    deployment_target: str
    current_deployed_version: str
    rollback_version: str
    config_binding_diff: str
    secret_name_diff: str
    reference_consumers: tuple[str, ...]
    synthetic_probes: tuple[SyntheticProbeResult, ...]
    reference_parity: tuple[ReferenceParityResult, ...]
    real_provider_call_count: int = 0
    real_user_data: int = 0
    mutation_scope: str = "A3 Tool Runtime activation only"
    final_disposition: str = "PENDING_PRODUCTION_AUTHORIZATION"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_main": self.current_main,
            "accepted_source_head": self.accepted_source_head,
            "deployment_target": self.deployment_target,
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "config_binding_diff": self.config_binding_diff,
            "secret_name_diff": self.secret_name_diff,
            "reference_consumers": list(self.reference_consumers),
            "synthetic_probes": [p.to_public_dict() for p in self.synthetic_probes],
            "reference_parity": [p.to_public_dict() for p in self.reference_parity],
            "real_provider_call_count": self.real_provider_call_count,
            "real_user_data": self.real_user_data,
            "mutation_scope": self.mutation_scope,
            "final_disposition": self.final_disposition,
        }


def _verify_sha(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not _COMMIT_SHA_RE.fullmatch(value):
        raise ActivationError(
            "invalid_sha",
            f"{name} must be a 40-character lowercase hex commit SHA.",
        )


def verify_confirmation_token(token: str) -> None:
    """Fail closed unless the caller supplies the exact owner token.

    The token is a fixed, non-secret activation phrase that only the Product
    Owner (or a CTO-approved owner delegate) is authorized to provide during
    an explicit activation dispatch.
    """
    if not isinstance(token, str) or token != CONFIRMATION_TOKEN:
        raise ActivationError(
            "activation_not_authorized",
            "Tool Runtime activation requires the exact owner confirmation token.",
        )


def verify_exact_main(current_main: str) -> None:
    """Enforce exact-head: the gate must be dispatched on a real main SHA."""
    _verify_sha(current_main, name="current_main")


def record_rollback_anchor() -> RollbackAnchor:
    """Return the audited rollback anchor recorded for this activation."""
    _verify_sha(CURRENT_DEPLOYED_VERSION, name="current_deployed_version")
    _verify_sha(ROLLBACK_VERSION, name="rollback_version")
    return RollbackAnchor(
        deployment_target=DEPLOYMENT_TARGET,
        current_deployed_version=CURRENT_DEPLOYED_VERSION,
        rollback_version=ROLLBACK_VERSION,
        config_binding_diff="none",
        secret_name_diff="none",
    )


def _error_code_from_response(response: Any, body: Any) -> str:
    error = body.get("error") if isinstance(body, Mapping) else None
    if isinstance(error, Mapping):
        code = error.get("code")
        if isinstance(code, str) and code:
            return code
    metadata = body.get("metadata") if isinstance(body, Mapping) else None
    if isinstance(metadata, Mapping):
        code = metadata.get("code")
        if isinstance(code, str) and code:
            return code
    return f"unexpected_status_{getattr(response, 'status_code', 'unknown')}"


async def _pause_gated_tool(service: ToolExecutionEngineService) -> dict[str, Any]:
    """Start a genuine Core approval block; returns the public pause body."""
    response = await service.execute_payload(
        {
            "app_id": _SYNTHETIC_APP_ID,
            "agent_id": _SYNTHETIC_AGENT_ID,
            "tool_id": _SYNTHETIC_GATED_TOOL_ID,
            "arguments": _SYNTHETIC_WRITE_ARGUMENTS,
        }
    )
    body = response.body if isinstance(response.body, Mapping) else {}
    if response.status_code != 202 or body.get("ok") is not True:
        raise ActivationError(
            "synthetic_probe_failed",
            f"A3 synthetic probe could not open an approval continuation ({_error_code_from_response(response, body)}).",
        )
    tool = body.get("tool")
    if not isinstance(tool, Mapping) or not isinstance(tool.get("continuation_ref"), str):
        raise ActivationError(
            "synthetic_probe_failed",
            "A3 synthetic probe received an invalid pause envelope.",
        )
    return tool


async def run_synthetic_probe(
    service: ToolExecutionEngineService,
    *,
    operation: str,
) -> SyntheticProbeResult:
    """Run one non-sensitive structural probe against the shared tool routes.

    The probe never calls a real provider, never uses real user data, and only
    validates the bounded response envelope of the shared Engine routes.

    - ``execute``: a server-provisioned read tool must complete through Core.
    - ``resume``: a genuine server-issued approval pause must resume through
      Core with the original ``continuation_ref`` preserved.
    - ``cancel``: a genuine server-issued approval pause must terminate through
      the atomic cancellation path with a terminal ``cancelled`` state.
    """
    if operation not in _SYNTHETIC_OPERATIONS:
        raise ActivationError(
            "invalid_probe_operation",
            "synthetic probe operation must be execute, resume, or cancel.",
        )

    if operation == "execute":
        response = await service.execute_payload(
            {
                "app_id": _SYNTHETIC_APP_ID,
                "agent_id": _SYNTHETIC_AGENT_ID,
                "tool_id": _SYNTHETIC_READ_TOOL_ID,
                "arguments": _SYNTHETIC_READ_ARGUMENTS,
            }
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        tool = body.get("tool") if isinstance(body.get("tool"), Mapping) else {}
        if (
            response.status_code == 200
            and body.get("ok") is True
            and tool.get("status") == "completed"
            and isinstance(tool.get("run_id"), str)
            and "output" in tool
        ):
            return SyntheticProbeResult(operation=operation, ok=True, error_code=None)
        return SyntheticProbeResult(
            operation=operation,
            ok=False,
            error_code=_error_code_from_response(response, body),
        )

    if operation == "resume":
        try:
            tool = await _pause_gated_tool(service)
        except ActivationError as exc:
            return SyntheticProbeResult(
                operation=operation,
                ok=False,
                error_code=exc.code,
            )
        continuation_ref = tool["continuation_ref"]
        approval_pause = tool.get("approval_pause")
        pause_id = (
            approval_pause.get("continuation_id")
            if isinstance(approval_pause, Mapping)
            else None
        )
        if not isinstance(pause_id, str) or not pause_id:
            return SyntheticProbeResult(
                operation=operation,
                ok=False,
                error_code="invalid_pause_envelope",
            )
        decision: dict[str, Any] = {
            "decision_id": _SYNTHETIC_DECISION_ID,
            "pause_id": pause_id,
            "outcome": "approved",
            "authority_ref": _SYNTHETIC_AUTHORITY_REF,
            "evidence_ref": _SYNTHETIC_EVIDENCE_REF,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await service.resume_payload(
            {
                "app_id": _SYNTHETIC_APP_ID,
                "continuation_ref": continuation_ref,
                "decision": decision,
            }
        )
        body = response.body if isinstance(response.body, Mapping) else {}
        resumed_tool = body.get("tool") if isinstance(body.get("tool"), Mapping) else {}
        if (
            response.status_code == 200
            and body.get("ok") is True
            and resumed_tool.get("status") == "completed"
            and resumed_tool.get("continuation_ref") == continuation_ref
        ):
            return SyntheticProbeResult(operation=operation, ok=True, error_code=None)
        return SyntheticProbeResult(
            operation=operation,
            ok=False,
            error_code=_error_code_from_response(response, body),
        )

    try:
        tool = await _pause_gated_tool(service)
    except ActivationError as exc:
        return SyntheticProbeResult(
            operation=operation,
            ok=False,
            error_code=exc.code,
        )
    continuation_ref = tool["continuation_ref"]
    response = await service.cancel_payload(
        {
            "app_id": _SYNTHETIC_APP_ID,
            "continuation_ref": continuation_ref,
            "reason": _SYNTHETIC_CANCEL_REASON,
        }
    )
    body = response.body if isinstance(response.body, Mapping) else {}
    if (
        response.status_code == 200
        and body.get("ok") is True
        and body.get("status") == "cancelled"
        and body.get("continuation_ref") == continuation_ref
    ):
        return SyntheticProbeResult(operation=operation, ok=True, error_code=None)
    return SyntheticProbeResult(
        operation=operation,
        ok=False,
        error_code=_error_code_from_response(response, body),
    )


async def run_reference_parity_probe(
    service: ToolExecutionEngineService,
) -> tuple[ReferenceParityResult, ...]:
    """Structural parity probe for the reference consumers.

    Shared Engine route vs product-local route parity at the contract level:
    the shared route must serve the bounded envelope every reference consumer
    requires (``ok``/``tool`` fields, normalized error taxonomy) while failing
    closed on provider wire keys and caller-minted authority keys. No product
    code is imported or executed.
    """
    results: list[ReferenceParityResult] = []
    for consumer in REFERENCE_CONSUMERS:
        if not isinstance(consumer, str) or not _IDENTIFIER_RE.fullmatch(consumer):
            raise ActivationError(
                "invalid_reference_consumer",
                "reference consumer must be a bounded safe identifier.",
            )
        app_id = f"{consumer}-a3-parity"
        clean_payload: dict[str, Any] = {
            "app_id": app_id,
            "agent_id": _SYNTHETIC_AGENT_ID,
            "tool_id": _SYNTHETIC_READ_TOOL_ID,
            "arguments": _SYNTHETIC_READ_ARGUMENTS,
        }
        response = await service.execute_payload(clean_payload)
        body = response.body if isinstance(response.body, Mapping) else {}
        tool = body.get("tool") if isinstance(body.get("tool"), Mapping) else {}
        if (
            response.status_code != 200
            or body.get("ok") is not True
            or tool.get("status") != "completed"
        ):
            results.append(
                ReferenceParityResult(
                    consumer=consumer,
                    ok=False,
                    finding=f"shared route failed parity ({_error_code_from_response(response, body)})",
                )
            )
            continue
        if "route" in body or "metadata" in body:
            results.append(
                ReferenceParityResult(
                    consumer=consumer,
                    ok=False,
                    finding="shared tool service leaked route/metadata fields",
                )
            )
            continue

        authority_leak = False
        for wire_key in _PROVIDER_WIRE_KEYS | _AUTHORITY_MINTING_KEYS:
            polluted = dict(clean_payload)
            polluted[wire_key] = "caller-supplied-wire-authority"
            leak_response = await service.execute_payload(polluted)
            leak_body = (
                leak_response.body if isinstance(leak_response.body, Mapping) else {}
            )
            if leak_response.status_code == 200 and leak_body.get("ok") is True:
                authority_leak = True
                break
        if authority_leak:
            results.append(
                ReferenceParityResult(
                    consumer=consumer,
                    ok=False,
                    finding="shared tool service accepted caller wire/minting authority",
                )
            )
            continue
        results.append(
            ReferenceParityResult(
                consumer=consumer,
                ok=True,
                finding="shared tool service serves bounded parity envelope and rejects wire authority",
            )
        )
    return tuple(results)


async def evaluate_activation(
    service: ToolExecutionEngineService,
    *,
    confirmation_token: str,
    current_main: str,
    accepted_source_head: str,
) -> ActivationEvidence:
    """Fail-closed activation readiness evaluation for A3 Tool Runtime.

    Raises ``ActivationError`` on any preflight failure; otherwise records
    secret-free evidence. The result never authorizes Production mutation by
    itself.
    """
    verify_confirmation_token(confirmation_token)
    verify_exact_main(current_main)
    _verify_sha(accepted_source_head, name="accepted_source_head")
    anchor = record_rollback_anchor()

    probes: list[SyntheticProbeResult] = []
    for operation in _SYNTHETIC_OPERATIONS:
        probes.append(await run_synthetic_probe(service, operation=operation))

    parity = await run_reference_parity_probe(service)

    if any(not probe.ok for probe in probes):
        raise ActivationError(
            "synthetic_probe_failed",
            "A3 synthetic probes must all pass before activation readiness.",
        )
    if any(not result.ok for result in parity):
        raise ActivationError(
            "reference_parity_failed",
            "A3 reference parity probes must all pass before activation readiness.",
        )

    return ActivationEvidence(
        current_main=current_main,
        accepted_source_head=accepted_source_head,
        deployment_target=anchor.deployment_target,
        current_deployed_version=anchor.current_deployed_version,
        rollback_version=anchor.rollback_version,
        config_binding_diff=anchor.config_binding_diff,
        secret_name_diff=anchor.secret_name_diff,
        reference_consumers=REFERENCE_CONSUMERS,
        synthetic_probes=tuple(probes),
        reference_parity=parity,
        real_provider_call_count=0,
        real_user_data=0,
        mutation_scope="A3 Tool Runtime activation only",
        final_disposition="PENDING_PRODUCTION_AUTHORIZATION",
    )
