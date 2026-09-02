from __future__ import annotations

from app.task_modes import TASK_MODE_REGISTRY, get_task_mode


def test_builtin_task_modes_do_not_impose_hidden_system_instructions_or_length_caps() -> None:
    assert TASK_MODE_REGISTRY
    for mode in TASK_MODE_REGISTRY.values():
        assert mode.system_instruction is None
        assert mode.max_tokens is None


def test_default_auto_mode_is_unconstrained() -> None:
    mode = get_task_mode()

    assert mode.id == "auto"
    assert mode.system_instruction is None
    assert mode.max_tokens is None
