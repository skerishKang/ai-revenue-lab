"""Browser-safe bootstrap/config contract for IP-SIDECAR.

The bootstrap carries only bounded, non-secret host/runtime metadata. Any
value that looks like a secret, credential, or token fails closed at parse
time, so the resulting config is always safe to expose to a browser host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .errors import SidecarContractError

_HOST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHELL_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SECRET_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization",
    re.IGNORECASE,
)

ALLOWED_LOCALES = frozenset({"ko", "en"})
ALLOWED_FEATURES = frozenset({"context-panel", "event-feed", "bootstrap-banner"})
MAX_HOST_NAME_CHARS = 80


def _reject_secret_like(field_name: str, value: str) -> None:
    if _SECRET_VALUE_RE.search(value):
        raise SidecarContractError(
            f"bootstrap field {field_name!r} looks like secret material; "
            "IP-SIDECAR bootstrap must stay browser-safe"
        )


@dataclass(frozen=True)
class BootstrapConfig:
    """Validated, immutable, JSON-serializable bootstrap metadata."""

    host_id: str
    shell_version: str
    locale: str = "ko"
    features: tuple[str, ...] = field(default_factory=tuple)
    host_name: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.host_id, str) or _HOST_ID_RE.fullmatch(self.host_id) is None:
            raise SidecarContractError("host_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        if not isinstance(self.shell_version, str) or _SHELL_VERSION_RE.fullmatch(self.shell_version) is None:
            raise SidecarContractError("shell_version must be MAJOR.MINOR.PATCH digits")
        if self.locale not in ALLOWED_LOCALES:
            raise SidecarContractError("locale must be one of: ko, en")
        if not isinstance(self.features, tuple):
            raise SidecarContractError("features must be a tuple of allowlisted names")
        if len(set(self.features)) != len(self.features):
            raise SidecarContractError("features must not repeat")
        for feature in self.features:
            if feature not in ALLOWED_FEATURES:
                raise SidecarContractError(f"feature {feature!r} is not reviewed for S2")
        if not isinstance(self.host_name, str):
            raise SidecarContractError("host_name must be text")
        if len(self.host_name) > MAX_HOST_NAME_CHARS:
            raise SidecarContractError("host_name exceeds the trusted bound")
        _reject_secret_like("host_id", self.host_id)
        _reject_secret_like("host_name", self.host_name)
        for feature in self.features:
            _reject_secret_like("features[]", feature)

    def to_public_dict(self) -> dict[str, object]:
        """Return the JSON-serializable public view (safe for browsers)."""
        return {
            "host_id": self.host_id,
            "shell_version": self.shell_version,
            "locale": self.locale,
            "features": list(self.features),
            "host_name": self.host_name,
        }


def parse_bootstrap_config(raw: Mapping[str, object]) -> BootstrapConfig:
    """Parse untrusted mapping input into a validated :class:`BootstrapConfig`."""
    if not isinstance(raw, Mapping):
        raise SidecarContractError("bootstrap config must be a mapping")
    allowed = {"host_id", "shell_version", "locale", "features", "host_name"}
    unknown = sorted(k for k in raw if k not in allowed)
    if unknown:
        raise SidecarContractError(f"unknown bootstrap fields: {', '.join(unknown)}")
    try:
        host_id = raw["host_id"]
        shell_version = raw["shell_version"]
    except KeyError as exc:
        raise SidecarContractError(f"missing required bootstrap field: {exc.args[0]}") from exc
    features = raw.get("features", ())
    if isinstance(features, list):
        features = tuple(features)
    locale = raw.get("locale", "ko")
    host_name = raw.get("host_name", "")
    if not isinstance(locale, str) or not isinstance(host_name, str):
        raise SidecarContractError("locale and host_name must be text")
    if not isinstance(host_id, str) or not isinstance(shell_version, str):
        raise SidecarContractError("host_id and shell_version must be text")
    if not isinstance(features, tuple) or not all(isinstance(f, str) for f in features):
        raise SidecarContractError("features must be a list of text names")
    return BootstrapConfig(
        host_id=host_id,
        shell_version=shell_version,
        locale=locale,
        features=features,
        host_name=host_name,
    )
