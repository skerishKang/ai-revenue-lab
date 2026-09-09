"""B53 site/app registration product projection.

Models only B53 product-side registration/config request/projection facts
needed for local conformance.  No canonical tenant/account/entitlement
identity is created; caller cannot self-assert trusted tenant/account
authority.  Server/trusted IDs are represented by deterministic fake/stub
authority in tests only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from padiem_embedded_runtime.errors import SidecarContractError

B53_PRODUCT_ID = "padiem-sidecar"
_MAX_SITE_NAME_CHARS = 80
_MAX_ORIGIN_CHARS = 256
_MAX_ADAPTER_ID_CHARS = 64
_ALLOWED_ADAPTER_VERSIONS = frozenset({"1.0.0", "1.0.1", "1.1.0"})


@dataclass(frozen=True)
class SiteRegistration:
    """B53 product-side site registration projection.

    Carries only product-side registration facts.  No tenant/account truth
    is minted; the registration is a product-side projection only.
    """

    product_id: str
    site_name: str
    host_origin: str
    adapter_id: str
    adapter_version: str
    environment: str
    config_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or self.product_id != B53_PRODUCT_ID:
            raise SidecarContractError("product_id must be the bounded B53 id")
        if not isinstance(self.site_name, str) or not self.site_name:
            raise SidecarContractError("site_name must be non-empty text")
        if len(self.site_name) > _MAX_SITE_NAME_CHARS:
            raise SidecarContractError("site_name exceeds the bound")
        if not isinstance(self.host_origin, str) or not self.host_origin:
            raise SidecarContractError("host_origin must be non-empty text")
        if len(self.host_origin) > _MAX_ORIGIN_CHARS:
            raise SidecarContractError("host_origin exceeds the bound")
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise SidecarContractError("adapter_id must be non-empty text")
        if len(self.adapter_id) > _MAX_ADAPTER_ID_CHARS:
            raise SidecarContractError("adapter_id exceeds the bound")
        if self.adapter_version not in _ALLOWED_ADAPTER_VERSIONS:
            raise SidecarContractError("adapter_version is not allowlisted")
        if self.environment not in ("dev", "preview", "production"):
            raise SidecarContractError("environment must be dev, preview, or production")
        if not isinstance(self.config_version, str) or not self.config_version:
            raise SidecarContractError("config_version must be non-empty text")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "site_name": self.site_name,
            "host_origin": self.host_origin,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "environment": self.environment,
            "config_version": self.config_version,
        }


def parse_site_registration(raw: Mapping[str, object]) -> SiteRegistration:
    """Parse untrusted mapping input into a validated :class:`SiteRegistration`."""
    if not isinstance(raw, Mapping):
        raise SidecarContractError("site registration must be a mapping")
    allowed = {
        "product_id", "site_name", "host_origin", "adapter_id",
        "adapter_version", "environment", "config_version",
    }
    unknown = sorted(k for k in raw if k not in allowed)
    if unknown:
        raise SidecarContractError(f"unknown registration fields: {', '.join(unknown)}")
    try:
        product_id = raw["product_id"]
        site_name = raw["site_name"]
        host_origin = raw["host_origin"]
        adapter_id = raw["adapter_id"]
        adapter_version = raw["adapter_version"]
        environment = raw["environment"]
        config_version = raw["config_version"]
    except KeyError as exc:
        raise SidecarContractError(f"missing required registration field: {exc.args[0]}") from exc
    return SiteRegistration(
        product_id=product_id,
        site_name=site_name,
        host_origin=host_origin,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        environment=environment,
        config_version=config_version,
    )