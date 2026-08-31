"""Product-neutral Skill registry and installation-state contracts for P01.

Registry truth, installation state, and runtime authority are deliberately
separate concepts:

- a registry says which canonical Skill packages exist;
- installation state says whether a product/subject has installed/enabled one;
- runtime authority still comes exclusively from TrustedSkillRuntimePolicy and
  the existing compile_skill_profile() adapter.

Installing or enabling a Skill therefore cannot grant tools, connectors,
entitlements, approvals, Provider access, or credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable

from .skill_package import ReusableSkillPackage


_SKILL_ID_RE = re.compile(
    r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_REGISTERED_SKILLS = 512
MAX_INSTALLATIONS = 2_048


class SkillRegistryError(ValueError):
    """Safe registry/state contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("skill registry error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise SkillRegistryError(
            "invalid_skill_registry_contract",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _skill_id(value: str) -> str:
    if not isinstance(value, str) or not _SKILL_ID_RE.fullmatch(value):
        raise SkillRegistryError(
            "invalid_skill_registry_contract",
            "skill_id must match skill:<owner>:<id>@<major>",
        )
    return value


def _package_fingerprint(package: ReusableSkillPackage) -> str:
    """Return deterministic package-content identity for conflict detection.

    The fingerprint is registry/internal metadata only. It is intentionally
    derived from declarative package fields, not runtime grants or credentials.
    """

    payload = {
        "skill_id": package.skill_id,
        "publisher_id": package.publisher_id,
        "description": package.description,
        "instruction": package.instruction,
        "input_contract_ref": package.input_contract_ref,
        "output_contract_ref": package.output_contract_ref,
        "required_capabilities": list(package.required_capabilities),
        "allowed_tool_ids": list(package.allowed_tool_ids),
        "connector_requirement_ids": list(package.connector_requirement_ids),
        "context_policy_ref": package.context_policy_ref,
        "model_policy_ref": package.model_policy_ref,
        "execution_budget": {
            "max_steps": package.execution_budget.max_steps,
            "max_tool_calls": package.execution_budget.max_tool_calls,
            "max_wall_seconds": package.execution_budget.max_wall_seconds,
        },
        "approval_hooks": [hook.value for hook in package.approval_hooks],
        "entitlement_ref": package.entitlement_ref,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RegisteredSkill:
    package: ReusableSkillPackage
    fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, ReusableSkillPackage):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "package must be ReusableSkillPackage",
            )
        expected = _package_fingerprint(self.package)
        if self.fingerprint != expected:
            raise SkillRegistryError(
                "skill_registry_fingerprint_mismatch",
                "registered Skill fingerprint does not match package content",
            )

    @classmethod
    def from_package(cls, package: ReusableSkillPackage) -> "RegisteredSkill":
        if not isinstance(package, ReusableSkillPackage):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "package must be ReusableSkillPackage",
            )
        return cls(package=package, fingerprint=_package_fingerprint(package))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.package.skill_id,
            "publisher_id": self.package.publisher_id,
            "required_capabilities": list(self.package.required_capabilities),
            "allowed_tool_ids": list(self.package.allowed_tool_ids),
            "connector_requirement_ids": list(self.package.connector_requirement_ids),
        }


@dataclass(frozen=True, slots=True)
class SkillRegistrySnapshot:
    """Immutable product-neutral registry snapshot."""

    entries: tuple[RegisteredSkill, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "entries must be a tuple",
            )
        if len(self.entries) > MAX_REGISTERED_SKILLS:
            raise SkillRegistryError(
                "skill_registry_budget_exceeded",
                "registry exceeds the bounded Skill count",
            )
        if any(not isinstance(entry, RegisteredSkill) for entry in self.entries):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "entries must contain RegisteredSkill values",
            )
        ids = tuple(entry.package.skill_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise SkillRegistryError(
                "duplicate_skill_registry_id",
                "registry contains duplicate canonical Skill ids",
            )
        if ids != tuple(sorted(ids)):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "registry entries must be sorted by canonical Skill id",
            )

    @classmethod
    def from_packages(
        cls,
        packages: Iterable[ReusableSkillPackage],
    ) -> "SkillRegistrySnapshot":
        if isinstance(packages, (str, bytes)):
            raise SkillRegistryError(
                "invalid_skill_registry_contract",
                "packages must be an iterable of ReusableSkillPackage values",
            )
        entries = tuple(RegisteredSkill.from_package(package) for package in packages)
        by_id: dict[str, RegisteredSkill] = {}
        for entry in entries:
            existing = by_id.get(entry.package.skill_id)
            if existing is not None:
                if existing.fingerprint != entry.fingerprint:
                    raise SkillRegistryError(
                        "skill_registry_version_conflict",
                        "the same canonical Skill id maps to different package content",
                    )
                raise SkillRegistryError(
                    "duplicate_skill_registry_id",
                    "registry contains duplicate canonical Skill ids",
                )
            by_id[entry.package.skill_id] = entry
        return cls(entries=tuple(sorted(by_id.values(), key=lambda item: item.package.skill_id)))

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(entry.package.skill_id for entry in self.entries)

    def get(self, skill_id: str) -> RegisteredSkill:
        canonical_id = _skill_id(skill_id)
        for entry in self.entries:
            if entry.package.skill_id == canonical_id:
                return entry
        raise SkillRegistryError(
            "skill_not_registered",
            "requested Skill is not present in the registry",
        )

    def with_package(self, package: ReusableSkillPackage) -> "SkillRegistrySnapshot":
        candidate = RegisteredSkill.from_package(package)
        current = {entry.package.skill_id: entry for entry in self.entries}
        existing = current.get(package.skill_id)
        if existing is not None:
            if existing.fingerprint == candidate.fingerprint:
                return self
            raise SkillRegistryError(
                "skill_registry_version_conflict",
                "canonical Skill id is already registered with different content",
            )
        if len(current) >= MAX_REGISTERED_SKILLS:
            raise SkillRegistryError(
                "skill_registry_budget_exceeded",
                "registry exceeds the bounded Skill count",
            )
        current[package.skill_id] = candidate
        return SkillRegistrySnapshot(
            entries=tuple(sorted(current.values(), key=lambda item: item.package.skill_id))
        )


class SkillInstallStatus(str, Enum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class SkillInstallation:
    """Non-authoritative installation state for one product/subject."""

    app_id: str
    subject_id: str
    skill_id: str
    status: SkillInstallStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _safe_id("app_id", self.app_id))
        object.__setattr__(self, "subject_id", _safe_id("subject_id", self.subject_id))
        object.__setattr__(self, "skill_id", _skill_id(self.skill_id))
        if not isinstance(self.status, SkillInstallStatus):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "status must be SkillInstallStatus",
            )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.app_id, self.subject_id, self.skill_id)

    @property
    def enabled(self) -> bool:
        return self.status is SkillInstallStatus.ENABLED

    def to_public_dict(self) -> dict[str, object]:
        return {
            "app_id": self.app_id,
            "subject_id": self.subject_id,
            "skill_id": self.skill_id,
            "status": self.status.value,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class SkillInstallationSnapshot:
    """Immutable state snapshot; it contains no permission/grant fields."""

    installations: tuple[SkillInstallation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.installations, tuple):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "installations must be a tuple",
            )
        if len(self.installations) > MAX_INSTALLATIONS:
            raise SkillRegistryError(
                "skill_installation_budget_exceeded",
                "installation state exceeds the bounded item count",
            )
        if any(
            not isinstance(installation, SkillInstallation)
            for installation in self.installations
        ):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "installations must contain SkillInstallation values",
            )
        keys = tuple(item.key for item in self.installations)
        if len(set(keys)) != len(keys):
            raise SkillRegistryError(
                "duplicate_skill_installation",
                "installation snapshot contains duplicate Skill state",
            )
        if keys != tuple(sorted(keys)):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "installations must be sorted deterministically",
            )

    @classmethod
    def from_installations(
        cls,
        installations: Iterable[SkillInstallation],
    ) -> "SkillInstallationSnapshot":
        if isinstance(installations, (str, bytes)):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "installations must be an iterable of SkillInstallation values",
            )
        values = tuple(installations)
        if any(not isinstance(item, SkillInstallation) for item in values):
            raise SkillRegistryError(
                "invalid_skill_installation",
                "installations must contain SkillInstallation values",
            )
        return cls(installations=tuple(sorted(values, key=lambda item: item.key)))

    def get(self, *, app_id: str, subject_id: str, skill_id: str) -> SkillInstallation:
        key = (_safe_id("app_id", app_id), _safe_id("subject_id", subject_id), _skill_id(skill_id))
        for installation in self.installations:
            if installation.key == key:
                return installation
        raise SkillRegistryError(
            "skill_not_installed",
            "requested Skill has no installation state for this subject",
        )


def resolve_enabled_skill(
    *,
    registry: SkillRegistrySnapshot,
    installations: SkillInstallationSnapshot,
    app_id: str,
    subject_id: str,
    skill_id: str,
) -> ReusableSkillPackage:
    """Resolve an enabled package without creating any runtime authority.

    The returned package is still purely declarative. Callers must separately
    invoke `compile_skill_profile(package, TrustedSkillRuntimePolicy(...))` before
    execution so installation state can never substitute for trusted grants.
    """

    if not isinstance(registry, SkillRegistrySnapshot):
        raise SkillRegistryError(
            "invalid_skill_registry_contract",
            "registry must be SkillRegistrySnapshot",
        )
    if not isinstance(installations, SkillInstallationSnapshot):
        raise SkillRegistryError(
            "invalid_skill_installation",
            "installations must be SkillInstallationSnapshot",
        )
    entry = registry.get(skill_id)
    installation = installations.get(
        app_id=app_id,
        subject_id=subject_id,
        skill_id=skill_id,
    )
    if installation.status is not SkillInstallStatus.ENABLED:
        raise SkillRegistryError(
            "skill_not_enabled",
            "requested Skill is installed but not enabled",
        )
    return entry.package
