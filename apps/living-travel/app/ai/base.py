"""AI provider protocol for Living Travel."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.models import ProviderResult


_DEFAULT_ATTEMPT_LIMIT = 1


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI generation providers.

    Attributes
    ----------
    attempt_limit : int
        Maximum number of outbound requests per task.

    The provider must enforce this limit — it may fail fast or return
    ``ProviderResult(success=False)`` after the limit is exceeded.
    """

    attempt_limit: int = _DEFAULT_ATTEMPT_LIMIT

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult: ...

    @property
    def redacted_api_key(self) -> str:
        """API key with sensitive portion redacted for logging."""
        ...

    @property
    def source_allowlist_predicate(self) -> callable | None:
        """Optional predicate to validate source_ref values from this provider."""
        ...
