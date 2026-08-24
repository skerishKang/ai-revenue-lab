from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    title: str
    url: str
    snippet: str
    retrieved_at: str
    provider: str
    source_type: str

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
