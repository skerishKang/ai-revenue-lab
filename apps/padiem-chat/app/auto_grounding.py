from __future__ import annotations

from dataclasses import dataclass

from padiem_ai_core.grounding_runtime import GroundingRuntimeError, PreparedGrounding
from padiem_ai_core.search_decision import SearchDecision, SearchDisposition, decide_search
from padiem_ai_core.search_preparation import prepare_search_grounding

from .b14_client import MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS
from .grounding import (
    GroundingError,
    _CoreWebProviderAdapter,
    _translate_core_error,
    search_query_too_long_error,
)
from .task_modes import TaskMode
from .web_tools import MAX_QUERY_CHARS, SEARCH_QUERY_TOO_LONG_CODE, MockWebProvider, WebProvider


@dataclass(frozen=True, slots=True)
class AutoGroundingPlan:
    decision: SearchDecision
    prepared: PreparedGrounding | None
    error: GroundingError | None = None

    @property
    def searched(self) -> bool:
        return self.prepared is not None


# #6090: an automatic decision that would hand a document-sized body to the web
# provider is not a search. Recording the reason keeps the skip auditable instead
# of looking like "the classifier said no".
AUTOMATIC_SEARCH_OVER_QUERY_CAP = "automatic_search_body_exceeds_provider_query_cap"


def auto_grounding_may_continue(decision: SearchDecision, error: GroundingError) -> bool:
    """Owner 2026-10-24: failed web retrieval never terminates a Chat turn."""
    return (
        error.code.startswith("web_grounding_")
        or error.code in {"no_evidence", SEARCH_QUERY_TOO_LONG_CODE}
    )


def auto_grounding_skip_fields(decision: SearchDecision) -> dict:
    """Korean disclosure for a current-fact question that could not be searched.

    A long document that happens to contain a freshness word is not a search
    query. Skipping retrieval is right, and staying silent would let the model
    answer a current-fact question from memory, so the skip is disclosed with
    the same guidance the explicit path uses.
    """
    if decision.reason != AUTOMATIC_SEARCH_OVER_QUERY_CAP or not decision.evidence_required:
        return {}
    from .grounding import grounding_fallback_fields

    return grounding_fallback_fields(search_query_too_long_error())



def latest_user_question(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            text = item["content"].strip()
            if text:
                return text
    raise GroundingError(422, "tool_input_required", "검색 여부를 판단할 사용자 질문이 필요합니다.")


# #6046: a declared utility scope is the request's own routing label, and these
# three are document-drafting tasks whose answer comes from the text the user
# supplied. Their request body is that source document, so the classifier must
# never read cues inside it as a question about the current world.
_DOCUMENT_UTIL_SCOPES = frozenset({"speech", "sns", "meeting"})


class AutoGroundingService:
    """B62 consumer of Core-owned search decision and grounding contracts."""

    def __init__(self, web_provider: WebProvider):
        self._web_provider = web_provider
        self._core_provider = _CoreWebProviderAdapter(web_provider)
        self._automatic_search_enabled = bool(
            getattr(web_provider, "_automatic_search_enabled", True)
        )

    def decide(
        self,
        messages: list[dict[str, str]],
        *,
        skill: TaskMode,
        explicit_search: bool = False,
        util_scope: str | None = None,
    ) -> SearchDecision:
        if explicit_search:
            return SearchDecision(SearchDisposition.MUST_SEARCH, "explicit_search_request", latest_user_question(messages))
        if util_scope in _DOCUMENT_UTIL_SCOPES:
            return SearchDecision(
                SearchDisposition.NO_SEARCH,
                "document_util_scope",
                latest_user_question(messages),
                evidence_required=False,
            )
        decision = decide_search(latest_user_question(messages), task_id=skill.id)
        # #6090: automatic search is a factuality feature, and its query is the
        # user's words. A body longer than the search provider's query contract
        # is a document: sending it would both export the whole body and be
        # refused. The turn then answers without retrieval (and, for a
        # current-fact question, says so in Korean) rather than failing at 422.
        if decision.requires_search and len(decision.query) > MAX_QUERY_CHARS:
            return SearchDecision(
                SearchDisposition.NO_SEARCH,
                AUTOMATIC_SEARCH_OVER_QUERY_CAP,
                decision.query,
                evidence_required=decision.evidence_required,
            )
        # Automatic grounding is a live factuality feature. Preview providers created
        # from mock Settings explicitly disable it. MockWebProvider evidence is QA-only
        # and must never silently count as current-world verification.
        if decision.requires_search and (
            not self._automatic_search_enabled
            or isinstance(self._web_provider, MockWebProvider)
        ):
            return SearchDecision(
                SearchDisposition.NO_SEARCH,
                "preview_auto_search_disabled",
                decision.query,
            )
        return decision

    async def prepare(
        self,
        messages: list[dict[str, str]],
        *,
        skill: TaskMode,
        additional_system_context: str | None,
        explicit_search: bool = False,
        util_scope: str | None = None,
    ) -> AutoGroundingPlan:
        decision = self.decide(messages, skill=skill, explicit_search=explicit_search, util_scope=util_scope)
        if not decision.requires_search:
            # The stream path has no other place to disclose a length-driven
            # skip, and a current-fact question must not look unsearched-but-fine.
            error = None
            if decision.reason == AUTOMATIC_SEARCH_OVER_QUERY_CAP and decision.evidence_required:
                error = search_query_too_long_error()
            return AutoGroundingPlan(decision=decision, prepared=None, error=error)

        try:
            prepared = await prepare_search_grounding(
                self._core_provider,
                decision.query,
                additional_system_context=additional_system_context,
                max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
            )
        except GroundingRuntimeError as exc:
            error = _translate_core_error(exc)
            if auto_grounding_may_continue(decision, error):
                return AutoGroundingPlan(decision=decision, prepared=None, error=error)
            raise error from exc

        return AutoGroundingPlan(decision=decision, prepared=prepared)
