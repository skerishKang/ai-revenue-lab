from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.models import ProviderResult


@runtime_checkable
class AIProvider(Protocol):
    """Provider-neutral structured generation protocol.

    Implementations must never open a network socket. The MockProvider is the
    only implementation used by the MVP and is fully programmable offline.
    """

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult: ...
