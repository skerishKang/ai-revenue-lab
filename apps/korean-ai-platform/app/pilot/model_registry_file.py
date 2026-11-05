"""Validated, owner-maintained B14 model registry. Only metadata, never secret values.

Edit b14_models.json to add/remove an existing compatible provider model.
The JSON is parsed at boot; invalid registry aborts startup (no stale fallback).
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from .reasoning_policy import normalize_policy
from .platform_secrets import (
    CredentialSource, PlatformProviderSpec, register_platform_provider
)

REGISTRY_PATH = Path(__file__).with_name("b14_models.json")
REGISTRY_PATH_ENV = "B14_REGISTRY_PATH"
REGISTRY_OVERLAY_PATH_ENV = "B14_REGISTRY_OVERLAY_PATH"
_OVERLAY_SUFFIX = ".overrides.json"


def registry_path() -> Path:
    """The one registry file this deployment reads.

    A host that keeps its application checkout read-only can relocate the file
    with B14_REGISTRY_PATH. That is the same authority at a different path, not
    a second one: nothing is merged with a package default, so a host either
    reads the file it points at or fails closed at boot.
    """
    raw = os.environ.get(REGISTRY_PATH_ENV, "").strip()
    return Path(raw).expanduser() if raw else REGISTRY_PATH


def overlay_path(base: Path | None = None) -> Path:
    """The Owner-written overlay applied on top of the base registry.

    The base file stays the shipped, source-controlled catalog. Everything the
    Owner registers from the model console lands here, next to the base file, so
    an application update never has to merge two human edits by hand. A host can
    relocate it with ``B14_REGISTRY_OVERLAY_PATH``.
    """
    raw = os.environ.get(REGISTRY_OVERLAY_PATH_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    target = base or registry_path()
    return target.with_name(target.stem + _OVERLAY_SUFFIX)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_BINDING = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_GROUPS = ("plus", "pro", "max")

# A Provider row may declare static extra request headers (for example a
# vendor-required version marker). The fixed auth header is built by the adapter,
# so a row can never replace it, and a row can never carry a key value: these are
# non-secret metadata only.
_REQUIRED_PROVIDER_KEYS = {
    "base_origin", "allowed_hosts", "credential_source",
    "credential_binding_name", "enabled",
}
_OPTIONAL_PROVIDER_KEYS = {"extra_headers"}
_REQUIRED_ROOT_KEYS = {"schema_version", "comment", "providers", "models", "groups"}
_OPTIONAL_ROOT_KEYS = {"retired_models"}
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,64}$")
_HEADER_VALUE = re.compile(r"^[\x20-\x7e]{0,512}$")
_RESERVED_HEADERS = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "content-type",
})
# A bare long token is how a key value usually looks. Refuse it here instead of
# relying on a reviewer to notice a credential pasted into the registry.
_BARE_CREDENTIAL = re.compile(r"^[A-Za-z0-9_\-+/=.]{32,}$")
_CREDENTIAL_PREFIX = re.compile(r"^(?:bearer|basic|token)\s+", re.IGNORECASE)


def _validated_headers(raw: object) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > 16:
        raise ModelRegistryError("provider extra_headers must be a small mapping")
    headers: dict[str, str] = {}
    lowered: set[str] = set()
    for name, value in raw.items():
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise ModelRegistryError("invalid extra header name")
        folded = name.casefold()
        if folded in _RESERVED_HEADERS or folded in lowered:
            raise ModelRegistryError("extra header may not replace a fixed header")
        if not isinstance(value, str) or not _HEADER_VALUE.fullmatch(value):
            raise ModelRegistryError("invalid extra header value")
        if _CREDENTIAL_PREFIX.match(value) or _BARE_CREDENTIAL.fullmatch(value.strip()):
            raise ModelRegistryError("extra header value looks like a credential")
        lowered.add(folded)
        headers[name] = value
    return headers


def _validated_retired(raw: object, registered: set[str]) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list) or len(raw) > 512:
        raise ModelRegistryError("retired_models must be a bounded list")
    retired: set[str] = set()
    for model_id in raw:
        if not isinstance(model_id, str) or not _ID.fullmatch(model_id):
            raise ModelRegistryError("invalid retired model identity")
        if model_id in retired:
            raise ModelRegistryError("duplicate retired model identity")
        if model_id in registered:
            raise ModelRegistryError("retired model must not be registered")
        retired.add(model_id)
    return frozenset(retired)

# The capability vocabulary the registry may use. A capability that is not
# listed here is a typo, and a typo in the tool capability would silently
# disable tool calling for that model instead of failing loudly.
_KNOWN_CAPABILITIES = frozenset({
    "chat",
    "coding",
    "free",
    "image",
    "long_context",
    "tools",
})

class ModelRegistryError(ValueError):
    """Invalid source-controlled registry: reject without dispatch."""

def _strict_keys(row: dict, keys: set, label: str) -> None:
    if not isinstance(row,dict) or set(row) != keys:
        raise ModelRegistryError(label + ": unexpected/missing keys")

def _read_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelRegistryError("invalid B14 JSON " + label) from exc
    if not isinstance(data, dict):
        raise ModelRegistryError("invalid B14 JSON " + label)
    return data


def merge_overlay(base: dict, overlay: dict) -> dict:
    """Apply the Owner overlay to the base document.

    Provider rows replace by id and model rows replace by id (new ids append).
    A retired identity always wins: an id in ``retired_models`` is absent from
    the effective catalog and from every group, whichever document named it.
    Group membership is therefore derived from the effective catalog instead of
    being a second hand-edited list that could disagree with it.
    """
    merged = json.loads(json.dumps(base))
    if not overlay:
        return merged
    unknown = set(overlay) - {"schema_version", "providers", "models", "retired_models"}
    if unknown:
        raise ModelRegistryError("overlay: unexpected keys")
    if "schema_version" in overlay and overlay["schema_version"] != 1:
        raise ModelRegistryError("overlay: unsupported schema")

    providers = overlay.get("providers", {})
    if not isinstance(providers, dict):
        raise ModelRegistryError("overlay: providers must be a mapping")
    merged["providers"].update(json.loads(json.dumps(providers)))

    models = overlay.get("models", [])
    if not isinstance(models, list):
        raise ModelRegistryError("overlay: models must be a list")
    rows = {row.get("id"): row for row in merged["models"] if isinstance(row, dict)}
    order = [row.get("id") for row in merged["models"] if isinstance(row, dict)]
    for row in models:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ModelRegistryError("overlay: invalid model row")
        if row["id"] not in rows:
            order.append(row["id"])
        rows[row["id"]] = json.loads(json.dumps(row))
    overlay_retired = overlay.get("retired_models", [])
    if not isinstance(overlay_retired, list) or not all(isinstance(x, str) for x in overlay_retired):
        raise ModelRegistryError("overlay: retired_models must be a list of ids")
    retired = set(base.get("retired_models") or []) | set(overlay_retired)
    retired = [model_id for model_id in dict.fromkeys(retired) if isinstance(model_id, str)]
    if len(retired) > 512:
        raise ModelRegistryError("overlay: retired_models too long")
    merged["models"] = [rows[model_id] for model_id in order if model_id not in retired]
    if retired:
        merged["retired_models"] = sorted(retired)
    else:
        merged.pop("retired_models", None)
    registered = {row["id"] for row in merged["models"]}
    merged["groups"] = {
        group: [model_id for model_id in items if model_id in registered]
        for group, items in merged["groups"].items()
    }
    return merged


def read_registry(path: Path | None = None) -> dict:
    """Return the effective registry: the base document plus the Owner overlay."""
    base = path or registry_path()
    merged = merge_overlay(_read_json(base, "registry"), read_overlay(base))
    return validate_registry(merged)


def read_overlay(path: Path | None = None) -> dict:
    """Return the Owner overlay document, or ``{}`` when none is installed."""
    target = overlay_path(path)
    if not target.is_file():
        return {}
    return _read_json(target, "registry overlay")


def overlay_state(path: Path | None = None) -> dict:
    """Value-free shape of the overlay, for the Owner console."""
    target = overlay_path(path)
    if not target.is_file():
        return {"present": False, "path": target.name, "providers": 0, "models": 0,
                "retired_models": 0}
    overlay = read_overlay(path)
    return {
        "present": True,
        "path": target.name,
        "providers": len(overlay.get("providers") or {}),
        "models": len(overlay.get("models") or []),
        "retired_models": len(overlay.get("retired_models") or []),
    }


def write_overlay(update: dict, path: Path | None = None) -> dict:
    """Merge ``update`` into the overlay and install it in one validated step.

    ``update`` carries only ``providers`` / ``models`` / ``retired_models``.
    The effective document is validated before the overlay file is replaced, so
    a rejected edit never becomes the thing the next boot reads.
    """
    if not isinstance(update, dict) or set(update) - {"providers", "models", "retired_models"}:
        raise ModelRegistryError("overlay: invalid update")
    base = path or registry_path()
    current = read_overlay(base)
    merged_overlay = {
        "schema_version": 1,
        "providers": dict(current.get("providers") or {}),
        "models": [dict(row) for row in current.get("models") or []],
        "retired_models": list(current.get("retired_models") or []),
    }
    merged_overlay["providers"].update(json.loads(json.dumps(update.get("providers") or {})))
    rows = {row.get("id"): row for row in merged_overlay["models"] if isinstance(row, dict)}
    order = [row.get("id") for row in merged_overlay["models"] if isinstance(row, dict)]
    for row in update.get("models") or []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ModelRegistryError("overlay: invalid model row")
        if row["id"] not in rows:
            order.append(row["id"])
        rows[row["id"]] = json.loads(json.dumps(row))
    if "retired_models" in update:
        replacement = update["retired_models"]
        if (not isinstance(replacement, list)
                or not all(isinstance(x, str) for x in replacement)):
            raise ModelRegistryError("overlay: retired_models must be a list of ids")
        merged_overlay["retired_models"] = list(dict.fromkeys(replacement))
    merged_overlay["models"] = [rows[model_id] for model_id in order if model_id in rows]
    if not merged_overlay["providers"]:
        merged_overlay.pop("providers")
    if not merged_overlay["models"]:
        merged_overlay.pop("models")
    if not merged_overlay["retired_models"]:
        merged_overlay.pop("retired_models")

    effective = merge_overlay(_read_json(base, "registry"), merged_overlay)
    validate_registry(effective)
    target = overlay_path(base)
    text = json.dumps(merged_overlay, ensure_ascii=False, indent=2) + "\n"
    try:
        handle, temp_path = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_path, 0o644)
            os.replace(temp_path, target)
        except BaseException:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise ModelRegistryError("registry overlay write failed") from exc
    return effective


def install_registry() -> dict:
    """Re-read the effective registry and reinstall it into the adapter registry.

    The Owner console calls this after a write so the next request uses the new
    catalog without a process restart, and the base JSON file is untouched.
    """
    data = read_registry()
    install_models(data)
    return data

def write_registry(data: dict, path: Path | None = None) -> None:
    """Validate fully, then replace the file in one step.

    The Owner's registration screen writes through here, so a half-edited
    registry — which would abort the next boot — is not reachable: the new
    content is validated before anything is written and moved into place with a
    single rename inside the same directory.
    """
    target = path or registry_path()
    validate_registry(data)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle, temp_path = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, target)
    except OSError as exc:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise ModelRegistryError("registry write failed") from exc

def validate_registry(data: dict) -> dict:
    """Validate any trusted source before modifying the active catalog."""
    if not isinstance(data, dict):
        raise ModelRegistryError("root: unexpected/missing keys")
    root_keys = set(data)
    if not _REQUIRED_ROOT_KEYS <= root_keys or root_keys - _REQUIRED_ROOT_KEYS - _OPTIONAL_ROOT_KEYS:
        raise ModelRegistryError("root: unexpected/missing keys")
    if data["schema_version"] != 1 or not isinstance(data["comment"],str):
        raise ModelRegistryError("unsupported B14 registry schema")
    if not isinstance(data["providers"],dict) or not data["providers"]:
        raise ModelRegistryError("providers must be a nonempty mapping")
    if not isinstance(data["models"],list) or not data["models"]:
        raise ModelRegistryError("models must be a nonempty list")
    if not isinstance(data["groups"],dict) or set(data["groups"]) != set(_GROUPS):
        raise ModelRegistryError("groups must be plus/pro/max")
    for pid, entry in data["providers"].items():
        if not isinstance(entry, dict):
            raise ModelRegistryError("provider: unexpected/missing keys")
        keys = set(entry)
        if not _REQUIRED_PROVIDER_KEYS <= keys or keys - _REQUIRED_PROVIDER_KEYS - _OPTIONAL_PROVIDER_KEYS:
            raise ModelRegistryError("provider: unexpected/missing keys")
        _validated_headers(entry.get("extra_headers"))
        if not isinstance(pid,str) or not _ID.fullmatch(pid) or type(entry["enabled"]) is not bool:
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
        keys=set(m)
        # #6858: the Owner overlay carries the per-model reasoning block on an
        # otherwise exact row. Everything outside {expected, +reasoning} stays a
        # hard error, and the block itself must normalise or the boot aborts.
        if not expected <= keys or keys - expected - {"reasoning"}:
            raise ModelRegistryError("model: unexpected/missing keys")
        if "reasoning" in m:
            try:
                normalize_policy(m["reasoning"])
            except ValueError as exc:
                raise ModelRegistryError(f"model reasoning block rejected: {exc}") from exc
        mid=m["id"]
        if not isinstance(mid,str) or not _ID.fullmatch(mid) or mid in found or mid.startswith("padiem-profile/"):
            raise ModelRegistryError("invalid or duplicate model identity")
        found.add(mid)
        if m["provider_id"] not in data["providers"] or not mid.startswith(m["provider_id"]+"/"):
            raise ModelRegistryError("model provider mismatch")
        if type(m["enabled"]) is not bool or not isinstance(m["display_name"],str) or not m["display_name"].strip():
            raise ModelRegistryError("invalid model enabled/display")
        if not isinstance(m["provider_name"],str) or not m["provider_name"]:
            raise ModelRegistryError("invalid provider display")
        if not isinstance(m["upstream_model"],str) or not _ID.fullmatch(m["upstream_model"]):
            raise ModelRegistryError("invalid upstream identity")
        if not isinstance(m["capabilities"],list) or "chat" not in m["capabilities"] or len(set(m["capabilities"])) != len(m["capabilities"]) or not all(isinstance(x,str) and x for x in m["capabilities"]):
            raise ModelRegistryError("invalid model capabilities")
        unknown = sorted(set(m["capabilities"]) - _KNOWN_CAPABILITIES)
        if unknown:
            raise ModelRegistryError("unknown model capability: " + unknown[0])
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
    _validated_retired(data.get("retired_models"), found)
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

def retired_model_ids(path: Path | None = None) -> frozenset[str]:
    """Exact model identities the Owner retired, read from the same registry.

    Every retirement surface (route tests, the evaluation gate, the dispatcher)
    derives from this list instead of keeping a second hand-maintained copy that
    a new registration could silently fall out of sync with.
    """
    return frozenset(read_registry(path).get("retired_models", []))

def provider_extra_headers(provider_id: str, path: Path | None = None) -> dict[str, str]:
    """Static request headers a Provider row declares (names only, no values)."""
    entry = read_registry(path)["providers"].get(provider_id)
    return dict(entry.get("extra_headers", {})) if entry else {}

def credential_binding_names(path: Path | None = None) -> frozenset[str]:
    """Every platform credential NAME the registry declares, enabled or not.

    Both entrypoints derive their per-request credential scope from this, so a
    new Provider is onboarded by this file plus the value on its own host;
    neither the Worker entrypoint nor the COM2 adapter keeps a second list that
    an onboarding would also have to edit. Disabled Providers are included so a
    Provider can be turned on without touching code. Names only — never values.
    """
    return frozenset(
        entry["credential_binding_name"]
        for entry in read_registry(path)["providers"].values()
        if entry["credential_source"] == CredentialSource.PLATFORM_SECRET.value
        and entry["credential_binding_name"]
    )

def _reasoning_fields(raw: dict) -> tuple[bool, str | None, bool]:
    """The catalog view of one row's reasoning block (#6838).

    Returns ``(supported, default, thought_summary)``. The thought-summary
    switch rides the same block and is honoured only on a supported model.
    """
    if "reasoning" not in raw:
        return (False, None, False)
    supported, _values, default, thought_summary = normalize_policy(raw["reasoning"])
    return (supported, default if supported else None, thought_summary if supported else False)


def install_models(data:dict|None=None) -> None:
    """Install the one canonical registry into existing B14 execution adapters."""
    from .catalog import CATALOG_BY_ID, CATALOG_MODELS, CatalogModel
    data = read_registry() if data is None else validate_registry(data)
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
            enabled=raw["enabled"],
            extra_headers=tuple(raw.get("extra_headers", {}).items()),
        ))
    for index, raw in enumerate(data["models"]):
        # #6838/#6890: the reasoning block reaches the catalog here. Before
        # this call the block was validated at boot but never applied, so an
        # overlay-only reasoning decision stayed inert (see PR notes).
        supported, default, thought_summary = _reasoning_fields(raw)
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
            reasoning_supported=supported, reasoning_default=default,
            thought_summary_enabled=thought_summary,
            sort_order=index,enabled=(raw["enabled"] and data["providers"][raw["provider_id"]]["enabled"]),
        ))
    CATALOG_BY_ID.clear()
    CATALOG_MODELS.clear()
    for spec in specs:
        register_platform_provider(spec)
    for model in parsed:
        CATALOG_BY_ID[model.model_id] = model
