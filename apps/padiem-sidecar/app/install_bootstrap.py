"""B53 install/embed bootstrap version contract.

Represents versioned local install/embed bootstrap metadata without
publishing or claiming a real CDN/package endpoint.  All inputs are
validated and malformed/unknown values fail closed.

B53 owns the product-side bootstrap contract; Engine machine credentials,
Provider secrets, and canonical tenant truth stay outside B53.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from padiem_embedded_runtime.errors import SidecarContractError

B53_PRODUCT_ID = "padiem-sidecar"
B53_RUNTIME_MAJOR = 1
B53_RUNTIME_MINOR = 0
B53_RUNTIME_PATCH = 0
B53_RUNTIME_VERSION = f"{B53_RUNTIME_MAJOR}.{B53_RUNTIME_MINOR}.{B53_RUNTIME_PATCH}"

_ALLOWED_INSTALL_MODES = frozenset({"embed", "snippet", "panel"})
_ALLOWED_LOCALES = frozenset({"ko", "en"})
_ALLOWED_FEATURES = frozenset({"context-panel", "event-feed", "bootstrap-banner"})
_HOST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SECRET_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization",
    re.IGNORECASE,
)
_MAX_HOST_NAME_CHARS = 80
_MAX_BRAND_CHARS = 64
_MAX_THEME_CHARS = 32


def _reject_secret_like(field_name: str, value: str) -> None:
    if _SECRET_VALUE_RE.search(value):
        raise SidecarContractError(
            f"bootstrap field {field_name!r} looks like secret material; "
            "B53 bootstrap must stay browser-safe"
        )


@dataclass(frozen=True)
class InstallBootstrap:
    """Validated, immutable, JSON-serializable install/embed bootstrap metadata."""

    product_id: str
    host_id: str
    runtime_version: str
    install_mode: str
    locale: str = "ko"
    features: tuple[str, ...] = field(default_factory=tuple)
    brand: str = ""
    theme: str = ""
    host_name: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or self.product_id != B53_PRODUCT_ID:
            raise SidecarContractError("product_id must be the bounded B53 id")
        if not isinstance(self.host_id, str) or _HOST_ID_RE.fullmatch(self.host_id) is None:
            raise SidecarContractError("host_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        if not isinstance(self.runtime_version, str) or _VERSION_RE.fullmatch(self.runtime_version) is None:
            raise SidecarContractError("runtime_version must be MAJOR.MINOR.PATCH digits")
        major = int(self.runtime_version.split(".", 1)[0])
        if major != B53_RUNTIME_MAJOR:
            raise SidecarContractError("runtime_version major is not supported")
        if self.install_mode not in _ALLOWED_INSTALL_MODES:
            raise SidecarContractError("install_mode is not allowlisted")
        if self.locale not in _ALLOWED_LOCALES:
            raise SidecarContractError("locale must be one of: ko, en")
        if not isinstance(self.features, tuple):
            raise SidecarContractError("features must be a tuple of allowlisted names")
        if len(set(self.features)) != len(self.features):
            raise SidecarContractError("features must not repeat")
        for feature in self.features:
            if feature not in _ALLOWED_FEATURES:
                raise SidecarContractError(f"feature {feature!r} is not reviewed")
        if not isinstance(self.brand, str) or len(self.brand) > _MAX_BRAND_CHARS:
            raise SidecarContractError("brand exceeds the bound")
        if not isinstance(self.theme, str) or len(self.theme) > _MAX_THEME_CHARS:
            raise SidecarContractError("theme exceeds the bound")
        if not isinstance(self.host_name, str):
            raise SidecarContractError("host_name must be text")
        if len(self.host_name) > _MAX_HOST_NAME_CHARS:
            raise SidecarContractError("host_name exceeds the trusted bound")
        _reject_secret_like("host_id", self.host_id)
        _reject_secret_like("host_name", self.host_name)
        _reject_secret_like("brand", self.brand)
        _reject_secret_like("theme", self.theme)
        for feature in self.features:
            _reject_secret_like("features[]", feature)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "host_id": self.host_id,
            "runtime_version": self.runtime_version,
            "install_mode": self.install_mode,
            "locale": self.locale,
            "features": list(self.features),
            "brand": self.brand,
            "theme": self.theme,
            "host_name": self.host_name,
        }


def parse_install_bootstrap(raw: Mapping[str, object]) -> InstallBootstrap:
    """Parse untrusted mapping input into a validated :class:`InstallBootstrap`."""
    if not isinstance(raw, Mapping):
        raise SidecarContractError("install bootstrap must be a mapping")
    allowed = {
        "product_id", "host_id", "runtime_version", "install_mode",
        "locale", "features", "brand", "theme", "host_name",
    }
    unknown = sorted(k for k in raw if k not in allowed)
    if unknown:
        raise SidecarContractError(f"unknown bootstrap fields: {', '.join(unknown)}")
    try:
        product_id = raw["product_id"]
        host_id = raw["host_id"]
        runtime_version = raw["runtime_version"]
        install_mode = raw["install_mode"]
    except KeyError as exc:
        raise SidecarContractError(f"missing required bootstrap field: {exc.args[0]}") from exc
    locale = raw.get("locale", "ko")
    features = raw.get("features", ())
    if isinstance(features, list):
        features = tuple(features)
    brand = raw.get("brand", "")
    theme = raw.get("theme", "")
    host_name = raw.get("host_name", "")
    if not isinstance(locale, str) or not isinstance(host_name, str):
        raise SidecarContractError("locale and host_name must be text")
    if not isinstance(product_id, str) or not isinstance(host_id, str):
        raise SidecarContractError("product_id and host_id must be text")
    if not isinstance(runtime_version, str) or not isinstance(install_mode, str):
        raise SidecarContractError("runtime_version and install_mode must be text")
    if not isinstance(features, tuple) or not all(isinstance(f, str) for f in features):
        raise SidecarContractError("features must be a list of text names")
    return InstallBootstrap(
        product_id=product_id,
        host_id=host_id,
        runtime_version=runtime_version,
        install_mode=install_mode,
        locale=locale,
        features=features,
        brand=brand,
        theme=theme,
        host_name=host_name,
    )