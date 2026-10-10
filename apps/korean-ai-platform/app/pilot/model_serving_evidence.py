"""Read-only exact-serving-model evidence for the canonical B14 registry (#3977).

Do not infer model maker, tuned variant, provider defaults or output maximum
from an API alias. Unknown means UNKNOWN, not supported or prohibited.
No credentials, network access, default routing or model calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model_registry_file import read_registry
from .model_native_parameters import _SUPPORTED

EvidenceStatus = Literal["DOCUMENTED", "UNKNOWN"]


@dataclass(frozen=True)
class ServingModelEvidence:
    model_id: str
    serving_provider_id: str
    upstream_model: str
    serving_origin: str
    registry_source: str
    registry_checked_at: str
    manufacturer: str | None = None
    variant_kind: str | None = None
    manufacturer_model_max_output: int | None = None
    serving_model_max_output: int | None = None
    native_override_fields: tuple[str, ...] = ()
    native_override_status: EvidenceStatus = "UNKNOWN"

    @property
    def provenance_status(self) -> EvidenceStatus:
        return "DOCUMENTED" if self.manufacturer and self.variant_kind else "UNKNOWN"

    @property
    def output_limit_status(self) -> EvidenceStatus:
        return (
            "DOCUMENTED"
            if self.manufacturer_model_max_output is not None
            and self.serving_model_max_output is not None
            else "UNKNOWN"
        )


def registered_serving_evidence() -> tuple[ServingModelEvidence, ...]:
    """Return truthful model-to-serving tuples without adding unsupported claims.

    An exact key in the current native option allow-list is the only source
    of opted-in fields.  An absent key is UNKNOWN, not automatic support.
    Registry source strings are catalog provenance, not manufacturer proof.
    """
    registry = read_registry()
    providers = registry["providers"]
    result: list[ServingModelEvidence] = []
    for model in registry["models"]:
        model_id = model["id"]
        provider_id = model["provider_id"]
        if not model_id.startswith(provider_id + "/"):
            raise ValueError("B14 exact model/provider tuple mismatch")
        native = _SUPPORTED.get(model_id)
        result.append(ServingModelEvidence(
            model_id=model_id,
            serving_provider_id=provider_id,
            upstream_model=model["upstream_model"],
            serving_origin=providers[provider_id]["base_origin"],
            registry_source=model["source"],
            registry_checked_at=model["source_checked_at"],
            native_override_fields=tuple(sorted(native)) if native else (),
            native_override_status="DOCUMENTED" if native is not None else "UNKNOWN",
        ))
    unknown_ids = set(_SUPPORTED) - {item.model_id for item in result}
    if unknown_ids:
        raise ValueError("native override profile refers to an unregistered B14 exact model")
    return tuple(result)
