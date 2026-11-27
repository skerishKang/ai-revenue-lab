"""B54 Claw general composer: shared request/response contract constants (#7809).

Moved verbatim out of ``claw_general_routes``, which re-exports every name so existing
importers keep working. Constants only: no imports, no logic, no state.
"""

from __future__ import annotations

# This is the existing Chat HTTP resource envelope, not a provider/model cap.
# The separate P01 Engine ingress guard remains in force until #4383 is resolved.
# #4379: the Claw request body carries no PADIEM byte total. The reader
# stays incremental.
MAX_CLAW_GENERAL_BODY_BYTES: int | None = None
# Kept importable for older clients; None means no Claw-general pilot text cap.
MAX_CLAW_GENERAL_MESSAGE_CHARS: int | None = None
MAX_CLAW_GENERAL_MESSAGES: int | None = None
# #4379: the owned prior context is not cut to a PADIEM transport envelope.
# The Engine applies its own request contract; nothing is silently truncated.
P01_ENGINE_REQUEST_ENVELOPE_BYTES: int | None = None
CLAW_LIVE_REQUEST_HEADER = "X-Padiem-Claw-Live"
CLAW_LIVE_REQUEST_MARKER = "p01-events-v1"

# NO_EXECUTABLE_ROUTE product HOLD (#3568/#3566): these adapter codes mean the
# run was refused before any Engine/B14/provider dispatch because the selected
# tier has no executable route yet. They are product states, not engine
# failures, so they must not surface as a generic 502 engine error.
_MODEL_HOLD_ERROR_CODES = frozenset({"tier_hold", "max_tier_hold"})
_MODEL_HOLD_USER_MESSAGE = (
    "선택한 AI 모델을 현재 사용할 수 없습니다. 다른 모델을 선택해 주세요."
)
