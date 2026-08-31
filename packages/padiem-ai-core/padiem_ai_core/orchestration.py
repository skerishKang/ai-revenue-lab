"""Product-neutral bounded orchestration pipeline for Padiem AI Core.

This module coordinates existing P01 primitives (Execution, Memory/RAG, Agent,
Skill, Tool/Connector, Evidence, and Verification) into a unified, bounded
execution pipeline without elevating untrusted references or widening authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import uuid
from typing import Any, Callable

from .agent_definition import BoundedAgentDefinition
from .agent_planner import AgentPlan, AgentPlanner, validate_agent_plan
from .agent_profile_adapter import CompiledAgentProfile
from .connector_registry import ConnectorDescriptor, ConnectorRegistrySnapshot
from .contracts import AgentProfile, ErrorClass, Evidence, RunMetadata, RunStatus, ToolEvent, ToolSpec, UsageMetadata
from .evidence_assessment import ClaimAssessment, ClaimAssessmentState, assess_claim, is_verification_satisfied
from .evidence_citation import GroundedCitation, GroundedCitationBundle, project_grounded_citations
from .evidence_graph import ClaimDerivation, ClaimEvidenceLink, ClaimEvidenceRelation, EvidenceClaim, EvidenceGraph, evidence_graph
from .evidence_verification import (
    AcceptedVerification,
    EvidenceValidator,
    TrustedVerificationPolicy,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    accept_verification_verdict,
)
from .execution_context import (
    ExecutionContext,
    IdempotencyAdapter,
    IdempotencyConflictError,
    request_fingerprint,
)
from .execution_runtime import ExecutionRequest, ExecutionResult, ExecutionRuntimeError
from .memory import MemoryNamespace, MemoryScope
from .memory_read import MemoryReadAuthorization, MemoryReadPolicy
from .memory_context import RankedMemoryItem, assemble_long_context, rank_retrieval_results
from .orchestration_events import (
    OrchestrationEvent,
    OrchestrationEventError,
    OrchestrationEventKind,
    public_orchestration_event,
)
from .retrieval import RetrievedItem
from .skill_activation import ActivatedSkillProfile, compile_enabled_skill
from .skill_registry import SkillInstallationSnapshot, SkillRegistrySnapshot
from .skill_runtime_adapter import TrustedSkillRuntimePolicy
from .tool_registry import ToolRegistrySnapshot
from .tool_resource_policy import EffectiveToolResources, ToolResourcePolicy, resolve_tool_resources

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class OrchestrationError(ValueError):
    """Raised when an orchestration boundary or contract invariant is violated."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("orchestration error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise OrchestrationError("invalid_orchestration_identifier", f"{name} must be a bounded safe identifier")
    return value


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    """Composition root for a bounded orchestration run."""

    execution_request: ExecutionRequest
    context: ExecutionContext
    app_id: str
    subject_id: str | None = None

    # Memory / RAG (Optional)
    memory_authorization: MemoryReadAuthorization | None = None
    memory_items: tuple[RetrievedItem, ...] = ()
    memory_read_policy: MemoryReadPolicy | None = None

    # Agent Planning (Optional)
    agent_definition: BoundedAgentDefinition | None = None
    agent_planner: AgentPlanner | None = None
    agent_plan: AgentPlan | None = None
    compiled_agent_profile: CompiledAgentProfile | None = None

    # Skill (Optional)
    skill_id: str | None = None
    skill_registry: SkillRegistrySnapshot | None = None
    skill_installations: SkillInstallationSnapshot | None = None
    skill_runtime_policy: TrustedSkillRuntimePolicy | None = None

    # Tool & Connector (Optional)
    tool_registry: ToolRegistrySnapshot | None = None
    connector_registry: ConnectorRegistrySnapshot | None = None
    tool_resource_policy: ToolResourcePolicy | None = None

    # Evidence & Verification (Optional)
    evidence_sources: tuple[Evidence, ...] = ()
    evidence_claims: tuple[EvidenceClaim, ...] = ()
    evidence_links: tuple[ClaimEvidenceLink, ...] = ()
    evidence_validator: EvidenceValidator | None = None
    verification_policy: TrustedVerificationPolicy | None = None
    require_evidence: bool = False
    require_verification: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.execution_request, ExecutionRequest):
            raise OrchestrationError("invalid_orchestration_request", "execution_request must be ExecutionRequest")
        if not isinstance(self.context, ExecutionContext):
            raise OrchestrationError("invalid_orchestration_request", "context must be ExecutionContext")
        object.__setattr__(self, "app_id", _safe_id("app_id", self.app_id))
        if self.subject_id is not None:
            object.__setattr__(self, "subject_id", _safe_id("subject_id", self.subject_id))

        # Trace ID alignment invariant
        if self.execution_request.trace_id != self.context.trace_id:
            raise OrchestrationError("trace_id_conflict", "execution_request trace_id must match execution_context trace_id")


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Structured, immutable outcome of an orchestration pipeline run."""

    execution_result: ExecutionResult
    context: ExecutionContext
    app_id: str
    subject_id: str | None
    plan: AgentPlan | None
    activated_skill: ActivatedSkillProfile | None
    resolved_tool_ids: tuple[str, ...]
    evidence_graph: EvidenceGraph | None
    claim_assessments: tuple[ClaimAssessment, ...]
    grounded_citations: tuple[GroundedCitation, ...]
    events: tuple[OrchestrationEvent, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "execution": {
                "answer": self.execution_result.answer,
                "route": self.execution_result.route.to_public_dict(),
                "metadata": self.execution_result.metadata.to_public_dict(),
            },
            "context": self.context.to_public_dict(),
            "app_id": self.app_id,
            "subject_id": self.subject_id,
            "plan": self.plan.to_public_dict() if self.plan is not None else None,
            "activated_skill": self.activated_skill.to_public_dict() if self.activated_skill is not None else None,
            "resolved_tool_ids": list(self.resolved_tool_ids),
            "evidence": {
                "claim_count": len(self.evidence_graph.claims) if self.evidence_graph is not None else 0,
                "source_count": len(self.evidence_graph.sources) if self.evidence_graph is not None else 0,
                "assessments": [a.to_public_dict() for a in self.claim_assessments],
                "citations": [c.to_public_dict() for c in self.grounded_citations],
            },
            "events": [e.to_public_dict() for e in self.events],
        }


class OrchestrationRunner:
    """Bounded, provider-neutral execution pipeline runner."""

    def __init__(
        self,
        *,
        runtime: Any,
        idempotency: IdempotencyAdapter | None = None,
    ) -> None:
        if not hasattr(runtime, "run") or not callable(getattr(runtime, "run", None)):
            raise OrchestrationError("invalid_runtime", "runtime must provide a callable run method")
        self._runtime = runtime
        self._idempotency = idempotency

    async def run(self, request: OrchestrationRequest) -> OrchestrationResult:
        if not isinstance(request, OrchestrationRequest):
            raise OrchestrationError("invalid_orchestration_request", "request must be OrchestrationRequest")

        run_id = f"orch_run_{uuid.uuid4().hex[:16]}"
        trace_id = request.context.trace_id
        app_id = request.app_id
        events: list[OrchestrationEvent] = []
        seq = 1
        terminated = False

        def emit(kind: OrchestrationEventKind, message: str | None = None, metadata: Mapping[str, Any] | None = None) -> None:
            nonlocal seq, terminated
            if terminated:
                return
            evt = public_orchestration_event(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                trace_id=trace_id,
                app_id=app_id,
                kind=kind,
                sequence=seq,
                message=message,
                metadata=metadata or {},
            )
            events.append(evt)
            seq += 1
            if kind in (OrchestrationEventKind.RUN_COMPLETED, OrchestrationEventKind.RUN_FAILED, OrchestrationEventKind.RUN_CANCELLED):
                terminated = True

        async def _abort_idempotency(reason: str) -> None:
            if request.context.idempotency_key is not None and self._idempotency is not None:
                if hasattr(self._idempotency, "abort") and callable(getattr(self._idempotency, "abort", None)):
                    try:
                        await self._idempotency.abort(app_id=app_id, idempotency_key=request.context.idempotency_key, reason=reason)
                    except Exception:
                        pass
                elif hasattr(self._idempotency, "release") and callable(getattr(self._idempotency, "release", None)):
                    try:
                        await self._idempotency.release(app_id=app_id, idempotency_key=request.context.idempotency_key)
                    except Exception:
                        pass

        # 1. RUN_STARTED
        emit(OrchestrationEventKind.RUN_STARTED, f"Orchestration started for app '{app_id}'", {"app_id": app_id})

        # 2. CONTEXT_PREPARED & Idempotency Check
        fingerprint_payload = {
            "app_id": app_id,
            "agent_id": request.execution_request.agent.id,
            "messages": [m for m in request.execution_request.messages],
        }
        fp = request_fingerprint(fingerprint_payload)
        emit(OrchestrationEventKind.CONTEXT_PREPARED, "Execution context validated and bound", {
            "timeout_seconds": request.context.timeout_seconds,
            "idempotency_present": request.context.idempotency_key is not None,
            "request_fingerprint": fp,
        })

        if request.context.idempotency_key is not None:
            if self._idempotency is None:
                raise OrchestrationError("idempotency_unavailable", "idempotency_key supplied but no IdempotencyAdapter injected")
            replay = await self._idempotency.begin(
                app_id=app_id,
                idempotency_key=request.context.idempotency_key,
                request_fingerprint=fp,
            )
            if replay is not None:
                if not isinstance(replay, ExecutionResult):
                    raise IdempotencyConflictError("idempotency adapter returned invalid replay")
                emit(OrchestrationEventKind.RUN_COMPLETED, "Execution completed via idempotency replay", {"replay": True})
                return OrchestrationResult(
                    execution_result=replay,
                    context=request.context,
                    app_id=app_id,
                    subject_id=request.subject_id,
                    plan=request.agent_plan,
                    activated_skill=None,
                    resolved_tool_ids=request.execution_request.agent.allowed_tools,
                    evidence_graph=None,
                    claim_assessments=(),
                    grounded_citations=(),
                    events=tuple(events),
                )

        # 3. Optional Memory Read & Bounded Context Assembly
        composed_system_context = request.execution_request.additional_system_context
        if request.memory_items:
            if request.memory_authorization is not None:
                if request.memory_authorization.app_id != app_id:
                    await _abort_idempotency("memory_authorization_mismatch")
                    emit(OrchestrationEventKind.RUN_FAILED, "Memory authorization mismatch", {"error": "memory_authorization_mismatch"})
                    raise OrchestrationError("memory_authorization_mismatch", "memory_authorization app_id does not match caller app_id")
            
            ranked = rank_retrieval_results(request.memory_items)
            ref_context = assemble_long_context(ranked)
            if ref_context:
                fenced_memory = (
                    "\n\n[UNTRUSTED_REFERENCE: Memory & Retrieved Context]\n"
                    f"{ref_context}\n"
                    "[END_UNTRUSTED_REFERENCE]"
                )
                if composed_system_context:
                    composed_system_context = f"{composed_system_context}{fenced_memory}"
                else:
                    composed_system_context = fenced_memory
            
            emit(OrchestrationEventKind.MEMORY_READ, "Retrieved memory items assembled as untrusted reference", {
                "items_count": len(request.memory_items),
                "ranked_count": len(ranked),
            })

        # 4. Optional Agent Planning
        plan = request.agent_plan
        if plan is None and request.agent_planner is not None and request.agent_definition is not None and request.compiled_agent_profile is not None:
            user_text = " ".join(m.get("content", "") for m in request.execution_request.messages if m.get("role") == "user")
            plan = await request.agent_planner.plan(
                input_text=user_text or "Execute plan",
                definition=request.agent_definition,
                compiled_profile=request.compiled_agent_profile,
            )

        if plan is not None:
            if request.agent_definition is not None and request.compiled_agent_profile is not None:
                validate_agent_plan(plan, definition=request.agent_definition, compiled_profile=request.compiled_agent_profile)
            emit(OrchestrationEventKind.PLAN_CREATED, f"Validated agent plan with {len(plan.steps)} steps", {
                "agent_id": plan.agent_id,
                "step_count": len(plan.steps),
            })

        # 5. Optional Skill Resolution & Trusted Compilation
        activated_skill: ActivatedSkillProfile | None = None
        if request.skill_id is not None:
            if request.skill_registry is None or request.skill_installations is None or request.skill_runtime_policy is None:
                await _abort_idempotency("skill_context_missing")
                emit(OrchestrationEventKind.RUN_FAILED, "Skill context missing", {"error": "skill_context_missing"})
                raise OrchestrationError("skill_context_missing", "skill_id requested but registry, installations, or runtime_policy missing")
            
            activated_skill = compile_enabled_skill(
                registry=request.skill_registry,
                installations=request.skill_installations,
                app_id=app_id,
                subject_id=request.subject_id or "default_subject",
                skill_id=request.skill_id,
                runtime_policy=request.skill_runtime_policy,
            )
            for sk_tool in activated_skill.compiled.runtime_profile.allowed_tools:
                if sk_tool not in request.execution_request.agent.allowed_tools:
                    await _abort_idempotency("authority_widening_rejected")
                    emit(OrchestrationEventKind.RUN_FAILED, "Authority widening rejected", {"error": "authority_widening_rejected"})
                    raise OrchestrationError("authority_widening_rejected", f"skill requests tool '{sk_tool}' outside agent profile allowlist")

            emit(OrchestrationEventKind.SKILL_RESOLVED, f"Skill '{request.skill_id}' resolved and compiled", {
                "skill_id": request.skill_id,
                "canonical_skill_id": activated_skill.compiled.canonical_skill_id,
            })

        # 6. Tool & Connector Resolution
        resolved_tools: tuple[str, ...] = request.execution_request.agent.allowed_tools
        if request.tool_resource_policy is not None:
            emit(OrchestrationEventKind.TOOL_RESOLUTION, "Resolved effective tool resources", {
                "max_argument_bytes": request.tool_resource_policy.max_argument_bytes,
                "max_output_bytes": request.tool_resource_policy.max_output_bytes,
                "max_timeout_seconds": request.tool_resource_policy.max_timeout_seconds,
            })

        # 7. Bounded Agent Execution
        effective_agent = request.execution_request.agent
        if activated_skill is not None:
            effective_agent = AgentProfile(
                id=effective_agent.id,
                title=effective_agent.title,
                description=effective_agent.description,
                system_instruction=effective_agent.system_instruction,
                task_type=activated_skill.compiled.runtime_profile.task_type,
                optimize_for=activated_skill.compiled.runtime_profile.optimize_for,
                max_tokens=min(effective_agent.max_tokens, activated_skill.compiled.runtime_profile.max_tokens),
                allowed_tools=resolved_tools,
                required_capabilities=effective_agent.required_capabilities,
                model_policy=effective_agent.model_policy,
                max_steps=min(effective_agent.max_steps, activated_skill.compiled.runtime_profile.max_steps),
            )

        exec_req = ExecutionRequest(
            agent=effective_agent,
            messages=request.execution_request.messages,
            session_id=request.execution_request.session_id,
            additional_system_context=composed_system_context,
            trace_id=trace_id,
        )

        try:
            result = await asyncio.wait_for(
                self._runtime.run(exec_req),
                timeout=request.context.timeout_seconds,
            )
            # Emit Tool lifecycle events ONLY for actual tool events from the execution result
            for te in getattr(result.metadata, "tool_events", ()):
                emit(OrchestrationEventKind.TOOL_STARTED, f"Tool '{te.tool_id}' started", {"tool_id": te.tool_id})
                if te.status is RunStatus.COMPLETED:
                    emit(OrchestrationEventKind.TOOL_COMPLETED, f"Tool '{te.tool_id}' completed", {
                        "tool_id": te.tool_id,
                        "status": "completed",
                        "duration_ms": te.duration_ms,
                    })
                elif te.status is RunStatus.FAILED:
                    emit(OrchestrationEventKind.TOOL_FAILED, f"Tool '{te.tool_id}' failed", {
                        "tool_id": te.tool_id,
                        "status": "failed",
                        "error_class": te.error_class.value if te.error_class else None,
                        "duration_ms": te.duration_ms,
                    })
        except asyncio.TimeoutError:
            await _abort_idempotency("timeout")
            emit(OrchestrationEventKind.RUN_FAILED, "Execution timed out", {"reason": "timeout"})
            raise OrchestrationError("orchestration_timeout", f"Execution exceeded {request.context.timeout_seconds}s timeout") from None
        except asyncio.CancelledError:
            await _abort_idempotency("cancelled")
            emit(OrchestrationEventKind.RUN_CANCELLED, "Execution was cancelled", {"reason": "downstream_cancellation"})
            raise
        except ExecutionRuntimeError as exc:
            await _abort_idempotency(exc.code)
            emit(OrchestrationEventKind.RUN_FAILED, f"Execution failed: {exc.safe_message}", {"error_code": exc.code})
            raise
        except Exception as exc:
            await _abort_idempotency("internal_error")
            emit(OrchestrationEventKind.RUN_FAILED, "Unexpected execution failure", {"error": "internal_error"})
            raise

        # 8. Evidence & Provenance Integration
        eg: EvidenceGraph | None = None
        assessments: list[ClaimAssessment] = []
        citations: list[GroundedCitation] = []

        if request.evidence_sources or request.evidence_claims:
            eg = evidence_graph(
                sources=list(request.evidence_sources),
                claims=list(request.evidence_claims),
                links=list(request.evidence_links),
            )
            emit(OrchestrationEventKind.EVIDENCE_ATTACHED, f"Evidence graph constructed with {len(eg.sources)} sources", {
                "sources_count": len(eg.sources),
                "claims_count": len(eg.claims),
            })

            # Verification & Assessment
            for claim in eg.claims:
                verdict: VerificationVerdict | None = None
                if request.evidence_validator is not None and request.verification_policy is not None:
                    verdict_cand = await request.evidence_validator.verify(
                        VerificationRequest(claim_id=claim.id, producer_id=effective_agent.id),
                        graph=eg,
                    )
                    verdict = accept_verification_verdict(
                        verdict_cand,
                        request=VerificationRequest(claim_id=claim.id, producer_id=effective_agent.id),
                        graph=eg,
                        policy=request.verification_policy,
                    )

                ass = assess_claim(eg, claim.id, verification=verdict)
                assessments.append(ass)

                bundle = project_grounded_citations(eg, claim.id, verification=verdict)
                citations.extend(bundle.citations)

            emit(OrchestrationEventKind.VERIFICATION_COMPLETED, f"Assessed {len(assessments)} claims", {
                "assessments_count": len(assessments),
                "citations_count": len(citations),
            })

        # Required evidence check
        if request.require_evidence:
            if eg is None or len(eg.sources) == 0:
                await _abort_idempotency("required_evidence_missing")
                emit(OrchestrationEventKind.RUN_FAILED, "Required evidence was missing", {"error": "required_evidence_missing"})
                raise OrchestrationError("required_evidence_missing", "Orchestration request required evidence but none was attached")

        # Required verification check - enforces SUPPORTED only; rejects UNVERIFIED, CONTRADICTED, and CONFLICTED
        if request.require_verification:
            if not assessments or any(not is_verification_satisfied(a) for a in assessments):
                await _abort_idempotency("verification_failed")
                emit(OrchestrationEventKind.RUN_FAILED, "Required verification failed or was unverified/conflicted", {"error": "verification_failed"})
                raise OrchestrationError("verification_failed", "Claim verification did not achieve a verified SUPPORTED status")

        # 9. Idempotency Commit & Completion
        if request.context.idempotency_key is not None and self._idempotency is not None:
            if hasattr(self._idempotency, "commit"):
                await self._idempotency.commit(
                    app_id=app_id,
                    idempotency_key=request.context.idempotency_key,
                    request_fingerprint=fp,
                    result=result,
                )
            elif hasattr(self._idempotency, "complete"):
                await self._idempotency.complete(
                    app_id=app_id,
                    idempotency_key=request.context.idempotency_key,
                    request_fingerprint=fp,
                    result=result.to_public_dict() if hasattr(result, "to_public_dict") else {"answer": result.answer},
                )

        emit(OrchestrationEventKind.RUN_COMPLETED, "Orchestration completed successfully", {
            "status": "completed",
        })

        return OrchestrationResult(
            execution_result=result,
            context=request.context,
            app_id=app_id,
            subject_id=request.subject_id,
            plan=plan,
            activated_skill=activated_skill,
            resolved_tool_ids=resolved_tools,
            evidence_graph=eg,
            claim_assessments=tuple(assessments),
            grounded_citations=tuple(citations),
            events=tuple(events),
        )
