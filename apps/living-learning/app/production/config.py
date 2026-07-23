"""Production wiring helpers (fail-closed).

These helpers resolve the identity verifier and AI provider from configuration,
failing closed on missing/invalid configuration. They never log secrets.
"""

from __future__ import annotations

from app.config import Settings
from app.identity import (
    FirebaseIdentityVerifier,
    IdentityVerifier,
    RejectingIdentityVerifier,
)


def resolve_verifier(settings: Settings) -> IdentityVerifier:
    """Resolve the identity verifier from config (fail-closed).

    ``firebase`` builds a ``FirebaseIdentityVerifier`` (requires a project id);
    ``fake`` returns a rejecting verifier here — tests inject a
    ``FakeIdentityVerifier`` explicitly via ``set_identity_verifier``.
    """
    provider = (settings.identity_provider or "fake").strip().lower()
    if provider == "firebase":
        if not settings.firebase_project_id.strip():
            raise ValueError("firebase identity requires LL_FIREBASE_PROJECT_ID")
        return FirebaseIdentityVerifier(settings.firebase_project_id)
    # No verifier configured for local/fake mode: reject everything until a
    # verifier is explicitly injected (fail-closed default).
    return RejectingIdentityVerifier()


def resolve_provider(settings: Settings):
    """Resolve the AI provider from config (fail-closed).

    A mock provider is permitted for local/synthetic-staging only; it is never a
    live production provider. Unsupported provider names fail closed.
    """
    from app.ai import MockProvider

    provider_type = (settings.provider_type or "mock").strip().lower()
    if provider_type == "mock":
        return MockProvider(model=settings.provider_model)
    # A real provider adapter would be resolved here. Until one is configured,
    # any non-mock provider fails closed rather than pretending to be live.
    raise ValueError(f"unsupported provider type: {provider_type}")
