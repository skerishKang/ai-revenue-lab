from __future__ import annotations

from types import MappingProxyType

from padiem_ai_core import AgentProfile


class TaskMode(AgentProfile):
    """B62 user-facing task metadata backed by Core's profile contract.

    A TaskMode remains a product UX choice for one request. It is not a reusable
    installable Skill, does not grant tools or authorization, and does not impose
    a hidden answer style or response-length limit.
    """

    __slots__ = ()

    def __init__(
        self,
        id: str,
        title: str,
        short_description: str,
        system_instruction: str | None,
        task_type: str,
        optimize_for: str,
        max_tokens: int | None,
    ) -> None:
        AgentProfile.__init__(
            self,
            id=id,
            title=title,
            description=short_description,
            system_instruction=system_instruction,
            task_type=task_type,
            optimize_for=optimize_for,
            max_tokens=max_tokens,
        )

    @property
    def short_description(self) -> str:
        return self.description


_TASK_MODES = (
    TaskMode(
        id="auto",
        title="자동 추천",
        short_description="일반 질문에 자연스럽게 답합니다.",
        system_instruction=None,
        task_type="general",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="explain",
        title="쉽게 설명",
        short_description="어려운 내용을 쉬운 말과 예시로 풉니다.",
        system_instruction=None,
        task_type="general",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="plan",
        title="계획 세우기",
        short_description="실행 가능한 순서와 선택지를 정리합니다.",
        system_instruction=None,
        task_type="general",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="write",
        title="글쓰기",
        short_description="문장을 쓰거나 자연스럽게 다듬습니다.",
        system_instruction=None,
        task_type="document",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="translate",
        title="번역",
        short_description="의미와 말투를 살려 번역합니다.",
        system_instruction=None,
        task_type="korean",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="summarize",
        title="텍스트 요약",
        short_description="붙여넣은 내용을 핵심 위주로 줄입니다.",
        system_instruction=None,
        task_type="document",
        optimize_for="korean",
        max_tokens=None,
    ),
    TaskMode(
        id="code",
        title="코딩 도움",
        short_description="코드 작성, 설명, 오류 해결을 돕습니다.",
        system_instruction=None,
        task_type="coding",
        optimize_for="balanced",
        max_tokens=None,
    ),
    TaskMode(
        id="brainstorm",
        title="아이디어 발상",
        short_description="여러 방향의 아이디어와 선택지를 만듭니다.",
        system_instruction=None,
        task_type="general",
        optimize_for="balanced",
        max_tokens=None,
    ),
)

if len({mode.id for mode in _TASK_MODES}) != len(_TASK_MODES):
    raise RuntimeError("duplicate Padiem Chat task mode id")

TASK_MODE_REGISTRY = MappingProxyType({mode.id: mode for mode in _TASK_MODES})


def get_task_mode(mode_id: str | None = None) -> TaskMode:
    resolved_id = "auto" if mode_id is None else mode_id
    try:
        return TASK_MODE_REGISTRY[resolved_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 작업 모드입니다.") from exc


def task_mode_public_metadata(mode: TaskMode) -> dict[str, str]:
    return {"id": mode.id, "title": mode.title}