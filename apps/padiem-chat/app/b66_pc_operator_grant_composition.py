"""#4434 follow-up — B66 operator PC grant from the trusted Worker composition.

WHAT THIS IS
    The single reviewed place that turns owner-managed Worker configuration
    into the B66 product PC policy consumed by ``create_app``. It reuses the
    existing grant structure only: :class:`ProductPcAccessGrant` and
    :class:`ProductPcAccessPolicy` from the canonical Control Plane contract,
    plus the existing ``create_app(b66_pc_access_policy=...)`` seam.

WHAT THIS IS NOT
    * not a new grant-issuing authority, admin API, D1 table or credential
      store — the only trust root is the Worker environment the owner already
      manages (same pattern as ``B66_MEMBERSHIP_ENFORCED`` and the other B66
      rollout flags);
    * not a second vocabulary — the product id is pinned to ``"b66"`` and the
      operation allow-list is a strict subset of the canonical
      :class:`PcAccessOperation` values;
    * not an activation — anything missing or malformed resolves to
      ``ProductPcAccessPolicy.default_off()``, so production stays exactly as
      today until the owner sets both values.

MANAGEMENT PATH (owner-operated, unchanged tooling)
    ``B66_PC_OPERATOR_WORKSPACE_REF`` — the exact workspace of the currently
    authenticated B66 test account, e.g. ``owner:usr_<id>``.
    ``B66_PC_OPERATOR_OPERATIONS`` — comma-separated subset of
    ``device.list,file.list,file.read,task.status,task.result``.
    ``file.write`` is never granted through this path.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessGrant,
    ProductPcAccessPolicy,
)

B66_PRODUCT_ID = "b66"
B66_PC_OPERATOR_WORKSPACE_ENV = "B66_PC_OPERATOR_WORKSPACE_REF"
B66_PC_OPERATOR_OPERATIONS_ENV = "B66_PC_OPERATOR_OPERATIONS"

# The production workspace is the Control Plane session tenant
# (``tenant_<hex>``); deployments without the identity authority fall back to
# the ``owner:<uid>`` compatibility namespace. Only these two server-issued
# namespaces are accepted here; anything else fails closed even though the
# canonical token grammar is wider. The server-side equality check
# (grant.workspace_ref vs the request workspace) remains the real boundary.
_WORKSPACE_RE = re.compile(r"^(?:owner:|tenant_)[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")

# The B66 TXT slice needs FILE_READ to dispatch and TASK_RESULT to land the
# terminal observation. DEVICE_LIST keeps the existing status panel truthful.
# FILE_WRITE is deliberately absent: a READ grant never implies WRITE.
_ALLOWED_OPERATIONS = frozenset({
    PcAccessOperation.DEVICE_LIST,
    PcAccessOperation.FILE_LIST,
    PcAccessOperation.FILE_READ,
    PcAccessOperation.TASK_STATUS,
    PcAccessOperation.TASK_RESULT,
})


def _env_value(env: Any, key: str) -> Any:
    if isinstance(env, Mapping):
        return env.get(key)
    return getattr(env, key, None)


def build_b66_pc_operator_policy(env: Any) -> ProductPcAccessPolicy:
    """Compose the B66 product PC policy from trusted Worker configuration.

    Fail-closed: any missing, malformed or out-of-allow-list value returns
    ``ProductPcAccessPolicy.default_off()`` — identical to today's production
    behavior when the Worker composition injects nothing.
    """
    workspace = _env_value(env, B66_PC_OPERATOR_WORKSPACE_ENV)
    if not isinstance(workspace, str):
        return ProductPcAccessPolicy.default_off()
    workspace = workspace.strip()
    if not _WORKSPACE_RE.fullmatch(workspace):
        return ProductPcAccessPolicy.default_off()

    raw_operations = _env_value(env, B66_PC_OPERATOR_OPERATIONS_ENV)
    if not isinstance(raw_operations, str):
        return ProductPcAccessPolicy.default_off()
    operations: set[PcAccessOperation] = set()
    for token in raw_operations.split(","):
        text = token.strip().lower()
        if not text:
            continue
        try:
            operation = PcAccessOperation(text)
        except ValueError:
            return ProductPcAccessPolicy.default_off()
        if operation not in _ALLOWED_OPERATIONS:
            return ProductPcAccessPolicy.default_off()
        operations.add(operation)
    if not operations:
        return ProductPcAccessPolicy.default_off()

    try:
        return ProductPcAccessPolicy(grants=(
            ProductPcAccessGrant(
                product_id=B66_PRODUCT_ID,
                operations=frozenset(operations),
                workspace_ref=workspace,
            ),
        ))
    except Exception:
        return ProductPcAccessPolicy.default_off()


__all__ = [
    "B66_PRODUCT_ID",
    "B66_PC_OPERATOR_OPERATIONS_ENV",
    "B66_PC_OPERATOR_WORKSPACE_ENV",
    "build_b66_pc_operator_policy",
]
