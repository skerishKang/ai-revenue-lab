from __future__ import annotations

from .grounding_runtime import (
    GroundingPolicy,
    GroundingRuntimeError,
    PreparedGrounding,
    prepare_combined_grounding_context,
)
from .source_quality import select_grounding_evidence
from .web_runtime import MAX_QUERY_CHARS, WebProvider, WebRuntimeError


async def prepare_search_grounding(
    web_provider: WebProvider,
    query: str,
    *,
    additional_system_context: str | None,
    max_total_context_chars: int,
    policy: GroundingPolicy | None = None,
) -> PreparedGrounding:
    """Retrieve and prepare bounded search evidence without running synthesis.

    This is the shared pre-synthesis seam used by products that need progressive
    model streaming after retrieval. Retrieval and source-quality selection stay
    Core-owned; callers only receive the prepared, injection-safe evidence context.
    """

    if not isinstance(query, str):
        raise GroundingRuntimeError("invalid_tool_input", "query must be a string", 422)
    safe_query = query.strip()
    if not safe_query or len(safe_query) > MAX_QUERY_CHARS:
        raise GroundingRuntimeError(
            "invalid_tool_input",
            f"query must contain 1 to {MAX_QUERY_CHARS} characters",
            422,
        )

    resolved_policy = policy or GroundingPolicy()
    try:
        found = await web_provider.search(
            safe_query,
            limit=resolved_policy.max_simple_sources,
        )
    except WebRuntimeError as exc:
        raise GroundingRuntimeError(exc.code, exc.message, exc.status_code) from exc

    selection = select_grounding_evidence(
        safe_query,
        found,
        policy=resolved_policy.source_quality_policy,
        limit=resolved_policy.max_simple_sources,
    )
    return prepare_combined_grounding_context(
        selection.evidence,
        additional_system_context=additional_system_context,
        max_total_context_chars=max_total_context_chars,
        policy=resolved_policy,
        max_sources=resolved_policy.max_simple_sources,
    )
