"""AIProvider protocol — provider-neutral structured generation boundary.

Independent from sibling apps. Any provider implementing this protocol
can generate structured episode plans and content. In Phase 1, only
MockProvider is used (network-free, deterministic).

The protocol now includes identity contract:
- provider_name: stable provider identifier
- model: advertised model name
- cost_class: cost tier (free/paid/local/unknown)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.enums import CostClass
from app.domain.models import ProviderResult


@runtime_checkable
class AIProvider(Protocol):
    @property
    def provider_name(self) -> str:
        """Stable provider identifier (e.g. 'openai', 'anthropic', 'mock')."""
        ...

    @property
    def model(self) -> str:
        """Advertised model name (e.g. 'gpt-4', 'claude-3', 'mock-living-fiction-v1')."""
        ...

    @property
    def cost_class(self) -> CostClass:
        """Cost tier classification."""
        ...

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult: ...
