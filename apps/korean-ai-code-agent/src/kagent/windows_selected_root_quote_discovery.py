"""#3580 opt-in, exact-P01-approved, metadata-only quote file chooser.

This deliberately does NOT change WindowsSelectedRootFileRuntime's file READ
contract or its DIRECTORY_ENUMERATION_SUPPORTED=False. File listing is a
different canonical P01 tool invocation with a separately verified user
decision. It never opens file content, recursively scans, or grants READ.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
from typing import Any, Protocol

from padiem_ai_core.agent_approval import (
    AgentApprovalError, ApprovalOutcome, ContinuationStatus, resolve_approval_pause,
    tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

from .contracts import ContractError
from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform
from .local_agent_permissions import (
    DevicePermissionProfile, LocalCapability, LocalEnforcementResult,
    evaluate_local_permission,
)
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsFileAuthorityEvidence,
    WindowsFileAuthorityEvidencePort, UnconfiguredWindowsFileAuthorityEvidencePort,
    MAX_SELECTED_ROOT_FILE_BYTES,
)

DISCOVERY_TOOL_ID = "local.filesystem.list.quote-candidates"
MAX_DISCOVERY_CANDIDATES = 40
MAX_DISCOVERY_SCANNED_ENTRIES = 4096
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
_VALID_FILENAME = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f\x7f]{1,160}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_ALLOWED_EXT = frozenset({".xls", ".xlsx"})


def _ref(value: str, name: str) -> str:
    if type(value) is not str or not _SAFE_REF.fullmatch(value):
        raise ContractError(f"{name} must be a bounded canonical reference")
    return value


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ContractError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class QuoteDiscoveryRequest:
    action_id: str
    run_id: str
    device_id: str
    root_ref: str
    requested_at: datetime
    max_candidates: int = MAX_DISCOVERY_CANDIDATES
    name_contains: str = ""

    def __post_init__(self) -> None:
        for key in ("action_id", "run_id", "device_id", "root_ref"):
            _ref(getattr(self, key), key)
        object.__setattr__(self, "requested_at", _utc(self.requested_at, "requested_at"))
        if (type(self.max_candidates) is not int
                or not 1 <= self.max_candidates <= MAX_DISCOVERY_CANDIDATES):
            raise ContractError("candidate count must be bounded by 40")
        if (type(self.name_contains) is not str or len(self.name_contains) > 40
                or any(ord(ch) < 32 or ch in "/\\:*?\"<>|" for ch in self.name_contains)):
            raise ContractError("quote filename search must be a bounded safe substring")


def quote_discovery_fingerprint(request: QuoteDiscoveryRequest) -> str:
    if not isinstance(request, QuoteDiscoveryRequest):
        raise ContractError("canonical quote discovery request required")
    fields = {
        "action_id": request.action_id, "run_id": request.run_id,
        "device_id": request.device_id, "root_ref": request.root_ref,
        "requested_at": request.requested_at.isoformat(),
        "max_candidates": request.max_candidates,
        "name_contains": request.name_contains,
        "recursive": False, "extensions": ["xls", "xlsx"],
        "metadata_only": True, "max_scanned_entries": MAX_DISCOVERY_SCANNED_ENTRIES,
    }
    return sha256(json.dumps(
        fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def quote_discovery_tool_invocation(request: QuoteDiscoveryRequest) -> ToolInvocation:
    return ToolInvocation(
        tool_id=DISCOVERY_TOOL_ID,
        arguments={
            "action_id": request.action_id, "run_id": request.run_id,
            "device_id": request.device_id, "root_ref": request.root_ref,
            "request_fingerprint": quote_discovery_fingerprint(request),
            "max_candidates": request.max_candidates,
            "name_contains": request.name_contains,
            "metadata_only": True, "recursive": False, "read_content": False,
            "file_extensions": ["xls", "xlsx"], "whole_pc_scan": False,
        },
    )


@dataclass(frozen=True, slots=True)
class QuoteFileCandidate:
    filename: str
    size_bytes: int
    modified_at: str
    kind: str
    candidate_ref: str

    def public_projection(self) -> dict[str, Any]:
        return {
            "filename": self.filename, "size_bytes": self.size_bytes,
            "modified_at": self.modified_at, "kind": self.kind,
            "candidate_ref": self.candidate_ref, "raw_bytes": False,
        }


@dataclass(frozen=True, slots=True)
class QuoteDiscoveryResult:
    request: QuoteDiscoveryRequest
    candidates: tuple[QuoteFileCandidate, ...]
    matching_count: int
    limited: bool

    def public_projection(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-selected-root-quote-discovery.v1",
            "device_ref": self.request.device_id, "run_ref": self.request.run_id,
            "root_ref": self.request.root_ref,
            "candidates": [item.public_projection() for item in self.candidates],
            "matching_count": self.matching_count, "limited": self.limited,
            "metadata_only": True, "content_read": False,
            "read_authorized": False, "drive_upload_authorized": False,
            "requires_separate_p01_read": True,
        }

    def create_read_intent(
        self, *, candidate_ref: str, action_id: str, requested_at: datetime,
    ) -> LocalFileRequest:
        """Only a READ *request*, NEVER P01 permission or a file grant."""
        match = next((c for c in self.candidates if c.candidate_ref == candidate_ref), None)
        if match is None:
            raise ContractError("selected file is not in the approved candidate set")
        return LocalFileRequest(
            action_id=_ref(action_id, "action_id"),
            run_id=self.request.run_id,
            device_id=self.request.device_id,
            root_ref=self.request.root_ref,
            operation=LocalFileOperation.READ,
            path_relative=match.filename,
            requested_at=_utc(requested_at, "requested_at"),
        )


class P01ApprovedSelectedRootQuoteDiscovery:
    """Local-only metadata scan after exact canonical *listing* P01 approval."""

    def __init__(
        self, *, device: LocalAgentDeviceProfile,
        permission_profile: DevicePermissionProfile,
        evidence_port: WindowsFileAuthorityEvidencePort | None = None,
    ) -> None:
        if (not isinstance(device, LocalAgentDeviceProfile)
                or device.platform is not LocalAgentPlatform.WINDOWS
                or not isinstance(permission_profile, DevicePermissionProfile)
                or permission_profile.device_id != device.device_id
                or permission_profile.workspace_ref != device.workspace_ref):
            raise ContractError("selected Windows device and local policy required")
        self._device = device
        self._profile = permission_profile
        self._evidence = evidence_port or UnconfiguredWindowsFileAuthorityEvidencePort()
        self._used_fingerprints: set[str] = set()
        self._used_decisions: set[str] = set()
        self._lock = Lock()

    def discover(self, request: QuoteDiscoveryRequest, *, now: datetime) -> QuoteDiscoveryResult:
        if os.name != "nt":
            raise ContractError("local quote discovery is Windows-only")
        if not isinstance(request, QuoteDiscoveryRequest):
            raise ContractError("canonical quote discovery request required")
        now = _utc(now, "now")
        if request.device_id != self._device.device_id or request.requested_at > now:
            raise ContractError("quote discovery request device/time mismatch")
        selected = self._device.root(request.root_ref)
        fingerprint = quote_discovery_fingerprint(request)
        evidence = self._evidence.resolve(fingerprint)
        if not isinstance(evidence, WindowsFileAuthorityEvidence):
            raise ContractError("verified P01 listing evidence required")
        perm = evidence.permission_request
        if (evidence.request_fingerprint != fingerprint or evidence.expires_at <= now
                or perm.run_id != request.run_id or perm.device_id != request.device_id
                or perm.root_ref != request.root_ref
                or perm.target_ref != fingerprint
                or perm.capability is not LocalCapability.FILESYSTEM_READ):
            raise ContractError("P01 listing grant is not scoped to the exact request")
        local_decision = evaluate_local_permission(profile=self._profile, request=perm)
        if local_decision.result is LocalEnforcementResult.DENIED:
            raise ContractError("local selected-root read policy denied listing")
        pause, decision = evidence.approval_pause, evidence.approval_decision
        invocation = quote_discovery_tool_invocation(request)
        if (pause.run_id != request.run_id
                or pause.tool_id != invocation.tool_id
                or pause.invocation_sha256 != tool_invocation_digest(invocation)
                or LocalCapability.FILESYSTEM_READ.value not in pause.approval_scope
                or decision.outcome is not ApprovalOutcome.APPROVED):
            raise ContractError("explicit P01 listing approval mismatch or denial")
        try:
            approved = resolve_approval_pause(pause, decision, now=now)
        except AgentApprovalError:
            raise ContractError("P01 quote-list approval is not verified") from None
        if approved.status is not ContinuationStatus.RESUMABLE:
            raise ContractError("P01 quote-list approval has expired or been denied")
        with self._lock:
            if (fingerprint in self._used_fingerprints
                    or decision.decision_id in self._used_decisions):
                raise ContractError("P01 listing approval has already been consumed")
            self._used_fingerprints.add(fingerprint)
            self._used_decisions.add(decision.decision_id)

        root = Path(selected.windows_path)
        try:
            # Do not follow an operator-selected root symlink/junction.
            root_stat = root.lstat()
            if (root.is_symlink()
                    or getattr(root_stat, "st_file_attributes", 0) & _REPARSE_POINT
                    or not root.is_dir()):
                raise ContractError("selected-root directory is not a regular directory")
            matches: list[QuoteFileCandidate] = []
            scanned = 0
            with os.scandir(root) as entries:
                for item in entries:
                    scanned += 1
                    if scanned > MAX_DISCOVERY_SCANNED_ENTRIES:
                        raise ContractError("selected-root directory listing exceeds bounded scan")
                    name = item.name
                    if (request.name_contains.casefold() not in name.casefold()
                            or not _VALID_FILENAME.fullmatch(name) or name.startswith("~$")
                            or Path(name).suffix.lower() not in _ALLOWED_EXT
                            or item.is_symlink()):
                        continue
                    info = item.stat(follow_symlinks=False)
                    if (not stat.S_ISREG(info.st_mode)
                            or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT
                            or not 0 < info.st_size <= MAX_SELECTED_ROOT_FILE_BYTES):
                        continue
                    extension = Path(name).suffix.lower().lstrip(".")
                    modified = datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).isoformat()
                    token = sha256((
                        fingerprint + "|" + name + "|" + str(info.st_size)
                        + "|" + str(info.st_mtime_ns)
                    ).encode("utf-8")).hexdigest()
                    matches.append(QuoteFileCandidate(
                        filename=name, size_bytes=info.st_size,
                        modified_at=modified, kind=extension, candidate_ref=token,
                    ))
            matches.sort(key=lambda x: (x.filename.casefold(), x.candidate_ref))
            return QuoteDiscoveryResult(
                request=request,
                candidates=tuple(matches[:request.max_candidates]),
                matching_count=len(matches), limited=len(matches) > request.max_candidates,
            )
        except ContractError:
            raise
        except (OSError, ValueError):
            raise ContractError("selected-root quote metadata is not accessible") from None


PRODUCTION_QUOTE_DISCOVERY_COMPOSED = False
WHOLE_PC_QUOTE_SCAN_SUPPORTED = False
FILE_CONTENT_READ_FROM_DISCOVERY = False
