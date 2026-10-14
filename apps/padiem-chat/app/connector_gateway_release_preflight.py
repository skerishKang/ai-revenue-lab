"""#4139 static deployment readiness report; no Worker request or credential IO.

This tool checks *committed source declarations only*. It cannot access
Cloudflare deployment state, validate a TLS connection, attest an actual PC,
inspect DNS, mint an enrollment, or authorize activation. A service-binding
declaration on its own is NOT proof that its target Worker exists or is safe.
"""
from __future__ import annotations

from dataclasses import dataclass
import tomllib

from .canonical_connector_gateway_source_composition import (
    CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED,
    CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED,
)
from .connector_gateway_worker_binding_composition import (
    WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED,
    WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED,
    WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED,
)
from .worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
)

RELEASE_PREFLIGHT_VERSION = "padiem.connector-gateway.release-preflight.v1"
_REQUIRED_BINDINGS = frozenset((
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME,
))


@dataclass(frozen=True)
class GatewayReleasePreflight:
    """Bounded NO-SECRETS facts from the checked-in Worker manifest."""

    deployment_ready: bool
    declared_bindings: tuple[str, ...]
    missing_required_bindings: tuple[str, ...]
    blockers: tuple[str, ...]
    contract_version: str = RELEASE_PREFLIGHT_VERSION
    evidence_scope: str = "repository_source_only"

    def safe_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "evidence_scope": self.evidence_scope,
            "deployment_ready": self.deployment_ready,
            "declared_bindings": list(self.declared_bindings),
            "missing_required_bindings": list(self.missing_required_bindings),
            "blockers": list(self.blockers),
        }


def inspect_checked_in_gateway_release(
    *, wrangler_toml: str, worker_entrypoint_source: str,
) -> GatewayReleasePreflight:
    """Truthful and deterministic negative readiness review; NEVER activates.

    A missing declaration is conclusive negative evidence. A present binding
    is merely a configuration claim, not an operational authorization.
    """
    if type(wrangler_toml) is not str or type(worker_entrypoint_source) is not str:
        raise ValueError("release source content required")
    try:
        config = tomllib.loads(wrangler_toml)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise ValueError("Worker Wrangler config could not be parsed") from exc
    declarations = config.get("services", [])
    if type(declarations) is not list:
        raise ValueError("Worker Service Binding declarations invalid")
    names: set[str] = set()
    for declaration in declarations:
        if type(declaration) is not dict:
            raise ValueError("Worker Service Binding declaration invalid")
        name = declaration.get("binding")
        if type(name) is not str:
            raise ValueError("Worker Service Binding name invalid")
        if name in names:
            raise ValueError("Duplicate Worker Service Binding name")
        names.add(name)

    missing = tuple(sorted(_REQUIRED_BINDINGS - names))
    blockers: list[str] = []
    if missing:
        blockers.append("required_private_service_bindings_not_declared")
    if not WORKER_GATEWAY_SERVICE_BINDINGS_PRODUCTION_WIRED:
        blockers.append("worker_private_binding_wiring_not_reviewed")
    if (not CONNECTOR_GATEWAY_WORKER_TLS_PROVENANCE_WIRED
        or not WORKER_GATEWAY_TRUSTED_INGRESS_PRODUCTION_WIRED):
        blockers.append("worker_tls_ingress_provenance_not_verified")
    if (not CONNECTOR_GATEWAY_WSS_PRODUCTION_MOUNTED
        or not WORKER_GATEWAY_PUBLIC_ENTRYPOINT_MOUNTED
        or "build_review_only_gateway_from_worker_env" not in worker_entrypoint_source):
        blockers.append("public_worker_wss_route_not_mounted")
    # Not provable by a Git commit or a source-only synthetic frame test.
    blockers.extend((
        "production_tls_wss_peer_not_independently_attested",
        "two_pc_owner_consent_dpapi_restart_heartbeat_e2e_not_proven",
    ))
    return GatewayReleasePreflight(
        deployment_ready=False,
        declared_bindings=tuple(sorted(names)),
        missing_required_bindings=missing,
        blockers=tuple(blockers),
    )
