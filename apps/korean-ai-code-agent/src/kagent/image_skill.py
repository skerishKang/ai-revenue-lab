"""KAgent facade for the bounded deterministic image foundation (#3037)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from padiem_ai_core.image_helpers import (
    ImageContractError,
    ImageInspection,
    ImageOutput,
    inspect_image,
    thumbnail_image,
    transform_image,
)
from .file_intake_safety import DetectedFormat, FileIntakeResult, inspect_file

__all__ = ["ImageSkillError", "ImageInspectResult", "image_inspect", "image_transform", "image_thumbnail"]

class ImageSkillError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

@dataclass(frozen=True, slots=True)
class ImageInspectResult:
    intake: FileIntakeResult
    inspection: ImageInspection

    def safe_dict(self) -> dict[str, object]:
        return {"intake": self.intake.safe_dict(), "image": self.inspection.safe_dict()}

def _admit(data: bytes, filename: str | None) -> FileIntakeResult:
    result = inspect_file(filename or "image.bin", data)
    if result.detected_format not in {DetectedFormat.PNG, DetectedFormat.JPEG, DetectedFormat.WEBP, DetectedFormat.GIF} or not result.safe_to_parse:
        raise ImageSkillError("image_intake_refused")
    return result

def image_inspect(data: bytes, *, filename: str | None = None) -> ImageInspectResult:
    try:
        intake = _admit(data, filename)
        return ImageInspectResult(intake, inspect_image(data))
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc

def image_transform(data: bytes, *, output_format: Literal["PNG", "JPEG", "WEBP"], filename: str | None = None, rotate: int = 0, crop: tuple[int, int, int, int] | None = None, resize: tuple[int, int] | None = None, normalize_orientation: bool = True, preserve_icc: bool = False) -> ImageOutput:
    _admit(data, filename)
    try:
        return transform_image(data, output_format=output_format, rotate=rotate, crop=crop, resize=resize, normalize_orientation=normalize_orientation, preserve_icc=preserve_icc)
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc

def image_thumbnail(data: bytes, *, filename: str | None = None, size: tuple[int, int] = (256, 256), output_format: Literal["PNG", "JPEG", "WEBP"] = "PNG") -> ImageOutput:
    _admit(data, filename)
    try:
        return thumbnail_image(data, size=size, output_format=output_format)
    except ImageContractError as exc:
        raise ImageSkillError(exc.code) from exc
