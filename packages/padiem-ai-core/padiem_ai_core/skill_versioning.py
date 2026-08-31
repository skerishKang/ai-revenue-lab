"""Deterministic Skill major-version compatibility for P01.

Skill identity is frozen to ``skill:<owner>:<id>@<major>``. This module does not
perform package migration or silently upgrade an installation. It only returns
a deterministic compatibility decision using trusted server-declared migration
maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping

_SKILL_ID_RE = re.compile(r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@([1-9][0-9]*)$")
_MAX_MAJOR = 2**31 - 1


class SkillVersionError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class SkillCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    MIGRATION_REQUIRED = "migration_required"
    INCOMPATIBLE = "incompatible"


def parse_skill_major(skill_id: str) -> int:
    if not isinstance(skill_id, str):
        raise SkillVersionError("invalid_skill_version", "skill_id must be a string")
    match = _SKILL_ID_RE.fullmatch(skill_id)
    if match is None:
        raise SkillVersionError("invalid_skill_version", "skill_id must match skill:<owner>:<id>@<major>")
    major = int(match.group(1))
    if major < 1 or major > _MAX_MAJOR:
        raise SkillVersionError("invalid_skill_version", "Skill major version is outside the supported range")
    return major


@dataclass(frozen=True, slots=True)
class SkillMigrationMap:
    """Trusted server-declared migration edges between concrete Skill majors."""

    edges: Mapping[int, int]

    def __post_init__(self) -> None:
        if not isinstance(self.edges, Mapping):
            raise SkillVersionError("invalid_skill_migration", "edges must be a mapping")
        normalized: dict[int, int] = {}
        for source, target in self.edges.items():
            if isinstance(source, bool) or isinstance(target, bool) or not isinstance(source, int) or not isinstance(target, int):
                raise SkillVersionError("invalid_skill_migration", "migration versions must be integers")
            if not 1 <= source <= _MAX_MAJOR or not 1 <= target <= _MAX_MAJOR:
                raise SkillVersionError("invalid_skill_migration", "migration versions are outside the supported range")
            if source == target:
                raise SkillVersionError("invalid_skill_migration", "migration edges must change major version")
            normalized[source] = target
        object.__setattr__(self, "edges", normalized)

    def target_for(self, source_major: int) -> int | None:
        return self.edges.get(source_major)


@dataclass(frozen=True, slots=True)
class SkillCompatibilityDecision:
    skill_key: str
    installed_major: int
    required_major: int
    status: SkillCompatibility
    migration_target_major: int | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.skill_key, str) or not self.skill_key:
            raise SkillVersionError("invalid_skill_version", "skill_key must be non-empty")
        for name in ("installed_major", "required_major"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SkillVersionError("invalid_skill_version", f"{name} must be a positive integer")
        if not isinstance(self.status, SkillCompatibility):
            raise SkillVersionError("invalid_skill_version", "status must be SkillCompatibility")
        if self.migration_target_major is not None:
            if isinstance(self.migration_target_major, bool) or not isinstance(self.migration_target_major, int) or self.migration_target_major < 1:
                raise SkillVersionError("invalid_skill_version", "migration_target_major must be a positive integer or None")
        if not isinstance(self.reason, str) or len(self.reason) > 256:
            raise SkillVersionError("invalid_skill_version", "reason must be a bounded string")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "skill_key": self.skill_key,
            "installed_major": self.installed_major,
            "required_major": self.required_major,
            "status": self.status.value,
            "migration_target_major": self.migration_target_major,
            "reason": self.reason,
        }


def evaluate_skill_compatibility(
    *,
    installed_skill_id: str,
    required_skill_id: str,
    migration_map: SkillMigrationMap | None = None,
) -> SkillCompatibilityDecision:
    """Return compatibility without executing a migration or changing state."""
    installed_match = _SKILL_ID_RE.fullmatch(installed_skill_id or "") if isinstance(installed_skill_id, str) else None
    required_match = _SKILL_ID_RE.fullmatch(required_skill_id or "") if isinstance(required_skill_id, str) else None
    if installed_match is None or required_match is None:
        raise SkillVersionError("invalid_skill_version", "Skill ids must use the canonical versioned grammar")

    installed_major = parse_skill_major(installed_skill_id)
    required_major = parse_skill_major(required_skill_id)
    if installed_skill_id.split("@", 1)[0] != required_skill_id.split("@", 1)[0]:
        return SkillCompatibilityDecision(
            skill_key=required_skill_id.split("@", 1)[0],
            installed_major=installed_major,
            required_major=required_major,
            status=SkillCompatibility.INCOMPATIBLE,
            reason="skill_identity_changed",
        )
    if installed_major == required_major:
        return SkillCompatibilityDecision(
            skill_key=required_skill_id.split("@", 1)[0],
            installed_major=installed_major,
            required_major=required_major,
            status=SkillCompatibility.COMPATIBLE,
            reason="same_major_version",
        )

    target = (migration_map or SkillMigrationMap({})).target_for(installed_major)
    if target == required_major:
        return SkillCompatibilityDecision(
            skill_key=required_skill_id.split("@", 1)[0],
            installed_major=installed_major,
            required_major=required_major,
            status=SkillCompatibility.MIGRATION_REQUIRED,
            migration_target_major=required_major,
            reason="trusted_migration_edge_declared",
        )

    return SkillCompatibilityDecision(
        skill_key=required_skill_id.split("@", 1)[0],
        installed_major=installed_major,
        required_major=required_major,
        status=SkillCompatibility.INCOMPATIBLE,
        reason="no_trusted_migration_path",
    )
