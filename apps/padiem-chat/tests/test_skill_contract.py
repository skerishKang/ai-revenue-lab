from __future__ import annotations

import importlib

import pytest
from padiem_ai_core import AgentProfile

from app.task_modes import TaskMode, get_task_mode, task_mode_public_metadata

def test_b62_task_modes_are_product_presets_and_the_skill_alias_is_gone():
    mode = get_task_mode("plan")

    assert isinstance(mode, TaskMode)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.skills")
    assert isinstance(mode, AgentProfile)
    assert mode.short_description == "실행 가능한 순서와 선택지를 정리합니다."
    assert mode.description == mode.short_description
    assert mode.allowed_tools == ()
    assert mode.required_capabilities == ()
    assert mode.max_steps is None
    assert task_mode_public_metadata(mode) == {"id": "plan", "title": "계획 세우기"}


def test_historical_skill_constructor_and_public_metadata_stay_compatible():
    mode = TaskMode(
        "compat_skill",
        "호환 작업",
        "호환 설명",
        "서버 소유 시스템 지침",
        "general",
        "korean",
        321,
    )

    assert isinstance(mode, TaskMode)
    assert isinstance(mode, AgentProfile)
    assert mode.id == "compat_skill"
    assert mode.title == "호환 작업"
    assert mode.short_description == "호환 설명"
    assert mode.system_instruction == "서버 소유 시스템 지침"
    assert mode.task_type == "general"
    assert mode.optimize_for == "korean"
    assert mode.max_tokens == 321
    assert task_mode_public_metadata(mode) == {"id": "compat_skill", "title": "호환 작업"}
    assert "system_instruction" not in mode.to_public_dict()
