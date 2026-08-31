"""Trusted activation bridge from enabled Skill state to runtime compilation.

An enabled installation is only a product/subject preference. It does not carry
execution authority. This bridge first resolves an exact enabled package from
the registry, then delegates all capability/tool/connector/entitlement checks
to the existing trusted Skill runtime compiler.
"""

from __future__ import annotations

from dataclasses import dataclass

from .skill_registry import (
    SkillInstallationSnapshot,
    SkillRegistryError,
    SkillRegistrySnapshot,
    resolve_enabled_skill,
)
from .skill_runtime_adapter import (
    CompiledSkillProfile,
    TrustedSkillRuntimePolicy,
    compile_skill_profile,
)


@dataclass(frozen=True, slots=True)
class ActivatedSkillProfile:
    """Server-side activation result bound to product/subject installation state."""

    app_id: str
    subject_id: str
    compiled: CompiledSkillProfile

    def __post_init__(self) -> None:
        if not isinstance(self.app_id, str) or not self.app_id.strip():
            raise SkillRegistryError(
                "invalid_skill_activation",
                "app_id must be a non-empty string",
            )
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise SkillRegistryError(
                "invalid_skill_activation",
                "subject_id must be a non-empty string",
            )
        if not isinstance(self.compiled, CompiledSkillProfile):
            raise SkillRegistryError(
                "invalid_skill_activation",
                "compiled must be CompiledSkillProfile",
            )

    def to_public_dict(self) -> dict[str, str]:
        """Expose identity only; runtime grants/policies stay server-side."""

        return {
            "app_id": self.app_id,
            "subject_id": self.subject_id,
            "skill_id": self.compiled.canonical_skill_id,
            "runtime_profile_id": self.compiled.runtime_profile.id,
        }


def compile_enabled_skill(
    *,
    registry: SkillRegistrySnapshot,
    installations: SkillInstallationSnapshot,
    app_id: str,
    subject_id: str,
    skill_id: str,
    runtime_policy: TrustedSkillRuntimePolicy,
) -> ActivatedSkillProfile:
    """Resolve enabled state, then independently compile trusted runtime authority.

    This function intentionally performs no permission synthesis. Missing
    capabilities, connector authorization, entitlement, policy refs or trusted
    Tool bindings continue to fail inside `compile_skill_profile()`.
    """

    package = resolve_enabled_skill(
        registry=registry,
        installations=installations,
        app_id=app_id,
        subject_id=subject_id,
        skill_id=skill_id,
    )
    compiled = compile_skill_profile(package, runtime_policy)
    if compiled.canonical_skill_id != skill_id:
        raise SkillRegistryError(
            "skill_activation_identity_mismatch",
            "compiled Skill identity does not match the enabled installation",
        )
    return ActivatedSkillProfile(
        app_id=app_id,
        subject_id=subject_id,
        compiled=compiled,
    )
