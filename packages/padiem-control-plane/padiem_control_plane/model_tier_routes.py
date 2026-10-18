"""#4428: tenant-scoped per-product/tier primary and fallback route contract.

B14 stays the catalog, secret and execution authority. This module only
describes which already-registered, owner-allowed and live-ready model a
product should select for a grade. It never creates a provider connection,
never mutates the B14 registry and never authorizes a provider call.

A missing route preserves the historical static product contract. An explicit
row is authoritative: disabled means the grade is unavailable, and the primary
is never silently replaced by a model the administrator did not select.
"""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import ControlPlaneContractError
from .model_assignment_policy import (
    MAX_CHANGES,
    CatalogModel,
    TIERS,
    _model,
    _scope,
)

ROUTE_PRODUCTS = frozenset({"chat", "claw", "b66"})
ROUTE_ACTIONS = frozenset({"set", "reset"})
MAX_ROUTES = 3 * len(TIERS)


def _err(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, code)


@dataclass(frozen=True, slots=True)
class TierRoute:
    product: str
    tier: str
    primary_model_id: str
    fallback_model_id: str | None
    enabled: bool

    def __post_init__(self) -> None:
        if self.product not in ROUTE_PRODUCTS or self.tier not in TIERS:
            raise _err("invalid_model_route_scope")
        _model(self.primary_model_id)
        if self.fallback_model_id is not None:
            _model(self.fallback_model_id)
            if self.fallback_model_id == self.primary_model_id:
                raise _err("invalid_model_route_fallback")
        if type(self.enabled) is not bool:
            raise _err("invalid_model_route_enabled")

    @property
    def key(self) -> tuple[str, str]:
        return self.product, self.tier

    def public(self) -> dict[str, object]:
        return {
            "product": self.product,
            "tier": self.tier,
            "primary_model_id": self.primary_model_id,
            "fallback_model_id": self.fallback_model_id,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class TierRouteChange:
    product: str
    tier: str
    action: str
    primary_model_id: str | None = None
    fallback_model_id: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.product not in ROUTE_PRODUCTS or self.tier not in TIERS:
            raise _err("invalid_model_route_scope")
        if self.action not in ROUTE_ACTIONS:
            raise _err("invalid_model_route_action")
        if type(self.enabled) is not bool:
            raise _err("invalid_model_route_enabled")
        if self.action == "reset":
            if self.primary_model_id is not None or self.fallback_model_id is not None:
                raise _err("invalid_model_route_change")
            return
        if self.primary_model_id is None:
            raise _err("invalid_model_route_change")
        _model(self.primary_model_id)
        if self.fallback_model_id is not None:
            _model(self.fallback_model_id)
            if self.fallback_model_id == self.primary_model_id:
                raise _err("invalid_model_route_fallback")

    @property
    def key(self) -> tuple[str, str]:
        return self.product, self.tier

    def public(self) -> dict[str, object]:
        return {
            "product": self.product,
            "tier": self.tier,
            "action": self.action,
            "primary_model_id": self.primary_model_id,
            "fallback_model_id": self.fallback_model_id,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class TierRouteSnapshot:
    workspace_id: str
    revision: int
    routes: tuple[TierRoute, ...]

    def __post_init__(self) -> None:
        _scope("workspace_id", self.workspace_id)
        if type(self.revision) is not int or self.revision < 0:
            raise _err("invalid_model_route_revision")
        if not isinstance(self.routes, tuple) or len(self.routes) > MAX_ROUTES:
            raise _err("invalid_model_routes")
        if any(not isinstance(row, TierRoute) for row in self.routes):
            raise _err("invalid_model_routes")
        keys = [row.key for row in self.routes]
        if len(keys) != len(set(keys)):
            raise _err("duplicate_model_route")

    def lookup(self, product: str, tier: str) -> TierRoute | None:
        return next((row for row in self.routes if row.key == (product, tier)), None)


@dataclass(frozen=True, slots=True)
class TierRouteResolution:
    ok: bool
    model_id: str | None
    fallback_model_id: str | None
    source: str
    reason: str


def static_tier_route(
    static_primary: str | None, static_fallback: str | None = None,
) -> TierRouteResolution:
    if static_primary is None:
        return TierRouteResolution(False, None, None, "static", "tier_unavailable")
    return TierRouteResolution(True, static_primary, static_fallback, "static", "allowed")


def effective_tier_route(
    snapshot: TierRouteSnapshot | None,
    *,
    workspace_id: str,
    product: str,
    tier: str,
    static_primary: str | None,
    static_fallback: str | None = None,
    blocked_model_ids: frozenset[str] = frozenset(),
) -> TierRouteResolution:
    """Resolve one grade without widening the administrator's selection.

    The static contract is used only when no central row exists (or the row
    cannot be read). A stored row is authoritative: a disabled row fails
    closed and the fallback is used only when it was explicitly configured.
    """
    if product not in ROUTE_PRODUCTS or tier not in TIERS:
        raise _err("invalid_model_route_scope")
    if snapshot is not None and snapshot.workspace_id != workspace_id:
        snapshot = None
    row = snapshot.lookup(product, tier) if snapshot is not None else None
    if row is None:
        return static_tier_route(static_primary, static_fallback)
    if not row.enabled:
        return TierRouteResolution(False, None, None, "central", "central_route_disabled")
    for candidate, fallback in ((row.primary_model_id, row.fallback_model_id),
                                (row.fallback_model_id, None)):
        if candidate is not None and candidate not in blocked_model_ids:
            return TierRouteResolution(True, candidate, fallback, "central", "allowed")
    return TierRouteResolution(False, None, None, "central", "central_route_unavailable")


def _check_route_changes(
    changes: tuple[TierRouteChange, ...], catalog: dict[str, CatalogModel],
) -> None:
    if not isinstance(changes, tuple) or not 1 <= len(changes) <= MAX_CHANGES:
        raise _err("invalid_model_route_batch")
    if any(not isinstance(row, TierRouteChange) for row in changes):
        raise _err("invalid_model_route_change")
    if len({row.key for row in changes}) != len(changes):
        raise _err("duplicate_model_route_change")
    for row in changes:
        if row.action == "reset":
            continue
        for model_id in (row.primary_model_id, row.fallback_model_id):
            if model_id is None:
                continue
            found = catalog.get(model_id)
            if found is None or not isinstance(found, CatalogModel) or not found.registered:
                raise _err("model_route_unknown_model")
            if not found.live_ready:
                raise _err("model_route_offline_model")


def _updated_routes(
    snapshot: TierRouteSnapshot, changes: tuple[TierRouteChange, ...],
) -> TierRouteSnapshot:
    values = {row.key: row for row in snapshot.routes}
    for change in changes:
        if change.action == "reset":
            values.pop(change.key, None)
        else:
            values[change.key] = TierRoute(
                product=change.product,
                tier=change.tier,
                primary_model_id=change.primary_model_id or "",
                fallback_model_id=change.fallback_model_id,
                enabled=change.enabled,
            )
    ordered = tuple(values[k] for k in sorted(values))
    return TierRouteSnapshot(snapshot.workspace_id, snapshot.revision + 1, ordered)


def _route_diff(
    snapshot: TierRouteSnapshot, changes: tuple[TierRouteChange, ...],
) -> list[dict[str, object]]:
    diff: list[dict[str, object]] = []
    for change in changes:
        before = snapshot.lookup(change.product, change.tier)
        diff.append({
            "product": change.product,
            "tier": change.tier,
            "action": change.action,
            "previous": before.public() if before is not None else None,
            "next": (
                None if change.action == "reset" else {
                    "product": change.product,
                    "tier": change.tier,
                    "primary_model_id": change.primary_model_id,
                    "fallback_model_id": change.fallback_model_id,
                    "enabled": change.enabled,
                }
            ),
        })
    return diff


__all__ = [
    "MAX_ROUTES",
    "ROUTE_ACTIONS",
    "ROUTE_PRODUCTS",
    "TierRoute",
    "TierRouteChange",
    "TierRouteResolution",
    "TierRouteSnapshot",
    "_check_route_changes",
    "_route_diff",
    "_updated_routes",
    "effective_tier_route",
    "static_tier_route",
]
