"""Pure conversation compaction adapted from OpenCode (MIT).

Source: https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/compaction.ts
Copyright (c) 2025 opencode. See THIRD_PARTY_NOTICES.md.
The caller owns model invocation, token accounting and persistence.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

HEADINGS = ("완료한 것", "진행 중", "남은 일", "중요한 파일·경로")
SUMMARY_PROMPT = (
    "다음 대화 기록을 이어서 작업할 수 있도록 요약하세요. "
    "사실을 지어내지 말고 아래 네 개의 제목을 순서대로 모두 사용하세요:\n"
    + "\n".join("## " + heading for heading in HEADINGS)
)
DEFAULT_KEEP_RECENT = 8


def needs_compaction(messages: Sequence[Mapping[str, Any]], token_budget: int) -> bool:
    """Compare a conservative text-size estimate with a caller-provided budget.

    An actual tokenizer/provider count is not available in this pure interface.
    Count the larger of character count and UTF-8 bytes / 4; this estimate is
    intentionally conservative for Korean and is not an exact model token count.
    """
    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
        raise ValueError("token_budget must be a positive integer")
    text = json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))
    estimate = max(len(text), (len(text.encode("utf-8")) + 3) // 4)
    return estimate > token_budget


def compact(
    messages: Sequence[Mapping[str, Any]],
    summarize_fn: Callable[[list[Mapping[str, Any]], str], str],
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> dict[str, Any]:
    """Summarize older non-user messages; preserve all user turns and the tail.

    summarize_fn receives (older_non_user_messages, SUMMARY_PROMPT). It must
    return text with all four headings. The original messages are not mutated.
    Only removed messages are reported in dropped_ids, in original order.
    """
    if isinstance(keep_recent, bool) or not isinstance(keep_recent, int) or keep_recent < 0:
        raise ValueError("keep_recent must be a non-negative integer")
    if not callable(summarize_fn):
        raise TypeError("summarize_fn must be callable")
    source = list(messages)
    if any(not isinstance(message, Mapping) for message in source):
        raise ValueError("messages must contain mappings")
    tail_start = max(0, len(source) - keep_recent)
    kept = [message for index, message in enumerate(source)
            if index >= tail_start or message.get("role") == "user"]
    older = [message for index, message in enumerate(source)
             if index < tail_start and message.get("role") != "user"]
    ids = [message.get("id") for message in older]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("each removed message must have a unique non-empty id")
    if not older:
        summary = "\n".join("## " + heading for heading in HEADINGS)
    else:
        summary = summarize_fn(older, SUMMARY_PROMPT)
        if not isinstance(summary, str):
            raise ValueError("summary must be text")
        positions = [summary.find("## " + heading) for heading in HEADINGS]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            raise ValueError("summary must contain the four headings in order")
    return {"summary": summary, "kept": kept, "dropped_ids": ids}
