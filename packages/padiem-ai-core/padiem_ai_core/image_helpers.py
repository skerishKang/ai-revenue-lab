"""Deterministic, provider-free raster image helpers for the B54 image foundation."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

from PIL import Image, ImageOps

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_FRAMES = 1
SUPPORTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF"})
OUTPUT_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

class ImageContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

@dataclass(frozen=True, slots=True)
class ImageInspection:
    format: str
    width: int
    height: int
    frame_count: int
    orientation_present: bool
    orientation_value: int | None
    mode: str
    channels: int
    has_exif: bool
    has_gps: bool
    has_xmp: bool
    has_icc_profile: bool
    multi_frame: bool

    def safe_dict(self) -> dict[str, object]:
        return self.__dict__ if False else {
            "format": self.format, "width": self.width, "height": self.height,
            "frame_count": self.frame_count, "orientation_present": self.orientation_present,
            "orientation_value": self.orientation_value, "mode": self.mode,
            "channels": self.channels, "has_exif": self.has_exif, "has_gps": self.has_gps,
            "has_xmp": self.has_xmp, "has_icc_profile": self.has_icc_profile,
            "multi_frame": self.multi_frame,
        }

@dataclass(frozen=True, slots=True)
class ImageOutput:
    data: bytes
    format: str
    width: int
    height: int
    metadata_sanitized: bool = True

    def safe_dict(self) -> dict[str, object]:
        return {"format": self.format, "width": self.width, "height": self.height, "bytes": len(self.data), "metadata_sanitized": self.metadata_sanitized}

def _open(data: bytes) -> Image.Image:
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageContractError("image_bytes_invalid")
    try:
        probe = Image.open(BytesIO(data))
        if probe.format not in SUPPORTED_FORMATS:
            raise ImageContractError("image_format_unsupported")
        width, height = probe.size
        if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
            raise ImageContractError("image_dimensions_exceeded")
        frame_count = int(getattr(probe, "n_frames", 1))
        if frame_count < 1 or frame_count > 100:
            raise ImageContractError("image_frame_count_exceeded")
        probe.verify()
        image = Image.open(BytesIO(data))
        image.load()
        return image
    except ImageContractError:
        raise
    except Exception as exc:
        raise ImageContractError("image_decode_failed") from exc

def _metadata(image: Image.Image, data: bytes) -> tuple[bool, int | None, bool, bool, bool, bool]:
    try:
        exif = image.getexif()
        orientation = exif.get(274) if exif else None
        has_exif = bool(exif)
        has_gps = bool(exif.get_ifd(34853)) if exif else False
        info = image.info
        has_xmp = "xmp" in info or b"<x:xmpmeta" in data
        has_icc = "icc_profile" in info
        return has_exif, int(orientation) if orientation is not None else None, has_gps, has_xmp, has_icc, False
    except Exception as exc:
        raise ImageContractError("image_metadata_uncertain") from exc

def inspect_image(data: bytes) -> ImageInspection:
    image = _open(data)
    try:
        exif, orientation, gps, xmp, icc, _ = _metadata(image, data)
        channels = len(image.getbands())
        return ImageInspection(image.format or "UNKNOWN", image.width, image.height, int(getattr(image, "n_frames", 1)), exif, orientation, image.mode, channels, exif, gps, xmp, icc, int(getattr(image, "n_frames", 1)) > 1)
    finally:
        image.close()

def _single_frame(image: Image.Image) -> None:
    if int(getattr(image, "n_frames", 1)) != 1:
        raise ImageContractError("multi_frame_transform_refused")

def transform_image(data: bytes, *, output_format: Literal["PNG", "JPEG", "WEBP"], rotate: int = 0, crop: tuple[int, int, int, int] | None = None, resize: tuple[int, int] | None = None, normalize_orientation: bool = True, preserve_icc: bool = False) -> ImageOutput:
    if output_format not in OUTPUT_FORMATS:
        raise ImageContractError("output_format_unsupported")
    image = _open(data)
    try:
        _single_frame(image)
        if normalize_orientation:
            image = ImageOps.exif_transpose(image)
        if rotate % 360 != 0:
            image = image.rotate(rotate, expand=True, resample=Image.Resampling.BICUBIC)
        if crop is not None:
            if len(crop) != 4 or crop[2] <= crop[0] or crop[3] <= crop[1] or crop[0] < 0 or crop[1] < 0 or crop[2] > image.width or crop[3] > image.height:
                raise ImageContractError("crop_rectangle_invalid")
            image = image.crop(crop)
        if resize is not None:
            if len(resize) != 2 or resize[0] <= 0 or resize[1] <= 0 or resize[0] * resize[1] > MAX_IMAGE_PIXELS:
                raise ImageContractError("resize_target_invalid")
            image = image.resize(resize, resample=Image.Resampling.LANCZOS)
        if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_IMAGE_PIXELS:
            raise ImageContractError("output_dimensions_exceeded")
        clean = Image.new(image.mode, image.size)
        clean.putdata(list(image.getdata()))
        buffer = BytesIO()
        save_kwargs: dict[str, Any] = {}
        if preserve_icc and "icc_profile" in image.info:
            save_kwargs["icc_profile"] = image.info["icc_profile"]
        if output_format == "JPEG":
            if clean.mode not in ("RGB", "L"):
                clean = clean.convert("RGB")
            save_kwargs.update(quality=90, optimize=False, progressive=False)
        elif output_format == "WEBP":
            if clean.mode not in ("RGB", "RGBA"):
                clean = clean.convert("RGBA" if "A" in image.getbands() else "RGB")
            save_kwargs.update(quality=80, method=6)
        else:
            save_kwargs.update(optimize=False, compress_level=6)
        clean.save(buffer, format=output_format, **save_kwargs)
        result = buffer.getvalue()
        if len(result) > MAX_OUTPUT_BYTES:
            raise ImageContractError("output_bytes_exceeded")
        return ImageOutput(result, output_format, clean.width, clean.height)
    finally:
        image.close()
        if 'clean' in locals():
            clean.close()

def thumbnail_image(data: bytes, *, size: tuple[int, int] = (256, 256), output_format: Literal["PNG", "JPEG", "WEBP"] = "PNG") -> ImageOutput:
    if len(size) != 2 or size[0] <= 0 or size[1] <= 0:
        raise ImageContractError("thumbnail_size_invalid")
    image = _open(data)
    try:
        _single_frame(image)
        image.thumbnail(size, Image.Resampling.LANCZOS)
        return transform_image(data, output_format=output_format, resize=image.size)
    finally:
        image.close()
