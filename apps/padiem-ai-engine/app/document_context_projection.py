"""Context-window projection of a resolved document for Engine E5B-S3 (#1750).

Projects the canonical Core ``NormalizedDocument`` into the smallest view that
is safe to mount in an LLM context window: validated metadata plus a bounded
prefix preview. Storage locators, ``att_*`` references, caller scope and full
segment bodies never cross into this projection (evidence retention owns the
full body). The projection is read-only derivation: it mutates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from padiem_ai_core.document_normalization import NormalizedDocument

logger = logging.getLogger("padiem.engine.document_context_projection")

MAX_CONTEXT_PREVIEW_CHARS = 40_000
DEFAULT_CONTEXT_MAX_TEXT_CHARS = 4_000
DEFAULT_CONTEXT_MAX_SEGMENTS = 10
TRUNCATION_STRATEGIES = frozenset({"prefix"})


class ContextTruncationPolicy:
    """Bounded prefix truncation for context-mounted document text."""

    def __init__(
        self,
        *,
        max_text_chars: int = DEFAULT_CONTEXT_MAX_TEXT_CHARS,
        max_segments: int = DEFAULT_CONTEXT_MAX_SEGMENTS,
        strategy: str = "prefix",
    ) -> None:
        if isinstance(max_text_chars, bool) or not isinstance(max_text_chars, int) or not 1 <= max_text_chars <= MAX_CONTEXT_PREVIEW_CHARS:
            raise ValueError("context preview budget is out of bounds")
        if isinstance(max_segments, bool) or not isinstance(max_segments, int) or not 1 <= max_segments <= 512:
            raise ValueError("context segment budget is out of bounds")
        if strategy not in TRUNCATION_STRATEGIES:
            raise ValueError("only the prefix truncation strategy is implemented in S3")
        self.max_text_chars = max_text_chars
        self.max_segments = max_segments
        self.strategy = strategy

    @staticmethod
    def truncate_text(text: str, max_chars: int) -> str:
        """Keep the first ``max_chars`` characters and mark the dropped size."""

        if not isinstance(text, str):
            raise ValueError("truncation requires a string")
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("truncation budget must be a positive integer")
        if len(text) <= max_chars:
            return text
        dropped = len(text) - max_chars
        return text[:max_chars] + f"... [truncated {dropped} chars]"


@dataclass(frozen=True, slots=True)
class ContextWindowProjection:
    """Context-window-safe view of one normalized document.

    Never contains: the full segment body, a ``DocumentLocator``, an ``att_*``
    reference, a storage locator, or any caller scope identifier.
    """

    kind: str
    name: str
    media_type: str
    byte_size: int
    text_chars: int
    segment_count: int
    status: str
    content_trust_class: str
    truncated_text_preview: str | None

    @classmethod
    def from_normalized(
        cls,
        doc: NormalizedDocument,
        *,
        max_text_chars: int = DEFAULT_CONTEXT_MAX_TEXT_CHARS,
        max_segments: int = DEFAULT_CONTEXT_MAX_SEGMENTS,
    ) -> "ContextWindowProjection":
        if not isinstance(doc, NormalizedDocument):
            raise ValueError("context projection requires a canonical NormalizedDocument")
        policy = ContextTruncationPolicy(max_text_chars=max_text_chars, max_segments=max_segments)
        if doc.segment_count > policy.max_segments:
            logger.warning(
                "document segments exceed the context budget and were truncated for projection"
            )
        included = doc.segments[: policy.max_segments]
        joined = "\n".join(segment.text for segment in included)
        preview = policy.truncate_text(joined, policy.max_text_chars)
        return cls(
            kind=doc.kind.value if doc.kind is not None else "unknown",
            name=doc.name,
            media_type=doc.media_type,
            byte_size=doc.byte_size,
            text_chars=doc.text_chars,
            segment_count=doc.segment_count,
            status=doc.status.value,
            content_trust_class=doc.content_trust_class,
            truncated_text_preview=preview,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
            "text_chars": self.text_chars,
            "segment_count": self.segment_count,
            "status": self.status,
            "content_trust_class": self.content_trust_class,
            "truncated_text_preview": self.truncated_text_preview,
        }
