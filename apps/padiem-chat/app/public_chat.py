from __future__ import annotations

from typing import Any

# Browser-facing chat responses are an explicit product contract. Anything not
# allowlisted here remains server-side by default so future routing metadata
# cannot become public merely because an internal result dict grows a new key.
_PUBLIC_TOP_LEVEL_KEYS = frozenset(
    {
        "answer",
        "runtime",
        "profile",
        "skill",
        "attachments",
        "answer_status",
        "evidence",
        "tool",
        "research",
        "usage",
        "project_files_used",
        "conversation_id",
        "project_id",
        "project",
    }
)

# These identity/operational keys are never part of the B62 browser contract,
# including when nested inside evidence/tool/research payloads.
_PRIVATE_KEYS = frozenset(
    {
        "route",
        "request_id",
        "provider",
        "provider_id",
        "provider_route_id",
        "model",
        "model_id",
        "selected_provider",
        "selected_model",
        "upstream_model",
        "credential_binding_name",
        "credential_source",
        "routing_reason",
        "routing_evidence",
    }
)


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_value(item)
            for key, item in value.items()
            if str(key) not in _PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    return value


def public_chat_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project an internal chat result onto B62's browser-safe contract.

    The internal B14/Core result may retain exact route/provider/model evidence;
    this function is applied only at the HTTP product boundary.
    """
    if not isinstance(result, dict):
        raise TypeError("chat result must be a dict")

    return {
        key: _public_value(result[key])
        for key in _PUBLIC_TOP_LEVEL_KEYS
        if key in result
    }
