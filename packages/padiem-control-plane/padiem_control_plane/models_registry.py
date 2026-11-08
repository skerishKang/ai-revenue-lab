"""#6828 2단계 ② — the private B14 model registry file and its fail-closed load.

The public repository carries the FORMAT of the real registry (``docs/registry``)
and a placeholder example, never the values. A host reads the real document from
``PADIEM_MODELS_REGISTRY`` (default ``/etc/padiem/registry/models-private.json``,
``0640``) or, for an operator emergency, ``PADIEM_MODELS_REGISTRY_OVERRIDE``.

Failure policy (the #6828 design memo, unchanged):

* a missing or unreadable file is NOT a reason to fall back to a value that once
  shipped in the repository. The loader answers an EMPTY registry (0 models), so
  nothing executes instead of something unapproved;
* a document that fails validation raises ``PrivateRegistryUnavailable`` with a
  reason CODE. The caller keeps its last good snapshot and refuses new work;
* a file that other users can read is refused before it is parsed (the
  deployment script enforces ``0640``);
* nothing here logs or returns a provider origin, model identity or credential
  value: failures carry the file NAME and the reason code only.

This module performs no I/O beyond reading that one file, no network access and
no provider dispatch.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

FORMAT_VERSION = "padiem.models.private.v1"
REGISTRY_PATH_ENV = "PADIEM_MODELS_REGISTRY"
REGISTRY_OVERRIDE_ENV = "PADIEM_MODELS_REGISTRY_OVERRIDE"
DEFAULT_REGISTRY_PATH = "/etc/padiem/registry/models-private.json"

#: The user-visible grades a host must declare. ``admin`` is accepted when a
#: host keeps the administrator lane in the same document; the four product
#: grades are required so a half-edited file cannot silently drop one of them.
REQUIRED_TIER_NAMES = ("free", "plus", "pro", "max")
OPTIONAL_TIER_NAMES = ("admin",)

_CREDENTIAL_BINDING_PREFIX = "PADIEM_B14_CREDENTIAL_"
_KNOWN_CAPABILITIES = frozenset({"chat", "coding", "free", "image", "long_context", "tools"})
_ROOT_KEYS = frozenset({"version", "comment", "providers", "models", "tiers"})
_PROVIDER_KEYS = frozenset({"base_origin", "allowed_hosts", "credential_binding"})
_MODEL_KEYS = frozenset({
    "id", "provider_id", "upstream_model", "capabilities", "enabled",
    "display_name", "context_window",
})
_MAX_BYTES = 512 * 1024

_LOG = logging.getLogger("padiem.models_registry")


class PrivateRegistryUnavailable(ValueError):
    """The private registry could not be used. Carries a value-free code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PrivateRegistry:
    """One validated private registry document."""

    version: str
    providers: dict = field(default_factory=dict)
    models: tuple = ()
    tiers: dict = field(default_factory=dict)
    source: str = "private"

    @property
    def model_ids(self) -> frozenset:
        return frozenset(row["id"] for row in self.models)

    @property
    def ready(self) -> bool:
        """Whether this snapshot may serve traffic at all (0 models never may)."""
        return bool(self.models)


@dataclass(frozen=True, slots=True)
class RegistryLoad:
    """Result of one load attempt, with the failure reason kept value-free."""

    registry: PrivateRegistry
    loaded: bool
    code: str | None
    path_name: str
    source: str

    @property
    def ready(self) -> bool:
        return self.loaded and self.registry.ready


def empty_registry() -> PrivateRegistry:
    """The fail-closed answer: a valid registry with nothing to execute."""
    return PrivateRegistry(
        version=FORMAT_VERSION, providers={}, models=(), tiers={}, source="empty")


def registry_source() -> str:
    """Where the path came from, for the journal line: never the path itself."""
    if os.environ.get(REGISTRY_OVERRIDE_ENV, "").strip():
        return "override"
    if os.environ.get(REGISTRY_PATH_ENV, "").strip():
        return "configured"
    return "default"


def registry_path() -> Path:
    """The one file this host reads: one authority, at one path, or none."""
    override = os.environ.get(REGISTRY_OVERRIDE_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    configured = os.environ.get(REGISTRY_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(DEFAULT_REGISTRY_PATH)


def readiness(load: RegistryLoad) -> dict:
    """Value-free readiness for the health surface: counts and a reason code."""
    return {
        "ok": load.ready,
        "models": len(load.registry.models),
        "reason": load.code,
    }


def _safe_identifier(value: object, *, limit: int = 256) -> bool:
    if not isinstance(value, str) or not value or len(value) > limit:
        return False
    if value.strip() != value:
        return False
    first = value[0]
    if not (first.isalnum() and first.isascii()):
        return False
    allowed = set("._:/-")
    for character in value:
        if not (character.isalnum() or character in allowed):
            return False
    return True


def _safe_host(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 255:
        return False
    if "://" in value or "/" in value or " " in value:
        return False
    if not value[0].isalnum():
        return False
    for character in value:
        if not (character.isalnum() or character in ".-:"):
            return False
    return True


def is_credential_binding_name(value: object) -> bool:
    """Whether this is a platform secret NAME, never a value.

    The registry may only say which env binding holds a key. A pasted key never
    matches this shape, so it cannot reach a provider row.
    """
    if not isinstance(value, str) or not value.startswith(_CREDENTIAL_BINDING_PREFIX):
        return False
    suffix = value[len(_CREDENTIAL_BINDING_PREFIX):]
    return len(suffix) in (2, 3) and suffix.isdigit()


def _reject(code: str) -> PrivateRegistryUnavailable:
    return PrivateRegistryUnavailable(code)


def _validated_providers(raw: object) -> dict:
    if not isinstance(raw, dict) or not raw or len(raw) > 64:
        raise _reject("registry_providers")
    providers: dict = {}
    for provider_id, entry in raw.items():
        if not _safe_identifier(provider_id, limit=64):
            raise _reject("registry_provider_id")
        if not isinstance(entry, dict) or set(entry) != _PROVIDER_KEYS:
            raise _reject("registry_provider_keys")
        origin = entry["base_origin"]
        if (not isinstance(origin, str) or not origin.startswith("https://")
                or len(origin) > 512 or origin.strip() != origin):
            raise _reject("registry_provider_origin")
        hosts = entry["allowed_hosts"]
        if (not isinstance(hosts, list) or not hosts or len(hosts) > 8
                or not all(_safe_host(host) for host in hosts)):
            raise _reject("registry_provider_hosts")
        binding = entry["credential_binding"]
        if not is_credential_binding_name(binding):
            raise _reject("registry_provider_credential_binding")
        providers[provider_id] = {
            "base_origin": origin,
            "allowed_hosts": tuple(hosts),
            "credential_binding": binding,
        }
    return providers


def _validated_models(raw: object, providers: dict) -> tuple:
    if not isinstance(raw, list) or not raw or len(raw) > 512:
        raise _reject("registry_models")
    models = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict) or not set(row) <= _MODEL_KEYS:
            raise _reject("registry_model_keys")
        model_id = row.get("id")
        provider_id = row.get("provider_id")
        if not _safe_identifier(model_id) or model_id in seen:
            raise _reject("registry_model_id")
        if not isinstance(provider_id, str) or provider_id not in providers:
            raise _reject("registry_model_provider")
        if not model_id.startswith(provider_id + "/"):
            raise _reject("registry_model_provider_mismatch")
        if not _safe_identifier(row.get("upstream_model")):
            raise _reject("registry_model_upstream")
        capabilities = row.get("capabilities")
        if (not isinstance(capabilities, list) or not capabilities
                or len(set(capabilities)) != len(capabilities)
                or not all(isinstance(item, str) and item in _KNOWN_CAPABILITIES
                           for item in capabilities)):
            raise _reject("registry_model_capabilities")
        if type(row.get("enabled")) is not bool:
            raise _reject("registry_model_enabled")
        if "display_name" in row and (not isinstance(row["display_name"], str)
                                      or not row["display_name"].strip()):
            raise _reject("registry_model_display")
        if "context_window" in row and (type(row["context_window"]) is not int
                                        or row["context_window"] < 0):
            raise _reject("registry_model_context_window")
        seen.add(model_id)
        models.append({key: row[key] for key in _MODEL_KEYS if key in row})
    return tuple(models)


def _validated_tiers(raw: object, model_ids: frozenset) -> dict:
    if not isinstance(raw, dict):
        raise _reject("registry_tiers")
    allowed = set(REQUIRED_TIER_NAMES) | set(OPTIONAL_TIER_NAMES)
    if set(raw) - allowed or not set(REQUIRED_TIER_NAMES) <= set(raw):
        raise _reject("registry_tier_names")
    tiers: dict = {}
    for name in REQUIRED_TIER_NAMES + OPTIONAL_TIER_NAMES:
        if name not in raw:
            continue
        entry = raw[name]
        if not isinstance(entry, dict) or set(entry) != {"primary", "fallback"}:
            raise _reject("registry_tier_keys")
        primary = entry["primary"]
        fallback = entry["fallback"]
        if primary not in model_ids:
            raise _reject("registry_tier_unknown_model")
        if not isinstance(fallback, list) or len(set(fallback)) != len(fallback):
            raise _reject("registry_tier_fallback")
        if not all(item in model_ids for item in fallback):
            raise _reject("registry_tier_unknown_model")
        if primary in fallback:
            raise _reject("registry_tier_primary_in_fallback")
        tiers[name] = {"primary": primary, "fallback": tuple(fallback)}
    return tiers


def validate_document(document: object) -> PrivateRegistry:
    """Validate one complete private document, or refuse it with a code."""
    if not isinstance(document, dict):
        raise _reject("registry_document_invalid")
    if set(document) - _ROOT_KEYS:
        raise _reject("registry_root_keys")
    if document.get("version") != FORMAT_VERSION:
        raise _reject("registry_version_unsupported")
    if "comment" in document and not isinstance(document["comment"], str):
        raise _reject("registry_comment")
    providers = _validated_providers(document.get("providers"))
    models = _validated_models(document.get("models"), providers)
    tiers = _validated_tiers(
        document.get("tiers"), frozenset(row["id"] for row in models))
    return PrivateRegistry(
        version=FORMAT_VERSION, providers=providers, models=models, tiers=tiers,
        source="private")


def _check_permissions(path: Path) -> None:
    """Refuse a registry other users can read: the deployment enforces 0640."""
    if os.name != "posix":
        return
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        # A missing file is reported as missing by the read, not as unreadable
        # here: the two reasons send an operator to different places.
        return
    except OSError:
        raise _reject("registry_file_unreadable")
    if mode & 0o007:
        raise _reject("registry_permissions_too_open")


def _read_document(path: Path) -> dict:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise _reject("registry_file_missing")
    except OSError:
        raise _reject("registry_file_unreadable")
    if len(raw) > _MAX_BYTES:
        raise _reject("registry_file_too_large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _reject("registry_document_invalid")
    if not isinstance(document, dict):
        raise _reject("registry_document_invalid")
    return document


def load_private_registry(path: Path | None = None) -> PrivateRegistry:
    """Load and validate the private file, or raise a value-free code."""
    target = path or registry_path()
    _check_permissions(target)
    registry = validate_document(_read_document(target))
    source = registry_source()
    return PrivateRegistry(
        version=registry.version, providers=registry.providers,
        models=registry.models, tiers=registry.tiers,
        source="override" if source == "override" else "private")


def load_snapshot(path: Path | None = None, *, previous: PrivateRegistry | None = None,
                  logger: logging.Logger | None = None) -> RegistryLoad:
    """Never raise: answer a load with a reason code, keeping the last good one.

    A caller that must refuse traffic keeps ``previous`` and checks ``ready``;
    a caller that has nothing yet gets the empty registry, which is also the
    fail-closed answer. The log line names the file and the code only.
    """
    target = path or registry_path()
    source = registry_source()
    try:
        registry = load_private_registry(target)
    except PrivateRegistryUnavailable as exc:
        (logger or _LOG).warning(
            "models_registry_unavailable code=%s file=%s source=%s",
            exc.code, target.name, source)
        kept = previous if previous is not None else empty_registry()
        return RegistryLoad(
            registry=kept, loaded=False, code=exc.code,
            path_name=target.name, source=source)
    return RegistryLoad(
        registry=registry, loaded=True, code=None,
        path_name=target.name, source=source)


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "FORMAT_VERSION",
    "OPTIONAL_TIER_NAMES",
    "PrivateRegistry",
    "PrivateRegistryUnavailable",
    "REGISTRY_OVERRIDE_ENV",
    "REGISTRY_PATH_ENV",
    "REQUIRED_TIER_NAMES",
    "RegistryLoad",
    "empty_registry",
    "is_credential_binding_name",
    "load_private_registry",
    "load_snapshot",
    "readiness",
    "registry_path",
    "registry_source",
    "validate_document",
]
