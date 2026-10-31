"""#2107 the append-only registry writes the Owner makes from the COM2 screen.

One Provider, one credential name, any number of models: the registry already
models it that way (``credential_binding_name`` sits on the Provider and every
model row points at its ``provider_id``), so this module only has to keep the
existing guarantees while a browser is the one typing. Nothing here adds a
per-Provider execution path — a saved Provider is served by the same
OpenAI-compatible adapter as every other platform Provider, which is what
``provider_type == "platform"`` means.

Writes are append-only. An existing row's privilege is never widened and never
rewritten, so a screen mis-click cannot silently re-point a live Provider's
credential or move a model to another vendor.
"""

from __future__ import annotations

from typing import Any

from app.pilot import com2_secret_store as secrets

OK = ""
PROVIDER_EXISTS = "provider_already_registered"
PROVIDER_ID_INVALID = "provider_id_invalid"
SECRET_NAME_INVALID = "secret_name_invalid"
SECRET_NAME_RESERVED = secrets.CLOUDFLARE_RESERVED
MODEL_ID_INVALID = "model_id_invalid"
MODEL_EXISTS = "model_already_registered"
MODEL_UPSTREAM_INVALID = "model_upstream_id_invalid"
CAPABILITY_UNKNOWN = "capability_unknown"
PRICE_INVALID = "price_invalid"
CONTEXT_INVALID = "context_window_invalid"
PROVENANCE_REQUIRED = "source_and_checked_date_required"
ORIGIN_INVALID = "upstream_origin_invalid"
REGISTRY_CHANGED = "registry_modified_during_write"
REGISTRY_INVALID = "registry_invalid"

_CAPABILITIES = frozenset({"chat", "coding", "free", "image", "long_context", "tools"})


def _row(provider_id: str, model: dict[str, Any], provider_name: str) -> dict[str, Any]:
    upstream = str(model["upstream_model"]).strip()
    source = str(model["source"]).strip()
    cached = model.get("cached_input_price_usd_per_1m")
    if cached is not None:
        # The registry carries one input and one output price, so the cached
        # figure is preserved in the provenance field until the schema has its
        # own column. Reported as remaining work rather than dropped.
        source = f"{source}; cached input US${cached} per 1M tokens"
    return {
        "id": f"{provider_id}/{upstream}",
        "provider_id": provider_id,
        "upstream_model": upstream,
        "display_name": str(model.get("display_name") or upstream).strip(),
        "provider_name": provider_name,
        "capabilities": sorted(set(model.get("capabilities") or ["chat"])),
        "context_window": int(model.get("context_window") or 0),
        "input_price_usd_per_1m": model.get("input_price_usd_per_1m"),
        "output_price_usd_per_1m": model.get("output_price_usd_per_1m"),
        "source": source,
        "source_checked_at": str(model["source_checked_at"]).strip(),
        "enabled": bool(model.get("enabled", True)),
    }


def _check_prices(row: dict[str, Any]) -> str:
    if "free" in row["capabilities"] and not (
        row["input_price_usd_per_1m"] == 0 and row["output_price_usd_per_1m"] == 0
    ):
        return PRICE_INVALID
    for field in ("input_price_usd_per_1m", "output_price_usd_per_1m"):
        value = row[field]
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
        ):
            return PRICE_INVALID
    return OK


def prepare(
    *, provider_id: str, base_origin: str, allowed_hosts: list[str],
    credential_binding_name: str, provider_name: str, models: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Build the appended registry, or return why it cannot be appended."""
    from app.pilot.model_registry_file import read_registry, validate_registry

    data = read_registry()
    if not provider_id or provider_id in data["providers"]:
        return None, PROVIDER_EXISTS
    secret_code = secrets.validate_name(credential_binding_name, for_new_provider=True)
    if secret_code:
        return None, secret_code
    if not allowed_hosts:
        allowed_hosts = [_host_of(base_origin)]

    try:
        from app.pilot.platform_secrets import CredentialSource, PlatformProviderSpec

        PlatformProviderSpec(
            provider_id=provider_id,
            credential_source=CredentialSource.PLATFORM_SECRET,
            credential_binding_name=credential_binding_name,
            base_origin=base_origin,
            allowed_hosts=tuple(allowed_hosts),
        )
    except (ValueError, TypeError):
        return None, ORIGIN_INVALID

    existing_ids = {row["id"] for row in data["models"]}
    appended: list[dict[str, Any]] = []
    for model in models:
        upstream = str(model.get("upstream_model") or "").strip()
        if not upstream:
            return None, MODEL_UPSTREAM_INVALID
        row = _row(provider_id, model, provider_name or provider_id)
        if row["id"] in existing_ids or row["id"] in {r["id"] for r in appended}:
            return None, MODEL_EXISTS
        if not set(row["capabilities"]) <= _CAPABILITIES or "chat" not in row["capabilities"]:
            return None, CAPABILITY_UNKNOWN
        price_code = _check_prices(row)
        if price_code:
            return None, price_code
        if not str(row["source"]).strip() or not str(row["source_checked_at"]).strip():
            return None, PROVENANCE_REQUIRED
        appended.append(row)

    candidate = {**data, "providers": {
        **data["providers"],
        provider_id: {
            "base_origin": base_origin,
            "allowed_hosts": list(allowed_hosts),
            "credential_source": "platform_secret",
            "credential_binding_name": credential_binding_name,
            "enabled": True,
        },
    }, "models": [*data["models"], *appended]}
    try:
        validate_registry(candidate)
    except Exception:
        return None, REGISTRY_INVALID
    return candidate, OK


def save(**kwargs: Any) -> tuple[list[str], str]:
    """Append one Provider and its models. Returns (model ids, error code)."""
    from app.pilot.model_registry_file import (
        install_models, registry_path, write_registry,
    )

    try:
        # prepare() reads and validates the file; if a git checkout or a second
        # screen lands on it in between, this write is abandoned instead of
        # overwriting what arrived.
        before = registry_path().read_bytes()
    except OSError:
        return [], REGISTRY_INVALID
    candidate, code = prepare(**kwargs)
    if code:
        return [], code
    try:
        if registry_path().read_bytes() != before:
            return [], REGISTRY_CHANGED
    except OSError:
        return [], REGISTRY_INVALID

    write_registry(candidate)
    install_models()
    provider_id = kwargs["provider_id"]
    from app.pilot.model_registry_file import read_registry

    return (
        [row["id"] for row in read_registry()["models"] if row["provider_id"] == provider_id],
        OK,
    )


def _host_of(origin: str) -> str:
    from urllib.parse import urlparse

    return urlparse(origin).hostname or ""
