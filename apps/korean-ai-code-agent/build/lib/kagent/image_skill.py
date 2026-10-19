"""#3037/#2828: thin KAgent image facade over the bounded Core image helper.

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

#2828 adds the third already-reserved identity, ``image.ocr``, on the same fixed
composition. OCR is **not** a new decode path and **not** a new authority::

    caller filename + in-memory bytes
    -> inspect_file(filename, payload)                    (existing #2824 gate, first)
    -> transform_image(payload, output_format="PNG")      (existing Core #3037,
                                                           normalized EXIF, single
                                                           frame, sanitized metadata)
    -> kagent.image_ocr_isolation.ocr_png_isolated(...)   (new kagent-local child)

The child never sees the caller's bytes: it receives only the canonical
single-frame PNG the existing Core transform produced, so the gate and the Core
transform remain the only intake of untrusted input
(``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0``). The child holds no image decoder of
its own (``SECOND_UNTRUSTED_IMAGE_DECODER=0``) — it re-validates that canonical
PNG from its signature, ``IHDR`` header and SHA-256, and PaddleOCR's own pipeline
decodes it inside the isolated process. The OCR runtime is resolved from two
explicit local model directories whose exact official manifests are verified on
the parent side before spawn and again in the child before import, with document
orientation, unwarping and textline orientation all disabled, and it runs in a
dedicated killable child process. This is a bounded, **non-Production** adapter:
the heavy PaddleOCR/PaddleX stack is deliberately absent from the product
manifests, so an unprovisioned environment gets the bounded
``image_ocr_runtime_missing`` refusal rather than a download.

Non-goals, unchanged: no vision inference, no document layout, no table or
formula parsing, no model or provider call, no existing-PDF parsing/merge/split,
no HWPX, no EPS/Ghostscript, and no host filesystem read or write by the facade.
The helper's output is bytes in memory; the facade returns them as bytes and
never materializes a file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from padiem_ai_core.image_helpers import (
    IMAGE_ERROR_CODES,
    ImageContractError,
    ImageInspection,
    ImageOutput,
    ImagePdfOutput,
    image_to_pdf as _core_image_to_pdf,
    inspect_image,
    thumbnail_image,
    transform_image,
)

from .claw_skill_registry import (
    CAPABILITY_IMAGE_INSPECT,
    CAPABILITY_IMAGE_OCR,
    CAPABILITY_IMAGE_TRANSFORM,
    RESERVED_CAPABILITY_IDS,
)
from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file
from .image_ocr_isolation import (
    DEFAULT_OCR_ISOLATION_POLICY,
    IsolatedOcrResult,
    OcrIsolationPolicy,
    ocr_png_isolated,
)

__all__ = [
    "FACADE_ERROR_CODES",
    "IMAGE_SKILL_CAPABILITY_IDS",
    "ImageInspectResult",
    "ImageOcrResult",
    "ImageSkillError",
    "image_inspect",
    "image_ocr",
    "image_thumbnail",
    "image_to_pdf",
    "image_transform",
]


#: Capability identities this facade serves. Reused from the existing reserved
#: set; the facade registers nothing and mints no new identity. ``image.ocr`` is
#: the third reserved image identity, served through the same gate and the same
#: Core transform as the other two.
IMAGE_SKILL_CAPABILITY_IDS: frozenset[str] = frozenset(
    {CAPABILITY_IMAGE_INSPECT, CAPABILITY_IMAGE_OCR, CAPABILITY_IMAGE_TRANSFORM}
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


@dataclass(frozen=True, slots=True)
class ImageOcrResult:
    """Intake decision, sanitized normalization and the bounded OCR outcome.

    The receipt is deliberately three-part so the provenance chain is visible
    end to end: the gate that admitted the bytes, the Core transform that
    reduced them to one sanitized upright PNG, and the isolated child that read
    text out of it. Only the normalized image's *facts* are projected — never
    its bytes — so a public note can be built from :meth:`safe_dict` without
    carrying an image.
    """

    capability_id: str
    intake: FileIntakeResult
    image: ImageOutput
    ocr: IsolatedOcrResult

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection.

        No payload bytes, no model directory, no child stderr, no host path.
        """

        return {
            "capability_id": self.capability_id,
            "intake": self.intake.safe_dict(),
            "image": self.image.safe_dict(),
            "ocr": self.ocr.safe_dict(),
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


def image_ocr(
    payload: bytes,
    *,
    filename: str,
    detector_dir: str,
    recognizer_dir: str,
    policy: OcrIsolationPolicy = DEFAULT_OCR_ISOLATION_POLICY,
) -> ImageOcrResult:
    """Serve reserved ``image.ocr`` over in-memory bytes.

    The order is the contract and is not configurable:

    1. the existing #2824 intake gate admits the payload;
    2. the existing Core #3037 ``transform_image`` normalizes it to a canonical
       sanitized single-frame PNG — EXIF orientation applied, metadata stripped,
       multi-frame input refused, ICC dropped; and
    3. the kagent-local OCR child reads that canonical PNG with document
       orientation, unwarping and textline orientation all disabled.

    The original untrusted bytes stop at step 2: the child is handed only the
    Core output, so ``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0`` holds by
    construction rather than by convention.

    ``filename`` is required for the same reason as in :func:`image_inspect`: the
    gate's decision record is part of the receipt.

    ``detector_dir`` and ``recognizer_dir`` are explicit local model
    directories. The runtime is never downloaded, and a directory that does not
    hold the exact pinned official manifests is the bounded
    ``image_ocr_runtime_missing`` refusal rather than a fallback. ``policy`` may
    only narrow the bounded lifecycle, never widen it.
    """

    if CAPABILITY_IMAGE_OCR not in RESERVED_CAPABILITY_IDS:  # pragma: no cover
        raise ImageSkillError("image_intake_refused")
    intake = _admit(filename, payload)
    try:
        normalized = transform_image(
            payload,
            output_format="PNG",
            # EXIF orientation is normalized here, once, by the existing Core
            # transform. The child is given an upright frame with every
            # orientation stage disabled, so no second geometry authority runs.
            normalize_orientation=True,
            # Metadata sanitation is the existing transform's job; carrying an
            # ICC profile into an OCR receipt would only add bytes the reader
            # never uses.
            preserve_icc=False,
        )
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc

    ocr = ocr_png_isolated(
        png=normalized.data,
        width=normalized.width,
        height=normalized.height,
        detector_dir=detector_dir,
        recognizer_dir=recognizer_dir,
        policy=policy,
    )
    return ImageOcrResult(
        capability_id=CAPABILITY_IMAGE_OCR,
        intake=intake,
        image=normalized,
        ocr=ocr,
    )


def image_to_pdf(items: tuple[tuple[str, bytes], ...]) -> ImagePdfOutput:
    """Emit a new PDF from admitted images without touching PDF authority.

    ``items`` is a filename/bytes sequence. The common file-intake gate runs
    for every item before the existing image helper emits the image-owned PDF
    artifact. This function never reads or transforms an existing PDF.
    """

    if not isinstance(items, tuple) or not items:
        raise ImageSkillError("image_bytes_invalid")
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ImageSkillError("image_bytes_invalid")
        filename, payload = item
        _admit(filename, payload)
    try:
        return _core_image_to_pdf(tuple(payload for _, payload in items))
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc
