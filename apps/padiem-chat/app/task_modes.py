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
        id="plan",
        title="계획 세우기",
        short_description="실행 가능한 순서와 선택지를 정리합니다.",
        system_instruction=None,
        task_type="general",
        optimize_for="korean",
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