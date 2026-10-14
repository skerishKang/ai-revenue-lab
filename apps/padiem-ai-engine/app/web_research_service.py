"""Cross-runtime projection of Core Web / Grounded Research through Engine.

The Engine owns only the trusted internal wire and runtime composition. Web
provider selection, URL safety, source quality, grounding, evidence and
research budgets remain Padiem AI Core authority. B14 remains the only model
execution/routing authority used for planning and synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Mapping, Protocol

from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeError,
    MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
)
from padiem_ai_core.grounding_runtime import (
    GroundedResearchResult,
    GroundedResearchRuntime,
    GroundedSynthesisResult,
    GroundingRuntimeError,
)
from padiem_ai_core.web_runtime import MAX_QUERY_CHARS

from app.evidence_projection import (
    EngineEvidenceProjectionError,
    project_terminal_evidence,
    project_engine_evidence,
)
from app.service import (
    ServiceContractError,
    ServiceResponse,
    _service_error,
    _status_for_runtime_error,
    build_execution_request,
)

RESEARCH_PATH = "/internal/v1/research"
MAX_RESEARCH_REQUEST_BODY_BYTES = 128 * 1024

_OPERATIONS = frozenset(
    {"search", "fetch", "deep_research", "search_evidence", "search_judgement"}
)
_TOP_LEVEL_REQUIRED = frozenset({"app_id", "operation", "query", "agent"})
_TOP_LEVEL_ALLOWED = frozenset(
    {
        "app_id",
        "operation",
        "query",
        "url",
        "agent",
        "additional_system_context",
        "trace_id",
    }
)


# #4469: AI conversation judgement for public web search. The judgement is
# Engine-owned and product-neutral: it decides whether current public evidence is
# needed and how to ask for it. It never retrieves, never answers, and grants no
# tool or provider authority. The fixed `b14/auto` chain stays on the Router side,
# so the caller's selected answer model is untouched.
_JUDGE_INSTRUCTION = (
    "Decide whether this conversation needs current public web evidence to answer "
    "accurately. Search only for facts that can have changed outside the model: news, "
    "law or policy changes, prices, programme or application windows, and current state. "
    "Do not search for general knowledge, writing, summarising, translation, arithmetic, "
    "or material the user already supplied. Use the conversation to resolve anaphora such "
    "as 'then' or 'this year' into a standalone public topic. If the conversation cannot "
    "pin a safe public topic, choose needs_search false with reason clarify_context. Never "
    "place private, customer, pricing-sheet, account, credential or attachment content in "
    "the query. Respond with exactly one JSON object: "
    '{"needs_search": true|false, "query": string|null, "reason": "fresh_public_fact"|'
    '"explicit_request"|"volatile_business_fact"|"stable_knowledge"|"user_supplied_text"|'
    '"clarify_context"}.'
)
_JUDGE_REASONS = frozenset(
    {
        "fresh_public_fact",
        "explicit_request",
        "volatile_business_fact",
        "stable_knowledge",
        "user_supplied_text",
        "clarify_context",
    }
)
_MAX_JUDGE_QUERY_CHARS = 200
_PRIVATE_QUERY_RE = re.compile(
    r"(?i)(bearer|refresh[-_ ]?token|api[-_ ]?key|client[-_ ]?secret|cookie"
    r"|[\w.+-]+@[\w-]+\.[\w.-]+|01[01][- ]?\d{3,4}[- ]?\d{4}|\d{2,3}[- ]?\d{3,4}[- ]?\d{4}"
    r"|\.(?:pdf|xlsx|docx|csv|zip|png|jpg)\b|usr_|session[-_]?id"
    r"|(?:견적|단가|원가|계좌|고객명|거래처|주민등록|여권번호))"
)


def _judge_profile() -> AgentProfile:
    return AgentProfile(
        id="engine-search-judgement",
        title="Conversation search judgement",
        description="Decides whether public web evidence is required for this conversation.",
        system_instruction=_JUDGE_INSTRUCTION,
        task_type="general",
        optimize_for="balanced",
        max_tokens=256,
        allowed_tools=(),
        required_capabilities=(),
        model_policy={"model": "b14/auto"},
        max_steps=1,
    )


def _judge_verdict(answer: Any) -> tuple[bool, str | None, str]:
    """Parse one bounded model verdict; anything unrecognisable means no search."""

    if not isinstance(answer, str) or not answer.strip():
        return False, None, "clarify_context"
    text = answer.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else ""
    start, stop = text.find("{"), text.rfind("}")
    if start < 0 or stop <= start:
        return False, None, "clarify_context"
    try:
        data = json.loads(text[start:stop + 1])
    except json.JSONDecodeError:
        return False, None, "clarify_context"
    if not isinstance(data, dict) or data.get("needs_search") is not True:
        reason = data.get("reason") if isinstance(data, dict) else None
        return False, None, reason if reason in _JUDGE_REASONS else "clarify_context"
    query = data.get("query")
    reason = data.get("reason")
    if not isinstance(query, str):
        return False, None, "clarify_context"
    query = " ".join(query.split())[:_MAX_JUDGE_QUERY_CHARS].strip()
    if len(query) < 2 or _PRIVATE_QUERY_RE.search(query):
        # A private or unusable query is a refusal, never a redaction promise.
        return False, None, "clarify_context"
    return True, query, reason if isinstance(reason, str) and reason in _JUDGE_REASONS else "fresh_public_fact"


class ExecutionRunner(Protocol):
    async def run(self, request: ExecutionRequest) -> ExecutionResult: ...


ResearchRuntimeFactory = Callable[[str], GroundedResearchRuntime]
ExecutionRuntimeFactory = Callable[[str], ExecutionRunner]


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    app_id: str
    operation: str
    query: str
    url: str | None
    agent: AgentProfile
    additional_system_context: str | None
    trace_id: str | None


class ResearchContractError(ValueError):
    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _exact_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchContractError(
            "invalid_research_request",
            "Research request must be an object.",
        )
    data = dict(value)
    if set(data) - _TOP_LEVEL_ALLOWED:
        raise ResearchContractError(
            "invalid_research_request",
            "Research request contains unsupported fields.",
        )
    if _TOP_LEVEL_REQUIRED - set(data):
        raise ResearchContractError(
            "invalid_research_request",
            "Research request is missing required fields.",
        )
    return data


def _query(value: Any) -> str:
    if not isinstance(value, str):
        raise ResearchContractError(
            "invalid_research_request",
            "query must be a non-empty string.",
        )
    text = value.strip()
    if not text or len(text) > MAX_QUERY_CHARS:
        raise ResearchContractError(
            "invalid_research_request",
            "query exceeds the bounded research limit.",
        )
    return text


def _additional_system_context(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchContractError(
            "invalid_research_request",
            "additional_system_context must be text.",
        )
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS:
        raise ResearchContractError(
            "invalid_research_request",
            "additional_system_context exceeds the bounded context limit.",
        )
    return text


def build_research_request(payload: Any) -> ResearchRequest:
    data = _exact_object(payload)
    operation = data.get("operation")
    if operation not in _OPERATIONS:
        raise ResearchContractError(
            "invalid_research_operation",
            "Research operation must be search, fetch, deep_research, or search_evidence.",
        )

    query = _query(data.get("query"))
    url = data.get("url")
    if operation == "fetch":
        if not isinstance(url, str) or not url.strip():
            raise ResearchContractError(
                "invalid_research_request",
                "fetch research requires a URL.",
            )
        url = url.strip()
    elif url is not None:
        raise ResearchContractError(
            "invalid_research_request",
            "url is supported only for fetch research.",
        )

    # Reuse the accepted /execute interpretation of app/agent fields instead
    # of creating a second Engine model-routing contract.
    execute_shape: dict[str, Any] = {
        "app_id": data["app_id"],
        "agent": data["agent"],
        "messages": [{"role": "user", "content": query}],
    }
    if data.get("trace_id") is not None:
        execute_shape["trace_id"] = data["trace_id"]
    try:
        app_id, execution_request, _context = build_execution_request(execute_shape)
    except ServiceContractError as exc:
        raise ResearchContractError(
            exc.code,
            exc.safe_message,
            status_code=exc.status_code,
        ) from None

    return ResearchRequest(
        app_id=app_id,
        operation=operation,
        query=query,
        url=url,
        agent=execution_request.agent,
        additional_system_context=_additional_system_context(
            data.get("additional_system_context")
        ),
        trace_id=execution_request.trace_id,
    )


def _research_runtime_error(exc: GroundingRuntimeError) -> ServiceResponse:
    return _service_error(
        exc.code,
        exc.message,
        status_code=exc.status_code,
        retryable=exc.status_code in {502, 503, 504},
    )


def _public_result(
    *,
    request: ResearchRequest,
    result: GroundedSynthesisResult | GroundedResearchResult,
) -> ServiceResponse:
    synthesis = result.synthesis
    if not isinstance(synthesis, ExecutionResult):
        return _service_error(
            "invalid_research_result",
            "Padiem AI Engine returned an invalid research synthesis result.",
            status_code=500,
        )

    # Keep the research contract narrower than the generic /execute contract.
    # B14 route/model/provider metadata and execution metadata are intentionally
    # not projected upward; only the answer and Core-owned public evidence are.
    # Evidence is projected through the single canonical #1745 Engine projection.
    try:
        evidence_fields = project_terminal_evidence(result)
    except EngineEvidenceProjectionError as exc:
        return _service_error(exc.code, exc.safe_message, status_code=500)
    body: dict[str, Any] = {
        "ok": True,
        "operation": request.operation,
        "answer": synthesis.answer,
        **evidence_fields,
        "research": None,
    }
    if isinstance(result, GroundedResearchResult):
        body["research"] = {
            **result.progress.to_public_dict(),
            "planner_fallback": bool(result.planner_fallback),
        }
    return ServiceResponse(status_code=200, body=body)


class WebResearchEngineService:
    """Bounded internal Engine projection over Core GroundedResearchRuntime."""

    def __init__(
        self,
        *,
        research_runtime_factory: ResearchRuntimeFactory,
        execution_runtime_factory: ExecutionRuntimeFactory,
        b14_service_bound: bool,
    ) -> None:
        if not callable(research_runtime_factory) or not callable(
            execution_runtime_factory
        ):
            raise ValueError("research and execution runtime factories must be callable")
        self._research_runtime_factory = research_runtime_factory
        self._execution_runtime_factory = execution_runtime_factory
        self._b14_service_bound = bool(b14_service_bound)

    async def research_payload(self, payload: Any) -> ServiceResponse:
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        try:
            request = build_research_request(payload)
        except ResearchContractError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
            )

        try:
            research_runtime = self._research_runtime_factory(request.app_id)
            # Evidence-only must not construct, select, or invoke a B14 model.
            execution_runtime = (
                None if request.operation == "search_evidence"
                else self._execution_runtime_factory(request.app_id)
            )
        except Exception:
            return _service_error(
                "web_runtime_unavailable",
                "Padiem AI Engine web runtime is unavailable.",
                status_code=503,
                retryable=True,
            )

        async def synthesize(grounded_context: str) -> ExecutionResult:
            execution_request = ExecutionRequest(
                agent=request.agent,
                messages=({"role": "user", "content": request.query},),
                additional_system_context=grounded_context,
                trace_id=request.trace_id,
            )
            return await execution_runtime.run(execution_request)

        async def plan(query: str) -> str:
            # Planner identity/instruction are Engine-owned and product-neutral.
            # Callers cannot submit a compiled planner or widen capabilities.
            planner_agent = AgentProfile(
                id="engine-research-planner",
                title="Research query planner",
                description="Produces bounded public-web queries for Core research.",
                system_instruction=(
                    "Return exactly one JSON object with key queries and 1 to 3 "
                    "concise search query strings. Do not include prose, markdown, "
                    "tools, URLs, credentials, or private reasoning."
                ),
                task_type="general",
                optimize_for="balanced",
                max_tokens=240,
                allowed_tools=(),
                required_capabilities=(),
                # #2101: the Engine-owned planner stays on the Router-owned
                # fixed `b14/auto` chain, but the route is now declared
                # explicitly. Core no longer synthesizes it when omitted.
                model_policy={"model": "b14/auto"},
                max_steps=1,
            )
            planner_result = await execution_runtime.run(
                ExecutionRequest(
                    agent=planner_agent,
                    messages=({"role": "user", "content": query},),
                    trace_id=request.trace_id,
                )
            )
            return planner_result.answer

        try:
            if request.operation == "search_judgement":
                # Judgement only: the model decides whether public evidence is needed
                # and how to ask for it. Nothing is retrieved or answered here, and the
                # caller's selected answer model is untouched.
                if request.additional_system_context is not None:
                    return _service_error(
                        "invalid_research_request",
                        "Search judgement cannot carry private system context.",
                        status_code=400,
                    )
                verdict = await execution_runtime.run(
                    ExecutionRequest(
                        agent=_judge_profile(),
                        messages=({"role": "user", "content": request.query},),
                        trace_id=request.trace_id,
                    )
                )
                needs_search, public_query, reason = _judge_verdict(verdict.answer)
                return ServiceResponse(status_code=200, body={
                    "ok": True,
                    "operation": "search_judgement",
                    "needs_search": needs_search,
                    "query": public_query if needs_search else None,
                    "reason": reason,
                    "answer": None,
                    "sources": [],
                    "research": None,
                })
            if request.operation == "search_evidence":
                # Existing authenticated Engine research route, not a browser
                # endpoint. Caller-supplied system context is not accepted on
                # this model-free public search path.
                if request.additional_system_context is not None:
                    return _service_error(
                        "invalid_research_request",
                        "Evidence-only search cannot carry private system context.",
                        status_code=400,
                    )
                prepared = await research_runtime.prepare_search(
                    request.query,
                    additional_system_context=None,
                    max_total_context_chars=32_768,
                )
                return ServiceResponse(status_code=200, body={
                    "ok": True,
                    "operation": "search_evidence",
                    "answer": None,
                    "sources": project_engine_evidence(prepared.evidence),
                    "grounding_context": prepared.context,
                    "research": None,
                })
            if request.operation == "search":
                result = await research_runtime.run_search(
                    request.query,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            elif request.operation == "fetch":
                assert request.url is not None
                result = await research_runtime.run_fetch(
                    request.url,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            else:
                result = await research_runtime.run_deep_research(
                    request.query,
                    planner=plan,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
        except GroundingRuntimeError as exc:
            return _research_runtime_error(exc)
        except ExecutionRuntimeError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=_status_for_runtime_error(exc),
                retryable=exc.retryable,
            )
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_research_request",
                "Research request fields are invalid.",
                status_code=400,
            )
        except Exception:
            return _service_error(
                "engine_internal_error",
                "Padiem AI Engine research failed.",
                status_code=500,
            )

        return _public_result(request=request, result=result)

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != RESEARCH_PATH:
            return _service_error(
                "not_found",
                "Internal Engine route not found.",
                status_code=404,
            )
        if normalized_method != "POST":
            return _service_error(
                "method_not_allowed",
                "Method not allowed.",
                status_code=405,
            )
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request",
                "Request body is invalid.",
                status_code=400,
            )
        raw = bytes(body)
        if len(raw) > MAX_RESEARCH_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )
        return await self.research_payload(payload)
