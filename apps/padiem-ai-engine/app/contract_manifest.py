"""Versioned internal contract manifest for Padiem AI Engine.

The existing Engine wire paths are already ``/internal/v1/*``. This module
makes that compatibility surface explicit for first-party cross-runtime clients
without creating a new public endpoint or changing request/response semantics.

The manifest reports Engine/Core-facing capabilities only. It deliberately does
not expose Provider/model inventory, credentials, B14 routing internals, account
IDs, Cloudflare bindings, or product entitlement state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .service import EXECUTE_PATH, HEALTH_PATH
from .streaming_service import STREAM_PATH

ENGINE_CONTRACT_FAMILY = "padiem-ai-engine"
ENGINE_CONTRACT_MAJOR = 1
ENGINE_CONTRACT_VERSION = "1.0"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ContractManifestError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("manifest error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class EngineFeatureState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class EngineEndpointContract:
    path: str
    method: str
    response_media_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.startswith("/internal/v1/"):
            raise ContractManifestError("invalid_engine_contract", "Engine endpoint must be under /internal/v1/")
        if self.method not in {"GET", "POST"}:
            raise ContractManifestError("invalid_engine_contract", "Engine endpoint method is unsupported")
        if not isinstance(self.response_media_type, str) or not self.response_media_type.strip():
            raise ContractManifestError("invalid_engine_contract", "response_media_type is required")

    def to_public_dict(self) -> dict[str, str]:
        return {"path": self.path, "method": self.method, "response_media_type": self.response_media_type}


@dataclass(frozen=True, slots=True)
class EngineFeatureContract:
    id: str
    state: EngineFeatureState

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _IDENTIFIER_RE.fullmatch(self.id):
            raise ContractManifestError("invalid_engine_contract", "feature id must be a bounded safe identifier")
        if not isinstance(self.state, EngineFeatureState):
            raise ContractManifestError("invalid_engine_contract", "feature state must be EngineFeatureState")

    def to_public_dict(self) -> dict[str, str]:
        return {"id": self.id, "state": self.state.value}


@dataclass(frozen=True, slots=True)
class EngineContractManifest:
    family: str
    major: int
    version: str
    endpoints: tuple[EngineEndpointContract, ...]
    features: tuple[EngineFeatureContract, ...]

    def __post_init__(self) -> None:
        if self.family != ENGINE_CONTRACT_FAMILY or self.major != ENGINE_CONTRACT_MAJOR or self.version != ENGINE_CONTRACT_VERSION:
            raise ContractManifestError("invalid_engine_contract", "contract identity is invalid")
        if not isinstance(self.endpoints, tuple) or not self.endpoints:
            raise ContractManifestError("invalid_engine_contract", "endpoints must be a non-empty tuple")
        if any(not isinstance(item, EngineEndpointContract) for item in self.endpoints):
            raise ContractManifestError("invalid_engine_contract", "endpoints contain an invalid value")
        paths = tuple(item.path for item in self.endpoints)
        if len(set(paths)) != len(paths):
            raise ContractManifestError("invalid_engine_contract", "endpoint paths must be unique")
        if not isinstance(self.features, tuple) or not self.features:
            raise ContractManifestError("invalid_engine_contract", "features must be a non-empty tuple")
        if any(not isinstance(item, EngineFeatureContract) for item in self.features):
            raise ContractManifestError("invalid_engine_contract", "features contain an invalid value")
        feature_ids = tuple(item.id for item in self.features)
        if len(set(feature_ids)) != len(feature_ids):
            raise ContractManifestError("invalid_engine_contract", "feature ids must be unique")

    def feature_state(self, feature_id: str) -> EngineFeatureState:
        if not isinstance(feature_id, str) or not _IDENTIFIER_RE.fullmatch(feature_id):
            raise ContractManifestError("invalid_engine_feature", "feature_id must be a bounded safe identifier")
        for feature in self.features:
            if feature.id == feature_id:
                return feature.state
        raise ContractManifestError("unknown_engine_feature", "Engine feature is not declared by this contract version")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "major": self.major,
            "version": self.version,
            "endpoints": [item.to_public_dict() for item in self.endpoints],
            "features": [item.to_public_dict() for item in self.features],
        }


def current_engine_contract_manifest() -> EngineContractManifest:
    return EngineContractManifest(
        family=ENGINE_CONTRACT_FAMILY,
        major=ENGINE_CONTRACT_MAJOR,
        version=ENGINE_CONTRACT_VERSION,
        endpoints=(
            EngineEndpointContract(EXECUTE_PATH, "POST", "application/json"),
            EngineEndpointContract(STREAM_PATH, "POST", "application/x-ndjson"),
            EngineEndpointContract(HEALTH_PATH, "GET", "application/json"),
        ),
        features=(
            EngineFeatureContract("completed_run", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("streaming_run", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("service_identity_contract", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("service_identity_wire_enforcement", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("execution_context", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("execution_idempotency_replay_completed", EngineFeatureState.AVAILABLE),
            EngineFeatureContract("execution_idempotency_replay_streaming", EngineFeatureState.DEFERRED),
            EngineFeatureContract("tool_runtime_projection", EngineFeatureState.DEFERRED),
            EngineFeatureContract("skill_runtime_projection", EngineFeatureState.DEFERRED),
            EngineFeatureContract("agent_runtime_projection", EngineFeatureState.DEFERRED),
            EngineFeatureContract("memory_rag_projection", EngineFeatureState.DEFERRED),
            EngineFeatureContract("public_browser_api", EngineFeatureState.UNAVAILABLE),
            EngineFeatureContract("provider_selection", EngineFeatureState.UNAVAILABLE),
        ),
    )


def require_compatible_engine_contract(*, requested_major: int, required_features: tuple[str, ...] = ()) -> EngineContractManifest:
    if isinstance(requested_major, bool) or not isinstance(requested_major, int):
        raise ContractManifestError("invalid_engine_contract_version", "requested_major must be an integer")
    manifest = current_engine_contract_manifest()
    if requested_major != manifest.major:
        raise ContractManifestError("incompatible_engine_contract", "requested Engine contract major is not supported")
    if isinstance(required_features, (str, bytes)) or len(set(required_features)) != len(required_features):
        raise ContractManifestError("invalid_engine_feature", "required_features must be a unique tuple of feature ids")
    for feature_id in required_features:
        if manifest.feature_state(feature_id) is not EngineFeatureState.AVAILABLE:
            raise ContractManifestError("engine_feature_unavailable", "required Engine feature is not available in this contract version")
    return manifest
