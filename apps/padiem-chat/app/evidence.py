from __future__ import annotations

from padiem_ai_core import Evidence as CoreEvidence


class Evidence(CoreEvidence):
    """B62 compatibility view over the shared Core Evidence contract.

    The explicit initializer preserves Padiem Chat's historical positional argument
    order while storage and validation remain owned by Core Evidence.
    """

    __slots__ = ()

    def __init__(
        self,
        id: str,
        title: str,
        url: str,
        snippet: str,
        retrieved_at: str,
        provider: str,
        source_type: str,
    ) -> None:
        CoreEvidence.__init__(
            self,
            id=id,
            title=title,
            snippet=snippet,
            retrieved_at=retrieved_at,
            provider=provider,
            source_type=source_type,
            url=url,
        )

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "source_type": self.source_type,
        }
