"""#3037: thin KAgent image facade over the bounded Core image helper.

This module is a facade, not an authority and not a registry. It adds no second
image parser, no second decode path, no second Skill registry, no capability
invention and no new runtime dependency. Every raster fact and every encoded
byte comes from :mod:`padiem_ai_core.image_helpers`.

Composition order is fixed and is the same for every surface::

    caller filename + in-memory bytes
    -> kagent.file_intake_safety.inspect_file(filename, payload)   (gate, always first)
    -> intake decision must be SAFE_CANDIDATE and an image format
    -> padiem_ai_core.image_helpers.inspect_image / transform_image / thumbnail_image
    -> bounded Core error mapped to one stable facade code

The intake gate is not optional and is not reorderable: a payload that the gate
refuses never reaches the Core helper, so a format the gate does not recognize
can never be decoded by a facade. Only the two already-reserved capability
identities are reused (``image.inspect`` and ``image.transform``);
``image.ocr`` stays reserved and unimplemented.

Non-goals, unchanged: no OCR, no vision inference, no model or provider call,
no image-to-PDF, no HWPX, no EPS/Ghostscript, and no host filesystem read or
write. The helper's output is bytes in memory; the facade returns them as bytes
and never materializes a file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from padiem_ai_core.image_helpers import (
    IMAGE_ERROR_CODES,
    ImageContractError,
    ImageInspection,
    ImageOutput,
    inspect_image,
    thumbnail_image,
    transform_image,
)

from .claw_skill_registry import (
    CAPABILITY_IMAGE_INSPECT,
    CAPABILITY_IMAGE_TRANSFORM,
    RESERVED_CAPABILITY_IDS,
)
from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file

__all__ = [
    "FACADE_ERROR_CODES",
    "IMAGE_SKILL_CAPABILITY_IDS",
    "ImageInspectResult",
    "ImageSkillError",
    "image_inspect",
    "image_thumbnail",
    "image_transform",
]


#: Capability identities this facade serves. Reused from the existing reserved
#: set; the facade registers nothing and mints no new identity.
IMAGE_SKILL_CAPABILITY_IDS: frozenset[str] = frozenset(
    {CAPABILITY_IMAGE_INSPECT, CAPABILITY_IMAGE_TRANSFORM}
)

#: Formats the existing intake gate classifies as images. The Core helper makes
#: the same decision independently, so this is an early, cheap refusal rather
#: than the only gate.
_IMAGE_INTAKE_FORMATS = frozenset(
    {
        DetectedFormat.PNG,
        DetectedFormat.JPEG,
        DetectedFormat.WEBP,
        DetectedFormat.GIF,
    }
)

#: Stable facade codes. ``image_intake_refused`` is the only code this module
#: originates; everything else is a Core code surfaced unchanged, so a caller
#: can branch on the same value regardless of which layer failed closed.
FACADE_ERROR_CODES = frozenset({"image_intake_refused"}) | IMAGE_ERROR_CODES


class ImageSkillError(ValueError):
    """Fail-closed signal carrying one :data:`FACADE_ERROR_CODES` value."""

    def __init__(self, code: str) -> None:
        if code not in FACADE_ERROR_CODES:
            raise ValueError(f"unknown image facade error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ImageInspectResult:
    """Intake decision plus the Core inspection, both already bounded."""

    capability_id: str
    intake: FileIntakeResult
    inspection: ImageInspection

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. No payload bytes, no host paths."""

        return {
            "capability_id": self.capability_id,
            "intake": self.intake.safe_dict(),
            "image": self.inspection.safe_dict(),
        }


def _admit(filename: str, payload: bytes) -> FileIntakeResult:
    """Run the existing intake gate first. Always, for every surface.

    This is the composition point the #2824 gate requires: the gate decides
    admission, the Core helper decides raster facts. Neither replaces the other.
    """

    result = inspect_file(filename, payload)
    if result.detected_format not in _IMAGE_INTAKE_FORMATS or not result.safe_to_parse:
        raise ImageSkillError("image_intake_refused")
    return result


def image_inspect(payload: bytes, *, filename: str) -> ImageInspectResult:
    """Serve reserved ``image.inspect`` over in-memory bytes.

    ``filename`` is required, not optional: the gate's extension comparison and
    its decision record are part of the receipt, so a facade that ran without a
    name would drop evidence it is required to report.
    """

    if CAPABILITY_IMAGE_INSPECT not in RESERVED_CAPABILITY_IDS:  # pragma: no cover
        raise ImageSkillError("image_intake_refused")
    intake = _admit(filename, payload)
    try:
        inspection = inspect_image(payload)
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc
    return ImageInspectResult(
        capability_id=CAPABILITY_IMAGE_INSPECT,
        intake=intake,
        inspection=inspection,
    )


def image_transform(
    payload: bytes,
    *,
    filename: str,
    output_format: Literal["PNG", "JPEG", "WEBP"],
    rotate: int = 0,
    crop: tuple[int, int, int, int] | None = None,
    resize: tuple[int, int] | None = None,
    normalize_orientation: bool = True,
    preserve_icc: bool = False,
) -> ImageOutput:
    """Serve reserved ``image.transform`` over in-memory bytes."""

    if CAPABILITY_IMAGE_TRANSFORM not in RESERVED_CAPABILITY_IDS:  # pragma: no cover
        raise ImageSkillError("image_intake_refused")
    _admit(filename, payload)
    try:
        return transform_image(
            payload,
            output_format=output_format,
            rotate=rotate,
            crop=crop,
            resize=resize,
            normalize_orientation=normalize_orientation,
            preserve_icc=preserve_icc,
        )
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc


def image_thumbnail(
    payload: bytes,
    *,
    filename: str,
    size: tuple[int, int] = (256, 256),
    output_format: Literal["PNG", "JPEG", "WEBP"] = "PNG",
) -> ImageOutput:
    """Bounded preview, served through the same gate and the same Core helper."""

    _admit(filename, payload)
    try:
        return thumbnail_image(payload, size=size, output_format=output_format)
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc
