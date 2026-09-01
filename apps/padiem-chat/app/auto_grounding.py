from __future__ import annotations

from dataclasses import dataclass
import os

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


def latest_user_question(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            text = item["content"].strip()
            if text:
                return text
    raise GroundingError(422, "tool_input_required", "검색 여부를 판단할 사용자 질문이 필요합니다.")


def _mock_runtime_active() -> bool:
    return os.getenv("PADIEM_CHAT_RUNTIME_MODE", "").strip().lower() == "mock"


class AutoGroundingService:
    """B62 consumer of Core-owned search decision and grounding contracts."""

    def __init__(self, web_provider: WebProvider):
        self._web_provider = web_provider
        self._core_provider = _CoreWebProviderAdapter(web_provider)

    def decide(self, messages: list[dict[str, str]], *, skill: TaskMode) -> SearchDecision:
        decision = decide_search(latest_user_question(messages), task_id=skill.id)
        # Automatic grounding is a live factuality feature. Preview/mock runtime must
        # preserve its deterministic zero-network answer path, and MockWebProvider
        # evidence is QA-only rather than truthful current-world verification.
        if decision.requires_search and (
            _mock_runtime_active() or isinstance(self._web_provider, MockWebProvider)
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
    ) -> AutoGroundingPlan:
        decision = self.decide(messages, skill=skill)
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
            raise _translate_core_error(exc) from exc

        return AutoGroundingPlan(decision=decision, prepared=prepared)
