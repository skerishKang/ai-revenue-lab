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
from .task_modes import TaskMode
from .tool_presentations import ToolPresentationDescriptor
from .web_tools import (
    MAX_QUERY_CHARS,
    SEARCH_QUERY_TOO_LONG_CODE,
    SEARCH_QUERY_TOO_LONG_MESSAGE,
    WebProvider,
    WebToolError,
)


_RESEARCH_PLANNER_SKILL = TaskMode(
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

_DEEP_RESEARCH_SKILL = TaskMode(
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
    # Final user-visible synthesis is not a 1,500-token internal planning job.
    # Let the selected provider/model decide response length.
    max_tokens=None,
)


@dataclass
class GroundingError(Exception):
    status_code: int
    code: str
    user_message: str
    source_code: str | None = None

    def __str__(self) -> str:
        return self.user_message


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            text = item["content"].strip()
            if text:
                return text
    raise GroundingError(422, "tool_input_required", "검색에 사용할 사용자 질문이 필요합니다.")


def _to_core_evidence(item: CoreEvidence) -> CoreEvidence:
    """Keep Core evidence authority; B62 Evidence subclasses pass through."""
    if not isinstance(item, CoreEvidence):
        raise TypeError("grounding requires Core Evidence")
    return item


class _CoreWebProviderAdapter:
    """Translate the existing B62 WebProvider boundary into the shared Core protocol."""

    def __init__(self, provider: WebProvider):
        self._provider = provider

    async def search(self, query: str, limit: int = 5) -> list[CoreEvidence]:
        try:
            found = await self._provider.search(query, limit=limit)
        except WebToolError as exc:
            raise WebRuntimeError(exc.code, exc.user_message, exc.status_code) from exc
        except Exception as exc:
            raise WebRuntimeError("web_unavailable", "웹 검색을 사용할 수 없습니다.", 502) from exc
        if not isinstance(found, (list, tuple)):
            raise WebRuntimeError("web_invalid_response", "웹 검색 응답 형식을 확인하지 못했습니다.", 502)
        return [_to_core_evidence(item) for item in found if isinstance(item, CoreEvidence)]

    async def fetch(self, url: str) -> CoreEvidence:
        try:
            item = await self._provider.fetch(url)
        except WebToolError as exc:
            raise WebRuntimeError(exc.code, exc.user_message, exc.status_code) from exc
        except Exception as exc:
            raise WebRuntimeError("web_unavailable", "웹 검색을 사용할 수 없습니다.", 502) from exc
        if not isinstance(item, CoreEvidence):
            raise WebRuntimeError("web_invalid_response", "웹 근거 응답 형식이 올바르지 않습니다.", 502)
        return _to_core_evidence(item)


def _translate_core_error(exc: GroundingRuntimeError) -> GroundingError:
    # Input/URL validation remains a refusal; provider errors never borrow
    # the model authentication vocabulary or echo a provider response.
    if exc.code in {"invalid_tool_input", "tool_input_required", "unsupported_tool"}:
        return GroundingError(exc.status_code, exc.code, "검색 요청 형식이 올바르지 않습니다.")
    if exc.code in {"no_evidence", "web_grounding_no_evidence"}:
        return GroundingError(exc.status_code, "web_grounding_no_evidence", "웹 근거를 찾지 못했습니다.", source_code=exc.code)
    if exc.status_code in {401, 403} or exc.code in {"upstream_auth_error", "web_grounding_auth_error"}:
        return GroundingError(exc.status_code, "web_grounding_auth_error", "웹 검색 인증을 확인하지 못했습니다.", source_code=exc.code)
    return GroundingError(exc.status_code, "web_grounding_unavailable", "웹 검색을 사용할 수 없습니다.", source_code=exc.code)


def search_query_too_long_error() -> GroundingError:
    """#6090: the request is longer than any query the search provider accepts.

    Not a turn-ending client error: the provider's query contract is the real
    limit, so the same selected model answers without web evidence and the
    Korean guidance names both ways forward (split it, or attach the file).
    """
    return GroundingError(413, SEARCH_QUERY_TOO_LONG_CODE, SEARCH_QUERY_TOO_LONG_MESSAGE)


def grounding_fallback_fields(error: GroundingError) -> dict:
    # #6090: checked before the translation, which folds unknown codes into the
    # generic web-grounding family.
    if error.code == SEARCH_QUERY_TOO_LONG_CODE:
        # The degradation notice is the actionable Korean guidance, not the
        # generic "웹 검색을 사용할 수 없어" line, because the cause here is the
        # shape of the user's own request and the user can fix it.
        return {
            "notice": SEARCH_QUERY_TOO_LONG_MESSAGE,
            "metadata": {"web_grounding_error": SEARCH_QUERY_TOO_LONG_CODE},
        }
    error = _translate_core_error(GroundingRuntimeError(error.code, "", error.status_code))
    if error.code not in {"web_grounding_auth_error", "web_grounding_unavailable", "web_grounding_no_evidence"}:
        error = GroundingError(error.status_code, "web_grounding_unavailable", "웹 검색을 사용할 수 없습니다.")
    notice = (
        "웹 근거를 찾지 못해 근거 없이 답변합니다"
        if error.code == "web_grounding_no_evidence"
        else "웹 검색을 사용할 수 없어 근거 없이 답변합니다"
    )
    return {"notice": notice, "metadata": {"web_grounding_error": error.code}}


def prepare_grounding_context(
    evidence_items: list[CoreEvidence],
    *,
    max_context_chars: int = MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS,
    max_sources: int = MAX_GROUNDED_SOURCES,
) -> PreparedGrounding:
    try:
        return core_prepare_grounding_context(
            [_to_core_evidence(item) for item in evidence_items if isinstance(item, CoreEvidence)],
            max_context_chars=max_context_chars,
            max_sources=max_sources,
        )
    except GroundingRuntimeError as exc:
        raise _translate_core_error(exc) from exc


def build_grounding_context(evidence_items: list[CoreEvidence]) -> str:
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
        tool: ToolPresentationDescriptor,
        tool_input: str | None,
        additional_system_context: str | None,
    ) -> dict:
        query = (tool_input or _latest_user_message(messages)).strip()
        if not query:
            raise GroundingError(422, "invalid_tool_input", "검색할 내용을 한 줄로 알려 주세요.")
        if len(query) > MAX_QUERY_CHARS:
            raise search_query_too_long_error()

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
            error = _translate_core_error(exc)
            if not error.code.startswith("web_grounding_"):
                raise error from exc
            result = await self._b14_client.complete(
                messages, skill=_DEEP_RESEARCH_SKILL,
                additional_system_context=additional_system_context,
            )
            return {**result, **grounding_fallback_fields(error)}

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
        skill: TaskMode,
        tool: ToolPresentationDescriptor,
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
                if not query:
                    raise GroundingError(422, "invalid_tool_input", "검색할 내용을 한 줄로 알려 주세요.")
                if len(query) > MAX_QUERY_CHARS:
                    raise search_query_too_long_error()
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
            error = _translate_core_error(exc)
            if not error.code.startswith("web_grounding_"):
                raise error from exc
            result = await self._b14_client.complete(
                messages, skill=skill,
                additional_system_context=additional_system_context,
            )
            return {**result, **grounding_fallback_fields(error)}

        result = grounded.synthesis
        return {
            **result,
            "answer_status": "answered_with_evidence",
            "evidence": [item.to_public_dict() for item in grounded.prepared.evidence],
            "tool": {"id": tool.id, "title": tool.title},
        }
