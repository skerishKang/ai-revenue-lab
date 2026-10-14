"""#2822: Claw Skill Registry + typed capability manifest contract.

Padiem Claw treats file/document/business capabilities as explicit, typed,
versioned and auditable Skills rather than something inferred from prompts.
This module is the canonical registry and manifest contract those Skills are
registered under.

What this module is, precisely
------------------------------
* A **declarative contract**: typed manifests, a deterministic registry, MIME
  compatibility checks, explicit authority metadata, composition rules and a
  bounded safe public projection.
* **Not a runtime**: nothing here invokes a parser, provider, network call,
  sandbox, module import or shell command. ``skill_id`` is a lookup key only
  and is never executed.

Authority model
---------------
``AUTHORITY_INHERITANCE=NO`` and ``SILENT_AUTHORITY_ESCALATION=NO``. A Skill's
effective authority is exactly what its own manifest declares. The invocation
request must ask for that authority **exactly**: a narrower request fails
closed (no silent escalation onto the Skill) and a wider request fails closed
(undeclared authority). Ambient caller authority is never copied onto a Skill,
and a Skill never widens because of who called it. Composition unions component
authorities for planning, but each member invocation is still bounded by the
member's own manifest (``composition authority widening = rejected``).

Relationship to existing modules
--------------------------------
``padiem_ai_core.skill_registry`` remains the P01 reusable *agent* Skill
package registry (``ReusableSkillPackage``). This module is the Claw
*document/file capability* manifest registry required by #2821/#2822 and is
consumed together with the #2824 pre-parser file intake gate. It introduces no
parser, no OSS intake decision (#2823) and no provider call.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ACCEPTANCE",
    "CAPABILITY_FILE_INSPECT",
    "CAPABILITY_HWPX_CREATE",
    "CAPABILITY_HWPX_EDIT",
    "CAPABILITY_HWPX_READ",
    "CAPABILITY_HWPX_TEMPLATE_FILL",
    "CAPABILITY_HWPX_VALIDATE",
    "CAPABILITY_HWP_CONVERT_TO_HWPX",
    "CAPABILITY_HWP_READ",
    "CAPABILITY_IMAGE_INSPECT",
    "CAPABILITY_IMAGE_OCR",
    "CAPABILITY_IMAGE_TRANSFORM",
    "CAPABILITY_PDF_CREATE",
    "CAPABILITY_PDF_INSPECT",
    "CAPABILITY_PDF_OCR",
    "CAPABILITY_PDF_READ",
    "CAPABILITY_PDF_TRANSFORM",
    "MAX_FILESYSTEM_SCOPE",
    "MAX_INPUT_BYTES_LIMIT",
    "MAX_PAGES_OR_ARCHIVE_EXPANSION_LIMIT",
    "MAX_REGISTERED_SKILLS",
    "MAX_SIDE_EFFECT_CLASS",
    "REQUIRED_MANIFEST_FIELDS",
    "REQUIRED_MANIFEST_FIELD_NAMES",
    "RESERVED_CAPABILITY_IDS",
    "FilesystemScope",
    "SideEffectClass",
    "SkillInvocationGrant",
    "SkillInvocationRequest",
    "SkillManifest",
    "SkillRegistryContractError",
    "SkillRegistrySnapshot",
    "authorize_composed_member",
    "authorize_invocation",
    "build_claw_skill_registry",
    "compose_skills",
    "is_reserved_capability",
]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

_SAFE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_SKILL_ID_RE = re.compile(
    r"^skill:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_CAPABILITY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,127}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
# Provenance is public metadata: a bounded reference, never a host path.
_PROVENANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,255}$")

MAX_REGISTERED_SKILLS = 512
MAX_MIME_ENTRIES = 16
MAX_INPUT_BYTES_LIMIT = 64 * 1024 * 1024
MAX_PAGES_OR_ARCHIVE_EXPANSION_LIMIT = 100_000


class SkillRegistryContractError(ValueError):
    """Safe, bounded registry/manifest contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_CODE_RE.fullmatch(code):
            raise ValueError("skill registry error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _fail(code: str, message: str) -> SkillRegistryContractError:
    return SkillRegistryContractError(code, message)


# --------------------------------------------------------------------------
# Typed authority enums
# --------------------------------------------------------------------------


class SideEffectClass(str, Enum):
    """Known side-effect class; required before invocation."""

    NONE = "none"
    LOCAL_WRITE = "local_write"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class FilesystemScope(str, Enum):
    """Bounded filesystem authority declared by a Skill manifest."""

    NONE = "none"
    SCOPED_READ = "scoped_read"
    SCOPED_WRITE = "scoped_write"


_SIDE_EFFECT_ORDER: dict[SideEffectClass, int] = {
    SideEffectClass.NONE: 0,
    SideEffectClass.LOCAL_WRITE: 1,
    SideEffectClass.EXTERNAL_SIDE_EFFECT: 2,
}
_FILESYSTEM_ORDER: dict[FilesystemScope, int] = {
    FilesystemScope.NONE: 0,
    FilesystemScope.SCOPED_READ: 1,
    FilesystemScope.SCOPED_WRITE: 2,
}

MAX_SIDE_EFFECT_CLASS = SideEffectClass.EXTERNAL_SIDE_EFFECT
MAX_FILESYSTEM_SCOPE = FilesystemScope.SCOPED_WRITE


def _max_side_effect(values: Iterable[SideEffectClass]) -> SideEffectClass:
    return max(values, key=lambda item: _SIDE_EFFECT_ORDER[item])


def _max_filesystem_scope(values: Iterable[FilesystemScope]) -> FilesystemScope:
    return max(values, key=lambda item: _FILESYSTEM_ORDER[item])


# --------------------------------------------------------------------------
# Reserved capability identities (#2821 P0 child capability names)
# --------------------------------------------------------------------------

CAPABILITY_PDF_INSPECT = "pdf.inspect"
CAPABILITY_PDF_READ = "pdf.read"
CAPABILITY_PDF_OCR = "pdf.ocr"
CAPABILITY_PDF_CREATE = "pdf.create"
CAPABILITY_PDF_TRANSFORM = "pdf.transform"

CAPABILITY_IMAGE_INSPECT = "image.inspect"
CAPABILITY_IMAGE_OCR = "image.ocr"
CAPABILITY_IMAGE_TRANSFORM = "image.transform"

CAPABILITY_HWPX_READ = "hwpx.read"
CAPABILITY_HWPX_CREATE = "hwpx.create"
CAPABILITY_HWPX_EDIT = "hwpx.edit"
CAPABILITY_HWPX_TEMPLATE_FILL = "hwpx.template_fill"
CAPABILITY_HWPX_VALIDATE = "hwpx.validate"

CAPABILITY_HWP_READ = "hwp.read"
CAPABILITY_HWP_CONVERT_TO_HWPX = "hwp.convert_to_hwpx"

CAPABILITY_FILE_INSPECT = "file.inspect"

#: Closed set of capability identities reserved by #2821/#2822.
RESERVED_CAPABILITY_IDS: frozenset[str] = frozenset(
    {
        CAPABILITY_PDF_INSPECT,
        CAPABILITY_PDF_READ,
        CAPABILITY_PDF_OCR,
        CAPABILITY_PDF_CREATE,
        CAPABILITY_PDF_TRANSFORM,
        CAPABILITY_IMAGE_INSPECT,
        CAPABILITY_IMAGE_OCR,
        CAPABILITY_IMAGE_TRANSFORM,
        CAPABILITY_HWPX_READ,
        CAPABILITY_HWPX_CREATE,
        CAPABILITY_HWPX_EDIT,
        CAPABILITY_HWPX_TEMPLATE_FILL,
        CAPABILITY_HWPX_VALIDATE,
        CAPABILITY_HWP_READ,
        CAPABILITY_HWP_CONVERT_TO_HWPX,
        CAPABILITY_FILE_INSPECT,
    }
)


def is_reserved_capability(capability_id: str) -> bool:
    return isinstance(capability_id, str) and capability_id in RESERVED_CAPABILITY_IDS


# --------------------------------------------------------------------------
# Acceptance tokens (#2822)
# --------------------------------------------------------------------------

#: The 14 fields required by the #2822 capability manifest contract.
#: ``capability_id`` is an additional typed discovery key, not a replacement.
REQUIRED_MANIFEST_FIELD_NAMES: tuple[str, ...] = (
    "skill_id",
    "version",
    "input_mime",
    "output_mime",
    "filesystem_scope",
    "network_required",
    "provider_required",
    "sandbox_required",
    "side_effect_class",
    "approval_required",
    "max_input_bytes",
    "max_pages_or_archive_expansion",
    "provenance",
    "license",
)
REQUIRED_MANIFEST_FIELDS = len(REQUIRED_MANIFEST_FIELD_NAMES)

ACCEPTANCE: dict[str, str] = {
    "SKILL_REGISTRY_CANONICAL": "YES",
    "CAPABILITY_MANIFEST_TYPED": "YES",
    "REQUIRED_MANIFEST_FIELDS": str(REQUIRED_MANIFEST_FIELDS),
    "UNKNOWN_SKILL_FAIL_CLOSED": "YES",
    "DUPLICATE_ID_VERSION_REJECTED": "YES",
    "MIME_MISMATCH_REJECTED": "YES",
    "UNDECLARED_NETWORK_AUTHORITY_REJECTED": "YES",
    "UNDECLARED_PROVIDER_AUTHORITY_REJECTED": "YES",
    "UNDECLARED_SANDBOX_AUTHORITY_REJECTED": "YES",
    "FILESYSTEM_SCOPE_WIDENING_REJECTED": "YES",
    "SILENT_AUTHORITY_ESCALATION": "NO",
    "AUTHORITY_INHERITANCE": "NO",
    "COMPOSITION_AUTHORITY_WIDENING": "NO",
    "READONLY_PROVIDER_SIDE_EFFECT_NONE": "YES",
    "ARBITRARY_SHELL_FROM_SKILL_ID": "NO",
    "SAFE_PROJECTION": "PASS",
    "PARSER_IMPLEMENTATION": "0",
    "OSS_ADOPTION": "0",
    "PROVIDER_CALLS": "0",
    "PRODUCTION_MUTATION": "0",
}


# --------------------------------------------------------------------------
# Typed capability manifest
# --------------------------------------------------------------------------


def _require_mime_tuple(name: str, values: tuple[str, ...], *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise _fail("invalid_capability_manifest", f"{name} must be a tuple")
    if not values and not allow_empty:
        raise _fail("invalid_capability_manifest", f"{name} must declare at least one MIME type")
    if len(values) > MAX_MIME_ENTRIES:
        raise _fail("capability_manifest_budget_exceeded", f"{name} exceeds the bounded MIME count")
    if len(set(values)) != len(values):
        raise _fail("invalid_capability_manifest", f"{name} contains duplicates")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not _MIME_RE.fullmatch(value):
            raise _fail("invalid_capability_manifest", f"{name} entries must be bounded MIME types")
        normalized.append(value)
    return tuple(normalized)


def _require_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise _fail("invalid_capability_manifest", f"{name} must be a boolean")
    return value


def _require_bounded_int(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail("invalid_capability_manifest", f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise _fail(
            "capability_manifest_budget_exceeded",
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """Typed, versioned capability manifest for one Claw Skill.

    Every authority-relevant field is explicit. There is no default that
    grants network, provider, sandbox, filesystem or external side effects.
    """

    skill_id: str
    version: str
    capability_id: str
    input_mime: tuple[str, ...]
    output_mime: tuple[str, ...]
    filesystem_scope: FilesystemScope
    network_required: bool
    provider_required: bool
    sandbox_required: bool
    side_effect_class: SideEffectClass
    approval_required: bool
    max_input_bytes: int
    max_pages_or_archive_expansion: int
    provenance: str
    license: str

    def __post_init__(self) -> None:
        if not isinstance(self.skill_id, str) or not _SKILL_ID_RE.fullmatch(self.skill_id):
            raise _fail(
                "invalid_capability_manifest",
                "skill_id must match skill:<owner>:<id>@<major>",
            )
        if not isinstance(self.version, str) or not _VERSION_RE.fullmatch(self.version):
            raise _fail("invalid_capability_manifest", "version must be major.minor.patch")
        if (
            not isinstance(self.capability_id, str)
            or not _CAPABILITY_RE.fullmatch(self.capability_id)
        ):
            raise _fail("invalid_capability_manifest", "capability_id must be a bounded identifier")

        object.__setattr__(self, "input_mime", _require_mime_tuple("input_mime", self.input_mime, allow_empty=False))
        object.__setattr__(
            self, "output_mime", _require_mime_tuple("output_mime", self.output_mime, allow_empty=True)
        )

        if not isinstance(self.filesystem_scope, FilesystemScope):
            raise _fail("invalid_capability_manifest", "filesystem_scope must be FilesystemScope")
        if not isinstance(self.side_effect_class, SideEffectClass):
            raise _fail("invalid_capability_manifest", "side_effect_class must be SideEffectClass")

        object.__setattr__(self, "network_required", _require_bool("network_required", self.network_required))
        object.__setattr__(self, "provider_required", _require_bool("provider_required", self.provider_required))
        object.__setattr__(self, "sandbox_required", _require_bool("sandbox_required", self.sandbox_required))
        object.__setattr__(self, "approval_required", _require_bool("approval_required", self.approval_required))

        # A provider call is always a networked call; never declare the reverse gap.
        if self.provider_required and not self.network_required:
            raise _fail(
                "invalid_capability_manifest",
                "provider_required implies network_required",
            )
        # External side effects must be approvable before invocation.
        if self.side_effect_class is SideEffectClass.EXTERNAL_SIDE_EFFECT and not self.approval_required:
            raise _fail(
                "invalid_capability_manifest",
                "external side effects require approval_required=True",
            )
        # A skill with no filesystem need must not declare filesystem authority.
        if self.filesystem_scope is FilesystemScope.SCOPED_WRITE and self.side_effect_class is SideEffectClass.NONE:
            raise _fail(
                "invalid_capability_manifest",
                "scoped_write requires a non-none side_effect_class",
            )

        object.__setattr__(
            self,
            "max_input_bytes",
            _require_bounded_int(
                "max_input_bytes",
                self.max_input_bytes,
                minimum=1,
                maximum=MAX_INPUT_BYTES_LIMIT,
            ),
        )
        object.__setattr__(
            self,
            "max_pages_or_archive_expansion",
            _require_bounded_int(
                "max_pages_or_archive_expansion",
                self.max_pages_or_archive_expansion,
                minimum=1,
                maximum=MAX_PAGES_OR_ARCHIVE_EXPANSION_LIMIT,
            ),
        )

        if not isinstance(self.provenance, str) or not _PROVENANCE_RE.fullmatch(self.provenance):
            raise _fail(
                "invalid_capability_manifest",
                "provenance must be a bounded reference (never a host path)",
            )
        if any(token in self.provenance for token in ("..", "\\", "\x00", "://")):
            raise _fail(
                "invalid_capability_manifest",
                "provenance must not contain path traversal or control material",
            )
        if self.provenance.startswith("/") or re.fullmatch(r"^[A-Za-z]:", self.provenance):
            raise _fail(
                "invalid_capability_manifest",
                "provenance must not be an absolute host path",
            )
        if not isinstance(self.license, str) or not _SAFE_REF_RE.fullmatch(self.license):
            raise _fail("invalid_capability_manifest", "license must be a bounded reference")

    @property
    def identity(self) -> tuple[str, str]:
        return (self.skill_id, self.version)

    def to_public_dict(self) -> dict[str, object]:
        """Bounded safe projection.

        Contains only manifest metadata. Never credentials, host/internal
        paths, provider payloads, raw bytes or executable instructions.
        """

        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "capability_id": self.capability_id,
            "input_mime": list(self.input_mime),
            "output_mime": list(self.output_mime),
            "filesystem_scope": self.filesystem_scope.value,
            "network_required": self.network_required,
            "provider_required": self.provider_required,
            "sandbox_required": self.sandbox_required,
            "side_effect_class": self.side_effect_class.value,
            "approval_required": self.approval_required,
            "max_input_bytes": self.max_input_bytes,
            "max_pages_or_archive_expansion": self.max_pages_or_archive_expansion,
            "provenance": self.provenance,
            "license": self.license,
        }


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillRegistrySnapshot:
    """Immutable, deterministic Skill registry snapshot.

    Discovery by ``skill_id`` and by ``capability_id`` is deterministic and
    fail-closed: an unknown id/capability raises rather than falling back to a
    default Skill or an arbitrary module name.
    """

    entries: tuple[SkillManifest, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise _fail("invalid_skill_registry_contract", "entries must be a tuple")
        if len(self.entries) > MAX_REGISTERED_SKILLS:
            raise _fail("skill_registry_budget_exceeded", "registry exceeds the bounded Skill count")
        if any(not isinstance(entry, SkillManifest) for entry in self.entries):
            raise _fail("invalid_skill_registry_contract", "entries must contain SkillManifest values")

        keys = tuple(entry.identity for entry in self.entries)
        if len(set(keys)) != len(keys):
            raise _fail("duplicate_skill_id_version", "registry contains a duplicate skill id/version")

        skill_ids = tuple(entry.skill_id for entry in self.entries)
        if len(set(skill_ids)) != len(skill_ids):
            raise _fail(
                "duplicate_skill_id_version",
                "registry maps one skill_id to multiple versions",
            )

        sorted_entries = tuple(sorted(self.entries, key=lambda item: item.identity))
        if self.entries != sorted_entries:
            raise _fail(
                "invalid_skill_registry_contract",
                "registry entries must be sorted by skill_id/version",
            )

    @classmethod
    def from_manifests(cls, manifests: Iterable[SkillManifest]) -> SkillRegistrySnapshot:
        if isinstance(manifests, (str, bytes)):
            raise _fail(
                "invalid_skill_registry_contract",
                "manifests must be an iterable of SkillManifest values",
            )
        values = tuple(manifests)
        if any(not isinstance(item, SkillManifest) for item in values):
            raise _fail("invalid_skill_registry_contract", "manifests must contain SkillManifest values")
        # from_manifests accepts any order; the snapshot enforces sortedness.
        return cls(entries=tuple(sorted(values, key=lambda item: item.identity)))

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(entry.skill_id for entry in self.entries)

    @property
    def capability_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entry in self.entries:
            if entry.capability_id not in seen:
                seen.append(entry.capability_id)
        return tuple(seen)

    def get(self, skill_id: str) -> SkillManifest:
        """Resolve one Skill by id. Unknown ids fail closed."""

        if not isinstance(skill_id, str) or not _SKILL_ID_RE.fullmatch(skill_id):
            raise _fail(
                "unknown_skill",
                "requested skill_id is not a registered canonical Skill",
            )
        for entry in self.entries:
            if entry.skill_id == skill_id:
                return entry
        raise _fail("unknown_skill", "requested Skill is not present in the registry")

    def discover(self, capability_id: str) -> tuple[SkillManifest, ...]:
        """Deterministic discovery by capability. Unknown capability → empty."""

        if not isinstance(capability_id, str) or not _CAPABILITY_RE.fullmatch(capability_id):
            return ()
        return tuple(entry for entry in self.entries if entry.capability_id == capability_id)

    def require_capability(self, capability_id: str) -> SkillManifest:
        """Exactly one Skill must provide the capability, else fail closed."""

        matches = self.discover(capability_id)
        if not matches:
            raise _fail(
                "unknown_capability",
                "no registered Skill provides the requested capability",
            )
        if len(matches) > 1:
            raise _fail(
                "ambiguous_capability",
                "multiple registered Skills provide the same capability",
            )
        return matches[0]

    def require_input_mime(self, skill_id: str, actual_mime: str) -> SkillManifest:
        """Fail closed when the actual input MIME is outside the manifest."""

        manifest = self.get(skill_id)
        if not isinstance(actual_mime, str) or not _MIME_RE.fullmatch(actual_mime):
            raise _fail("mime_mismatch", "actual MIME type is not a bounded MIME value")
        if actual_mime not in manifest.input_mime:
            raise _fail(
                "mime_mismatch",
                "actual MIME type is not declared in the Skill input manifest",
            )
        return manifest

    def with_manifest(self, manifest: SkillManifest) -> SkillRegistrySnapshot:
        if not isinstance(manifest, SkillManifest):
            raise _fail("invalid_skill_registry_contract", "manifest must be SkillManifest")
        current = {entry.identity: entry for entry in self.entries}
        if manifest.identity in current:
            existing = current[manifest.identity]
            if existing != manifest:
                raise _fail(
                    "duplicate_skill_id_version",
                    "skill id/version is already registered with different content",
                )
            return self
        skill_id_owner = {entry.skill_id for entry in self.entries}
        if manifest.skill_id in skill_id_owner:
            raise _fail(
                "duplicate_skill_id_version",
                "skill_id is already registered with a different version",
            )
        if len(self.entries) >= MAX_REGISTERED_SKILLS:
            raise _fail("skill_registry_budget_exceeded", "registry exceeds the bounded Skill count")
        return SkillRegistrySnapshot.from_manifests((*self.entries, manifest))

    def to_public_dicts(self) -> tuple[dict[str, object], ...]:
        return tuple(entry.to_public_dict() for entry in self.entries)


def build_claw_skill_registry(
    manifests: Iterable[SkillManifest] = (),
) -> SkillRegistrySnapshot:
    """Build the canonical Claw Skill registry snapshot."""

    return SkillRegistrySnapshot.from_manifests(manifests)


# --------------------------------------------------------------------------
# Invocation authority (explicit, never inherited)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillInvocationRequest:
    """Caller-side invocation request.

    Fields must equal the manifest's required authority exactly. They never
    grant authority; ambient caller state is not read here. A narrower or
    wider request fails closed at authorization time.
    """

    skill_id: str
    actual_input_mime: str
    wants_network: bool = False
    wants_provider: bool = False
    wants_sandbox: bool = False
    wants_filesystem_scope: FilesystemScope = FilesystemScope.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.skill_id, str):
            raise _fail("invalid_invocation_request", "skill_id must be a string")
        if not isinstance(self.actual_input_mime, str):
            raise _fail("invalid_invocation_request", "actual_input_mime must be a string")
        object.__setattr__(self, "wants_network", _require_bool("wants_network", self.wants_network))
        object.__setattr__(self, "wants_provider", _require_bool("wants_provider", self.wants_provider))
        object.__setattr__(self, "wants_sandbox", _require_bool("wants_sandbox", self.wants_sandbox))
        if not isinstance(self.wants_filesystem_scope, FilesystemScope):
            raise _fail(
                "invalid_invocation_request",
                "wants_filesystem_scope must be FilesystemScope",
            )
        if self.wants_provider and not self.wants_network:
            raise _fail(
                "invalid_invocation_request",
                "provider use implies a network request",
            )


@dataclass(frozen=True, slots=True)
class SkillInvocationGrant:
    """Effective authority for one authorized invocation.

    After a successful ``authorize_invocation``, requested authority equals
    required manifest authority exactly. Fields are copied from the resolved
    manifest, never from a caller-supplied ambient authority object.
    """

    skill_id: str
    version: str
    capability_id: str
    input_mime: tuple[str, ...]
    output_mime: tuple[str, ...]
    filesystem_scope: FilesystemScope
    network_required: bool
    provider_required: bool
    sandbox_required: bool
    side_effect_class: SideEffectClass
    approval_required: bool
    max_input_bytes: int
    max_pages_or_archive_expansion: int

    @classmethod
    def from_manifest(cls, manifest: SkillManifest) -> SkillInvocationGrant:
        return cls(
            skill_id=manifest.skill_id,
            version=manifest.version,
            capability_id=manifest.capability_id,
            input_mime=manifest.input_mime,
            output_mime=manifest.output_mime,
            filesystem_scope=manifest.filesystem_scope,
            network_required=manifest.network_required,
            provider_required=manifest.provider_required,
            sandbox_required=manifest.sandbox_required,
            side_effect_class=manifest.side_effect_class,
            approval_required=manifest.approval_required,
            max_input_bytes=manifest.max_input_bytes,
            max_pages_or_archive_expansion=manifest.max_pages_or_archive_expansion,
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "capability_id": self.capability_id,
            "filesystem_scope": self.filesystem_scope.value,
            "network_required": self.network_required,
            "provider_required": self.provider_required,
            "sandbox_required": self.sandbox_required,
            "side_effect_class": self.side_effect_class.value,
            "approval_required": self.approval_required,
            "max_input_bytes": self.max_input_bytes,
            "max_pages_or_archive_expansion": self.max_pages_or_archive_expansion,
        }


def authorize_invocation(
    registry: SkillRegistrySnapshot,
    request: SkillInvocationRequest,
) -> SkillInvocationGrant:
    """Authorize one invocation against the manifest; fail closed.

    Manifest ``*_required`` / ``filesystem_scope`` fields are the authority the
    Skill needs. The request must ask for exactly that authority:

    * authority the manifest does not declare but the request wants → fail;
    * authority the manifest requires but the request does not want → fail
      (no silent authority escalation).

    On success ``REQUESTED_AUTHORITY == REQUIRED_MANIFEST_AUTHORITY`` and the
    grant is rebuilt solely from the manifest, so ambient caller authority is
    never inherited.

    ``provider_required`` is independent of ``side_effect_class``: a read-only
    provider Skill may declare ``provider_required=True`` with
    ``side_effect_class=NONE``.
    """

    if not isinstance(registry, SkillRegistrySnapshot):
        raise _fail("invalid_skill_registry_contract", "registry must be SkillRegistrySnapshot")
    if not isinstance(request, SkillInvocationRequest):
        raise _fail("invalid_invocation_request", "request must be SkillInvocationRequest")

    manifest = registry.require_input_mime(request.skill_id, request.actual_input_mime)

    if request.wants_network and not manifest.network_required:
        raise _fail(
            "unauthorized_network_request",
            "Skill manifest does not declare network authority",
        )
    if manifest.network_required and not request.wants_network:
        raise _fail(
            "missing_network_authority_request",
            "Skill manifest requires network authority that the request did not request",
        )
    if request.wants_provider and not manifest.provider_required:
        raise _fail(
            "unauthorized_provider_request",
            "Skill manifest does not declare provider authority",
        )
    if manifest.provider_required and not request.wants_provider:
        raise _fail(
            "missing_provider_authority_request",
            "Skill manifest requires provider authority that the request did not request",
        )
    if request.wants_sandbox and not manifest.sandbox_required:
        raise _fail(
            "unauthorized_sandbox_request",
            "Skill manifest does not declare sandbox authority",
        )
    if manifest.sandbox_required and not request.wants_sandbox:
        raise _fail(
            "missing_sandbox_authority_request",
            "Skill manifest requires sandbox authority that the request did not request",
        )
    if _FILESYSTEM_ORDER[request.wants_filesystem_scope] > _FILESYSTEM_ORDER[manifest.filesystem_scope]:
        raise _fail(
            "unauthorized_filesystem_request",
            "requested filesystem scope exceeds the Skill manifest",
        )
    if _FILESYSTEM_ORDER[request.wants_filesystem_scope] < _FILESYSTEM_ORDER[manifest.filesystem_scope]:
        raise _fail(
            "missing_filesystem_authority_request",
            "Skill manifest requires a filesystem scope that the request did not request",
        )

    return SkillInvocationGrant.from_manifest(manifest)


# --------------------------------------------------------------------------
# Composition (cannot widen authority)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillComposition:
    """A planning-level union of member Skill authorities.

    The composition may expose the **union** of member authorities so a caller
    can plan multi-Skill work, but ``authorize_member`` still resolves the
    member's own manifest. A composition can therefore never widen any single
    Skill's authority.
    """

    skill_ids: tuple[str, ...]
    filesystem_scope: FilesystemScope
    network_required: bool
    provider_required: bool
    sandbox_required: bool
    side_effect_class: SideEffectClass
    approval_required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.skill_ids, tuple) or not self.skill_ids:
            raise _fail("invalid_skill_composition", "skill_ids must be a non-empty tuple")
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise _fail("invalid_skill_composition", "skill_ids must be unique")
        if not isinstance(self.filesystem_scope, FilesystemScope):
            raise _fail("invalid_skill_composition", "filesystem_scope must be FilesystemScope")
        if not isinstance(self.side_effect_class, SideEffectClass):
            raise _fail("invalid_skill_composition", "side_effect_class must be SideEffectClass")
        for name in ("network_required", "provider_required", "sandbox_required", "approval_required"):
            _require_bool(name, getattr(self, name))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "skill_ids": list(self.skill_ids),
            "filesystem_scope": self.filesystem_scope.value,
            "network_required": self.network_required,
            "provider_required": self.provider_required,
            "sandbox_required": self.sandbox_required,
            "side_effect_class": self.side_effect_class.value,
            "approval_required": self.approval_required,
        }


def compose_skills(
    registry: SkillRegistrySnapshot,
    skill_ids: Iterable[str],
) -> SkillComposition:
    """Compose Skills. Composition authority is the union of member manifests.

    Unknown members fail closed. The union is derived only from registered
    manifests — no caller-supplied authority field is accepted — so
    composition cannot widen any member beyond what that member declared.
    """

    if not isinstance(registry, SkillRegistrySnapshot):
        raise _fail("invalid_skill_registry_contract", "registry must be SkillRegistrySnapshot")
    if isinstance(skill_ids, (str, bytes)):
        raise _fail("invalid_skill_composition", "skill_ids must be an iterable of ids")

    ordered = tuple(skill_ids)
    if not ordered:
        raise _fail("invalid_skill_composition", "composition requires at least one Skill")
    if len(ordered) > MAX_REGISTERED_SKILLS:
        raise _fail("skill_registry_budget_exceeded", "composition exceeds the bounded Skill count")

    members = tuple(registry.get(skill_id) for skill_id in ordered)
    return SkillComposition(
        skill_ids=tuple(member.skill_id for member in members),
        filesystem_scope=_max_filesystem_scope(member.filesystem_scope for member in members),
        network_required=any(member.network_required for member in members),
        provider_required=any(member.provider_required for member in members),
        sandbox_required=any(member.sandbox_required for member in members),
        side_effect_class=_max_side_effect(member.side_effect_class for member in members),
        approval_required=any(member.approval_required for member in members),
    )


def authorize_composed_member(
    registry: SkillRegistrySnapshot,
    composition: SkillComposition,
    request: SkillInvocationRequest,
) -> SkillInvocationGrant:
    """Authorize one member invocation inside a composition.

    The composition's union authority is **not** applied to the member. Only
    the member's own manifest can authorize the request, so a wide composition
    can never widen a narrow member (``AUTHORITY_INHERITANCE=NO``).
    """

    if not isinstance(composition, SkillComposition):
        raise _fail("invalid_skill_composition", "composition must be SkillComposition")
    if request.skill_id not in composition.skill_ids:
        raise _fail(
            "unknown_skill",
            "requested Skill is not a member of this composition",
        )
    return authorize_invocation(registry, request)
