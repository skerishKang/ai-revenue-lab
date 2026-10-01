"""Worker-native client for the private Control Plane E7 binding.

The canonical Worker composition now constructs this adapter when the reviewed
private binding exists. Live Production availability remains separately gated:
missing or malformed authority must fail closed and the capability manifest
stays DEFERRED until post-deploy runtime evidence is accepted.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any


class ControlPlaneTrustClientError(RuntimeError):
    """Bounded private-authority failure without raw upstream material."""

    def __init__(self, code: str) -> None:
        super().__init__(
            "Control Plane Engine admission authority is unavailable"
        )
        self.code = code


async def _maybe_await(value: Any) -> Any:
    return (
        await value
        if inspect.isawaitable(value)
        else value
    )


def _closed_mapping(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ControlPlaneTrustClientError(
            f"invalid_{label}_response"
        )
    return dict(value)


def _unwrap(
    result: Any,
    *,
    key: str,
) -> dict[str, Any]:
    wire = _closed_mapping(
        result,
        label=key,
    )
    if wire.get("ok") is not True:
        error = wire.get("error")
        code = (
            error.get("code")
            if isinstance(error, Mapping)
            else None
        )
        if not isinstance(code, str) or not code:
            code = "control_plane_authority_error"
        raise ControlPlaneTrustClientError(code)
    if frozenset(wire) != frozenset({"ok", key}):
        raise ControlPlaneTrustClientError(
            f"invalid_{key}_response"
        )
    return _closed_mapping(
        wire[key],
        label=key,
    )


class CloudflareControlPlaneTrustClient:
    """Adapter from a Service Binding to ControlPlaneTrustClient."""

    def __init__(self, binding: Any) -> None:
        required = (
            "fetch_entitlement_snapshot",
            "reserve_usage",
            "record_usage",
        )
        if (
            binding is None
            or any(
                not callable(
                    getattr(binding, name, None)
                )
                for name in required
            )
        ):
            raise ControlPlaneTrustClientError(
                "control_plane_binding_unavailable"
            )
        self._binding = binding

    async def fetch_entitlement_snapshot(
        self,
        *,
        product_id: str,
        subject: Mapping[str, str],
    ) -> dict[str, Any]:
        result = await _maybe_await(
            self._binding.fetch_entitlement_snapshot(
                {
                    "product_id": product_id,
                    "subject": dict(subject),
                }
            )
        )
        return _unwrap(
            result,
            key="snapshot",
        )

    async def reserve_usage(
        self,
        *,
        reservation: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = await _maybe_await(
            self._binding.reserve_usage(
                {
                    "reservation": dict(
                        reservation
                    )
                }
            )
        )
        return _unwrap(
            result,
            key="reservation",
        )

    async def record_usage(
        self,
        *,
        usage_event: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = await _maybe_await(
            self._binding.record_usage(
                {
                    "usage_event": dict(
                        usage_event
                    )
                }
            )
        )
        return _unwrap(
            result,
            key="receipt",
        )


def control_plane_trust_client_for_env(
    env: Any,
) -> CloudflareControlPlaneTrustClient | None:
    """Return the binding adapter only when reviewed binding source exists."""

    binding = getattr(
        env,
        "CONTROL_PLANE_ENGINE_ADMISSION",
        None,
    )
    if binding is None:
        return None
    return CloudflareControlPlaneTrustClient(
        binding
    )


CONTROL_PLANE_LIVE_ADAPTER_SOURCE_READY = True
CANONICAL_WORKER_COMPOSITION_SOURCE_WIRED = True
PRODUCTION_LIVE_PROVEN = False
