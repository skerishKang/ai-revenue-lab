from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    ClawRunStatus,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseRequest,
)
from .runs import ClawRun, RunStateError
from .sandbox import SandboxLeasePort, SandboxUnavailableError
from .sandbox_conformance import SandboxSecurityPolicy
from .sandbox_conformance_harness import validate_lease_request_against_cloud_m1_policy


@dataclass(frozen=True, slots=True)
class WorkspacePolicy:
    resource_class: ResourceClass = ResourceClass.STANDARD
    ttl_seconds: int = 900
    network_policy: NetworkPolicy = NetworkPolicy.OFF
    writable_workspace: bool = True


class CloudWorkspacePreparer:
    """Prepare B54-owned cloud workspace resources without starting an agent.

    A successful lease leaves the product run in PREPARING. Only a later trusted
    P01 orchestration adapter may establish actual agent execution and advance
    the product projection to RUNNING.

    ``WorkspacePolicy`` is server-owned sizing; the Cloud M1 security policy is the
    ceiling it is measured against. Sizing that violates the ceiling — a relaxed
    network default, a TTL above the policy maximum — is refused before the request
    reaches a provider, because the provider port is the last place such a request
    could still be undone.
    """

    def __init__(
        self,
        sandbox: SandboxLeasePort,
        *,
        policy: WorkspacePolicy | None = None,
        security_policy: SandboxSecurityPolicy | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._policy = policy or WorkspacePolicy()
        self._security_policy = security_policy or SandboxSecurityPolicy()

    def prepare(self, run: ClawRun) -> SandboxLease:
        if run.intent.execution_mode is not ExecutionMode.CLOUD:
            raise RunStateError("cloud workspace preparation requires execution_mode=cloud")
        if run.status is ClawRunStatus.QUEUED:
            run.transition(ClawRunStatus.PREPARING, summary="클라우드 작업공간 준비")
        elif run.status is not ClawRunStatus.PREPARING:
            raise RunStateError(
                f"cloud workspace cannot be prepared from status={run.status.value}"
            )

        request = SandboxLeaseRequest(
            run_id=run.run_id,
            execution_mode=run.intent.execution_mode,
            repository_ref=run.intent.repository_ref,
            requested_revision=run.intent.requested_revision,
            resource_class=self._policy.resource_class,
            ttl_seconds=self._policy.ttl_seconds,
            network_policy=self._policy.network_policy,
            writable_workspace=self._policy.writable_workspace,
        )
        # Before allocate(): a request the Cloud M1 policy refuses must never reach a
        # provider. The transition above intentionally keeps its existing position —
        # where a run is left after a refused request is shared lifecycle behaviour
        # this slice does not redefine (#2775 already refused at this same point).
        validate_lease_request_against_cloud_m1_policy(request, policy=self._security_policy)

        try:
            return self._sandbox.allocate(request)
        except SandboxUnavailableError:
            run.transition(
                ClawRunStatus.FAILED,
                summary="클라우드 실행 환경이 구성되지 않아 실행하지 않았습니다.",
            )
            raise
