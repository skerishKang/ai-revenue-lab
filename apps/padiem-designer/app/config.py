"""Designer configuration.

Every credential is read from the environment. The app has no key screen, no
key store and no independent login authority: the model credential and the
session secret are the machine's existing settings, supplied by whoever runs
the app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    """The Designer's effective configuration."""

    #: ``openai_compatible`` is the dev route that speaks an OpenAI-compatible
    #: chat-completions contract. ``b14`` is the product route.
    model_route: str = "openai_compatible"
    model_base_url: str = ""
    model_api_key: str = ""
    model_id: str = ""
    model_timeout_seconds: int = 120
    #: A reasoning model spends a large part of its budget on reasoning before
    #: the tool call, so the ceiling has to leave room for the call itself.
    model_max_tokens: int = 8000
    #: How many times the route may ask again when a model answers in prose
    #: instead of calling the tool. One re-ask is enough for a free route that
    #: occasionally ignores the forced tool choice.
    model_tool_retries: int = 1
    #: The B14 route is reached through a service binding in the Worker
    #: runtime. This app speaks the binding's transport protocol.
    b14_base_url: str = ""
    b14_model_id: str = ""
    b14_session_secret: str = ""
    tenant_id: str = ""
    dev_user_id: str = ""
    dev_tenant_id: str = ""
    public_base_url: str = ""

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.model_base_url and self.model_api_key and self.model_id)

    @property
    def auth_configured(self) -> bool:
        return bool(self.b14_session_secret)

    def to_public_dict(self) -> dict[str, object]:
        """A truthful, secret-free description of what is actually configured."""

        return {
            "modelRoute": self.model_route,
            "modelId": self.model_id or None,
            "modelBaseUrl": self.model_base_url or None,
            "modelCredentialsConfigured": self.has_model_credentials,
            "b14RouteConfigured": bool(self.b14_base_url and self.b14_session_secret),
            "b14ModelId": self.b14_model_id or None,
            "sessionSecretConfigured": self.auth_configured,
            "tenantId": self.tenant_id or self.dev_tenant_id or None,
            "authMode": "padiem_session" if self.auth_configured else "dev_configured",
        }


def load_settings() -> Settings:
    """Read the Designer's settings from the environment."""

    try:
        timeout = int(_env("DESIGNER_MODEL_TIMEOUT_SECONDS", "120"))
    except ValueError:
        timeout = 120
    try:
        max_tokens = int(_env("DESIGNER_MODEL_MAX_TOKENS", "8000"))
    except ValueError:
        max_tokens = 8000
    try:
        tool_retries = int(_env("DESIGNER_MODEL_TOOL_RETRIES", "1"))
    except ValueError:
        tool_retries = 1

    return Settings(
        model_route=_env("DESIGNER_MODEL_ROUTE", "openai_compatible"),
        model_base_url=_env("DESIGNER_MODEL_BASE_URL"),
        model_api_key=_env("DESIGNER_MODEL_API_KEY"),
        model_id=_env("DESIGNER_MODEL_ID"),
        model_timeout_seconds=timeout,
        model_max_tokens=max_tokens,
        model_tool_retries=max(0, tool_retries),
        b14_base_url=_env("DESIGNER_B14_BASE_URL"),
        b14_model_id=_env("DESIGNER_B14_MODEL_ID"),
        b14_session_secret=_env("DESIGNER_SESSION_SECRET"),
        tenant_id=_env("DESIGNER_TENANT_ID"),
        dev_user_id=_env("DESIGNER_DEV_USER_ID", "designer-local"),
        dev_tenant_id=_env("DESIGNER_DEV_TENANT_ID", "designer-local-tenant"),
        public_base_url=_env("DESIGNER_PUBLIC_BASE_URL"),
    )
