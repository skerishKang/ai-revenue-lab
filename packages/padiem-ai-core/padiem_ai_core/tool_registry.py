"""Versioned canonical Tool registry layered over the existing ToolSpec contract.

This module does not introduce a second Tool specification format. Canonical
versioned Tool IDs map to the existing Core ``ToolSpec`` runtime contract. Actual
server-side handler registration and invocation remain exclusively in
``ToolRuntime``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable

from .contracts import ToolSpec


_TOOL_ID_RE = re.compile(
    r"^tool:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_REGISTERED_TOOLS = 1_024


class ToolRegistryError(ValueError):
    """Safe canonical Tool registry contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _SAFE_ID_RE.fullmatch(code):
            raise ValueError("tool registry error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _canonical_tool_id(value: str) -> str:
    if not isinstance(value, str) or not _TOOL_ID_RE.fullmatch(value):
        raise ToolRegistryError(
            "invalid_tool_registry_contract",
            "canonical_tool_id must match tool:<owner>:<id>@<major>",
        )
    return value


def _spec_fingerprint(spec: ToolSpec) -> str:
    if not isinstance(spec, ToolSpec):
        raise ToolRegistryError(
            "invalid_tool_registry_contract",
            "runtime_spec must be ToolSpec",
        )
    encoded = json.dumps(
        spec.to_public_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """Canonical versioned identity bound to one existing runtime ToolSpec."""

    canonical_tool_id: str
    runtime_spec: ToolSpec
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "canonical_tool_id",
            _canonical_tool_id(self.canonical_tool_id),
        )
        if not isinstance(self.runtime_spec, ToolSpec):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "runtime_spec must be ToolSpec",
            )
        expected = _spec_fingerprint(self.runtime_spec)
        if self.fingerprint != expected:
            raise ToolRegistryError(
                "tool_registry_fingerprint_mismatch",
                "registered Tool fingerprint does not match ToolSpec content",
            )

    @classmethod
    def from_spec(
        cls,
        *,
        canonical_tool_id: str,
        runtime_spec: ToolSpec,
    ) -> "RegisteredTool":
        return cls(
            canonical_tool_id=_canonical_tool_id(canonical_tool_id),
            runtime_spec=runtime_spec,
            fingerprint=_spec_fingerprint(runtime_spec),
        )

    @property
    def runtime_tool_id(self) -> str:
        return self.runtime_spec.id

    def to_public_dict(self) -> dict[str, object]:
        """Reuse ToolSpec public semantics while exposing canonical identity."""

        return {
            "canonical_tool_id": self.canonical_tool_id,
            "runtime_spec": self.runtime_spec.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class ToolRegistrySnapshot:
    """Immutable canonical registry; contains no handlers or credentials."""

    entries: tuple[RegisteredTool, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "entries must be a tuple",
            )
        if len(self.entries) > MAX_REGISTERED_TOOLS:
            raise ToolRegistryError(
                "tool_registry_budget_exceeded",
                "registry exceeds the bounded Tool count",
            )
        if any(not isinstance(entry, RegisteredTool) for entry in self.entries):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "entries must contain RegisteredTool values",
            )
        canonical_ids = tuple(entry.canonical_tool_id for entry in self.entries)
        runtime_ids = tuple(entry.runtime_tool_id for entry in self.entries)
        if len(set(canonical_ids)) != len(canonical_ids):
            raise ToolRegistryError(
                "duplicate_canonical_tool_id",
                "registry contains duplicate canonical Tool ids",
            )
        if len(set(runtime_ids)) != len(runtime_ids):
            raise ToolRegistryError(
                "duplicate_runtime_tool_id",
                "one runtime ToolSpec id cannot represent multiple canonical Tools",
            )
        if canonical_ids != tuple(sorted(canonical_ids)):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "registry entries must be sorted by canonical Tool id",
            )

    @classmethod
    def from_entries(
        cls,
        entries: Iterable[RegisteredTool],
    ) -> "ToolRegistrySnapshot":
        if isinstance(entries, (str, bytes)):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "entries must be an iterable of RegisteredTool values",
            )
        values = tuple(entries)
        if any(not isinstance(entry, RegisteredTool) for entry in values):
            raise ToolRegistryError(
                "invalid_tool_registry_contract",
                "entries must contain RegisteredTool values",
            )
        return cls(entries=tuple(sorted(values, key=lambda entry: entry.canonical_tool_id)))

    @property
    def canonical_tool_ids(self) -> tuple[str, ...]:
        return tuple(entry.canonical_tool_id for entry in self.entries)

    def get(self, canonical_tool_id: str) -> RegisteredTool:
        target = _canonical_tool_id(canonical_tool_id)
        for entry in self.entries:
            if entry.canonical_tool_id == target:
                return entry
        raise ToolRegistryError(
            "tool_not_registered",
            "requested canonical Tool is not present in the registry",
        )

    def with_tool(
        self,
        *,
        canonical_tool_id: str,
        runtime_spec: ToolSpec,
    ) -> "ToolRegistrySnapshot":
        candidate = RegisteredTool.from_spec(
            canonical_tool_id=canonical_tool_id,
            runtime_spec=runtime_spec,
        )
        by_canonical = {entry.canonical_tool_id: entry for entry in self.entries}
        existing = by_canonical.get(candidate.canonical_tool_id)
        if existing is not None:
            if (
                existing.fingerprint == candidate.fingerprint
                and existing.runtime_tool_id == candidate.runtime_tool_id
            ):
                return self
            raise ToolRegistryError(
                "tool_registry_version_conflict",
                "canonical Tool id is already bound to different ToolSpec content",
            )
        if any(
            entry.runtime_tool_id == candidate.runtime_tool_id
            for entry in self.entries
        ):
            raise ToolRegistryError(
                "duplicate_runtime_tool_id",
                "runtime ToolSpec id is already bound to another canonical Tool",
            )
        if len(self.entries) >= MAX_REGISTERED_TOOLS:
            raise ToolRegistryError(
                "tool_registry_budget_exceeded",
                "registry exceeds the bounded Tool count",
            )
        by_canonical[candidate.canonical_tool_id] = candidate
        return ToolRegistrySnapshot(
            entries=tuple(
                sorted(by_canonical.values(), key=lambda entry: entry.canonical_tool_id)
            )
        )
