from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Protocol

from .connector_trust import ConnectorWriteIntent
from .contracts import ContractError
from .security import redact_secrets

MAX_LOG_LINES = 200
MAX_LOG_LINE_CHARS = 2_000
MAX_PATTERN_COUNT = 128
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SAFE_PATH_PATTERN_RE = re.compile(r"^[A-Za-z0-9_./*?{}!+\-]{1,512}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    normalized = value.strip()
    if normalized == "*" or redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must be exact, bounded and secret-free")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha256(value: str, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not re.fullmatch(r"[a-f0-9]{64}", normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _unique_refs(values: tuple[str, ...], field_name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ContractError(f"{field_name} must be a tuple")
    normalized = tuple(_ref(item, field_name) for item in values)
    if not allow_empty and not normalized:
        raise ContractError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field_name} values must be unique")
    return normalized


def _path_pattern(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("build path pattern must be text")
    normalized = value.strip().replace("\\", "/")
    if not _SAFE_PATH_PATTERN_RE.fullmatch(normalized):
        raise ContractError("build path pattern contains unsupported characters")
    parts = [part for part in normalized.split("/") if part]
    if any(part == ".." for part in parts):
        raise ContractError("build path pattern must not traverse outside repository root")
    return normalized


def _path_patterns(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or len(values) > MAX_PATTERN_COUNT:
        raise ContractError("build path patterns must be a bounded tuple")
    normalized = tuple(_path_pattern(item) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ContractError("build path patterns must be unique")
    return normalized


class CloudflareCredentialSubject(str, Enum):
    USER = "user"
    ACCOUNT = "account"


class CloudflareEnvironment(str, Enum):
    PREVIEW = "preview"
    PRODUCTION = "production"


class CloudflareResourceKind(str, Enum):
    WORKER = "worker"
    PAGES_PROJECT = "pages_project"
    ZONE = "zone"


class CloudflareMutationAction(str, Enum):
    PREVIEW_DEPLOY = "preview_deploy"
    PRODUCTION_DEPLOY = "production_deploy"
    WORKER_ROLLBACK = "worker_rollback"
    PAGES_ROLLBACK = "pages_rollback"
    BUILD_CONFIG_UPDATE = "build_config_update"
    DNS_UPDATE = "dns_update"


@dataclass(frozen=True, slots=True)
class CloudflareCredentialProjection:
    credential_ref: str
    subject: CloudflareCredentialSubject
    permission_refs: tuple[str, ...]
    account_refs: tuple[str, ...]
    zone_refs: tuple[str, ...] = ()
    expires_at: datetime | None = None
    broad_all_accounts: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "credential_ref", _ref(self.credential_ref, "credential_ref"))
        if not isinstance(self.subject, CloudflareCredentialSubject):
            try:
                object.__setattr__(self, "subject", CloudflareCredentialSubject(self.subject))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Cloudflare credential subject") from exc
        permissions = _unique_refs(self.permission_refs, "permission_ref", allow_empty=False)
        accounts = _unique_refs(self.account_refs, "account_ref", allow_empty=False)
        zones = _unique_refs(self.zone_refs, "zone_ref")
        object.__setattr__(self, "permission_refs", permissions)
        object.__setattr__(self, "account_refs", accounts)
        object.__setattr__(self, "zone_refs", zones)
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if not isinstance(self.broad_all_accounts, bool) or self.broad_all_accounts:
            raise ContractError("broad all-account Cloudflare credentials are prohibited")
        if "workers_builds_configuration.edit" in permissions and self.subject is not CloudflareCredentialSubject.USER:
            raise ContractError("Workers Builds configuration requires a user-scoped credential")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "credential_ref": self.credential_ref,
            "subject": self.subject.value,
            "permission_refs": list(self.permission_refs),
            "account_refs": list(self.account_refs),
            "zone_refs": list(self.zone_refs),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z") if self.expires_at else None,
            "broad_all_accounts": False,
            "raw_token": False,
            "global_api_key": False,
        }


@dataclass(frozen=True, slots=True)
class CloudflareResourceBinding:
    binding_ref: str
    workspace_ref: str
    account_ref: str
    worker_refs: tuple[str, ...] = ()
    pages_project_refs: tuple[str, ...] = ()
    zone_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("binding_ref", "workspace_ref", "account_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        workers = _unique_refs(self.worker_refs, "worker_ref")
        pages = _unique_refs(self.pages_project_refs, "pages_project_ref")
        zones = _unique_refs(self.zone_refs, "zone_ref")
        if not (workers or pages or zones):
            raise ContractError("Cloudflare binding requires at least one exact resource")
        object.__setattr__(self, "worker_refs", workers)
        object.__setattr__(self, "pages_project_refs", pages)
        object.__setattr__(self, "zone_refs", zones)

    def require_resource(self, kind: CloudflareResourceKind, resource_ref: str) -> None:
        resource_ref = _ref(resource_ref, "resource_ref")
        allowed = {
            CloudflareResourceKind.WORKER: self.worker_refs,
            CloudflareResourceKind.PAGES_PROJECT: self.pages_project_refs,
            CloudflareResourceKind.ZONE: self.zone_refs,
        }[kind]
        if resource_ref not in allowed:
            raise ContractError("Cloudflare resource is outside the trusted binding")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "workspace_ref": self.workspace_ref,
            "account_ref": self.account_ref,
            "worker_refs": list(self.worker_refs),
            "pages_project_refs": list(self.pages_project_refs),
            "zone_refs": list(self.zone_refs),
            "all_account_resources": False,
        }


@dataclass(frozen=True, slots=True)
class CloudflareWorkerVersion:
    worker_ref: str
    version_ref: str
    created_at: datetime
    source_revision_ref: str | None
    compatibility_date: str | None
    bindings_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        object.__setattr__(self, "version_ref", _ref(self.version_ref, "version_ref"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if self.source_revision_ref is not None:
            object.__setattr__(self, "source_revision_ref", _ref(self.source_revision_ref, "source_revision_ref"))
        if self.compatibility_date is not None and not _DATE_RE.fullmatch(self.compatibility_date):
            raise ContractError("compatibility_date must use YYYY-MM-DD")
        object.__setattr__(self, "bindings_fingerprint", _sha256(self.bindings_fingerprint, "bindings_fingerprint"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "worker_ref": self.worker_ref,
            "version_ref": self.version_ref,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "source_revision_ref": self.source_revision_ref,
            "compatibility_date": self.compatibility_date,
            "bindings_fingerprint": self.bindings_fingerprint,
            "binding_values_present": False,
            "secret_values_present": False,
        }


@dataclass(frozen=True, slots=True)
class WorkerTrafficVersion:
    version_ref: str
    percentage: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "version_ref", _ref(self.version_ref, "version_ref"))
        if isinstance(self.percentage, bool) or not isinstance(self.percentage, (int, float)) or not 0 < float(self.percentage) <= 100:
            raise ContractError("Worker version traffic percentage must be >0 and <=100")
        object.__setattr__(self, "percentage", float(self.percentage))


@dataclass(frozen=True, slots=True)
class CloudflareWorkerDeployment:
    worker_ref: str
    deployment_ref: str
    created_at: datetime
    traffic: tuple[WorkerTrafficVersion, ...]
    active: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        object.__setattr__(self, "deployment_ref", _ref(self.deployment_ref, "deployment_ref"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if not isinstance(self.traffic, tuple) or not self.traffic or len(self.traffic) > 2:
            raise ContractError("Worker deployment must reference one or two versions")
        if not all(isinstance(item, WorkerTrafficVersion) for item in self.traffic):
            raise ContractError("traffic must contain WorkerTrafficVersion values")
        if len({item.version_ref for item in self.traffic}) != len(self.traffic):
            raise ContractError("Worker deployment version refs must be unique")
        if abs(sum(item.percentage for item in self.traffic) - 100.0) > 0.001:
            raise ContractError("Worker deployment traffic must total 100 percent")
        if not isinstance(self.active, bool):
            raise ContractError("active must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "worker_ref": self.worker_ref,
            "deployment_ref": self.deployment_ref,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "traffic": [{"version_ref": item.version_ref, "percentage": item.percentage} for item in self.traffic],
            "active": self.active,
        }


@dataclass(frozen=True, slots=True)
class CloudflareWorkerReleaseState:
    worker_ref: str
    current_deployment: CloudflareWorkerDeployment
    versions: tuple[CloudflareWorkerVersion, ...]
    rollback_target_version_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        if not isinstance(self.current_deployment, CloudflareWorkerDeployment) or not self.current_deployment.active:
            raise ContractError("current Worker deployment must be active")
        if self.current_deployment.worker_ref != self.worker_ref:
            raise ContractError("Worker release state resource mismatch")
        if not isinstance(self.versions, tuple) or not self.versions:
            raise ContractError("Worker release state requires visible versions")
        refs = {version.version_ref for version in self.versions if version.worker_ref == self.worker_ref}
        if len(refs) != len(self.versions):
            raise ContractError("Worker versions must be unique and match resource")
        for traffic in self.current_deployment.traffic:
            if traffic.version_ref not in refs:
                raise ContractError("active Worker deployment references an unknown visible version")
        if self.rollback_target_version_ref is not None:
            target = _ref(self.rollback_target_version_ref, "rollback_target_version_ref")
            if target not in refs or target in {item.version_ref for item in self.current_deployment.traffic}:
                raise ContractError("Worker rollback target must be a visible non-current version")
            object.__setattr__(self, "rollback_target_version_ref", target)


class PagesDeploymentEnvironment(str, Enum):
    PREVIEW = "preview"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class CloudflarePagesDeployment:
    project_ref: str
    deployment_ref: str
    environment: PagesDeploymentEnvironment
    successful: bool
    production_active: bool
    created_at: datetime
    source_revision_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_ref", _ref(self.project_ref, "project_ref"))
        object.__setattr__(self, "deployment_ref", _ref(self.deployment_ref, "deployment_ref"))
        if not isinstance(self.environment, PagesDeploymentEnvironment):
            try:
                object.__setattr__(self, "environment", PagesDeploymentEnvironment(self.environment))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Pages deployment environment") from exc
        if not isinstance(self.successful, bool) or not isinstance(self.production_active, bool):
            raise ContractError("Pages deployment state flags must be boolean")
        if self.production_active and (self.environment is not PagesDeploymentEnvironment.PRODUCTION or not self.successful):
            raise ContractError("active Pages production deployment must be successful production")
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        if self.source_revision_ref is not None:
            object.__setattr__(self, "source_revision_ref", _ref(self.source_revision_ref, "source_revision_ref"))

    @property
    def rollback_eligible(self) -> bool:
        return self.environment is PagesDeploymentEnvironment.PRODUCTION and self.successful and not self.production_active


@dataclass(frozen=True, slots=True)
class CloudflarePagesReleaseState:
    project_ref: str
    current_production: CloudflarePagesDeployment
    recent_deployments: tuple[CloudflarePagesDeployment, ...]
    rollback_target_deployment_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_ref", _ref(self.project_ref, "project_ref"))
        if not isinstance(self.current_production, CloudflarePagesDeployment) or not self.current_production.production_active:
            raise ContractError("Pages release state requires active production deployment")
        if self.current_production.project_ref != self.project_ref:
            raise ContractError("Pages release state project mismatch")
        if not isinstance(self.recent_deployments, tuple):
            raise ContractError("recent_deployments must be tuple")
        refs: dict[str, CloudflarePagesDeployment] = {}
        for deployment in self.recent_deployments:
            if not isinstance(deployment, CloudflarePagesDeployment) or deployment.project_ref != self.project_ref:
                raise ContractError("Pages recent deployment resource mismatch")
            if deployment.deployment_ref in refs:
                raise ContractError("Pages deployment refs must be unique")
            refs[deployment.deployment_ref] = deployment
        if self.rollback_target_deployment_ref is not None:
            target_ref = _ref(self.rollback_target_deployment_ref, "rollback_target_deployment_ref")
            target = refs.get(target_ref)
            if target is None or not target.rollback_eligible:
                raise ContractError("Pages rollback target must be a successful inactive production deployment")
            object.__setattr__(self, "rollback_target_deployment_ref", target_ref)


@dataclass(frozen=True, slots=True)
class CloudflareBuildTriggerProjection:
    worker_ref: str
    trigger_ref: str
    environment: CloudflareEnvironment
    root_directory: str
    branch_includes: tuple[str, ...]
    branch_excludes: tuple[str, ...]
    path_includes: tuple[str, ...]
    path_excludes: tuple[str, ...]
    build_command_fingerprint: str
    deploy_command_fingerprint: str
    environment_variable_names: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        object.__setattr__(self, "trigger_ref", _ref(self.trigger_ref, "trigger_ref"))
        if not isinstance(self.environment, CloudflareEnvironment):
            try:
                object.__setattr__(self, "environment", CloudflareEnvironment(self.environment))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Cloudflare build environment") from exc
        root = self.root_directory.strip().replace("\\", "/") if isinstance(self.root_directory, str) else ""
        if root in {"", "."}:
            root = "."
        elif not _SAFE_PATH_PATTERN_RE.fullmatch(root) or any(part == ".." for part in root.split("/")):
            raise ContractError("root_directory must be repository-relative")
        object.__setattr__(self, "root_directory", root)
        object.__setattr__(self, "branch_includes", _path_patterns(self.branch_includes))
        object.__setattr__(self, "branch_excludes", _path_patterns(self.branch_excludes))
        object.__setattr__(self, "path_includes", _path_patterns(self.path_includes))
        object.__setattr__(self, "path_excludes", _path_patterns(self.path_excludes))
        object.__setattr__(self, "build_command_fingerprint", _sha256(self.build_command_fingerprint, "build_command_fingerprint"))
        object.__setattr__(self, "deploy_command_fingerprint", _sha256(self.deploy_command_fingerprint, "deploy_command_fingerprint"))
        object.__setattr__(self, "environment_variable_names", _unique_refs(self.environment_variable_names, "environment_variable_name"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "worker_ref": self.worker_ref,
            "trigger_ref": self.trigger_ref,
            "environment": self.environment.value,
            "root_directory": self.root_directory,
            "branch_includes": list(self.branch_includes),
            "branch_excludes": list(self.branch_excludes),
            "path_includes": list(self.path_includes),
            "path_excludes": list(self.path_excludes),
            "build_command_fingerprint": self.build_command_fingerprint,
            "deploy_command_fingerprint": self.deploy_command_fingerprint,
            "environment_variable_names": list(self.environment_variable_names),
            "environment_variable_values_present": False,
            "build_token_present": False,
        }


def cloudflare_build_trigger_fingerprint(trigger: CloudflareBuildTriggerProjection) -> str:
    if not isinstance(trigger, CloudflareBuildTriggerProjection):
        raise ContractError("trigger must be CloudflareBuildTriggerProjection")
    payload = {
        "worker_ref": trigger.worker_ref,
        "trigger_ref": trigger.trigger_ref,
        "environment": trigger.environment.value,
        "root_directory": trigger.root_directory,
        "branch_includes": list(trigger.branch_includes),
        "branch_excludes": list(trigger.branch_excludes),
        "path_includes": list(trigger.path_includes),
        "path_excludes": list(trigger.path_excludes),
        "build_command_fingerprint": trigger.build_command_fingerprint,
        "deploy_command_fingerprint": trigger.deploy_command_fingerprint,
        "environment_variable_names": list(trigger.environment_variable_names),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CloudflareLogProjection:
    resource_ref: str
    log_ref: str
    lines: tuple[str, ...]
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_ref", _ref(self.resource_ref, "resource_ref"))
        object.__setattr__(self, "log_ref", _ref(self.log_ref, "log_ref"))
        if not isinstance(self.lines, tuple) or len(self.lines) > MAX_LOG_LINES:
            raise ContractError("Cloudflare logs exceed line bound")
        object.__setattr__(self, "lines", tuple(redact_secrets(str(line))[:MAX_LOG_LINE_CHARS] for line in self.lines))
        if not isinstance(self.truncated, bool):
            raise ContractError("truncated must be boolean")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "resource_ref": self.resource_ref,
            "log_ref": self.log_ref,
            "lines": list(self.lines),
            "truncated": self.truncated,
            "trusted_instruction": False,
        }


class TrustedCloudflareReadPort(Protocol):
    def inspect_worker_release(self, *, binding: CloudflareResourceBinding, worker_ref: str) -> CloudflareWorkerReleaseState:
        ...

    def inspect_pages_release(self, *, binding: CloudflareResourceBinding, project_ref: str) -> CloudflarePagesReleaseState:
        ...

    def inspect_build_trigger(self, *, binding: CloudflareResourceBinding, worker_ref: str, environment: CloudflareEnvironment) -> CloudflareBuildTriggerProjection:
        ...


class UnconfiguredCloudflareReadPort:
    def inspect_worker_release(self, **_: Any) -> CloudflareWorkerReleaseState:
        raise ContractError("trusted Cloudflare read adapter is not configured")

    def inspect_pages_release(self, **_: Any) -> CloudflarePagesReleaseState:
        raise ContractError("trusted Cloudflare read adapter is not configured")

    def inspect_build_trigger(self, **_: Any) -> CloudflareBuildTriggerProjection:
        raise ContractError("trusted Cloudflare read adapter is not configured")


@dataclass(frozen=True, slots=True)
class CloudflarePreviewMutationPlan:
    intent: ConnectorWriteIntent
    account_ref: str
    resource_kind: CloudflareResourceKind
    resource_ref: str
    source_revision_ref: str
    artifact_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ConnectorWriteIntent) or self.intent.connector_id != "cloudflare":
            raise ContractError("preview mutation requires Cloudflare ConnectorWriteIntent")
        if self.intent.tool_name not in {"preview_deploy", "retry_preview_build"}:
            raise ContractError("preview mutation plan cannot authorize Production actions")
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref"))
        if not isinstance(self.resource_kind, CloudflareResourceKind):
            object.__setattr__(self, "resource_kind", CloudflareResourceKind(self.resource_kind))
        object.__setattr__(self, "resource_ref", _ref(self.resource_ref, "resource_ref"))
        object.__setattr__(self, "source_revision_ref", _ref(self.source_revision_ref, "source_revision_ref"))
        object.__setattr__(self, "artifact_fingerprint", _sha256(self.artifact_fingerprint, "artifact_fingerprint"))


@dataclass(frozen=True, slots=True)
class CloudflareProductionMutationPlan:
    intent: ConnectorWriteIntent
    action: CloudflareMutationAction
    account_ref: str
    resource_kind: CloudflareResourceKind
    resource_ref: str
    expected_current_release_ref: str
    target_release_ref: str
    source_revision_ref: str
    artifact_fingerprint: str
    bounded_diff_ref: str
    recovery_target_ref: str
    smoke_plan_ref: str
    rollback_compatibility_checked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ConnectorWriteIntent) or self.intent.connector_id != "cloudflare":
            raise ContractError("Production mutation requires Cloudflare ConnectorWriteIntent")
        if not isinstance(self.action, CloudflareMutationAction):
            try:
                object.__setattr__(self, "action", CloudflareMutationAction(self.action))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid Cloudflare Production action") from exc
        if self.action not in {
            CloudflareMutationAction.PRODUCTION_DEPLOY,
            CloudflareMutationAction.WORKER_ROLLBACK,
            CloudflareMutationAction.PAGES_ROLLBACK,
        }:
            raise ContractError("generic Production plan supports only deploy/rollback release actions")
        for field_name in (
            "account_ref", "resource_ref", "expected_current_release_ref", "target_release_ref",
            "source_revision_ref", "bounded_diff_ref", "recovery_target_ref", "smoke_plan_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.resource_kind, CloudflareResourceKind):
            object.__setattr__(self, "resource_kind", CloudflareResourceKind(self.resource_kind))
        object.__setattr__(self, "artifact_fingerprint", _sha256(self.artifact_fingerprint, "artifact_fingerprint"))
        if self.intent.expected_version_ref != self.expected_current_release_ref:
            raise ContractError("P01 intent expected_version_ref must match current Cloudflare release")
        expected_tool = {
            CloudflareMutationAction.PRODUCTION_DEPLOY: "production_deploy",
            CloudflareMutationAction.WORKER_ROLLBACK: "worker_rollback",
            CloudflareMutationAction.PAGES_ROLLBACK: "pages_rollback",
        }[self.action]
        if self.intent.tool_name != expected_tool:
            raise ContractError("P01 Cloudflare tool does not match requested Production action")
        if self.target_release_ref == self.expected_current_release_ref:
            raise ContractError("Production target must differ from current release")
        if self.recovery_target_ref == self.target_release_ref:
            raise ContractError("recovery target must differ from requested target")
        if not isinstance(self.rollback_compatibility_checked, bool) or not self.rollback_compatibility_checked:
            raise ContractError("Production action requires rollback/resource compatibility review")

    def validate_binding(self, binding: CloudflareResourceBinding) -> None:
        if not isinstance(binding, CloudflareResourceBinding):
            raise ContractError("binding must be CloudflareResourceBinding")
        if binding.binding_ref != self.intent.binding_ref or binding.account_ref != self.account_ref:
            raise ContractError("Cloudflare Production plan binding/account mismatch")
        binding.require_resource(self.resource_kind, self.resource_ref)
        if self.intent.target_ref != self.resource_ref:
            raise ContractError("P01 intent target must match exact Cloudflare resource")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.safe_dict(),
            "action": self.action.value,
            "account_ref": self.account_ref,
            "resource_kind": self.resource_kind.value,
            "resource_ref": self.resource_ref,
            "expected_current_release_ref": self.expected_current_release_ref,
            "target_release_ref": self.target_release_ref,
            "source_revision_ref": self.source_revision_ref,
            "artifact_fingerprint": self.artifact_fingerprint,
            "bounded_diff_ref": self.bounded_diff_ref,
            "recovery_target_ref": self.recovery_target_ref,
            "smoke_plan_ref": self.smoke_plan_ref,
            "rollback_compatibility_checked": self.rollback_compatibility_checked,
            "explicit_p01_approval": True,
            "post_action_readback_required": True,
            "post_action_smoke_required": True,
        }


@dataclass(frozen=True, slots=True)
class CloudflareMutationReceipt:
    action: CloudflareMutationAction
    resource_ref: str
    before_release_ref: str
    after_release_ref: str
    expected_target_release_ref: str
    recovery_target_ref: str
    provider_request_ref: str
    readback_evidence_ref: str
    smoke_evidence_ref: str
    smoke_passed: bool
    completed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.action, CloudflareMutationAction):
            object.__setattr__(self, "action", CloudflareMutationAction(self.action))
        if self.action not in {
            CloudflareMutationAction.PRODUCTION_DEPLOY,
            CloudflareMutationAction.WORKER_ROLLBACK,
            CloudflareMutationAction.PAGES_ROLLBACK,
        }:
            raise ContractError("release receipt cannot represent build-config or DNS mutation")
        for field_name in (
            "resource_ref", "before_release_ref", "after_release_ref", "expected_target_release_ref",
            "recovery_target_ref", "provider_request_ref", "readback_evidence_ref", "smoke_evidence_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "completed_at", _aware(self.completed_at, "completed_at"))
        if self.after_release_ref != self.expected_target_release_ref:
            raise ContractError("Cloudflare readback does not match approved target release")
        if self.before_release_ref == self.after_release_ref:
            raise ContractError("Cloudflare mutation receipt must prove a release change")
        if not isinstance(self.smoke_passed, bool) or not self.smoke_passed:
            raise ContractError("Cloudflare Production mutation requires passing post-action smoke")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "resource_ref": self.resource_ref,
            "before_release_ref": self.before_release_ref,
            "after_release_ref": self.after_release_ref,
            "expected_target_release_ref": self.expected_target_release_ref,
            "recovery_target_ref": self.recovery_target_ref,
            "provider_request_ref": self.provider_request_ref,
            "readback_evidence_ref": self.readback_evidence_ref,
            "smoke_evidence_ref": self.smoke_evidence_ref,
            "smoke_passed": self.smoke_passed,
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "raw_token": False,
        }


@dataclass(frozen=True, slots=True)
class CloudflareBuildConfigMutationPlan:
    intent: ConnectorWriteIntent
    account_ref: str
    worker_ref: str
    environment: CloudflareEnvironment
    expected_current_config_fingerprint: str
    target_config_fingerprint: str
    bounded_diff_ref: str
    recovery_config_fingerprint: str
    negative_probe_plan_ref: str
    positive_probe_plan_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.intent, ConnectorWriteIntent) or self.intent.connector_id != "cloudflare":
            raise ContractError("build config mutation requires Cloudflare ConnectorWriteIntent")
        if self.intent.tool_name != "build_config_update":
            raise ContractError("build config mutation requires build_config_update P01 tool")
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        if not isinstance(self.environment, CloudflareEnvironment):
            object.__setattr__(self, "environment", CloudflareEnvironment(self.environment))
        for field_name in (
            "expected_current_config_fingerprint", "target_config_fingerprint", "recovery_config_fingerprint"
        ):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        for field_name in ("bounded_diff_ref", "negative_probe_plan_ref", "positive_probe_plan_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if self.intent.expected_version_ref != self.expected_current_config_fingerprint:
            raise ContractError("P01 expected_version_ref must match current build config fingerprint")
        if self.intent.target_ref != self.worker_ref:
            raise ContractError("P01 build config target must match exact Worker")
        if self.target_config_fingerprint == self.expected_current_config_fingerprint:
            raise ContractError("target build config must differ from current config")
        if self.recovery_config_fingerprint == self.target_config_fingerprint:
            raise ContractError("recovery build config must differ from target config")

    def validate_binding(self, binding: CloudflareResourceBinding) -> None:
        if not isinstance(binding, CloudflareResourceBinding):
            raise ContractError("binding must be CloudflareResourceBinding")
        if binding.binding_ref != self.intent.binding_ref or binding.account_ref != self.account_ref:
            raise ContractError("Cloudflare build config plan binding/account mismatch")
        binding.require_resource(CloudflareResourceKind.WORKER, self.worker_ref)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.safe_dict(),
            "account_ref": self.account_ref,
            "worker_ref": self.worker_ref,
            "environment": self.environment.value,
            "expected_current_config_fingerprint": self.expected_current_config_fingerprint,
            "target_config_fingerprint": self.target_config_fingerprint,
            "bounded_diff_ref": self.bounded_diff_ref,
            "recovery_config_fingerprint": self.recovery_config_fingerprint,
            "negative_probe_plan_ref": self.negative_probe_plan_ref,
            "positive_probe_plan_ref": self.positive_probe_plan_ref,
            "explicit_p01_approval": True,
            "post_action_config_readback_required": True,
            "negative_watch_probe_required": True,
            "positive_watch_probe_required": True,
        }


@dataclass(frozen=True, slots=True)
class CloudflareBuildConfigMutationReceipt:
    worker_ref: str
    environment: CloudflareEnvironment
    before_config_fingerprint: str
    after_config_fingerprint: str
    expected_target_config_fingerprint: str
    recovery_config_fingerprint: str
    provider_request_ref: str
    readback_evidence_ref: str
    negative_probe_evidence_ref: str
    positive_probe_evidence_ref: str
    negative_probe_passed: bool
    positive_probe_passed: bool
    completed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "worker_ref", _ref(self.worker_ref, "worker_ref"))
        if not isinstance(self.environment, CloudflareEnvironment):
            object.__setattr__(self, "environment", CloudflareEnvironment(self.environment))
        for field_name in (
            "before_config_fingerprint", "after_config_fingerprint", "expected_target_config_fingerprint",
            "recovery_config_fingerprint",
        ):
            object.__setattr__(self, field_name, _sha256(getattr(self, field_name), field_name))
        for field_name in (
            "provider_request_ref", "readback_evidence_ref", "negative_probe_evidence_ref", "positive_probe_evidence_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "completed_at", _aware(self.completed_at, "completed_at"))
        if self.after_config_fingerprint != self.expected_target_config_fingerprint:
            raise ContractError("Cloudflare build config readback does not match approved target")
        if self.before_config_fingerprint == self.after_config_fingerprint:
            raise ContractError("Cloudflare build config receipt must prove a config change")
        if not isinstance(self.negative_probe_passed, bool) or not self.negative_probe_passed:
            raise ContractError("nonmatching-path negative build probe must pass")
        if not isinstance(self.positive_probe_passed, bool) or not self.positive_probe_passed:
            raise ContractError("matching-path positive build probe must pass")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "worker_ref": self.worker_ref,
            "environment": self.environment.value,
            "before_config_fingerprint": self.before_config_fingerprint,
            "after_config_fingerprint": self.after_config_fingerprint,
            "expected_target_config_fingerprint": self.expected_target_config_fingerprint,
            "recovery_config_fingerprint": self.recovery_config_fingerprint,
            "provider_request_ref": self.provider_request_ref,
            "readback_evidence_ref": self.readback_evidence_ref,
            "negative_probe_evidence_ref": self.negative_probe_evidence_ref,
            "positive_probe_evidence_ref": self.positive_probe_evidence_ref,
            "negative_probe_passed": self.negative_probe_passed,
            "positive_probe_passed": self.positive_probe_passed,
            "completed_at": self.completed_at.isoformat().replace("+00:00", "Z"),
            "raw_token": False,
        }


RAW_CLOUDFLARE_TOKEN_IN_B54 = False
GLOBAL_API_KEY_SUPPORTED = False
SECRET_READBACK_SUPPORTED = False
DNS_DEFAULT_WRITE_SUPPORTED = False
BILLING_MUTATION_SUPPORTED = False
MEMBERSHIP_MUTATION_SUPPORTED = False
REAL_CLOUDFLARE_ADAPTER_CONFIGURED = False
PRODUCTION_MUTATION_CONFIGURED = False
