from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .contracts import ContractError, NetworkPolicy
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _repository(value: str) -> str:
    if not isinstance(value, str) or not _REPOSITORY_RE.fullmatch(value.strip()):
        raise ContractError("repository_ref must use bounded owner/repo syntax")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError("repository_ref must not contain credential material")
    return value


def _revision(value: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value.strip()):
        raise ContractError("input_revision must be an exact 40-hex commit SHA")
    return value.strip().lower()


class CloudM1Stage(str, Enum):
    ADMISSION = "admission"
    REPOSITORY_MATERIALIZATION = "repository_materialization"
    SANDBOX_READY = "sandbox_ready"
    AGENT_COMPUTER_READY = "agent_computer_ready"
    P01_EXECUTION = "p01_execution"
    VERIFICATION = "verification"
    ARTIFACT_COLLECTION = "artifact_collection"
    VERIFIED_DIFF = "verified_diff"
    OPTIONAL_DRAFT_PR = "optional_draft_pr"
    TEARDOWN = "teardown"


FIXED_CLOUD_M1_STAGE_ORDER = (
    CloudM1Stage.ADMISSION,
    CloudM1Stage.REPOSITORY_MATERIALIZATION,
    CloudM1Stage.SANDBOX_READY,
    CloudM1Stage.AGENT_COMPUTER_READY,
    CloudM1Stage.P01_EXECUTION,
    CloudM1Stage.VERIFICATION,
    CloudM1Stage.ARTIFACT_COLLECTION,
    CloudM1Stage.VERIFIED_DIFF,
    CloudM1Stage.OPTIONAL_DRAFT_PR,
    CloudM1Stage.TEARDOWN,
)


@dataclass(frozen=True, slots=True)
class CloudM1ExecutionPlan:
    plan_id: str
    run_id: str
    workspace_id: str
    repository_ref: str
    input_revision: str
    verification_command_ids: tuple[str, ...]
    artifact_policy_ref: str
    browser_required: bool = False
    preview_ports: tuple[int, ...] = ()
    draft_pr_requested: bool = False
    network_policy: NetworkPolicy = NetworkPolicy.OFF
    stages: tuple[CloudM1Stage, ...] = FIXED_CLOUD_M1_STAGE_ORDER

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "run_id", "workspace_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        object.__setattr__(self, "repository_ref", _repository(self.repository_ref))
        object.__setattr__(self, "input_revision", _revision(self.input_revision))
        if not isinstance(self.verification_command_ids, tuple) or not 1 <= len(self.verification_command_ids) <= 20:
            raise ContractError("verification_command_ids must contain between 1 and 20 registered command IDs")
        commands = tuple(_id(value, "verification_command_id") for value in self.verification_command_ids)
        if len(commands) != len(set(commands)):
            raise ContractError("verification_command_ids must be unique")
        object.__setattr__(self, "verification_command_ids", commands)
        object.__setattr__(self, "artifact_policy_ref", _id(self.artifact_policy_ref, "artifact_policy_ref"))
        if not isinstance(self.browser_required, bool):
            raise ContractError("browser_required must be boolean")
        if not isinstance(self.preview_ports, tuple) or len(self.preview_ports) > 8:
            raise ContractError("preview_ports must be a tuple with at most 8 entries")
        ports: list[int] = []
        for port in self.preview_ports:
            if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
                raise ContractError("preview ports must be between 1024 and 65535")
            ports.append(port)
        if len(ports) != len(set(ports)):
            raise ContractError("preview_ports must be unique")
        object.__setattr__(self, "preview_ports", tuple(ports))
        if not isinstance(self.draft_pr_requested, bool):
            raise ContractError("draft_pr_requested must be boolean")
        if self.network_policy is not NetworkPolicy.OFF:
            raise ContractError("Cloud M1 execution plan requires network-off policy")
        if self.stages != FIXED_CLOUD_M1_STAGE_ORDER:
            raise ContractError("Cloud M1 stage order is server-owned and cannot be changed")

    @property
    def fingerprint(self) -> str:
        payload = {
            "contract_version": "claw-cloud-m1-execution-plan.v1",
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "repository_ref": self.repository_ref,
            "input_revision": self.input_revision,
            "verification_command_ids": list(self.verification_command_ids),
            "artifact_policy_ref": self.artifact_policy_ref,
            "browser_required": self.browser_required,
            "preview_ports": list(self.preview_ports),
            "draft_pr_requested": self.draft_pr_requested,
            "network_policy": self.network_policy.value,
            "stages": [stage.value for stage in self.stages],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-cloud-m1-execution-plan.v1",
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "repository_ref": self.repository_ref,
            "input_revision": self.input_revision,
            "verification_command_ids": list(self.verification_command_ids),
            "artifact_policy_ref": self.artifact_policy_ref,
            "browser_required": self.browser_required,
            "preview_ports": list(self.preview_ports),
            "draft_pr_requested": self.draft_pr_requested,
            "network_policy": self.network_policy.value,
            "stages": [stage.value for stage in self.stages],
            "plan_fingerprint": self.fingerprint,
            "teardown_mandatory": self.stages[-1] is CloudM1Stage.TEARDOWN,
            "credentials_in_plan": False,
            "provider_route_in_plan": False,
            "raw_task_prompt_in_plan": False,
            "tool_args_in_plan": False,
            "hidden_reasoning_in_plan": False,
            "arbitrary_shell_in_plan": False,
            "real_execution": False,
        }


REAL_CLOUD_M1_PLAN_EXECUTION_CONFIGURED = False
CLIENT_CONTROLLED_STAGE_ORDER_SUPPORTED = False
CLIENT_CONTROLLED_TEARDOWN_OMISSION_SUPPORTED = False
