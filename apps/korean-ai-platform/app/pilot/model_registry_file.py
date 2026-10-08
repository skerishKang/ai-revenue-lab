"""Validated, owner-maintained B14 model registry. Only metadata, never secret values.

Edit b14_models.json to add/remove an existing compatible provider model.
The JSON is parsed at boot; invalid registry aborts startup (no stale fallback).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from .platform_secrets import (
    CredentialSource, PlatformProviderSpec, register_platform_provider
)

REGISTRY_PATH = Path(__file__).with_name("b14_models.json")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_BINDING = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_GROUPS = ("plus", "pro", "max")

class ModelRegistryError(ValueError):
    """Invalid source-controlled registry: reject without dispatch."""

def _strict_keys(row: dict, keys: set, label: str) -> None:
    if not isinstance(row,dict) or set(row) != keys:
        raise ModelRegistryError(label + ": unexpected/missing keys")

def read_registry(path: Path = REGISTRY_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelRegistryError("invalid B14 JSON registry") from exc
    _strict_keys(data,{"schema_version","comment","providers","models","groups"},"root")
    if data["schema_version"] != 1 or not isinstance(data["comment"],str):
        raise ModelRegistryError("unsupported B14 registry schema")
    if not isinstance(data["providers"],dict) or not data["providers"]:
        raise ModelRegistryError("providers must be a nonempty mapping")
    if not isinstance(data["models"],list) or not data["models"]:
        raise ModelRegistryError("models must be a nonempty list")
    if not isinstance(data["groups"],dict) or set(data["groups"]) != set(_GROUPS):
        raise ModelRegistryError("groups must be plus/pro/max")
    for pid, entry in data["providers"].items():
        _strict_keys(entry,{"base_origin","allowed_hosts","credential_source","credential_binding_name","enabled"},"provider")
        if not isinstance(pid,str) or not _ID.fullmatch(pid) or entry["enabled"] is not True:
            raise ModelRegistryError("invalid or disabled provider")
        if not isinstance(entry["allowed_hosts"],list) or not entry["allowed_hosts"] or not all(isinstance(x,str) and x for x in entry["allowed_hosts"]):
            raise ModelRegistryError("invalid host allowlist")
        if not isinstance(entry["credential_binding_name"],str):
            raise ModelRegistryError("invalid credential binding")
        if entry["credential_source"] == "platform_secret" and not _BINDING.fullmatch(entry["credential_binding_name"]):
            raise ModelRegistryError("expected secret binding NAME, not a value")
        try:
            PlatformProviderSpec(
                provider_id=pid,
                credential_source=CredentialSource(entry["credential_source"]),
                credential_binding_name=entry["credential_binding_name"],
                base_origin=entry["base_origin"],
                allowed_hosts=tuple(entry["allowed_hosts"]),
            )
        except (ValueError, TypeError) as exc:
            raise ModelRegistryError("invalid trusted provider metadata") from exc
    expected={"id","provider_id","upstream_model","display_name","provider_name",
              "capabilities","context_window","input_price_usd_per_1m",
              "output_price_usd_per_1m","source","source_checked_at","enabled"}
    found=set()
    for m in data["models"]:
        _strict_keys(m,expected,"model")
        mid=m["id"]
        if not isinstance(mid,str) or not _ID.fullmatch(mid) or mid in found or mid=="b14/auto" or mid.startswith("padiem-profile/"):
            raise ModelRegistryError("invalid or duplicate model identity")
        found.add(mid)
        if m["provider_id"] not in data["providers"] or not mid.startswith(m["provider_id"]+"/"):
            raise ModelRegistryError("model provider mismatch")
        if m["enabled"] is not True or not isinstance(m["display_name"],str) or not m["display_name"].strip():
            raise ModelRegistryError("invalid model enabled/display")
        if not isinstance(m["provider_name"],str) or not m["provider_name"]:
            raise ModelRegistryError("invalid provider display")
        if not isinstance(m["upstream_model"],str) or not _ID.fullmatch(m["upstream_model"]):
            raise ModelRegistryError("invalid upstream identity")
        if not isinstance(m["capabilities"],list) or "chat" not in m["capabilities"] or len(set(m["capabilities"])) != len(m["capabilities"]) or not all(isinstance(x,str) and x for x in m["capabilities"]):
            raise ModelRegistryError("invalid model capabilities")
        if not isinstance(m["context_window"],int) or m["context_window"]<0 or isinstance(m["context_window"],bool):
            raise ModelRegistryError("invalid context window")
        for field in ("input_price_usd_per_1m","output_price_usd_per_1m"):
            val=m[field]
            if val is not None and (isinstance(val,bool) or not isinstance(val,(float,int)) or val<0):
                raise ModelRegistryError("invalid model price")
        if "free" in m["capabilities"] and (m["input_price_usd_per_1m"]!=0 or m["output_price_usd_per_1m"]!=0):
            raise ModelRegistryError("free tag requires evidenced zero price")
        if not all(isinstance(m[f],str) and m[f].strip() for f in ("source","source_checked_at")):
            raise ModelRegistryError("invalid provenance")
    seen=set()
    for group in _GROUPS:
        items=data["groups"][group]
        if not isinstance(items,list) or not all(isinstance(x,str) and x in found for x in items):
            raise ModelRegistryError("unknown model in group")
        if len(set(items))!=len(items) or (set(items) & seen):
            raise ModelRegistryError("duplicate model group assignment")
        seen.update(items)
    return data

def group_model_ids() -> dict[str,list[str]]:
    return read_registry()["groups"]

def installed_model_ids() -> frozenset[str]:
    return frozenset(m["id"] for m in read_registry()["models"])

def install_models(data:dict|None=None) -> None:
    """Install the one canonical registry into existing B14 execution adapters."""
    from .catalog import CATALOG_BY_ID, CATALOG_MODELS, CatalogModel
    data = read_registry() if data is None else data
    # All validation first. Invalid edits must not partially modify in-memory state.
    parsed=[]
    specs=[]
    for pid, raw in data["providers"].items():
        specs.append(PlatformProviderSpec(
            provider_id=pid,
            credential_source=CredentialSource(raw["credential_source"]),
            credential_binding_name=raw["credential_binding_name"],
            base_origin=raw["base_origin"],
            allowed_hosts=tuple(raw["allowed_hosts"]),
            enabled=True,
        ))
    for index, raw in enumerate(data["models"]):
        parsed.append(CatalogModel(
            model_id=raw["id"], upstream_model=raw["upstream_model"],
            display_name=raw["display_name"], provider=raw["provider_name"],
            provider_type="platform",
            input_price_usd_per_1m=raw["input_price_usd_per_1m"],
            output_price_usd_per_1m=raw["output_price_usd_per_1m"],
            context_window=raw["context_window"],
            capabilities=frozenset(raw["capabilities"]),
            platform_provider_id=raw["provider_id"],
            source=raw["source"],source_checked_at=raw["source_checked_at"],
            sort_order=index,enabled=True,
        ))
    CATALOG_BY_ID.clear()
    CATALOG_MODELS.clear()  # Existing b14/auto is not a user model.
    for spec in specs:
        register_platform_provider(spec)
    for model in parsed:
        CATALOG_BY_ID[model.model_id] = model
