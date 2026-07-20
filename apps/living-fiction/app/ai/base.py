"""AIProvider protocol — provider-neutral structured generation boundary.

Independent from sibling apps. Any provider implementing this protocol
can generate structured episode plans and content. In Phase 1, only
MockProvider is used (network-free, deterministic).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.models import ProviderResult


@runtime_checkable
class AIProvider(Protocol):
    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult: ...
