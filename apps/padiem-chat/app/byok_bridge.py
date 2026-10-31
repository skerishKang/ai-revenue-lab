"""Opt-in user credentials on the existing Engine/B14 service-binding lane."""
import json
from .byok_client import resolve_owner_custom_credential
from .byok_credentials import CUSTOM_PROVIDERS

# Anthropic's existing Go messages adapter is pinned to the Go supplier; it
# cannot send an Anthropic customer key. Keep that provider on the direct wire.
SUPPORTED_PROVIDERS = frozenset({"openai", "gemini", "deepseek", "groq", "xai",
                                 "perplexity", "openrouter", "huggingface"})


def enabled(state):
    return getattr(getattr(state, "settings", None), "byok_via_b14", False) is True


class UserCredentialReference(str):
    def __repr__(self):
        return "UserCredentialReference(<redacted>)"


async def resolve_reference(state, uid, selection):
    if not enabled(state) or selection.provider not in SUPPORTED_PROVIDERS:
        return None
    credential = await resolve_owner_custom_credential(state, uid=uid, selection=selection)
    spec = CUSTOM_PROVIDERS[selection.provider]
    # Arbitrary custom endpoints are not part of B14's existing fixed wires.
    if credential.endpoint.rstrip("/") != spec.base_origin.rstrip("/"):
        return None
    provider = "google" if selection.provider == "gemini" else selection.provider
    model = selection.model
    model_id = model if model.startswith(provider + "/") else provider + "/" + model
    ref = UserCredentialReference(json.dumps({
        "provider": provider, "endpoint": credential.endpoint,
        "model": model, "key": credential.api_key,
    }, ensure_ascii=False, separators=(",", ":")))
    return model_id, ref
