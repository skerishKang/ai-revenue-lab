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
* **nothing in this module authorizes execution.** The product device view and
  the P2 preflight contract are decision *inputs*; ONLINE truth stays with the
  canonical Broker projection (``kagent.local_agent_server_projection``) and
  execution approval stays with the existing P01 path. This module can only
  *require* them, so ``dispatch_authorized`` is hard-wired ``False`` here and a
  PC-touching operation can never be released by anything returned from this
  file.

A device fact is a *fact the canonical Broker attested*, so the product view
accepts only the envelope the Broker marks ``owner_scoped: true`` **and**
``available: true``. Any other envelope — a missing or false attestation, an
``available: false`` envelope that still carries a device list, an empty
attested list, a duplicated device id, more than the Broker's device bound, a
declared count that does not match, a malformed state type or a mixed-in
session — refuses the *whole* view. A partially valid list is never handed to a
product as if it were complete.
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

#: The canonical ``device_truth`` / ``device_directory`` state vocabulary in
#: full. A row whose state is not one of these — wrong type, or an unknown
#: value — is a malformed directory row, never silently read as "not terminal".
CANONICAL_DEVICE_STATES = frozenset({ACTIONABLE_DEVICE_STATE}) | TERMINAL_DEVICE_STATES

#: Mirror of ``local_agent_broker_durable_runtime.MAX_DEVICE_DIRECTORY_DEVICES``.
#: The canonical Broker refuses a directory above this bound *whole*; the shared
#: product projection must not weaken that invariant, so it re-checks the bound
#: and a parity test asserts the two constants stay equal.
MAX_PRODUCT_VIEW_DEVICES = 24
BROKER_MAX_DEVICE_CONSTANT = (
    "local_agent_broker_durable_runtime.MAX_DEVICE_DIRECTORY_DEVICES"
)

#: The canonical envelope the Broker uses for "this owner has no device binding
#: yet". It is a legitimate empty read, not an error, and carries no device fact.
NO_DEVICE_BINDING_REASON = "no_device_binding"

#: Bounded reason codes this projection may return. They are this contract's own
#: vocabulary: the Broker's ``reason`` / ``error.code`` text is never echoed to a
#: product route or a browser.
VIEW_REASON_GRANTED = "granted"
VIEW_REASON_UNAVAILABLE = "device_directory_unavailable"
VIEW_REASON_UNVERIFIED = "device_directory_unverified"
VIEW_REASON_MALFORMED = "device_directory_malformed"

#: ONLINE truth is **not** decided anywhere in this contract; this names the
#: canonical owner a trustworthy dispatch decision would have to consult.
ONLINE_PROOF_AUTHORITY = "canonical_broker_fresh_online_projection"

#: The closed set of trusted facts a *future* dispatch gate must receive from the
#: canonical owners before anything may actually run on a PC. This contract can
#: never obtain them — they are not parameters here — so it grants nothing.
REQUIRED_DISPATCH_FACTS = (
    "canonical_broker_fresh_online_attestation",
    "canonical_device_session_and_heartbeat_recheck",
    "existing_p01_approval_verification",
    "work_ticket_scope_expiry_and_replay_check",
)

#: No dispatch gate exists yet. Declaring this ``False`` is what keeps
#: ``preflight_eligible`` from being mistaken for a run permission.
DISPATCH_GATE_WIRED = False


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


def _canonical_state(value: Any) -> str | None:
    """Return the state only when it is a real canonical state token.

    A missing state, an unknown value or a wrong type is a malformed row: the
    projection must never read an unrecognised value as "not terminal" and hand
    it to a product UI as if the computer were a normal, current device.
    """

    if not isinstance(value, str) or value not in CANONICAL_DEVICE_STATES:
        return None
    return value


def _device_row(facts: Mapping[str, Any]) -> dict[str, Any] | None:
    """Strictly project one canonical directory row, or ``None`` if malformed.

    ``None`` refuses the *whole* directory. A malformed record is never skipped
    while the remaining computers are shown, because a shortened list would look
    like a complete one. Only canonical, secret-free facts are read, and only the
    allowlisted output keys below are emitted.
    """

    binding = facts.get("binding")
    if not isinstance(binding, Mapping):
        return None
    device_id = binding.get("device_id")
    if not isinstance(device_id, str) or not _SAFE_TOKEN_RE.fullmatch(device_id):
        return None
    canonical_state = _canonical_state(facts.get("canonical_state"))
    if canonical_state is None:
        return None

    session = facts.get("session")
    if session is not None:
        if not isinstance(session, Mapping):
            return None
        # A session that does not speak for this same device and scope is
        # mixed-in or forged state, never a session belonging to this device.
        if session.get("device_id") != device_id:
            return None
        for key in ("binding_ref", "account_ref", "workspace_ref"):
            if key in session and session.get(key) != binding.get(key):
                return None

    heartbeat = facts.get("heartbeat_last_seen_at")
    if heartbeat is not None and not isinstance(heartbeat, str):
        return None

    return {
        "device_id": device_id,
        "canonical_state": canonical_state,
        "has_session": session is not None,
        "heartbeat_present": heartbeat is not None,
        "actionable": device_eligible_for_pc_access(facts),
        "online_decided_here": False,
    }


def _product_view(
    *,
    product_id: str,
    available: bool,
    reason: str,
    product_may_list_devices: bool,
    owner_scoped: bool,
    directory_verified: bool,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble one bounded product view.

    Every refusal path builds through here, so a refusal can never accidentally
    carry a device fact: ``devices`` is empty unless an attested, fully valid
    canonical directory was parsed.
    """

    rows = list(devices) if devices else []
    return {
        "ok": True,
        "available": available,
        "owner_scoped": owner_scoped,
        "directory_verified": directory_verified,
        "product_id": product_id,
        "product_may_list_devices": product_may_list_devices,
        "reason": reason,
        "devices": rows,
        "device_count": len(rows),
        "online_decided_here": False,
        "preflight_only": True,
        "dispatch_authorized": False,
        "sanitized": True,
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
    * accepts device facts **only** from the envelope the canonical Broker marks
      ``owner_scoped: true`` *and* ``available: true``, and only when every
      invariant the Broker guarantees still holds here (no duplicated device id,
      at most ``MAX_PRODUCT_VIEW_DEVICES`` devices, a matching declared
      ``device_count``, well-formed state/binding/session records). Anything
      else refuses the whole view with ``devices: []``, so a forged, truncated
      or contradictory envelope can never surface a device fact;
    * keeps the canonical ``no_device_binding`` empty read distinct, without ever
      reporting an empty list as a normal connected state;
    * never echoes the Broker's ``reason`` / ``error.code`` / ``error.message``
      text — every reason it returns is from its own bounded vocabulary;
    * consumes the canonical ``device_directory`` result unchanged — it never
      re-derives a device list, an ONLINE status or a device identity;
    * strips every owner/workspace/binding/session/credential field so a product
      route can never forward broker internals to a browser;
    * preserves the device id exactly, so Claw and B66 resolve the same physical
      PC to the same device id.

    A product without ``device.list`` gets ``available: false`` and an empty
    device list — never a guessed or partial device set. The returned view is an
    availability/preflight projection: it carries ``dispatch_authorized: false``
    and is not permission to run anything.
    """

    decision = evaluate_pc_access(
        policy=policy,
        product_id=product_id,
        operation=PcAccessOperation.DEVICE_LIST,
        bound_product_id=bound_product_id,
        workspace_ref=workspace_ref,
    )
    if not decision.allowed:
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=decision.reason,
            product_may_list_devices=False,
            owner_scoped=False,
            directory_verified=False,
        )

    if not isinstance(directory_result, Mapping) or directory_result.get("ok") is not True:
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=VIEW_REASON_UNAVAILABLE,
            product_may_list_devices=True,
            owner_scoped=False,
            directory_verified=False,
        )

    owner_scoped = directory_result.get("owner_scoped")
    available = directory_result.get("available")

    # Only the canonical attested envelope may carry device facts. The Broker
    # attests ``owner_scoped: true`` **and** ``available: true`` exactly, so both
    # are required by identity here: a missing attestation, a false attestation,
    # or an ``available: false`` envelope that still carries a device list is
    # forged or contradictory and is refused whole, with no fact emitted.
    if owner_scoped is not True or available is not True:
        if (
            available is False
            and owner_scoped is None
            and "devices" not in directory_result
        ):
            # No device fact exists in this shape, so it can be answered honestly
            # rather than refused. The canonical "this owner has no device
            # binding yet" read stays distinct and verified; any other
            # ``available: false`` text is *not* trusted, is reported with this
            # contract's own bounded code, and is never echoed.
            canonical_empty = directory_result.get("reason") == NO_DEVICE_BINDING_REASON
            return _product_view(
                product_id=decision.product_id,
                available=False,
                reason=(
                    NO_DEVICE_BINDING_REASON if canonical_empty else VIEW_REASON_UNAVAILABLE
                ),
                product_may_list_devices=True,
                owner_scoped=True,
                directory_verified=canonical_empty,
            )
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=VIEW_REASON_UNVERIFIED,
            product_may_list_devices=True,
            owner_scoped=False,
            directory_verified=False,
        )

    raw_devices = directory_result.get("devices")
    if not isinstance(raw_devices, (list, tuple)):
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=VIEW_REASON_MALFORMED,
            product_may_list_devices=True,
            owner_scoped=False,
            directory_verified=False,
        )

    # An attested, available directory with zero devices contradicts the canonical
    # contract (the Broker returns ``available: false`` when nothing is bound), so
    # an empty list is never reported as a normal, connected-looking state.
    if not raw_devices:
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=VIEW_REASON_UNVERIFIED,
            product_may_list_devices=True,
            owner_scoped=False,
            directory_verified=False,
        )

    declared_count = directory_result.get("device_count")
    declared_max = directory_result.get("max_devices")
    if (
        not isinstance(declared_count, int)
        or isinstance(declared_count, bool)
        or declared_count != len(raw_devices)
        or len(raw_devices) > MAX_PRODUCT_VIEW_DEVICES
        or (
            declared_max is not None
            and (
                not isinstance(declared_max, int)
                or isinstance(declared_max, bool)
                or declared_max != MAX_PRODUCT_VIEW_DEVICES
            )
        )
    ):
        return _product_view(
            product_id=decision.product_id,
            available=False,
            reason=VIEW_REASON_MALFORMED,
            product_may_list_devices=True,
            owner_scoped=False,
            directory_verified=False,
        )

    rows: list[dict[str, Any]] = []
    seen_device_ids: set[str] = set()
    for facts in raw_devices:
        if not isinstance(facts, Mapping):
            return _product_view(
                product_id=decision.product_id,
                available=False,
                reason=VIEW_REASON_MALFORMED,
                product_may_list_devices=True,
                owner_scoped=False,
                directory_verified=False,
            )
        row = _device_row(facts)
        if row is None or row["device_id"] in seen_device_ids:
            return _product_view(
                product_id=decision.product_id,
                available=False,
                reason=VIEW_REASON_MALFORMED,
                product_may_list_devices=True,
                owner_scoped=False,
                directory_verified=False,
            )
        seen_device_ids.add(row["device_id"])
        rows.append(row)

    return _product_view(
        product_id=decision.product_id,
        available=True,
        reason=VIEW_REASON_GRANTED,
        product_may_list_devices=True,
        owner_scoped=True,
        directory_verified=True,
        devices=rows,
    )


@dataclass(frozen=True, slots=True)
class PcPreflightDecision:
    """The bounded result of the P2 **preflight** contract.

    This object is deliberately **not** an execution permission:

    * ``preflight_eligible`` means only "every product, capability, scope and
      approval-boundary precondition this contract is able to check has passed".
      It is never proof that a computer is online.
    * ``dispatch_authorized`` is hard-wired ``False``. Releasing a PC-touching
      operation would require trusted *fresh* ONLINE and P01/ticket-verification
      facts from the canonical owners (see ``REQUIRED_DISPATCH_FACTS``). This
      contract does not receive them, does not stand up a second authority or
      heartbeat decider to obtain them, and therefore can never authorize
      anything to run.
    * ``p01_verified_by_existing_path`` is a **caller-supplied input** produced by
      the existing approval path; it is never proof, and the contract neither
      verifies nor mints an approval. Setting it true changes no dispatch fact.

    A product route, runner or UI must never key an execution decision off this
    object, and must not present ``preflight_eligible`` as a run permission.
    """

    preflight_eligible: bool
    product_id: str
    operation: PcAccessOperation | None
    reason: str
    requires_p01_approval: bool
    write_boundary: bool

    @property
    def dispatch_authorized(self) -> bool:
        """Hard-wired ``False``.

        A property, not a field, so a ``True`` dispatch authorization cannot be
        constructed at all — no caller can turn a preflight result into a run
        permission.
        """

        return False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "preflight_eligible": self.preflight_eligible,
            "product_id": self.product_id,
            "operation": self.operation.value if self.operation is not None else None,
            "reason": self.reason,
            "requires_p01_approval": self.requires_p01_approval,
            "write_boundary": self.write_boundary,
            "preflight_only": True,
            "dispatch_authorized": False,
            "dispatch_gate_wired": DISPATCH_GATE_WIRED,
            "required_dispatch_facts": list(REQUIRED_DISPATCH_FACTS),
            "online_proof_authority": ONLINE_PROOF_AUTHORITY,
            "fresh_online_proven_here": False,
            "p01_verification_authority": P01_APPROVAL_OWNER,
            "p01_verified_is_caller_supplied_input": True,
            "caller_approval_authority": False,
            "product_id_is_identity": False,
        }


def _preflight_decision(
    *,
    eligible: bool,
    product_id: str,
    operation: PcAccessOperation | None,
    reason: str,
) -> PcPreflightDecision:
    return PcPreflightDecision(
        preflight_eligible=eligible,
        product_id=product_id,
        operation=operation,
        reason=reason,
        requires_p01_approval=eligible and operation in PC_TOUCHING_OPERATIONS,
        write_boundary=operation in WRITE_PC_OPERATIONS,
    )


def pc_dispatch_requirements(
    *,
    product_id: Any,
    operation: Any,
) -> dict[str, Any]:
    """Declare what a *future* trusted dispatch gate must verify. Grants nothing.

    This is the contract-level hand-off for CENTRAL. Before any PC-touching
    operation may actually run, a dispatch decision has to be produced from fresh
    facts the canonical owners alone own — the Broker's ONLINE projection, the
    device session/heartbeat recheck, the existing P01 approval verification and
    the work-ticket scope/expiry/replay check.

    This function evaluates none of them and returns ``dispatch_authorized:
    False`` unconditionally: it exists so the boundary is explicit and testable
    instead of implied. It creates no authority and no gate.
    """

    try:
        product_token = _safe_token(product_id, "product_id")
        operation_token = (
            operation
            if isinstance(operation, PcAccessOperation)
            else PcAccessOperation(operation)
        )
    except (ControlPlaneContractError, TypeError, ValueError):
        return {
            "ok": False,
            "reason": "invalid_pc_access_request",
            "dispatch_authorized": False,
            "dispatch_gate_wired": DISPATCH_GATE_WIRED,
        }

    return {
        "ok": True,
        "product_id": product_token,
        "operation": operation_token.value,
        "pc_touching": operation_token in PC_TOUCHING_OPERATIONS,
        "dispatch_authorized": False,
        "dispatch_gate_wired": DISPATCH_GATE_WIRED,
        "preflight_only": True,
        "required_dispatch_facts": list(REQUIRED_DISPATCH_FACTS),
        "online_proof_authority": ONLINE_PROOF_AUTHORITY,
        "p01_verification_authority": P01_APPROVAL_OWNER,
        "new_authority_created": False,
    }


def evaluate_pc_preflight(
    *,
    policy: ProductPcAccessPolicy,
    product_id: Any,
    operation: Any,
    bound_product_id: Any,
    account_ref: Any,
    workspace_ref: Any,
    device_facts: Any,
    p01_verified_by_existing_path: bool = False,
    p01_product_id: Any = None,
    p01_read_only: bool = True,
    replay: bool = False,
) -> PcPreflightDecision:
    """P2 — the **preflight** contract a product must satisfy before the existing
    Local Runner may even consider executing anything on a PC.

    Every precondition the CENTRAL work contract requires is checked here, in
    order, and any failure refuses:

    1. the product holds the capability for the operation (``evaluate_pc_access``);
    2. the existing work ticket was minted for this same product;
    3. the canonical device binding belongs to this authenticated account and
       workspace (never a caller-supplied id);
    4. the device is in a non-terminal state with a bound session;
    5. a PC-touching operation presents an approval the *existing* path already
       verified, minted for this same product;
    6. a READ approval can never authorize WRITE;
    7. a replayed request is refused.

    What it deliberately can **not** do is release execution. There is no
    ``fresh_online_verified`` parameter, because this module cannot obtain a
    trustworthy fresh ONLINE fact and will not stand up a second heartbeat or
    presence authority to invent one. ``preflight_eligible=True`` only means
    "the preflight checks passed"; ``dispatch_authorized`` stays ``False`` in
    every case, and a caller-supplied ``p01_verified_by_existing_path`` is an
    input, never proof.

    ``p01_verified_by_existing_path`` / ``p01_product_id`` are results of the
    existing B54 approval path. The device id is never a parameter: it is read
    out of the canonical device row.
    """

    decision = evaluate_pc_access(
        policy=policy,
        product_id=product_id,
        operation=operation,
        bound_product_id=bound_product_id,
        workspace_ref=workspace_ref,
    )
    if not decision.allowed:
        return _preflight_decision(
            eligible=False,
            product_id=decision.product_id,
            operation=decision.operation,
            reason=decision.reason,
        )

    product_token = decision.product_id
    operation_token = decision.operation

    try:
        account_token = _safe_token(account_ref, "account_ref")
        workspace_token = _safe_token(workspace_ref, "workspace_ref")
        p01_token = (
            None
            if p01_product_id is None
            else _safe_token(p01_product_id, "p01_product_id")
        )
    except (ControlPlaneContractError, TypeError, ValueError):
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="invalid_pc_execution_request",
        )

    if not isinstance(device_facts, Mapping):
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    binding = device_facts.get("binding")
    if not isinstance(binding, Mapping):
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    # The device must belong to this authenticated account/workspace. The row is
    # read from the canonical Broker, so a caller cannot name a foreign device.
    if binding.get("account_ref") != account_token:
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_scope_mismatch",
        )
    if binding.get("workspace_ref") != workspace_token:
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_scope_mismatch",
        )

    if not device_eligible_for_pc_access(device_facts):
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="device_not_actionable",
        )

    if replay:
        return _preflight_decision(
            eligible=False,
            product_id=product_token,
            operation=operation_token,
            reason="replay_denied",
        )

    if operation_token in PC_TOUCHING_OPERATIONS:
        if p01_verified_by_existing_path is not True:
            return _preflight_decision(
                eligible=False,
                product_id=product_token,
                operation=operation_token,
                reason="p01_approval_required",
            )
        if p01_token != product_token:
            return _preflight_decision(
                eligible=False,
                product_id=product_token,
                operation=operation_token,
                reason="cross_product_approval_reuse_denied",
            )
        if operation_token in WRITE_PC_OPERATIONS and p01_read_only is True:
            return _preflight_decision(
                eligible=False,
                product_id=product_token,
                operation=operation_token,
                reason="read_approval_cannot_write",
            )

    return _preflight_decision(
        eligible=True,
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

# P0/P1 — the shared projection may only emit device facts from an attested,
# fully valid canonical envelope, and it never weakens a Broker invariant.
DEVICE_VIEW_REQUIRES_OWNER_SCOPE_ATTESTATION = True
DEVICE_VIEW_REQUIRES_AVAILABLE_ATTESTATION = True
DEVICE_VIEW_FAILS_CLOSED_ON_UNVERIFIED_ENVELOPE = True
DEVICE_VIEW_FAILS_CLOSED_ON_MALFORMED_ROW = True
DEVICE_VIEW_REPORTS_EMPTY_ATTESTED_DIRECTORY = False
DEVICE_VIEW_ENFORCES_MAX_DEVICES = True
DEVICE_VIEW_ENFORCES_DUPLICATE_DEVICE_ID = True
DEVICE_VIEW_ENFORCES_DECLARED_DEVICE_COUNT = True
DEVICE_VIEW_ECHOES_BROKER_ERROR_TEXT = False

# P2 — preflight only. No dispatch grant of any kind is produced here.
PREFLIGHT_ONLY_NO_DISPATCH_GRANT = True
DISPATCH_AUTHORIZED_BY_THIS_CONTRACT = False
P01_VERIFIED_IS_A_CALLER_SUPPLIED_INPUT = True
FRESH_ONLINE_PROVEN_IN_CONTRACT = False
TRUSTED_FRESH_ONLINE_FACT_AVAILABLE = False
ONLINE_TRUTH_AUTHORITY = ONLINE_PROOF_AUTHORITY
