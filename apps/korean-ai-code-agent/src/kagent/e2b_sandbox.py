"""E2B Cloud M1 launch adapter — request shape and lifecycle mapping only (#1405 step C).

This module is a prototype of how one real provider would satisfy the sandbox contracts the
repository already owns. It cannot reach E2B: there is no provider SDK import, no URL, no
credential and no socket anywhere in it. Every provider interaction goes through the narrow
``E2BSandboxTransport`` seam, which tests satisfy with a scripted in-memory fake. ``allocate``
here produces a canonical ``SandboxLease`` plus a request shape — it does not create anything
in a datacenter, and ``E2B_REAL_SANDBOX_ALLOCATIONS`` says so.

What this file is allowed to claim comes from three buckets, recorded in
``E2B_CONTROL_PROVENANCE`` and never blended together:

```text
PROVIDER_DOCUMENTED    E2B's own docs say it. Not conformance evidence: the repository's
                       review gate accepts only live-probe or trusted-attestation bases.
ADAPTER_BORNE          This file enforces it. A provider upgrade cannot be assumed to have
                       kept it, so it must be re-probed through the adapter.
UNVERIFIED_LIVE        Nobody has observed it. It stays unresolved until an authorized
                       live probe runs.
```

Two things are deliberately not modelled as solved. Termination is observed as a *reservation*
ending: no provider API in this space attests that a guest process tree died, so
``E2BTerminationEvidence`` has no field that could carry such a claim. And TTL enforcement,
link-local/metadata unreachability and the control-plane exception are recorded as
documentation or as unverified, never as measured.

FORMAL_PROVIDER_SELECTION=NO. E2B is the first prototype target and the leading candidate for
live evidence, which is a different statement, and the repository's own flags make the
difference enforceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

from .contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    SANDBOX_LEASE_MIN_TTL_SECONDS,
    ContractError,
    SandboxLease,
    SandboxLeaseRequest,
    SandboxLeaseState,
    _safe_id,
)
from .sandbox import SandboxLeaseError, SandboxUnavailableError
from .sandbox_conformance import IsolationPrimitive, SandboxSecurityPolicy
from .sandbox_conformance_harness import validate_lease_request_against_cloud_m1_policy
from .sandbox_provider_probe import SandboxProviderCandidate


# ---------------------------------------------------------------------------
# What E2B's current documentation states. Research bases only: none of these
# lines is conformance evidence, and several are things the adapter must
# counteract rather than rely on.
# ---------------------------------------------------------------------------

E2B_PROVIDER_CANDIDATE = SandboxProviderCandidate.E2B
E2B_ISOLATION_PRIMITIVE = IsolationPrimitive.MICROVM

#: E2B documents every sandbox as its own Firecracker microVM with its own kernel.
E2B_FIRECRACKER_MICROVM = "DOCUMENTED"

#: E2B sandboxes have outbound internet access unless the caller denies it. The
#: adapter therefore cannot accept a provider default for the one control Cloud M1
#: is most particular about.
E2B_DEFAULT_EGRESS = "ALLOW"
E2B_DENY_ALL = "DOCUMENTED"
E2B_DENY_ALL_ENCODING = "0.0.0.0/0"
E2B_RUNTIME_NETWORK_UPDATE = "DOCUMENTED"
E2B_NETWORK_UPDATE_SEMANTICS = "REPLACES_NOT_MERGES"

#: Documented lifetime behaviour. The 300-second default and the plan-bound
#: continuous maximum are provider facts; the clamp below is the adapter's.
E2B_DEFAULT_TIMEOUT_SECONDS = 300
#: E2B documents kill-on-timeout; the value below is the request field the adapter
#: sends so a future provider default change cannot move this lane. Research label in
#: the work order is E2B_TIMEOUT_DEFAULT_ACTION=KILL.
E2B_TIMEOUT_DEFAULT_ACTION = "kill"
E2B_HOBBY_CONTINUOUS_MAX_SECONDS = 3_600
E2B_PRO_CONTINUOUS_MAX_SECONDS = 86_400

#: A paused sandbox has no TTL and is never reaped by the provider, and snapshots,
#: forks and volume mounts outlive the sandbox that produced them. Those are
#: cross-run-state hazards, so the adapter forbids the states rather than
#: tolerating them.
E2B_PAUSED_SANDBOX_TTL = "NONE"
E2B_PERSISTENCE_FEATURES_FORBIDDEN = (
    "pause",
    "auto_pause",
    "auto_resume",
    "snapshot",
    "fork",
    "volume_mounts",
)

#: Sandbox URLs are public unless the create request restricts them.
E2B_PUBLIC_URL_DEFAULT = "PUBLIC"

#: Searched for on 2026-09-20 in https://docs.e2b.dev/network/internet-access and
#: https://docs.e2b.dev/faq/security-and-compliance and NOT FOUND. Recorded here as
#: the CENTRAL-supplied research correction it is, so a reader does not mistake the
#: absence of a statement for a statement of absence, and so the probe treats it as a
#: question rather than an answer.
E2B_LINK_LOCAL_169_254_BLOCKED = "CENTRAL_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
E2B_CONTROL_CHANNEL_EXCEPTION = "CENTRAL_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"

#: A live probe creates real provider resources under a real account. It is not this
#: child's to authorize, and no code path here can start one.
E2B_SECURITY_LIVE_PROBE_WRITTEN_CONSENT_REQUIRED = True

# ---------------------------------------------------------------------------
# Hard "not in this child" flags. These are the assertions the repository's
# review gates read, restated at the layer they now apply to.
# ---------------------------------------------------------------------------

E2B_ADAPTER_SDK_IMPORTS = 0
E2B_REAL_PROVIDER_CALLS = 0
E2B_REAL_SANDBOX_ALLOCATIONS = 0
E2B_LIVE_EXECUTION_READY = False
REAL_E2B_PROVIDER_SELECTED = False
REAL_E2B_PROVIDER_EVIDENCE_COLLECTION_CONFIGURED = False
E2B_TERMINATION_ATTESTES_PROCESS_TREE_KILL = False
E2B_ARTIFACT_PROJECTION_IN_THIS_CHILD = False

#: Keys this adapter never accepts from a caller, in any form. The endpoint-shaped ones are
#: why the adapter takes no base URL at all: a transport is handed to it out of band, so no
#: caller can redirect a launch. The persistence and credential ones are why the built
#: payload is asserted disjoint from this set on every call.
E2B_NEVER_ACCEPTED_KEYS = (
    "accessToken",
    "api_key",
    "api_url",
    "base_snapshot",
    "base_url",
    "docker_socket",
    "domain",
    "endpoint",
    "from_fork",
    "host_path",
    "host_secret",
    "sandbox_domain",
    "secret",
    "snapshot_id",
)

#: The closed launch-body shape. A new key is a decision, not an accident: this set is
#: asserted on every payload built.
E2B_PAYLOAD_KEYS = (
    "allow_internet_access",
    "allow_public_traffic",
    "auto_pause",
    "auto_resume",
    "control_provenance",
    "envs",
    "fork_source",
    "host_mounts",
    "materialization",
    "metadata",
    "network",
    "privileged",
    "public_ports",
    "requested_at",
    "runtime_socket",
    "secrets",
    "snapshot",
    "template",
    "timeout",
    "timeout_action",
    "volume_mounts",
)

#: Metadata the adapter correlates a launch with, and nothing else.
E2B_METADATA_KEYS = ("repository_ref", "requested_revision", "run_id")

E2B_TERMINAL_PROVIDER_STATES = ("killed", "finished", "not_found", "terminated")


class E2BControlProvenance(str, Enum):
    PROVIDER_DOCUMENTED = "provider_documented"
    ADAPTER_BORNE = "adapter_borne"
    UNVERIFIED_LIVE = "unverified_live"


#: Which layer is actually holding each Cloud M1 control for this prototype. A
#: promotion review reads this map, not the provider's marketing.
E2B_CONTROL_PROVENANCE: Mapping[str, str] = {
    "network_deny_by_default": E2BControlProvenance.ADAPTER_BORNE.value,
    "egress_policy_enforced": E2BControlProvenance.PROVIDER_DOCUMENTED.value,
    "exact_revision_materialization": E2BControlProvenance.ADAPTER_BORNE.value,
    "checkout_hooks_disabled": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "privileged_runtime_disabled": E2BControlProvenance.ADAPTER_BORNE.value,
    "host_mounts_disabled": E2BControlProvenance.ADAPTER_BORNE.value,
    "runtime_socket_hidden": E2BControlProvenance.ADAPTER_BORNE.value,
    "provider_metadata_blocked": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "host_secret_inheritance_disabled": E2BControlProvenance.ADAPTER_BORNE.value,
    "dedicated_workspace_per_run": E2BControlProvenance.ADAPTER_BORNE.value,
    "cross_run_reuse_disabled": E2BControlProvenance.ADAPTER_BORNE.value,
    "ttl_enforced": E2BControlProvenance.PROVIDER_DOCUMENTED.value,
    "hard_maximum_lifetime": E2BControlProvenance.ADAPTER_BORNE.value,
    "cancellation_kills_workload": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "teardown_guaranteed": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "artifact_allowlist_enforced": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "terminal_output_bounded": E2BControlProvenance.UNVERIFIED_LIVE.value,
    "preview_ports_private_by_default": E2BControlProvenance.ADAPTER_BORNE.value,
}


class E2BAdapterError(RuntimeError):
    """The adapter refused to build or accept something provider-shaped."""


class E2BSandboxTransport(Protocol):
    """The only seam between this adapter and E2B.

    Deliberately tiny and deliberately URL-free: the transport object is supplied by a
    future composition root through an approved channel, so no caller of the adapter can
    steer a launch at an endpoint of their choosing. In this child the only
    implementations are scripted test fakes.
    """

    def create(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Create one sandbox from an already-validated payload; return the provider body."""
        ...

    def state(self, sandbox_id: str) -> Mapping[str, Any]:
        """Observe one sandbox. Terminality must come from here, never from a call's return."""
        ...

    def kill(self, sandbox_id: str) -> bool:
        """Request termination. The bool is an acknowledgement, not an outcome."""
        ...

    def list_running(self) -> tuple[Mapping[str, Any], ...]:
        """Sandboxes the provider currently reports as running for this account."""
        ...


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise E2BAdapterError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _provider_id(value: object, field_name: str) -> str:
    """One identifier grammar for provider ids too: the canonical lease rule.

    The canonical shape excludes ``/``, so a URL can never be smuggled in through a
    field that is nominally an identifier.
    """
    try:
        return _safe_id(value if isinstance(value, str) else "", field_name)
    except ContractError as exc:
        raise E2BAdapterError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class E2BTerminationEvidence:
    """What a termination actually proved. There is no field for what it did not.

    The provider's kill call is an acknowledgement; the only evidence of an ending is
    the state observation that follows it. A physical process-tree kill has no
    producer in this space, so the dataclass carries no attestation field at all —
    a caller cannot set one, and a future author has to add a field and a control to
    fake one, which is the point.
    """

    sandbox_id: str
    reservation_terminated: bool
    terminal_state_observed: bool
    provider_terminal_state: str
    observed_at: datetime
    kill_acknowledged: bool
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sandbox_id", _provider_id(self.sandbox_id, "sandbox_id"))
        object.__setattr__(self, "provider_terminal_state",
                          _provider_id(self.provider_terminal_state, "provider_terminal_state"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        for name in ("reservation_terminated", "terminal_state_observed", "kill_acknowledged"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise E2BAdapterError(f"{name} must be boolean")
        # An acknowledged kill with no observed terminal state is exactly the shape
        # that would otherwise read as success.
        if self.reservation_terminated and not self.terminal_state_observed:
            raise E2BAdapterError(
                "reservation termination requires an observed terminal provider state"
            )
        if self.terminal_state_observed and self.provider_terminal_state not in E2B_TERMINAL_PROVIDER_STATES:
            raise E2BAdapterError("terminal observation requires a terminal provider state")

    @property
    def unresolved(self) -> bool:
        return not self.terminal_state_observed

    @property
    def physical_process_tree_kill_attested(self) -> bool:
        """Always False, by construction rather than by convention."""
        return E2B_TERMINATION_ATTESTES_PROCESS_TREE_KILL

    def safe_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "reservation_terminated": self.reservation_terminated,
            "terminal_state_observed": self.terminal_state_observed,
            "provider_terminal_state": self.provider_terminal_state,
            "observed_at": self.observed_at.isoformat(),
            "kill_acknowledged": self.kill_acknowledged,
            "unresolved": self.unresolved,
            # Recorded so no downstream projection can infer more than this saw.
            "process_tree_kill_attested": False,
            "physical_kill_claim_prohibited": True,
            "evidence_basis": "ADAPTER_OBSERVATION",
            "real_provider_calls": 0,
        }


def _assert_deny_shaped(payload: Mapping[str, Any]) -> None:
    """Decide once what an acceptable launch body is, and check every build against it.

    Each clause counters a documented E2B default rather than a hypothetical: egress and
    public URLs are open unless said otherwise, snapshots/pause have no provider TTL, and
    a provider that later changes a default must not be able to move this lane with it.
    """
    if set(payload) != set(E2B_PAYLOAD_KEYS):
        raise E2BAdapterError("launch payload shape is closed; it changed without a decision")
    accepted = set(payload).intersection(E2B_NEVER_ACCEPTED_KEYS)
    if accepted:
        raise E2BAdapterError(f"launch payload carries never-accepted keys: {sorted(accepted)}")
    if payload["allow_internet_access"] is not False:
        raise E2BAdapterError("launch must deny outbound internet access")
    if payload["network"] != {"deny_out": [E2B_DENY_ALL_ENCODING]}:
        raise E2BAdapterError("launch must carry the explicit all-traffic deny rule")
    if payload["allow_public_traffic"] is not False:
        raise E2BAdapterError("launch must restrict public traffic explicitly")
    if payload["public_ports"]:
        raise E2BAdapterError("launch may not expose ports")
    if payload["auto_pause"] or payload["auto_resume"]:
        raise E2BAdapterError("pause and auto-resume are forbidden; a paused sandbox has no TTL")
    if payload["timeout_action"] != E2B_TIMEOUT_DEFAULT_ACTION:
        raise E2BAdapterError("launch timeout must be wired to kill")
    if payload["snapshot"] is not None or payload["fork_source"] is not None:
        raise E2BAdapterError("snapshot and fork reuse are forbidden")
    if payload["volume_mounts"]:
        raise E2BAdapterError("volume mounts outlive the sandbox and are forbidden")
    if payload["privileged"] or payload["host_mounts"] or payload["runtime_socket"]:
        raise E2BAdapterError("privileged, host-mount and runtime-socket shapes are forbidden")
    if payload["envs"] or payload["secrets"]:
        raise E2BAdapterError("no credential may be readable by sandbox code")
    if payload["materialization"]["live_clone"] is not False:
        raise E2BAdapterError("live cloning needs egress and is not in this child")
    if not SANDBOX_LEASE_MIN_TTL_SECONDS <= payload["timeout"] <= SANDBOX_LEASE_MAX_TTL_SECONDS:
        raise E2BAdapterError("launch timeout must sit inside the canonical TTL contract")
    if tuple(sorted(payload["metadata"])) != E2B_METADATA_KEYS:
        raise E2BAdapterError("launch metadata keys are closed")


def build_e2b_launch_payload(
    request: SandboxLeaseRequest,
    *,
    template: str,
    content_ref: str,
    now: datetime,
    policy: SandboxSecurityPolicy | None = None,
) -> dict[str, Any]:
    """Build the provider request body for one Cloud M1 launch.

    Nothing is defaulted open: egress, public traffic, persistence and privilege are each
    written down explicitly, because E2B's own defaults for egress and public URLs are the
    opposite of what this lane needs.

    ``now`` is supplied rather than read, so a launch payload is reproducible from its
    inputs and this module never touches a wall clock.

    ``content_ref`` is a bounded reference to already-materialized exact-revision content.
    Live cloning is not in this child, and an adapter that quietly fetched over the network
    would break the deny-all claim it is making.
    """
    # One Cloud M1 entry point, not a partial re-implementation of it: the canonical
    # validator already refuses a non-CLOUD mode, a non-off network policy, an
    # out-of-ceiling TTL and a mutable revision, and it takes the policy an operator
    # tightens for a probe. Restating those rules here would let provider and
    # repository policy drift apart.
    validate_lease_request_against_cloud_m1_policy(request, policy=policy)

    observed = _aware(now, "now")
    payload = {
        "template": _provider_id(template, "template"),
        # The canonical validator above already refused anything outside policy; this is
        # the value leaving the process, checked once more where it is actually written.
        "timeout": request.ttl_seconds,
        # E2B's kill-on-timeout default is documented; the request says it anyway, so a
        # future provider default change cannot silently become this lane's policy.
        "timeout_action": E2B_TIMEOUT_DEFAULT_ACTION,
        "auto_pause": False,
        "auto_resume": False,
        "allow_internet_access": False,
        "network": {"deny_out": [E2B_DENY_ALL_ENCODING]},
        "allow_public_traffic": False,
        "public_ports": (),
        "privileged": False,
        "host_mounts": (),
        "runtime_socket": False,
        "volume_mounts": (),
        "snapshot": None,
        "fork_source": None,
        "envs": {},
        "secrets": (),
        "metadata": {
            "run_id": request.run_id,
            "repository_ref": request.repository_ref,
            "requested_revision": request.requested_revision,
        },
        "materialization": {
            "mode": "PRE_SUPPLIED_EXACT_REVISION_CONTENT",
            "content_ref": _provider_id(content_ref, "content_ref"),
            "live_clone": False,
        },
        "requested_at": observed.isoformat(),
        "control_provenance": dict(E2B_CONTROL_PROVENANCE),
    }
    _assert_deny_shaped(payload)
    return payload


class E2BCloudM1Adapter:
    """Maps a canonical Cloud M1 lease onto one E2B sandbox, through an injected transport.

    Implements ``SandboxLeasePort``, ``SandboxWorkloadCancellationPort`` and
    ``SandboxLeaseReclamationPort`` structurally — no new lease, state, identifier or
    revision contract is introduced here, and the canonical gate is consulted for every
    incoming request rather than a local copy of its rules.

    The provider is never trusted with an outcome it was only asked to perform:
    termination, expiry and cancellation all require a state observation, and an
    unobservable outcome raises so that the caller's sweep records the lease as needing
    reconciliation instead of reclaimed.
    """

    provider_candidate = E2B_PROVIDER_CANDIDATE
    isolation_primitive = E2B_ISOLATION_PRIMITIVE
    live_execution_ready = E2B_LIVE_EXECUTION_READY

    def __init__(
        self,
        transport: E2BSandboxTransport,
        *,
        template: str,
        clock: Callable[[], datetime],
        policy: SandboxSecurityPolicy | None = None,
    ) -> None:
        if transport is None:
            raise E2BAdapterError("an E2B transport must be supplied")
        if not callable(clock):
            raise E2BAdapterError("a clock must be supplied; this adapter never reads one")
        self._transport = transport
        self._template = _provider_id(template, "template")
        self._policy = policy
        self._clock = clock
        self._leases: dict[str, SandboxLease] = {}
        self._active_by_run: dict[str, str] = {}
        self._evidence: dict[str, E2BTerminationEvidence] = {}

    # -- canonical ports ----------------------------------------------------

    def allocate(self, request: SandboxLeaseRequest, *, content_ref: str) -> SandboxLease:
        """Validate, build an explicit-deny payload, and hold exactly one lease per run."""
        active_id = self._active_by_run.get(request.run_id)
        if active_id is not None:
            # Same canonical semantics as the in-repo providers: reading is what notices a
            # lapse, so a lapsed reservation cannot lock a run out of its next lease.
            if self.get(active_id).state is SandboxLeaseState.RESERVED:
                raise SandboxLeaseError(f"run already has an active lease: {request.run_id}")

        payload = build_e2b_launch_payload(
            request,
            template=self._template,
            content_ref=content_ref,
            now=self._now(),
            policy=self._policy,
        )
        response = self._transport_call("create", payload)
        sandbox_id = _provider_id(response.get("sandbox_id"), "sandbox_id")
        if sandbox_id in self._leases:
            # Two runs cannot share one reservation, and a reused id would silently
            # rewrite the existing record: the earlier run's lease would vanish from the
            # ledger while its sandbox kept running, and both run slots would point at one
            # id. Killing the sandbox instead is not safer — it would destroy whichever
            # lease genuinely holds that id. The launch is refused and the existing
            # records stay intact for an operator to reconcile.
            raise SandboxLeaseError(
                f"provider reused sandbox id {sandbox_id}; launch refused, "
                "existing lease records left intact for reconciliation"
            )
        now = self._now()
        lease = SandboxLease(
            lease_id=sandbox_id,
            run_id=request.run_id,
            execution_mode=request.execution_mode,
            resource_class=request.resource_class,
            network_policy=request.network_policy,
            writable_workspace=request.writable_workspace,
            created_at=now,
            expires_at=now + timedelta(seconds=payload["timeout"]),
        )
        self._leases[lease.lease_id] = lease
        self._active_by_run[request.run_id] = lease.lease_id
        return lease

    def get(self, lease_id: str) -> SandboxLease:
        """Canonical read semantics: a lapsed reservation is observed, not silently extended."""
        lease = self._recorded(lease_id)
        if lease.state is SandboxLeaseState.RESERVED and self._now() >= lease.expires_at:
            lease = lease.with_state(SandboxLeaseState.EXPIRED)
            self._leases[lease_id] = lease
            self._active_by_run.pop(lease.run_id, None)
        return lease

    def renew(self, lease_id: str, *, run_id: str, ttl_seconds: int) -> SandboxLease:
        """Refused, on purpose, until the seam can carry a provider-side timeout change.

        ``E2BSandboxTransport`` has no timeout-update operation, so writing a later
        ``expires_at`` would only move the ledger: the provider would still kill the sandbox
        at the lifetime it agreed to at launch, and the reservation would read as live past
        that point. An extension nobody honoured is the same class of overclaim as a kill
        acknowledgement presented as termination, so renewal is refused rather than faked.
        Enabling it belongs with a seam change that sends the update and observes the result.
        """
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        raise SandboxLeaseError(
            "E2B lease renewal is unavailable: the transport seam has no timeout update, "
            "so extending expires_at would claim a lifetime the provider never accepted"
        )

    def release(self, lease_id: str, *, run_id: str) -> SandboxLease:
        return self._terminate(
            self._active_for_run(lease_id, run_id), run_id, final=SandboxLeaseState.RELEASED
        )

    def cancel(self, lease_id: str, *, run_id: str) -> SandboxLease:
        """Map cancellation onto a provider kill intent.

        ``RESERVED -> RELEASED``, the same terminal state #2790 gave the in-repo providers:
        these verbs differ in reason, not in what "ended" means, and this adapter must not
        invent a third ending for the same lease. ``expire`` is the only path that records
        ``EXPIRED``.

        The lease ends because the provider was asked and the state was observed. That is
        still not proof that a guest process tree died — see ``termination_evidence``.
        """
        return self._terminate(
            self._active_for_run(lease_id, run_id), run_id, final=SandboxLeaseState.RELEASED
        )

    def active_leases(self) -> tuple[SandboxLease, ...]:
        """Recorded reservations only; observing a lapse is not reclaiming one.

        Read from the ledger, so it cannot raise a provider error mid-listing; a sweep that
        needs live provider truth learns it per lease, through the translated seam.
        """
        return tuple(
            lease
            for lease in self._leases.values()
            if lease.state is SandboxLeaseState.RESERVED
        )

    def expire(self, lease_id: str, *, run_id: str, now: datetime) -> SandboxLease:
        """Reclaim a lapsed reservation: RESERVED -> EXPIRED, with the observation required.

        Deliberately reads the recorded state rather than ``get``: reading first would apply
        the lapse rule, and the lease would then refuse its own reclamation as inactive —
        the exact defect #2803 removed for the in-repo providers.

        A provider that acknowledges the kill but will not confirm the sandbox is gone
        leaves this lease unresolved: the caller's sweep records it as needing
        reconciliation, and no ``fully_reclaimed`` claim can be built from it.
        """
        lease = self._recorded(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        try:
            observed = _aware(now, "now")
        except E2BAdapterError as exc:
            raise SandboxLeaseError(f"lease cannot be reclaimed: {exc}") from exc
        if observed < lease.expires_at:
            raise SandboxLeaseError("lease has not reached its TTL")
        return self._terminate(lease, run_id, final=SandboxLeaseState.EXPIRED)

    # -- adapter-specific evidence ------------------------------------------

    def termination_evidence(self, lease_id: str) -> E2BTerminationEvidence:
        try:
            return self._evidence[_provider_id(lease_id, "lease_id")]
        except KeyError as exc:
            raise E2BAdapterError("no termination was observed for that lease") from exc

    def launch_payload(self, request: SandboxLeaseRequest, *, content_ref: str) -> dict[str, Any]:
        """The request shape on its own, without a transport call. This is what the
        prototype exists to pin down."""
        return build_e2b_launch_payload(
            request,
            template=self._template,
            content_ref=content_ref,
            now=self._now(),
            policy=self._policy,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "provider_candidate": self.provider_candidate.value,
            "isolation_primitive": self.isolation_primitive.value,
            "formal_provider_selected": REAL_E2B_PROVIDER_SELECTED,
            "live_execution_ready": self.live_execution_ready,
            "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
            "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
            "provider_sdk_imports": E2B_ADAPTER_SDK_IMPORTS,
            "credential_material_read": 0,
            "active_lease_count": len(self.active_leases()),
            "unresolved_termination_count": sum(
                1 for evidence in self._evidence.values() if evidence.unresolved
            ),
            "control_provenance": dict(E2B_CONTROL_PROVENANCE),
            "production_claim": False,
        }

    # -- internals -----------------------------------------------------------

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock")

    def _recorded(self, lease_id: str) -> SandboxLease:
        try:
            return self._leases[_provider_id(lease_id, "lease_id")]
        except (KeyError, E2BAdapterError) as exc:
            raise SandboxLeaseError(f"unknown lease: {lease_id}") from exc

    def _terminate(self, lease: SandboxLease, run_id: str, *, final: SandboxLeaseState) -> SandboxLease:
        """Ask the provider to end one reservation, and only then record it as ended."""
        evidence = self._kill_and_observe(lease.lease_id)
        if evidence.unresolved:
            raise SandboxLeaseError(
                f"provider termination is unresolved for {lease.lease_id}: reconciliation required"
            )
        ended = lease.with_state(final)
        self._leases[lease.lease_id] = ended
        self._active_by_run.pop(run_id, None)
        return ended

    def _active_for_run(self, lease_id: str, run_id: str) -> SandboxLease:
        """The canonical active-lease precondition, read through the canonical rule."""
        lease = self.get(lease_id)
        if lease.run_id != run_id:
            raise SandboxLeaseError("lease belongs to a different run")
        if lease.state is not SandboxLeaseState.RESERVED:
            raise SandboxLeaseError(f"lease is not active: {lease.state.value}")
        return lease

    def _transport_call(self, operation: str, *args, **kwargs):
        """Run one seam call, translating any provider-side failure.

        A transport error must reach callers as a rejected lease operation. Left raw it
        would break the port's uniform ``SandboxLeaseError`` shape, and mid-sweep it would
        abort the pass with no report at all — hiding exactly the leases that were already
        reclaimed, which is the failure mode #2803 closed for refusals.
        """
        try:
            return getattr(self._transport, operation)(*args, **kwargs)
        except (SandboxLeaseError, SandboxUnavailableError):
            raise
        except Exception as exc:
            raise SandboxLeaseError(
                f"provider {operation} failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _kill_and_observe(self, lease_id: str) -> E2BTerminationEvidence:
        """Ask, then look. A returned acknowledgement is never an outcome."""
        acknowledged = bool(self._transport_call("kill", lease_id))
        state = self._transport_call("state", lease_id)
        raw_state = state.get("state") if isinstance(state, Mapping) else None
        running = state.get("running") if isinstance(state, Mapping) else None
        observed = raw_state if isinstance(raw_state, str) else ""
        normalized = observed.strip().lower()
        if normalized == "paused":
            # E2B documents no TTL for a paused sandbox, so a pause is a persistence
            # channel, not a stopped one. It must never be read as reclaimed.
            raise SandboxLeaseError(
                f"provider reports a paused sandbox for {lease_id}; Cloud M1 forbids pause/resume"
            )
        terminal_observed = normalized in E2B_TERMINAL_PROVIDER_STATES and running is False
        evidence = E2BTerminationEvidence(
            sandbox_id=lease_id,
            reservation_terminated=terminal_observed,
            terminal_state_observed=terminal_observed,
            provider_terminal_state=normalized or "unobserved",
            observed_at=self._now(),
            kill_acknowledged=acknowledged,
        )
        self._evidence[lease_id] = evidence
        return evidence


E2B_ADAPTER_REUSES_CANONICAL_PORTS = True
E2B_ADAPTER_DEFINES_NO_SECOND_LEASE_CONTRACT = True
E2B_ADAPTER_DEFINES_NO_SECOND_REVISION_CONTRACT = True
E2B_ADAPTER_DEFINES_NO_SECOND_IDENTIFIER_GRAMMAR = True
