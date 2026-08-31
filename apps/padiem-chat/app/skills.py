"""Compatibility aliases for the historical B62 Skill API.

B62 presets are TaskModes, not reusable/installable Core Skills. Keep these
names temporarily so existing callers and stored request values remain valid.
"""

from __future__ import annotations

from .task_modes import (
    TASK_MODE_REGISTRY,
    TaskMode,
    get_task_mode,
    task_mode_public_metadata,
)

Skill = TaskMode
SKILL_REGISTRY = TASK_MODE_REGISTRY


def get_skill(skill_id: str | None = None) -> TaskMode:
    return get_task_mode(skill_id)


def skill_public_metadata(skill: TaskMode) -> dict[str, str]:
    return task_mode_public_metadata(skill)


__all__ = [
    "Skill",
    "SKILL_REGISTRY",
    "get_skill",
    "skill_public_metadata",
    "TASK_MODE_REGISTRY",
    "TaskMode",
    "get_task_mode",
    "task_mode_public_metadata",
]
