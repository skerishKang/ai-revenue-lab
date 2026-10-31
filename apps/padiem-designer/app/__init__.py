"""PADIEM Designer — generative UI preview app (#5513).

The app turns a plain-language request into an interactive UI that the user can
operate, and lets the next AI turn see what the user changed.

Its generative-UI contract is reused from the pinned MIT upstream
``CopilotKit/OpenIntelligentUI`` release: the same tool name, the same
parameter order, the same sandbox rules. See ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

from .contracts import (
    DESIGNER_TOOL_NAME,
    GeneratedUi,
    InteractionState,
    ModelTurn,
    UiRequest,
    UiTurnResult,
)

__all__ = (
    "DESIGNER_TOOL_NAME",
    "GeneratedUi",
    "InteractionState",
    "ModelTurn",
    "UiRequest",
    "UiTurnResult",
)
