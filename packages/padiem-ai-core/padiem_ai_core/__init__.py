from __future__ import annotations

import importlib

from .contracts import (
    AgentProfile,
    ApprovalPolicy,
    ErrorClass,
    Evidence,
    RunMetadata,
    RunStatus,
    ToolEvent,
    ToolSideEffect,
    ToolSpec,
    UsageMetadata,
)
from .web_runtime import (
    FIRECRAWL_ORIGIN,
    MAX_PROVIDER_RESPONSE_BYTES,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MAX_SNIPPET_CHARS,
    MAX_TITLE_CHARS,
    MAX_URL_CHARS,
    FirecrawlWebProvider,
    MockWebProvider,
    OffWebProvider,
    WebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
    create_web_provider,
    normalize_public_url,
)
from .b14_execution import (
    B14_CHAT_COMPLETIONS_PATH,
    MAX_B14_RESPONSE_BYTES,
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
    B14RoutingOptions,
)
from .b14_multimodal import (
    B14MultimodalChatRequest,
    MAX_B14_IMAGE_BYTES,
    MAX_B14_MULTIMODAL_PARTS,
)
from .b14_transport import (
    B14PostJSONTransport,
    B14Transport,
    B14TransportResponse,
)
from .b14_streaming import (
    B14_STREAM_PREVIEW_PATH,
    B14StreamEvent,
    B14StreamingClient,
)
from .grounding_runtime import (
    DEFAULT_GROUNDING_PREAMBLE,
    MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS,
    MAX_GROUNDED_SOURCES,
    MAX_RESEARCH_PAGE_FETCHES,
    MAX_RESEARCH_QUERIES,
    MAX_RESEARCH_SOURCES,
    GroundedResearchResult,
    GroundedResearchRuntime,
    GroundedSynthesisResult,
    GroundingPolicy,
    GroundingRuntimeError,
    PreparedGrounding,
    ResearchProgress,
    dedupe_evidence,
    parse_research_queries,
    prepare_combined_grounding_context,
    prepare_grounding_context,
)
from .execution_runtime import (
    MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
    MAX_COMPOSED_SYSTEM_CHARS,
    MAX_EXECUTION_MESSAGE_CHARS,
    MAX_EXECUTION_MESSAGES,
    B14Executor,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
)
from .streaming_runtime import (
    B14StreamExecutor,
    StreamingExecutionEvent,
    StreamingExecutionRuntime,
)
from .agent_recovery import (
    AgentFailure,
    AgentFailureSource,
    AgentRecoveryAction,
    AgentRecoveryContext,
    AgentRecoveryDecision,
    AgentRecoveryError,
    AgentRecoveryPolicy,
    decide_agent_recovery,
)
from .agent_delegation import (
    AgentDelegationError,
    AgentDelegationRequest,
    DelegatedAgentAuthority,
    authorize_agent_delegation,
    delegation_fingerprint,
)
from .agent_events import (
    AgentEvent,
    AgentEventError,
    AgentEventKind,
    public_agent_event,
)

_TOOL_RUNTIME_EXPORTS = frozenset(
    {
        "MAX_TOOL_ARGUMENT_BYTES",
        "MAX_TOOL_OUTPUT_BYTES",
        "ToolAuthorizationContext",
        "ToolExecutionResult",
        "ToolHandler",
        "ToolInvocation",
        "ToolRuntime",
        "ToolRuntimeError",
    }
)


def __getattr__(name: str):
    if name not in _TOOL_RUNTIME_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        module = importlib.import_module(".tool_runtime", __name__)
    except ModuleNotFoundError as exc:
        if exc.name == "jsonschema":
            raise ImportError(
                "Tool Runtime requires the optional 'tools' dependency: "
                "install padiem-ai-core[tools]."
            ) from exc
        raise
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "AgentProfile",
    "ApprovalPolicy",
    "ErrorClass",
    "Evidence",
    "RunMetadata",
    "RunStatus",
    "ToolEvent",
    "ToolSideEffect",
    "ToolSpec",
    "UsageMetadata",
    "FIRECRAWL_ORIGIN",
    "MAX_PROVIDER_RESPONSE_BYTES",
    "MAX_QUERY_CHARS",
    "MAX_RESULTS",
    "MAX_SNIPPET_CHARS",
    "MAX_TITLE_CHARS",
    "MAX_URL_CHARS",
    "FirecrawlWebProvider",
    "MockWebProvider",
    "OffWebProvider",
    "WebProvider",
    "WebRuntimeConfig",
    "WebRuntimeError",
    "create_web_provider",
    "normalize_public_url",
    "B14_CHAT_COMPLETIONS_PATH",
    "MAX_B14_RESPONSE_BYTES",
    "B14ChatRequest",
    "B14ExecutionClient",
    "B14ExecutionConfig",
    "B14ExecutionError",
    "B14ExecutionResult",
    "B14RouteMetadata",
    "B14RoutingOptions",
    "B14MultimodalChatRequest",
    "MAX_B14_IMAGE_BYTES",
    "MAX_B14_MULTIMODAL_PARTS",
    "B14PostJSONTransport",
    "B14Transport",
    "B14TransportResponse",
    "B14_STREAM_PREVIEW_PATH",
    "B14StreamEvent",
    "B14StreamingClient",
    "DEFAULT_GROUNDING_PREAMBLE",
    "MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS",
    "MAX_GROUNDED_SOURCES",
    "MAX_RESEARCH_PAGE_FETCHES",
    "MAX_RESEARCH_QUERIES",
    "MAX_RESEARCH_SOURCES",
    "GroundedResearchResult",
    "GroundedResearchRuntime",
    "GroundedSynthesisResult",
    "GroundingPolicy",
    "GroundingRuntimeError",
    "PreparedGrounding",
    "ResearchProgress",
    "dedupe_evidence",
    "parse_research_queries",
    "prepare_combined_grounding_context",
    "prepare_grounding_context",
    "MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS",
    "MAX_COMPOSED_SYSTEM_CHARS",
    "MAX_EXECUTION_MESSAGE_CHARS",
    "MAX_EXECUTION_MESSAGES",
    "B14Executor",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionRuntime",
    "ExecutionRuntimeError",
    "B14StreamExecutor",
    "StreamingExecutionEvent",
    "StreamingExecutionRuntime",
    "AgentFailure",
    "AgentFailureSource",
    "AgentRecoveryAction",
    "AgentRecoveryContext",
    "AgentRecoveryDecision",
    "AgentRecoveryError",
    "AgentRecoveryPolicy",
    "decide_agent_recovery",
    "AgentDelegationError",
    "AgentDelegationRequest",
    "DelegatedAgentAuthority",
    "authorize_agent_delegation",
    "delegation_fingerprint",
    "AgentEvent",
    "AgentEventError",
    "AgentEventKind",
    "public_agent_event",
    "MAX_TOOL_ARGUMENT_BYTES",
    "MAX_TOOL_OUTPUT_BYTES",
    "ToolAuthorizationContext",
    "ToolExecutionResult",
    "ToolHandler",
    "ToolInvocation",
    "ToolRuntime",
    "ToolRuntimeError",
]
