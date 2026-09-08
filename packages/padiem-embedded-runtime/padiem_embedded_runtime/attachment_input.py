"""Browser-safe attachment input presentation for IP-SIDECAR (S5).

File/image selection input arrives from untrusted host surfaces. This module
projects bounded selection metadata, deterministic upload-lifecycle states,
and opaque server-issued ``att_*`` references into public-safe views. It
never reads File/Blob bytes, never owns a DOM input, never mints refs,
never implements or calls an upload endpoint, and never performs browser
network or storage access. Byte admission, ``att_*`` minting, and
app/tenant/subject scope/expiry/media authority belong to Engine; product
acceptance policy belongs to product adapters.

Pipeline:

    untrusted host selection/lifecycle/ref input
      -> bounded allowlisted normalization
      -> deterministic presentation projection
      -> shared validation hints (never authority)
      -> host-safe empty/degraded/rejected states (never raises)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .errors import SidecarContractError

STATUS_READY = "ready"
STATUS_EMPTY = "empty"
STATUS_DEGRADED = "degraded"
PRESENTATION_STATUSES = frozenset({STATUS_READY, STATUS_EMPTY, STATUS_DEGRADED})

STATUS_PRESENTED = "presented"
STATUS_REJECTED = "rejected"

DROP_REASON_MALFORMED_ITEM = "MALFORMED_ITEM"
DROP_REASON_INVALID_FIELD = "INVALID_FIELD"
_DROP_REASONS = frozenset({DROP_REASON_MALFORMED_ITEM, DROP_REASON_INVALID_FIELD})

REJECT_REASON_MALFORMED_ITEM = "MALFORMED_ITEM"
REJECT_REASON_URL_SHAPED = "URL_SHAPED_REF"
REJECT_REASON_INVALID_GRAMMAR = "INVALID_REF_GRAMMAR"
_REJECT_REASONS = frozenset(
    {REJECT_REASON_MALFORMED_ITEM, REJECT_REASON_URL_SHAPED, REJECT_REASON_INVALID_GRAMMAR}
)

ALLOWED_SELECTION_FIELDS = frozenset({"name", "media_type", "byte_size"})

MAX_SELECTIONS = 8
MAX_NAME_CHARS = 120
MAX_MEDIA_TYPE_CHARS = 64

# Hard sanity bound for normalization; the shared platform image bound below
# is a validation hint only, never an authority decision.
MAX_BYTE_SIZE_HARD = 256 * 1024 * 1024
SHARED_IMAGE_BOUND_BYTES = 4 * 1024 * 1024
SHARED_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

HINT_SUPPORTED_MEDIA_TYPE = "SUPPORTED_MEDIA_TYPE"
HINT_UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_SHARED_MEDIA_TYPE"
HINT_OVER_SHARED_BOUND = "OVER_SHARED_IMAGE_BOUND"

LIFECYCLE_STATES = frozenset(
    {"idle", "selecting", "validating", "ready", "uploaded", "failed"}
)
LIFECYCLE_REASON_CODES = frozenset(
    {
        "USER_CANCELLED",
        "VALIDATION_REJECTED",
        "UPLOAD_REJECTED",
        "HOST_ABORTED",
        "INVALID_HOST_INPUT",
    }
)
ALLOWED_LIFECYCLE_FIELDS = frozenset({"state", "reason_code", "selection_count"})

# Grammar-compatible mirror of the merged Engine attachment authority
# (apps/padiem-ai-engine/app/attachment_authority.py). Presentation only:
# the sidecar never mints references.
_ATTACHMENT_REF_RE = re.compile(r"^att_[A-Za-z0-9_-]{16,120}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-()]{0,119}$")
_MEDIA_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}/[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_URL_SHAPE_RE = re.compile(r"://|/|\\")
_GUARDED_VALUE_RE = re.compile(
    r"secret|passwd|password|credential|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|bearer|authorization|"
    r"reasoning|chain[_-]of[_-]thought|tool[_-]?arg|stdout|stderr|traceback|"
    r"<\s*/?\s*[a-z]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SelectionDescriptor:
    """One normalized, bounded, public-safe selection descriptor."""

    name: str
    media_type: str
    byte_size: int

    def to_public_dict(self) -> dict[str, object]:
        return {"name": self.name, "media_type": self.media_type, "byte_size": self.byte_size}


@dataclass(frozen=True)
class PresentedSelection:
    """A selection with its deterministic label and shared validation hints."""

    label: str
    selection: SelectionDescriptor
    hints: tuple[str, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, object]:
        return {"label": self.label, **self.selection.to_public_dict(), "hints": list(self.hints)}


@dataclass(frozen=True)
class SelectionPresentation:
    """Immutable host-safe selection presentation result. Never carries raw input."""

    status: str
    selections: tuple[PresentedSelection, ...] = field(default_factory=tuple)
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in PRESENTATION_STATUSES:
            raise SidecarContractError("presentation status is not an allowlisted code")
        for reason in self.drop_reasons:
            if reason not in _DROP_REASONS:
                raise SidecarContractError("drop reason is not an allowlisted code")
        if self.dropped_count < 0:
            raise SidecarContractError("dropped_count must be >= 0")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selections": [s.to_public_dict() for s in self.selections],
            "dropped_count": self.dropped_count,
            "drop_reasons": list(self.drop_reasons),
        }


@dataclass(frozen=True)
class UploadLifecyclePresentation:
    """Immutable host-safe lifecycle view; malformed input degrades safely."""

    state: str
    reason_code: str = ""
    selection_count: int = 0
    degraded: bool = False

    def __post_init__(self) -> None:
        if self.state not in LIFECYCLE_STATES:
            raise SidecarContractError("lifecycle state is not an allowlisted state")
        if self.reason_code and self.reason_code not in LIFECYCLE_REASON_CODES:
            raise SidecarContractError("lifecycle reason code is not an allowlisted code")
        if not 0 <= self.selection_count <= MAX_SELECTIONS:
            raise SidecarContractError("selection_count exceeds the bound")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reason_code": self.reason_code,
            "selection_count": self.selection_count,
            "degraded": self.degraded,
        }


@dataclass(frozen=True)
class AttachmentRefPresentation:
    """Opaque display token; rejected refs carry no raw value."""

    status: str
    label: str = ""
    reason_code: str = ""

    def __post_init__(self) -> None:
        if self.status not in (STATUS_PRESENTED, STATUS_REJECTED):
            raise SidecarContractError("ref status is not an allowlisted code")
        if self.status == STATUS_PRESENTED and not _ATTACHMENT_REF_RE.fullmatch(self.label):
            raise SidecarContractError("presented ref label must be a canonical att_* ref")
        if self.status == STATUS_REJECTED:
            if self.label:
                raise SidecarContractError("rejected refs never carry a label")
            if self.reason_code not in _REJECT_REASONS:
                raise SidecarContractError("reject reason is not an allowlisted code")

    def to_public_dict(self) -> dict[str, object]:
        return {"status": self.status, "label": self.label, "reason_code": self.reason_code}


def _selection_hints(selection: SelectionDescriptor) -> tuple[str, ...]:
    hints: list[str] = []
    if selection.media_type in SHARED_IMAGE_MEDIA_TYPES:
        hints.append(HINT_SUPPORTED_MEDIA_TYPE)
        if selection.byte_size > SHARED_IMAGE_BOUND_BYTES:
            hints.append(HINT_OVER_SHARED_BOUND)
    else:
        hints.append(HINT_UNSUPPORTED_MEDIA_TYPE)
    return tuple(hints)


def normalize_selection(raw: Mapping[str, object]) -> SelectionDescriptor:
    """Validate one untrusted selection descriptor into a bounded view or fail closed.

    Only ``name``/``media_type``/``byte_size`` are accepted. Names that look
    like paths, URLs, markup, or secret/tool/terminal material are rejected;
    local paths and storage locators can never pass.
    """
    if not isinstance(raw, Mapping):
        raise SidecarContractError("selection must be a mapping")
    unknown = sorted(k for k in raw if k not in ALLOWED_SELECTION_FIELDS)
    if unknown:
        raise SidecarContractError(f"unknown selection fields: {', '.join(unknown)}")
    if "name" not in raw or "media_type" not in raw or "byte_size" not in raw:
        raise SidecarContractError("selection requires name, media_type, and byte_size")

    name = raw["name"]
    if not isinstance(name, str) or len(name) > MAX_NAME_CHARS:
        raise SidecarContractError("selection name must be bounded text")
    if _NAME_RE.fullmatch(name) is None or _GUARDED_VALUE_RE.search(name):
        raise SidecarContractError("selection name must be a plain bounded file name")

    media_type = raw["media_type"]
    if (
        not isinstance(media_type, str)
        or len(media_type) > MAX_MEDIA_TYPE_CHARS
        or _MEDIA_TYPE_RE.fullmatch(media_type) is None
    ):
        raise SidecarContractError("selection media_type must be a bounded type token")

    byte_size = raw["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise SidecarContractError("selection byte_size must be an integer")
    if not 0 <= byte_size <= MAX_BYTE_SIZE_HARD:
        raise SidecarContractError("selection byte_size exceeds the sanity bound")

    return SelectionDescriptor(name=name, media_type=media_type, byte_size=byte_size)


def present_selections(raw_items: Sequence[object]) -> SelectionPresentation:
    """Project untrusted selection input into a deterministic host-safe view.

    Malformed items are dropped (counted, reason-coded, values never
    retained). Surviving items keep browser selection order, are deduplicated
    on ``(name, media_type, byte_size)``, are capped at ``MAX_SELECTIONS``,
    and receive ``[1]..[n]`` labels plus shared validation hints. This
    function never raises for untrusted data.
    """
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        return SelectionPresentation(
            status=STATUS_DEGRADED,
            drop_reasons=(DROP_REASON_MALFORMED_ITEM,),
            dropped_count=1,
        )

    normalized: list[SelectionDescriptor] = []
    drop_reasons: set[str] = set()
    dropped = 0
    for raw in raw_items:
        if len(normalized) >= MAX_SELECTIONS:
            dropped += 1
            drop_reasons.add(DROP_REASON_MALFORMED_ITEM)
            continue
        try:
            normalized.append(normalize_selection(raw))
        except SidecarContractError:
            dropped += 1
            drop_reasons.add(
                DROP_REASON_INVALID_FIELD
                if isinstance(raw, Mapping)
                else DROP_REASON_MALFORMED_ITEM
            )

    seen: dict[tuple[str, str, int], SelectionDescriptor] = {}
    for selection in normalized:
        key = (selection.name, selection.media_type, selection.byte_size)
        if key not in seen:
            seen[key] = selection

    presented = tuple(
        PresentedSelection(
            label=f"[{position}]",
            selection=selection,
            hints=_selection_hints(selection),
        )
        for position, selection in enumerate(seen.values(), start=1)
    )

    if dropped:
        status = STATUS_DEGRADED
    elif not presented:
        status = STATUS_EMPTY
    else:
        status = STATUS_READY
    return SelectionPresentation(
        status=status,
        selections=presented,
        dropped_count=dropped,
        drop_reasons=tuple(sorted(drop_reasons)),
    )


def present_upload_lifecycle(raw: Mapping[str, object]) -> UploadLifecyclePresentation:
    """Project host-driven lifecycle input into a safe public view.

    Only allowlisted states and reason codes pass. Any malformed or
    over-privileged input degrades to a safe ``idle``/``INVALID_HOST_INPUT``
    view instead of raising, so the host primary journey is never broken.
    """
    fallback = UploadLifecyclePresentation(
        state="idle", reason_code="INVALID_HOST_INPUT", degraded=True
    )
    if not isinstance(raw, Mapping):
        return fallback
    if any(k not in ALLOWED_LIFECYCLE_FIELDS for k in raw):
        return fallback

    state = raw.get("state")
    if not isinstance(state, str) or state not in LIFECYCLE_STATES:
        return fallback

    reason_raw = raw.get("reason_code", "")
    if not isinstance(reason_raw, str) or (
        reason_raw and reason_raw not in LIFECYCLE_REASON_CODES
    ):
        return fallback
    if reason_raw and state != "failed":
        return fallback

    count_raw = raw.get("selection_count", 0)
    if isinstance(count_raw, bool) or not isinstance(count_raw, int):
        return fallback
    if not 0 <= count_raw <= MAX_SELECTIONS:
        return fallback

    return UploadLifecyclePresentation(
        state=state, reason_code=reason_raw, selection_count=count_raw, degraded=False
    )


def present_attachment_ref(raw_ref: object) -> AttachmentRefPresentation:
    """Project one server-issued ``att_*`` ref into a non-clickable display token.

    The sidecar only validates the canonical grammar accepted by the merged
    Engine attachment authority; it never mints refs. Anything URL-, path-, or
    storage-shaped is rejected without retaining the raw value.
    """
    if not isinstance(raw_ref, str):
        return AttachmentRefPresentation(
            status=STATUS_REJECTED, reason_code=REJECT_REASON_MALFORMED_ITEM
        )
    if _ATTACHMENT_REF_RE.fullmatch(raw_ref) is not None:
        return AttachmentRefPresentation(status=STATUS_PRESENTED, label=raw_ref)
    if _URL_SHAPE_RE.search(raw_ref) or raw_ref.lower().startswith(("http:", "https:", "data:")):
        return AttachmentRefPresentation(
            status=STATUS_REJECTED, reason_code=REJECT_REASON_URL_SHAPED
        )
    return AttachmentRefPresentation(
        status=STATUS_REJECTED, reason_code=REJECT_REASON_INVALID_GRAMMAR
    )
