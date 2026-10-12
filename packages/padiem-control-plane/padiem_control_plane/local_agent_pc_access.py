"""#4139 — product-common PC access contract for every PADIEM B14 consumer.

B14 stays the **model execution** authority: provider/model registration,
model invocation and per-model policy. It is *not* a PC access authority and no
PC execution endpoint belongs inside it.

This module is the shared Control Plane declaration that decides, per product,
which *PC access operation* a product may even attempt on a Windows computer
the owner has bound to the canonical PADIEM Local Agent Broker. It exists so
that Padiem Claw, B66 Padiem Quote, Padiem Chat and Padiem Engine can share one
PC registration/permission/approval chain instead of each inventing a device
tables or an ONLINE rule.

What this module deliberately does **not** create:

* a second Broker, device authority, SQL table or ON/N OFF status source — the
  device facts always come from the existing canonical ``device_directory`` /
  ``device_truth`` read in
  ``local_agent_broker_durable_runtime.LocalAgentBrokerDurableRuntime``;
* a second capability vocabulary — the local capability tokens are *referenced*
  from ``kagent.local_agent_permissions.LocalCapability`` (see
  ``CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION``) rather than re-declared;
* a second approval issuer — P01 approval remains owned by the existing B54
  approval path and this contract can only *require* it, never mint it;
* a new AI engine, model router or Provider (that is B14, untouched here).

Consequences that the rest of the platform can rely on:

* ``PRODUCT_PC_ACCESS_DEFAULT = OFF`` — a product with no explicit grant gets
  nothing; the shipped policy is the empty ``ProductPcAccessPolicy.default_off``.
* the product identifier is a **routing/permission** input. It never
  authenticates a user and never establishes a workspace; the account and
  workspace always come from the server session.
* a device id is never an input to the product guard. A device id is an output
  of the canonical Broker read, so naming a device cannot widen a product.
* a work ticket / approval minted for one product can never be replayed by
  another product.
* a READ grant never implies WRITE. ``file.write`` needs its own grant *and*
  keeps the separate P01 approval boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import ControlPlaneContractError

PRODUCT_PC_ACCESS_CONTRACT_VERSION = "padiem.common-pc-access.v1"

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


class PcAccessOperation(str, Enum):
    """The closed set of product-level PC access operations.

    ``device.list`` / ``task.status`` / ``task.result`` are server-side reads of
    the canonical Broker. ``file.list`` / ``file.read`` / ``file.write`` reach
    the Windows computer through the existing Local Runner and therefore cross
    the local permission + P01 approval boundary.
    """

    DEVICE_LIST = "device.list"
    FILE_LIST = "file.list"
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    TASK_STATUS = "task.status"
    TASK_RESULT = "task.result"


#: Operations that touch the computer, so a product grant alone can never run
#: them: they still require the existing approval boundary.
PC_TOUCHING_OPERATIONS = frozenset(
    {
        PcAccessOperation.FILE_LIST,
        PcAccessOperation.FILE_READ,
        PcAccessOperation.FILE_WRITE,
    }
)

#: The WRITE boundary is separate and always approval-gated, never implied by a
#: READ grant.
WRITE_PC_OPERATIONS = frozenset({PcAccessOperation.FILE_WRITE})

#: Pure server-side canonical Broker reads. These never carry a raw credential
#: and never reach the computer.
SERVER_READ_OPERATIONS = frozenset(
    {
        PcAccessOperation.DEVICE_LIST,
        PcAccessOperation.TASK_STATUS,
        PcAccessOperation.TASK_RESULT,
    }
)

#: Declaration only. The token strings are owned by the canonical local
#: permission contract (``kagent.local_agent_permissions.LocalCapability``), so
#: this module can never drift into a second capability vocabulary. The pairing
#: test asserts these exact tokens still exist in that canonical source.
CANONICAL_LOCAL_CAPABILITY_FOR_OPERATION: dict[PcAccessOperation, str] = {
    PcAccessOperation.FILE_LIST: "filesystem.read",
    PcAccessOperation.FILE_READ: "filesystem.read",
    PcAccessOperation.FILE_WRITE: "filesystem.write",
}

LOCAL_CAPABILITY_VOCABULARY_OWNER = "kagent.local_agent_permissions.LocalCapability"
CANONICAL_BROKER_DEVICE_READ = "local_agent_broker_durable_runtime.LocalAgentBrokerDurableRuntime.device_directory"
P01_APPROVAL_OWNER = "existing_b54_approval_path"

#: Canonical states the Broker itself declares terminal for a device. Anything
#: else (including an unrecognised state) fails closed here.
TERMINAL_DEVICE_STATES = frozenset({"revoked", "credential_expired"})
ACTIONABLE_DEVICE_STATE = "paired_offline"


def _safe_token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_product_pc_access_policy",
            f"{label} must be a bounded safe identifier",
        )
    return value


@dataclass(frozen=True, slots=True)
class ProductPcAccessGrant:
    """One product's explicit PC access grant.

    A grant is configuration, never proof of identity: carrying a
    ``product_id`` never authenticates a user. ``workspace_ref`` optionally
    narrows the grant to a single canonical workspace; when it is set, a
    request from any other workspace is refused.
    """

    product_id: str
    operations: frozenset[PcAccessOperation]
    workspace_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", _safe_token(self.product_id, "product_id"))
        if not isinstance(self.operations, frozenset) or not self.operations:
            raise ControlPlaneContractError(
                "invalid_product_pc_access_policy",
                "operations must be a non-empty frozenset",
            )
        normalized: set[PcAccessOperation] = set()
        for item in self.operations:
            if isinstance(item, PcAccessOperation):
                normalized.add(item)
                continue
            try:
                normalized.add(PcAccessOperation(item))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError(
                    "invalid_product_pc_access_policy",
                    "unknown pc access operation in grant",
                ) from exc
        object.__setattr__(self, "operations", frozenset(normalized))
        if self.workspace_ref is not None:
            object.__setattr__(self, "workspace_ref", _safe_token(self.workspace_ref, "workspace_ref"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "operations": sorted(item.value for item in self.operations),
            "workspace_ref": self.workspace_ref,
            "product_id_is_identity": False,
        }


@dataclass(frozen=True, slots=True)
class ProductPcAccessPolicy:
    """The server-side product -> PC access grant table.

    The shipped default is empty (``default_off``): every product is refused
    until an operator configures a grant. There is intentionally no implicit
    product, no "any product" wildcard and no capability-by-default entry.
    """

    grants: tuple[ProductPcAccessGrant, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.grants, tuple):
            raise ControlPlaneContractError(
                "invalid_product_pc_access_policy",
                "grants must be a tuple",
            )
        if not all(isinstance(grant, ProductPcAccessGrant) for grant in self.grants):
            raise ControlPlaneContractError(
                "invalid_product_pc_access_policy",
                "grants must contain ProductPcAccessGrant values",
            )
        product_ids = [grant.product_id for grant in self.grants]
        if len(set(product_ids)) != len(product_ids):
            raise ControlPlaneContractError(
                "invalid_product_pc_access_policy",
                "product pc access grants must be unique per product",
            )

    @classmethod
    def default_off(cls) -> "ProductPcAccessPolicy":
        """The shipped policy: no product holds any PC access grant."""

        return cls(grants=())

    def grant_for(self, product_id: str) -> ProductPcAccessGrant | None:
        for grant in self.grants:
            if grant.product_id == product_id:
                return grant
        return None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": PRODUCT_PC_ACCESS_CONTRACT_VERSION,
            "default": "off",
            "grants": [grant.safe_dict() for grant in self.grants],
        }


@dataclass(frozen=True, slots=True)
class PcAccessDecision:
    """A bounded, secret-free PC access decision.

    ``requires_p01_approval`` is a *floor*, never a grant: it can only be true
    when the canonical local permission path would also require approval, and it
    never lowers the requirement the existing P01 path decides. A product UI must
    not treat ``allowed=True`` as permission to run anything.
    """

    allowed: bool
    product_id: str
    operation: PcAccessOperation | None
    reason: str
    requires_p01_approval: bool
    write_boundary: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "product_id": self.product_id,
            "operation": self.operation.value if self.operation is not None else None,
            "reason": self.reason,
            "requires_p01_approval": self.requires_p01_approval,
            "write_boundary": self.write_boundary,
            "p01_approval_authority": P01_APPROVAL_OWNER,
            "caller_approval_authority": False,
            "product_id_is_identity": False,
        }


def _decision(
    *,
    allowed: bool,
    product_id: str,
    operation: PcAccessOperation | None,
    reason: str,
) -> PcAccessDecision:
    return PcAccessDecision(
        allowed=allowed,
        product_id=product_id,
        operation=operation,
        reason=reason,
        requires_p01_approval=allowed and operation in PC_TOUCHING_OPERATIONS,
        write_boundary=operation in WRITE_PC_OPERATIONS,
    )


def evaluate_pc_access(
    *,
    policy: ProductPcAccessPolicy,
    product_id: Any,
    operation: Any,
    bound_product_id: Any = None,
    workspace_ref: Any = None,
) -> PcAccessDecision:
    """Decide whether ``product_id`` may attempt ``operation``.

    The guard takes **no** device id, subject, tenant or account parameter: the
    account/workspace come from the server session and the device id is an
    output of the canonical Broker read. ``bound_product_id`` is the product
    already recorded on an existing work ticket / approval, if any — a mismatch
    means a cross-product replay and is refused.

    Every rejection is a bounded reason code on a decision object; a malformed
    request fails closed rather than raising into the caller.
    """

    if not isinstance(policy, ProductPcAccessPolicy):
        raise ControlPlaneContractError(
            "invalid_product_pc_access_request",
            "policy must be ProductPcAccessPolicy",
        )

    product_token = ""
    operation_token: PcAccessOperation | None = None
    try:
        product_token = _safe_token(product_id, "product_id")
        if isinstance(operation, PcAccessOperation):
            operation_token = operation
        else:
            operation_token = PcAccessOperation(operation)
        bound_token = None if bound_product_id is None else _safe_token(bound_product_id, "bound_product_id")
        workspace_token = None if workspace_ref is None else _safe_token(workspace_ref, "workspace_ref")
    except (ControlPlaneContractError, TypeError, ValueError):
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="invalid_pc_access_request",
        )

    # Cross-product replay: an approval / work ticket issued for one product is
    # never reusable by a different product, in either direction.
    if bound_token is not None and bound_token != product_token:
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="cross_product_ticket_reuse_denied",
        )

    grant = policy.grant_for(product_token)
    if grant is None:
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="product_not_enabled",
        )
    if grant.workspace_ref is not None and grant.workspace_ref != workspace_token:
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="product_workspace_not_granted",
        )
    if operation_token not in grant.operations:
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="capability_not_granted",
        )
    # A READ grant never implies WRITE: the WRITE boundary needs its own grant.
    if operation_token in WRITE_PC_OPERATIONS and PcAccessOperation.FILE_READ not in grant.operations:
        return _decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="write_requires_read_grant",
        )

    return _decision(
        allowed=True,
        product_id=product_token,
        operation=operation_token,
        reason="granted",
    )


def device_eligible_for_pc_access(device_facts: Mapping[str, Any]) -> bool:
    """Whether one canonical Broker directory row may carry a PC operation.

    This does **not** decide ONLINE — the canonical
    ``kagent.local_agent_server_projection`` rule stays the only ONLINE
    authority. It only refuses the states the Broker itself already declares
    terminal (``revoked`` / ``credential_expired``), any unrecognised state, and
    a device with no bound session.
    """

    if not isinstance(device_facts, Mapping):
        return False
    if device_facts.get("canonical_state") != ACTIONABLE_DEVICE_STATE:
        return False
    return isinstance(device_facts.get("session"), Mapping)


def _device_row(facts: Mapping[str, Any]) -> dict[str, Any] | None:
    binding = facts.get("binding")
    if not isinstance(binding, Mapping):
        return None
    device_id = binding.get("device_id")
    if not isinstance(device_id, str) or not _SAFE_TOKEN_RE.fullmatch(device_id):
        return None
    return {
        "device_id": device_id,
        "canonical_state": facts.get("canonical_state"),
        "has_session": isinstance(facts.get("session"), Mapping),
        "heartbeat_present": facts.get("heartbeat_last_seen_at") is not None,
        "actionable": device_eligible_for_pc_access(facts),
        "online_decided_here": False,
    }


def build_product_device_view(
    *,
    policy: ProductPcAccessPolicy,
    product_id: Any,
    directory_result: Any,
    bound_product_id: Any = None,
    workspace_ref: Any = None,
) -> dict[str, Any]:
    """Project the canonical Broker directory for one product, sanitized.

    This is the product-neutral interface CENTRAL wires into B66 / Chat / Engine
    routes. It:

    * requires the product to hold ``device.list`` (default OFF);
    * consumes the canonical ``device_directory`` result unchanged — it never
      re-derives a device list, an ONLINE status or a device identity;
    * strips every owner/workspace/binding/session/credential field so a product
      route can never forward broker internals to a browser;
    * preserves the device id exactly, so Claw and B66 resolve the same physical
      PC to the same device id.

    A product without ``device.list`` gets ``available: false`` and an empty
    device list — never a guessed or partial device set.
    """

    decision = evaluate_pc_access(
        policy=policy,
        product_id=product_id,
        operation=PcAccessOperation.DEVICE_LIST,
        bound_product_id=bound_product_id,
        workspace_ref=workspace_ref,
    )
    if not decision.allowed:
        return {
            "ok": True,
            "available": False,
            "owner_scoped": True,
            "product_id": decision.product_id,
            "product_may_list_devices": False,
            "reason": decision.reason,
            "devices": [],
            "device_count": 0,
            "online_decided_here": False,
            "sanitized": True,
        }

    base: dict[str, Any] = {
        "ok": True,
        "available": False,
        "owner_scoped": True,
        "product_id": decision.product_id,
        "product_may_list_devices": True,
        "devices": [],
        "device_count": 0,
        "online_decided_here": False,
        "sanitized": True,
    }

    if not isinstance(directory_result, Mapping) or directory_result.get("ok") is not True:
        base["reason"] = "device_directory_unavailable"
        return base

    raw_devices = directory_result.get("devices")
    if raw_devices is None:
        # The canonical read is `available: false` (for example no binding yet).
        base["reason"] = str(directory_result.get("reason", "device_directory_unavailable"))
        return base
    if not isinstance(raw_devices, (list, tuple)):
        base["reason"] = "device_directory_unavailable"
        return base

    rows: list[dict[str, Any]] = []
    for facts in raw_devices:
        if not isinstance(facts, Mapping):
            base["reason"] = "device_directory_unavailable"
            return base
        row = _device_row(facts)
        if row is None:
            base["reason"] = "device_directory_unavailable"
            return base
        rows.append(row)

    base["available"] = True
    base["reason"] = "granted"
    base["devices"] = rows
    base["device_count"] = len(rows)
    return base


@dataclass(frozen=True, slots=True)
class PcExecutionDecision:
    """The bounded result of the P2 execution-authorization contract.

    ``p01_verified`` / ``p01_product_id`` are **inputs** produced by the
    existing approval path. This contract never verifies an approval itself and
    never mints one; it only refuses to let execution proceed without the
    canonical approval and refuses to let an approval cross a product boundary.
    """

    allowed: bool
    product_id: str
    operation: PcAccessOperation | None
    reason: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "product_id": self.product_id,
            "operation": self.operation.value if self.operation is not None else None,
            "reason": self.reason,
            "p01_verification_authority": P01_APPROVAL_OWNER,
            "caller_approval_authority": False,
        }


def _execution_decision(
    *,
    allowed: bool,
    product_id: str,
    operation: PcAccessOperation | None,
    reason: str,
) -> PcExecutionDecision:
    return PcExecutionDecision(
        allowed=allowed,
        product_id=product_id,
        operation=operation,
        reason=reason,
    )


def evaluate_pc_execution(
    *,
    policy: ProductPcAccessPolicy,
    product_id: Any,
    operation: Any,
    bound_product_id: Any,
    account_ref: Any,
    workspace_ref: Any,
    device_facts: Any,
    p01_verified: bool = False,
    p01_product_id: Any = None,
    p01_read_only: bool = True,
    replay: bool = False,
) -> PcExecutionDecision:
    """P2 — the authorization contract a product must satisfy before the
    existing Local Runner executes anything on a PC.

    Every precondition the CENTRAL work contract requires is checked here, in
    order, and any failure refuses execution:

    1. the product holds the capability for the operation (``evaluate_pc_access``);
    2. the existing work ticket was minted for this same product;
    3. the canonical device binding belongs to this authenticated account and
       workspace (never a caller-supplied id);
    4. the device is in a non-terminal state with a bound session;
    5. a PC-touching operation presents an approval the *existing* path already
       verified, minted for this same product;
    6. a READ approval can never authorize WRITE;
    7. a replayed request is refused.

    ``p01_verified`` is the result of the existing B54 approval path. The
    device id is never a parameter: it is read out of the canonical device row.
    """

    decision = evaluate_pc_access(
        policy=policy,
        product_id=product_id,
        operation=operation,
        bound_product_id=bound_product_id,
        workspace_ref=workspace_ref,
    )
    if not decision.allowed:
        return _execution_decision(
            allowed=False,
            product_id=decision.product_id,
            operation=decision.operation,
            reason=decision.reason,
        )

    product_token = decision.product_id
    operation_token = decision.operation

    try:
        account_token = _safe_token(account_ref, "account_ref")
        workspace_token = _safe_token(workspace_ref, "workspace_ref")
        p01_token = None if p01_product_id is None else _safe_token(p01_product_id, "p01_product_id")
    except (ControlPlaneContractError, TypeError, ValueError):
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="invalid_pc_execution_request",
        )

    if not isinstance(device_facts, Mapping):
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    binding = device_facts.get("binding")
    if not isinstance(binding, Mapping):
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    # The device must belong to this authenticated account/workspace. The row is
    # read from the canonical Broker, so a caller cannot name a foreign device.
    if binding.get("account_ref") != account_token:
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_scope_mismatch",
        )
    if binding.get("workspace_ref") != workspace_token:
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_scope_mismatch",
        )

    if not device_eligible_for_pc_access(device_facts):
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    if replay:
        return _execution_decision(
            allowed=False,
            product_id=product_token,
            operation=operation_token,
            reason="replay_denied",
        )

    if operation_token in PC_TOUCHING_OPERATIONS:
        if p01_verified is not True:
            return _execution_decision(
                allowed=False,
                product_id=product_token,
                operation=operation_token,
                reason="p01_approval_required",
            )
        if p01_token != product_token:
            return _execution_decision(
                allowed=False,
                product_id=product_token,
                operation=operation_token,
                reason="cross_product_approval_reuse_denied",
            )
        if operation_token in WRITE_PC_OPERATIONS and p01_read_only is True:
            return _execution_decision(
                allowed=False,
                product_id=product_token,
                operation=operation_token,
                reason="read_approval_cannot_write",
            )

    return _execution_decision(
        allowed=True,
        product_id=product_token,
        operation=operation_token,
        reason="granted",
    )


# --- non-negotiable invariants (mirrored by tests) -------------------------

PRODUCT_PC_ACCESS_DEFAULT = "off"
PRODUCT_ID_IS_AUTHENTICATION = False
PRODUCT_ID_IS_ROUTING_PERMISSION_INPUT = True
B14_IS_PC_ACCESS_AUTHORITY = False
NEW_ENGINE_CREATED = False
NEW_BROKER_CREATED = False
NEW_DEVICE_AUTHORITY_CREATED = False
NEW_DEVICE_TABLE_CREATED = False
NEW_P01_APPROVAL_SERVER_CREATED = False
ONLINE_DECIDED_IN_CONTRACT = False
CLIENT_DEVICE_ID_TRUSTED = False
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
READ_GRANT_IMPLIES_WRITE = False
WRITE_REQUIRES_SEPARATE_GRANT = True
WRITE_REQUIRES_P01_APPROVAL = True
CROSS_PRODUCT_TICKET_REUSE_ALLOWED = False
SECOND_ONLINE_AUTHORITY = False
SECOND_DEVICE_AUTHORITY = False
SECOND_CAPABILITY_VOCABULARY = False
PC_ACCESS_GRANT_IS_APPROVAL = False
PRODUCT_VIEW_EXPOSES_BROKER_INTERNALS = False
P01_VERIFIED_IS_AN_INPUT = True
READ_APPROVAL_CAN_AUTHORIZE_WRITE = False
PC_EXECUTION_PATH_NEWLY_WIRED = False
PC_EXECUTION_REQUIRES_DEVICE_SESSION = True
PC_EXECUTION_REPLAY_ALLOWED = False
