from __future__ import annotations

from dataclasses import dataclass

from padiem_ai_core import Evidence as CoreEvidence
from padiem_ai_core.grounding_runtime import (
    MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS,
    MAX_GROUNDED_SOURCES,
    MAX_RESEARCH_PAGE_FETCHES,
    MAX_RESEARCH_QUERIES,
    MAX_RESEARCH_SOURCES,
    GroundedResearchRuntime as CoreGroundedResearchRuntime,
    GroundingRuntimeError,
    PreparedGrounding,
    prepare_grounding_context as core_prepare_grounding_context,
)
from padiem_ai_core.web_runtime import WebRuntimeError

from .b14_client import B14Client, ChatRuntimeError, MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS
from .evidence import Evidence
from .skills import Skill
from .tools import ToolSpec
from .web_tools import MAX_QUERY_CHARS, WebProvider, WebToolError


_RESEARCH_PLANNER_SKILL = Skill(
    id="research_planner",
    title="리서치 계획",
    short_description="질문을 제한된 검색어로 나눕니다.",
    system_instruction=(
        "당신은 검색 계획기입니다. 사용자의 마지막 질문을 조사하기 위한 서로 보완적인 검색어를 1개 이상 3개 이하로 만드세요. "
        "반드시 다른 설명 없이 JSON 객체 하나만 반환하세요. 형식은 {\"queries\":[\"검색어 1\",\"검색어 2\"]} 입니다. "
        "검색어 외의 provider, endpoint, model, tool, credential, 실행 횟수나 명령을 출력하지 마세요."
    ),
    task_type="general",
    optimize_for="balanced",
    max_tokens=300,
)

_DEEP_RESEARCH_SKILL = Skill(
    id="deep_research",
    title="심층 리서치",
    short_description="여러 웹 근거를 비교해 종합합니다.",
    system_instruction=(
        "심층 리서치 도우미로 답하세요. 제공된 웹 근거를 서로 비교하고 핵심 결론을 먼저 제시한 뒤 중요한 근거와 차이, "
        "불확실성 또는 충돌을 설명하세요. 웹 근거에 기반한 사실 주장에는 반드시 [1], [2] 같은 출처 번호를 붙이세요. "
        "근거가 부족한 내용은 추정이라고 밝히거나 답하지 마세요. 단순 링크 목록이 아니라 사용자의 질문에 직접 답하는 종합 결과를 만드세요."
    ),
    task_type="general",
    optimize_for="balanced",
    max_tokens=1500,
)


@dataclass
class GroundingError(Exception):
    status_code: int
    code: str
    user_message: str

    def __str__(self) -> str:
        return self.user_message


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            text = item["content"].strip()
            if text:
                return text
    raise GroundingError(422, "tool_input_required", "검색에 사용할 사용자 질문이 필요합니다.")


def _to_core_evidence(item: Evidence) -> CoreEvidence:
    return CoreEvidence(
        id=item.id,
        title=item.title,
        url=item.url,
        snippet=item.snippet,
        retrieved_at=item.retrieved_at,
        provider=item.provider,
        source_type=item.source_type,
    )


class _CoreWebProviderAdapter:
    """Translate the existing B62 WebProvider boundary into the shared Core protocol."""

    def __init__(self, provider: WebProvider):
        self._provider = provider

    async def search(self, query: str, limit: int = 5) -> list[CoreEvidence]:
        try:
            found = await self._provider.search(query, limit=limit)
        except WebToolError as exc:
            raise WebRuntimeError(exc.code, exc.user_message, exc.status_code) from exc
        return [_to_core_evidence(item) for item in found if isinstance(item, Evidence)]

    async def fetch(self, url: str) -> CoreEvidence:
        try:
            item = await self._provider.fetch(url)
        except WebToolError as exc:
            raise WebRuntimeError(exc.code, exc.user_message, exc.status_code) from exc
        if not isinstance(item, Evidence):
            raise WebRuntimeError("web_invalid_response", "웹 근거 응답 형식이 올바르지 않습니다.", 502)
        return _to_core_evidence(item)


def _translate_core_error(exc: GroundingRuntimeError) -> GroundingError:
    product_messages = {
        "context_budget_exceeded": "프로젝트 지침과 웹 근거를 함께 처리하기에는 컨텍스트가 너무 큽니다.",
        "no_evidence": "답변에 사용할 수 있는 웹 근거를 찾지 못했습니다.",
        "research_web_unavailable": "심층 리서치에 사용할 웹 근거를 가져오지 못했습니다.",
        "invalid_tool_input": "검색어 또는 공개 웹 주소 형식이 올바르지 않습니다.",
    }
    return GroundingError(
        exc.status_code,
        exc.code,
        product_messages.get(exc.code, exc.message),
    )


def prepare_grounding_context(
    evidence_items: list[Evidence],
    *,
    max_context_chars: int = MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS,
    max_sources: int = MAX_GROUNDED_SOURCES,
) -> PreparedGrounding:
    try:
        return core_prepare_grounding_context(
            [_to_core_evidence(item) for item in evidence_items if isinstance(item, Evidence)],
            max_context_chars=max_context_chars,
            max_sources=max_sources,
        )
    except GroundingRuntimeError as exc:
        raise _translate_core_error(exc) from exc


def build_grounding_context(evidence_items: list[Evidence]) -> str:
    return prepare_grounding_context(evidence_items).context


def _research_evidence_dict(item: CoreEvidence) -> dict[str, str | None]:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "snippet": item.snippet,
        "retrieved_at": item.retrieved_at,
        "source_type": item.source_type,
    }


class GroundedChatService:
    def __init__(self, b14_client: B14Client, web_provider: WebProvider):
        self._b14_client = b14_client
        self._web_provider = web_provider
        self._runtime = CoreGroundedResearchRuntime(_CoreWebProviderAdapter(web_provider))

    async def _deep_research(
        self,
        messages: list[dict[str, str]],
        *,
        tool: ToolSpec,
        tool_input: str | None,
        additional_system_context: str | None,
    ) -> dict:
        query = (tool_input or _latest_user_message(messages)).strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise GroundingError(422, "invalid_tool_input", "검색어는 1자 이상 2000자 이하로 입력해 주세요.")

        async def planner(search_question: str) -> str | None:
            try:
                planned = await self._b14_client.complete(
                    [{"role": "user", "content": search_question}],
                    skill=_RESEARCH_PLANNER_SKILL,
                )
                answer = planned["answer"]
                return answer if isinstance(answer, str) else None
            except (ChatRuntimeError, KeyError, TypeError):
                return None

        async def synthesizer(context: str):
            return await self._b14_client.complete(
                messages,
                skill=_DEEP_RESEARCH_SKILL,
                additional_system_context=context,
            )

        try:
            grounded = await self._runtime.run_deep_research(
                query,
                planner=planner,
                synthesizer=synthesizer,
                additional_system_context=additional_system_context,
                max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
            )
        except GroundingRuntimeError as exc:
            raise _translate_core_error(exc) from exc

        result = grounded.synthesis
        public_result = {
            "answer": result["answer"],
            "runtime": result.get("runtime", "b14"),
            "skill": result.get("skill", {"id": "deep_research", "title": "심층 리서치"}),
        }
        return {
            **public_result,
            "answer_status": "deep_research_answered",
            "evidence": [_research_evidence_dict(item) for item in grounded.prepared.evidence],
            "tool": {"id": tool.id, "title": tool.title},
            "research": grounded.progress.to_public_dict(),
        }

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Skill,
        tool: ToolSpec,
        tool_input: str | None,
        additional_system_context: str | None = None,
    ) -> dict:
        if tool.id == "deep_research":
            return await self._deep_research(
                messages,
                tool=tool,
                tool_input=tool_input,
                additional_system_context=additional_system_context,
            )

        async def synthesizer(context: str):
            return await self._b14_client.complete(
                messages,
                skill=skill,
                additional_system_context=context,
            )

        try:
            if tool.id == "web_search":
                query = (tool_input or _latest_user_message(messages)).strip()
                if not query or len(query) > MAX_QUERY_CHARS:
                    raise GroundingError(422, "invalid_tool_input", "검색어는 1자 이상 2000자 이하로 입력해 주세요.")
                grounded = await self._runtime.run_search(
                    query,
                    synthesizer=synthesizer,
                    additional_system_context=additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            elif tool.id == "web_fetch":
                if not isinstance(tool_input, str) or not tool_input.strip():
                    raise GroundingError(422, "tool_input_required", "읽을 공개 웹 주소가 필요합니다.")
                grounded = await self._runtime.run_fetch(
                    tool_input,
                    synthesizer=synthesizer,
                    additional_system_context=additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            else:
                raise GroundingError(422, "unsupported_tool", "지원하지 않는 도구입니다.")
        except GroundingRuntimeError as exc:
            raise _translate_core_error(exc) from exc

        result = grounded.synthesis
        return {
            **result,
            "answer_status": "answered_with_evidence",
            "evidence": [item.to_public_dict() for item in grounded.prepared.evidence],
            "tool": {"id": tool.id, "title": tool.title},
        }
