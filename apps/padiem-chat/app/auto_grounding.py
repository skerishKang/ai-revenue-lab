from __future__ import annotations

from dataclasses import dataclass

from padiem_ai_core.grounding_runtime import GroundingRuntimeError, PreparedGrounding
from padiem_ai_core.search_decision import SearchDecision, SearchDisposition, decide_search
from padiem_ai_core.search_preparation import prepare_search_grounding

from .b14_client import MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS
from .grounding import GroundingError, _CoreWebProviderAdapter, _translate_core_error
from .task_modes import TaskMode
from .web_tools import MockWebProvider, WebProvider


@dataclass(frozen=True, slots=True)
class AutoGroundingPlan:
    decision: SearchDecision
    prepared: PreparedGrounding | None

    @property
    def searched(self) -> bool:
        return self.prepared is not None


def auto_grounding_may_continue(decision: SearchDecision, error: GroundingError) -> bool:
    """Whether a failed automatic search may continue as a normal answer.

    Only an AUTOMATIC search may continue. The search already ran and produced
    no usable evidence, and the request does not depend on current external
    facts, so the ordinary model answer is produced WITHOUT any evidence or
    source. An explicit user search request and a request about a current
    external fact (weather, news, rates) keep the honest failure, so a missing
    web result is never presented as a verified current fact.
    """
    return (
        error.code == "no_evidence"
        and decision.reason != "explicit_search_request"
        and not decision.evidence_required
    )


def latest_user_question(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            text = item["content"].strip()
            if text:
                return text
    raise GroundingError(422, "tool_input_required", "검색 여부를 판단할 사용자 질문이 필요합니다.")


class AutoGroundingService:
    """B62 consumer of Core-owned search decision and grounding contracts."""

    def __init__(self, web_provider: WebProvider):
        self._web_provider = web_provider
        self._core_provider = _CoreWebProviderAdapter(web_provider)
        self._automatic_search_enabled = bool(
            getattr(web_provider, "_automatic_search_enabled", True)
        )

    def decide(self, messages: list[dict[str, str]], *, skill: TaskMode, explicit_search: bool = False) -> SearchDecision:
        if explicit_search:
            return SearchDecision(SearchDisposition.MUST_SEARCH, "explicit_search_request", latest_user_question(messages))
        decision = decide_search(latest_user_question(messages), task_id=skill.id)
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
    ) -> AutoGroundingPlan:
        decision = self.decide(messages, skill=skill, explicit_search=explicit_search)
        if not decision.requires_search:
            return AutoGroundingPlan(decision=decision, prepared=None)

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
                # The automatic search found no usable evidence and the request
                # does not need it. The turn continues as a normal answer and
                # no source is shown.
                return AutoGroundingPlan(decision=decision, prepared=None)
            raise error from exc

        return AutoGroundingPlan(decision=decision, prepared=prepared)
