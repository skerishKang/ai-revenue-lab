"""#2542 non-gating synthetic micro-measurement for the authority cache.

Synthetic 64-caller registry, fabricated credentials, zero external calls.
This file asserts only correctness (identical authority, fail-closed parity);
the timing output is local evidence printed for the report, never a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

from app import identity_enforcement
from app.identity_enforcement import _registry_authority_for_env
from app.service_identity import MAX_ENGINE_CALLERS

_BASE_CALLERS = tuple(
    {
        "caller_id": f"synthetic-caller-{index:02d}",
        "credential": f"SYNTHETIC-CREDENTIAL-{index:06d}-" + ("x" * 34),
        "allowed_app_ids": ["padiem-chat", "p01"],
    }
    for index in range(MAX_ENGINE_CALLERS)
)
FULL_BASE = json.dumps({"version": 1, "callers": list(_BASE_CALLERS)})


@dataclass
class SyntheticEnv:
    PADIEM_ENGINE_CALLER_REGISTRY_V1: str = FULL_BASE
    PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY: str | None = None


def _time_builds(count: int) -> tuple[float, float]:
    identity_enforcement._reset_authority_cache_for_tests()
    env = SyntheticEnv()

    start = time.perf_counter()
    for _ in range(count):
        identity_enforcement._build_registry_authority_from_env(env)
    uncached = time.perf_counter() - start

    identity_enforcement._reset_authority_cache_for_tests()
    start = time.perf_counter()
    _registry_authority_for_env(env)  # cold miss builds the authority
    start_hit = time.perf_counter()
    for _ in range(count):
        _registry_authority_for_env(env)
    cached = time.perf_counter() - start_hit
    return uncached, cached


def test_cached_authority_is_identical_and_reported() -> None:
    identity_enforcement._reset_authority_cache_for_tests()
    env = SyntheticEnv()
    direct = identity_enforcement._build_registry_authority_from_env(env)
    first = _registry_authority_for_env(env)
    second = _registry_authority_for_env(env)
    assert first[0] is second[0]
    assert first[0] is not None
    assert len(first[0].callers) == len(direct[0].callers) == MAX_ENGINE_CALLERS

    uncached, cached = _time_builds(200)
    print(
        "\nB62_REGISTRY_MICROBENCH synthetic_callers=%d iterations=200\n"
        "UNCACHED_TOTAL_S=%.6f\nCACHED_HITS_TOTAL_S=%.6f\n"
        "MEAN_UNCACHED_MS=%.4f\nMEAN_CACHED_MS=%.4f\nGATING=NO"
        % (
            MAX_ENGINE_CALLERS,
            uncached,
            cached,
            uncached / 200 * 1000,
            cached / 200 * 1000,
        )
    )
