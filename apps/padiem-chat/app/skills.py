from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class Skill:
    id: str
    title: str
    short_description: str
    system_instruction: str
    task_type: str
    optimize_for: str
    max_tokens: int


_SKILLS = (
    Skill(
        id="auto",
        title="자동 추천",
        short_description="일반 질문에 자연스럽게 답합니다.",
        system_instruction=(
            "사용자의 요청에 직접적이고 도움이 되게 답하세요. 한국어 요청에는 자연스러운 한국어를 우선 사용하고, "
            "불필요한 전문용어와 장황한 서론은 피하세요. 확실하지 않은 사실은 단정하지 마세요."
        ),
        task_type="general",
        optimize_for="korean",
        max_tokens=700,
    ),
    Skill(
        id="explain",
        title="쉽게 설명",
        short_description="어려운 내용을 쉬운 말과 예시로 풉니다.",
        system_instruction=(
            "설명 도우미로 답하세요. 핵심부터 쉬운 말로 설명하고, 전문용어가 필요하면 바로 뜻을 풀어 주세요. "
            "가능하면 짧은 생활 예시를 하나 사용하고 사용자가 요청하지 않은 세부 이론은 과도하게 늘리지 마세요."
        ),
        task_type="general",
        optimize_for="korean",
        max_tokens=700,
    ),
    Skill(
        id="plan",
        title="계획 세우기",
        short_description="실행 가능한 순서와 선택지를 정리합니다.",
        system_instruction=(
            "계획 도우미로 답하세요. 사용자의 목표와 제약을 우선 반영하고, 실행 순서가 보이도록 단계와 선택지를 정리하세요. "
            "정보가 부족해도 안전하게 가정할 수 있는 범위에서는 최선의 초안을 먼저 제시하세요."
        ),
        task_type="general",
        optimize_for="korean",
        max_tokens=800,
    ),
    Skill(
        id="write",
        title="글쓰기",
        short_description="문장을 쓰거나 자연스럽게 다듬습니다.",
        system_instruction=(
            "글쓰기 도우미로 답하세요. 사용자가 지정한 목적, 독자, 길이, 말투를 우선 따르고, 지정이 없으면 명료하고 자연스러운 문장으로 작성하세요. "
            "사용자의 의미를 임의로 바꾸거나 사실을 새로 만들어 넣지 마세요."
        ),
        task_type="document",
        optimize_for="korean",
        max_tokens=900,
    ),
    Skill(
        id="translate",
        title="번역",
        short_description="의미와 말투를 살려 번역합니다.",
        system_instruction=(
            "번역 도우미로 답하세요. 사용자가 요청한 대상 언어로 원문의 의미, 숫자, 고유명사와 말투를 최대한 보존해 번역하세요. "
            "별도 요청이 없다면 번역문 외의 긴 해설은 붙이지 마세요."
        ),
        task_type="korean",
        optimize_for="korean",
        max_tokens=800,
    ),
    Skill(
        id="summarize",
        title="텍스트 요약",
        short_description="붙여넣은 내용을 핵심 위주로 줄입니다.",
        system_instruction=(
            "요약 도우미로 답하세요. 사용자가 제공한 텍스트 안의 정보만 근거로 핵심 주장, 중요한 수치와 결론을 보존해 간결하게 요약하세요. "
            "원문에 없는 사실을 보태지 말고, 불명확한 부분은 불명확하다고 표시하세요."
        ),
        task_type="document",
        optimize_for="korean",
        max_tokens=700,
    ),
    Skill(
        id="code",
        title="코딩 도움",
        short_description="코드 작성, 설명, 오류 해결을 돕습니다.",
        system_instruction=(
            "코딩 도우미로 답하세요. 먼저 사용자의 요구와 기존 코드 제약을 지키고, 가능한 경우 작고 검증 가능한 변경을 제안하세요. "
            "코드를 제시할 때는 필요한 부분만 정확히 보여 주고, 실행하지 않은 결과를 실행했다고 주장하지 마세요."
        ),
        task_type="coding",
        optimize_for="balanced",
        max_tokens=1000,
    ),
    Skill(
        id="brainstorm",
        title="아이디어 발상",
        short_description="여러 방향의 아이디어와 선택지를 만듭니다.",
        system_instruction=(
            "아이디어 도우미로 답하세요. 서로 겹치지 않는 여러 방향을 제안하고 각 선택지의 장점이나 적합한 상황을 짧게 구분하세요. "
            "단순히 개수를 채우기보다 사용자의 목표에 실제로 쓸 수 있는 아이디어를 우선하세요."
        ),
        task_type="general",
        optimize_for="balanced",
        max_tokens=900,
    ),
)

if len({skill.id for skill in _SKILLS}) != len(_SKILLS):
    raise RuntimeError("duplicate Padiem Chat skill id")
if any(len(skill.system_instruction) > 2_000 for skill in _SKILLS):
    raise RuntimeError("Padiem Chat skill instruction is too large")

SKILL_REGISTRY = MappingProxyType({skill.id: skill for skill in _SKILLS})


def get_skill(skill_id: str | None = None) -> Skill:
    resolved_id = "auto" if skill_id is None else skill_id
    try:
        return SKILL_REGISTRY[resolved_id]
    except KeyError as exc:
        raise ValueError("지원하지 않는 작업 모드입니다.") from exc


def skill_public_metadata(skill: Skill) -> dict[str, str]:
    return {
        "id": skill.id,
        "title": skill.title,
    }
