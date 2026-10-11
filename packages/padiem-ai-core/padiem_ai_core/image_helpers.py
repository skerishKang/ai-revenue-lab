"""Bounded, deterministic, provider-free in-memory raster image helpers.

This module is a product-neutral *helper*, not a Skill, not a registry and not
a document pipeline. It exists so that a caller with raw image bytes already in
memory can get a small, auditable set of raster answers without any authority
being widened:

* :func:`inspect_image` reports bounded static-frame facts about the payload.
* :func:`transform_image` performs orientation normalization, rotation, crop,
  resize, format conversion and metadata sanitation.
* :func:`sanitize_metadata` re-encodes with metadata removed and no geometry
  change.
* :func:`thumbnail_image` produces a bounded preview that fits inside a box.

Hard boundaries
---------------
Everything is in memory. There is no filesystem read or write, no temporary
file, no subprocess, no external helper executable, no network call, no model
or provider call, no OCR and no vision inference. EPS is not supported, so
Ghostscript is never a decode path. ``Image.show`` and ``ImageGrab`` are never
called. ``ImageFile.LOAD_TRUNCATED_IMAGES`` is never enabled, so truncated
input fails closed.

Every bound is checked *before* the work that could exhaust memory, and every
output is size-checked before it is returned. Failure is always a stable
:data:`IMAGE_ERROR_CODES` string, never a raw Pillow exception and never a
partially decoded object.

Determinism
-----------
Transform order is fixed: orientation normalization, rotation, crop, resize.
The resampling filters, the JPEG quality and the WEBP method are constants
below, so the same input bytes and the same arguments always produce the same
output bytes on a given Pillow build.

Alpha and colour handling is explicit rather than incidental:

* PNG and WEBP keep alpha. An alpha-bearing source is normalized to ``RGBA``;
  an opaque source becomes ``RGB``.
* JPEG has no alpha channel, so an alpha-bearing source is composited onto the
  fixed :data:`JPEG_MATTE_RGB` matte instead of having its alpha silently
  dropped or blackened by the encoder.
* A palette source with transparency is resolved to ``RGBA`` so the
  transparency is preserved rather than lost with the palette.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

from PIL import Image, ImageFile, ImageOps

__all__ = [
    "IMAGE_ERROR_CODES",
    "IMAGE_OUTPUT_FORMATS",
    "IMAGE_SUPPORTED_FORMATS",
    "JPEG_MATTE_RGB",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_PIXELS",
    "MAX_INSPECT_FRAMES",
    "MAX_OUTPUT_BYTES",
    "MAX_PDF_IMAGES",
    "MAX_PDF_INPUT_BYTES",
    "MAX_PDF_OUTPUT_BYTES",
    "MAX_PDF_TOTAL_PIXELS",
    "PDF_BACKGROUND_RGB",
    "PDF_DPI",
    "ImageContractError",
    "ImageInspection",
    "ImageOutput",
    "ImagePdfOutput",
    "PdfPageProvenance",
    "image_to_pdf",
    "inspect_image",
    "sanitize_metadata",
    "thumbnail_image",
    "transform_image",
]


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------

#: Largest accepted input payload, in bytes.
MAX_IMAGE_BYTES = 16 * 1024 * 1024

#: Largest accepted ``width * height`` for input and output.
MAX_IMAGE_PIXELS = 40_000_000

#: Largest encoded output payload, in bytes.
MAX_OUTPUT_BYTES = 8 * 1024 * 1024

#: Bounds for image -> new PDF/page artifacts. These are artifact-level caps;
#: each image still goes through the same decoder and per-image bounds above.
MAX_PDF_IMAGES = 32
MAX_PDF_INPUT_BYTES = 16 * 1024 * 1024
MAX_PDF_TOTAL_PIXELS = 40_000_000
MAX_PDF_OUTPUT_BYTES = 8 * 1024 * 1024

#: PDF pages use the normalized image pixels at a fixed 150 DPI. This keeps page
#: dimensions deterministic without inventing a user-specific paper size.
PDF_DPI = 150

#: Transparent images are flattened to explicit white before PDF emission.
PDF_BACKGROUND_RGB = (255, 255, 255)

#: Hard bound used while counting frames during inspection. A payload with more
#: frames than this is refused rather than counted, so inspection cannot be
#: turned into an unbounded seek loop by a crafted container.
MAX_INSPECT_FRAMES = 64

#: Input formats this helper will decode.
IMAGE_SUPPORTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF"})

#: Output formats this helper will encode.
IMAGE_OUTPUT_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

#: Fixed matte composited under alpha before a JPEG encode. JPEG cannot carry
#: alpha, and a deterministic matte is strictly better than a codec-dependent
#: black or a silently discarded alpha channel.
JPEG_MATTE_RGB = (255, 255, 255)

#: Deterministic encoder settings. Changing any of these changes output bytes.
_JPEG_QUALITY = 90
_JPEG_SUBSAMPLING = 0
_WEBP_QUALITY = 80
_WEBP_METHOD = 6
_PNG_COMPRESS_LEVEL = 6
_RESAMPLE = Image.Resampling.LANCZOS
_ROTATE_RESAMPLE = Image.Resampling.BICUBIC

# EXIF tag numbers used by this module. Kept as literals so the module does not
# depend on Pillow's tag enum keeping the same import shape.
_EXIF_TAG_ORIENTATION = 274
_EXIF_IFD_GPS = 34853

# XMP may live in a container chunk or as raw packet bytes in the payload.
_XMP_MARKERS = (b"<x:xmpmeta", b"http://ns.adobe.com/xap/1.0/", b"<?xpacket")

#: Every failure this module can report. Callers may branch on these strings;
#: nothing else is part of the contract.
IMAGE_ERROR_CODES = frozenset(
    {
        "image_bytes_invalid",
        "image_bytes_oversized",
        "image_format_unsupported",
        "image_pixels_exceeded",
        "image_decompression_bomb",
        "image_decode_failed",
        "image_frame_count_exceeded",
        "image_multiframe_refused",
        "image_metadata_unreadable",
        "image_crop_invalid",
        "image_resize_invalid",
        "image_rotate_invalid",
        "image_output_format_unsupported",
        "image_output_pixels_exceeded",
        "image_output_bytes_exceeded",
        "image_pdf_count_exceeded",
        "image_pdf_input_bytes_exceeded",
        "image_pdf_total_pixels_exceeded",
        "image_pdf_output_bytes_exceeded",
    }
)

# Pillow raises DecompressionBombError above the error threshold and warns
# with DecompressionBombWarning above the lower threshold. Both collapse to one
# stable code so a caller never depends on which threshold the build used.
_BOMB_ERRORS = (Image.DecompressionBombError, Image.DecompressionBombWarning)

# Info keys that carry free text rather than pixel data.
_TEXT_INFO_KEYS = ("text", "XML:com.adobe.xctp", "Description", "Comment")


class ImageContractError(ValueError):
    """Fail-closed signal carrying one :data:`IMAGE_ERROR_CODES` value."""

    def __init__(self, code: str) -> None:
        if code not in IMAGE_ERROR_CODES:
            raise ValueError(f"unknown image error code: {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ImageInspection:
    """Bounded, payload-free description of a payload's first static frame.

    Every field is derived from the decoded first frame. ``frame_count`` is the
    container's declared frame total, bounded by :data:`MAX_INSPECT_FRAMES`;
    ``multi_frame`` is the caller's signal that a single-frame transform must
    not be attempted.
    """

    format: str
    width: int
    height: int
    mode: str
    channels: int
    frame_count: int
    multi_frame: bool
    has_exif: bool
    has_gps: bool
    orientation: int | None
    has_xmp: bool
    has_icc_profile: bool
    has_text_metadata: bool

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection with no payload bytes and no host paths."""

        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "mode": self.mode,
            "channels": self.channels,
            "frame_count": self.frame_count,
            "multi_frame": self.multi_frame,
            "has_exif": self.has_exif,
            "has_gps": self.has_gps,
            "orientation": self.orientation,
            "has_xmp": self.has_xmp,
            "has_icc_profile": self.has_icc_profile,
            "has_text_metadata": self.has_text_metadata,
        }


@dataclass(frozen=True, slots=True)
class ImageOutput:
    """Encoded result. ``data`` is the only payload-bearing field."""

    data: bytes
    format: str
    width: int
    height: int
    icc_profile_preserved: bool

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. Never contains the encoded bytes."""

        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "size_bytes": len(self.data),
            "icc_profile_preserved": self.icc_profile_preserved,
        }


@dataclass(frozen=True, slots=True)
class PdfPageProvenance:
    """Bounded source receipt for one emitted PDF page."""

    page_number: int
    source_image_index: int
    source_format: str
    source_dimensions: tuple[int, int]
    normalized_orientation: bool

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "source_image_index": self.source_image_index,
            "source_format": self.source_format,
            "source_dimensions": list(self.source_dimensions),
            "normalized_orientation": self.normalized_orientation,
        }


@dataclass(frozen=True, slots=True)
class ImagePdfOutput:
    """A new PDF artifact plus bounded per-page source provenance."""

    data: bytes
    page_count: int
    pages: tuple[PdfPageProvenance, ...]

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def safe_dict(self) -> dict[str, object]:
        return {
            "page_count": self.page_count,
            "size_bytes": len(self.data),
            "pages": [page.safe_dict() for page in self.pages],
        }


# --------------------------------------------------------------------------
# Decode
# --------------------------------------------------------------------------


def _validate_payload(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ImageContractError("image_bytes_invalid")
    payload = bytes(data)
    if not payload:
        raise ImageContractError("image_bytes_invalid")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ImageContractError("image_bytes_oversized")
    return payload


def _check_pixels(width: int, height: int, *, output: bool = False) -> None:
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ImageContractError(
            "image_output_pixels_exceeded" if output else "image_pixels_exceeded"
        )


def _close(image: Image.Image | None) -> None:
    """Release the underlying decoder buffer. Never raises."""

    if image is None:
        return
    try:
        image.close()
    except Exception:  # pragma: no cover - close is not expected to fail
        pass


def _frame_count(image: Image.Image) -> int:
    """Bounded frame count. Never seeks past the cap."""

    try:
        declared = int(getattr(image, "n_frames", 1) or 1)
    except Exception as exc:
        raise ImageContractError("image_decode_failed") from exc
    if declared < 1:
        raise ImageContractError("image_decode_failed")
    if declared > MAX_INSPECT_FRAMES:
        raise ImageContractError("image_frame_count_exceeded")
    return declared


def _open_first_frame(payload: bytes) -> Image.Image:
    """Decode the first frame, or raise one stable fail-closed code.

    ``ImageFile.LOAD_TRUNCATED_IMAGES`` is asserted off here rather than
    globally mutated: truncated input must fail closed, and flipping a global
    Pillow flag to make it succeed would be an authority widening.
    """

    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ImageContractError("image_decode_failed")

    image: Image.Image | None = None
    try:
        image = Image.open(BytesIO(payload))
        if image.format not in IMAGE_SUPPORTED_FORMATS:
            raise ImageContractError("image_format_unsupported")
        _check_pixels(*image.size)
        _frame_count(image)
        image.load()
    except ImageContractError:
        _close(image)
        raise
    except _BOMB_ERRORS as exc:
        _close(image)
        raise ImageContractError("image_decompression_bomb") from exc
    except Exception as exc:
        # UnidentifiedImageError, truncated streams, broken C-level data and
        # every other Pillow decode failure collapse to one code.
        _close(image)
        raise ImageContractError("image_decode_failed") from exc
    return image


def _require_single_frame(image: Image.Image) -> None:
    if _frame_count(image) != 1:
        raise ImageContractError("image_multiframe_refused")


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MetadataView:
    has_exif: bool
    has_gps: bool
    orientation: int | None
    has_xmp: bool
    has_icc_profile: bool
    has_text_metadata: bool


def _read_metadata(image: Image.Image, payload: bytes) -> _MetadataView:
    """Read metadata presence, failing closed if it cannot be parsed.

    A metadata parse failure is never treated as "no metadata": a caller that
    cannot prove the metadata is empty must not be handed a
    sanitized-looking answer.
    """

    try:
        exif = image.getexif()
        has_exif = bool(exif)
        orientation: int | None = None
        has_gps = False
        if has_exif:
            raw_orientation = exif.get(_EXIF_TAG_ORIENTATION)
            if raw_orientation is not None:
                orientation = int(raw_orientation)
            has_gps = bool(exif.get_ifd(_EXIF_IFD_GPS))

        info = image.info
        return _MetadataView(
            has_exif=has_exif,
            has_gps=has_gps,
            orientation=orientation,
            has_xmp=(
                any(key in info for key in ("xmp", "XML:com.adobe.xmp"))
                or any(marker in payload for marker in _XMP_MARKERS)
            ),
            has_icc_profile="icc_profile" in info,
            has_text_metadata=any(key in info for key in _TEXT_INFO_KEYS),
        )
    except ImageContractError:
        raise
    except Exception as exc:
        raise ImageContractError("image_metadata_unreadable") from exc


def _bounded_icc(image: Image.Image, preserve_icc: bool) -> bytes | None:
    """Return the source ICC profile only when explicitly requested and valid.

    An absent or non-bytes profile simply means "no profile to preserve"; a
    profile that cannot be read at all is a metadata parse failure.
    """

    if not preserve_icc:
        return None
    try:
        profile = image.info.get("icc_profile")
    except Exception as exc:
        raise ImageContractError("image_metadata_unreadable") from exc
    if profile is None:
        return None
    if not isinstance(profile, (bytes, bytearray)) or not profile:
        return None
    return bytes(profile)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def _validate_crop(
    crop: tuple[int, int, int, int], width: int, height: int
) -> tuple[int, int, int, int]:
    if len(crop) != 4 or not all(isinstance(v, int) for v in crop):
        raise ImageContractError("image_crop_invalid")
    left, top, right, bottom = crop
    if left < 0 or top < 0 or right > width or bottom > height:
        raise ImageContractError("image_crop_invalid")
    if right <= left or bottom <= top:
        raise ImageContractError("image_crop_invalid")
    return crop


def _validate_resize(resize: tuple[int, int]) -> tuple[int, int]:
    if len(resize) != 2 or not all(isinstance(v, int) for v in resize):
        raise ImageContractError("image_resize_invalid")
    if resize[0] <= 0 or resize[1] <= 0:
        raise ImageContractError("image_resize_invalid")
    if resize[0] * resize[1] > MAX_IMAGE_PIXELS:
        raise ImageContractError("image_output_pixels_exceeded")
    return resize


def _fit_within(width: int, height: int, box: tuple[int, int]) -> tuple[int, int]:
    """Largest size that fits ``box`` while preserving aspect ratio.

    Only ever shrinks. Rounding down (not to nearest) guarantees the result
    never exceeds the box on either axis for any input ratio.
    """

    box_width, box_height = box
    scale = min(box_width / width, box_height / height, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale))


# --------------------------------------------------------------------------
# Colour normalization
# --------------------------------------------------------------------------


def _has_alpha(image: Image.Image) -> bool:
    if "A" in image.getbands():
        return True
    # A palette image can carry per-entry transparency that is not a band.
    return image.mode in {"P", "PA"} and "transparency" in image.info


def _to_output_mode(image: Image.Image, output_format: str) -> Image.Image:
    """Normalize the pixel representation so the encode is deterministic.

    Returns a new image in a mode the target encoder accepts. Modes that carry
    no meaningful RGB values for the target (``CMYK``, ``F``, ``I``) are
    converted explicitly rather than being handed to the encoder to
    reinterpret.
    """

    if output_format == "JPEG":
        if image.mode == "RGB":
            return image
        if image.mode == "L":
            return image
        if image.mode == "CMYK":
            return image.convert("RGB")
        if _has_alpha(image):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, JPEG_MATTE_RGB)
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            rgba.close()
            return flattened
        return image.convert("RGB")

    # PNG and WEBP keep alpha.
    if _has_alpha(image) or image.mode in {"P", "PA"}:
        return image.convert("RGBA")
    if image.mode in {"RGB", "RGBA", "L"}:
        return image
    return image.convert("RGB")


# --------------------------------------------------------------------------
# Encode
# --------------------------------------------------------------------------


def _encoder_kwargs(output_format: str, icc_profile: bytes | None) -> dict[str, Any]:
    if output_format == "JPEG":
        kwargs: dict[str, Any] = {
            "quality": _JPEG_QUALITY,
            "optimize": False,
            "progressive": False,
            "subsampling": _JPEG_SUBSAMPLING,
        }
    elif output_format == "WEBP":
        kwargs = {"quality": _WEBP_QUALITY, "method": _WEBP_METHOD, "lossless": False}
    else:
        kwargs = {"optimize": False, "compress_level": _PNG_COMPRESS_LEVEL}

    if icc_profile is not None:
        kwargs["icc_profile"] = icc_profile
    return kwargs


def _encode(image: Image.Image, output_format: str, icc_profile: bytes | None) -> bytes:
    """Encode with metadata removed.

    ``save`` is called with no ``exif``, ``xmp``, ``PNGinfo`` or text keys, so
    every encoder writes pixels only. ``icc_profile`` is the single permitted
    exception and is passed explicitly.
    """

    buffer = BytesIO()
    try:
        image.save(
            buffer, format=output_format, **_encoder_kwargs(output_format, icc_profile)
        )
    except Exception as exc:
        raise ImageContractError("image_decode_failed") from exc
    encoded = buffer.getvalue()
    if not encoded:
        raise ImageContractError("image_decode_failed")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ImageContractError("image_output_bytes_exceeded")
    return encoded


# --------------------------------------------------------------------------
# Public surface
# --------------------------------------------------------------------------


def inspect_image(data: bytes) -> ImageInspection:
    """Report bounded static-frame facts about ``data``.

    Inspection is allowed to *report* a multi-frame container, bounded by
    :data:`MAX_INSPECT_FRAMES`; only transforms refuse one. Every refusal is an
    :class:`ImageContractError` with a code from :data:`IMAGE_ERROR_CODES`.
    """

    payload = _validate_payload(data)
    image = _open_first_frame(payload)
    try:
        metadata = _read_metadata(image, payload)
        frame_count = _frame_count(image)
        return ImageInspection(
            format=image.format or "UNKNOWN",
            width=image.width,
            height=image.height,
            mode=image.mode,
            channels=len(image.getbands()),
            frame_count=frame_count,
            multi_frame=frame_count > 1,
            has_exif=metadata.has_exif,
            has_gps=metadata.has_gps,
            orientation=metadata.orientation,
            has_xmp=metadata.has_xmp,
            has_icc_profile=metadata.has_icc_profile,
            has_text_metadata=metadata.has_text_metadata,
        )
    finally:
        _close(image)


def sanitize_metadata(
    data: bytes,
    *,
    output_format: Literal["PNG", "JPEG", "WEBP"] = "PNG",
    preserve_icc: bool = False,
) -> ImageOutput:
    """Re-encode ``data`` with EXIF, GPS, XMP and text metadata removed.

    This is :func:`transform_image` with no geometry change, exposed
    separately because "strip the metadata" is a real caller need.
    ``preserve_icc`` copies only the source ICC profile and still removes every
    other metadata class.
    """

    return transform_image(
        data,
        output_format=output_format,
        normalize_orientation=False,
        preserve_icc=preserve_icc,
    )


def transform_image(
    data: bytes,
    *,
    output_format: Literal["PNG", "JPEG", "WEBP"],
    rotate: int = 0,
    crop: tuple[int, int, int, int] | None = None,
    resize: tuple[int, int] | None = None,
    normalize_orientation: bool = True,
    preserve_icc: bool = False,
) -> ImageOutput:
    """Apply the fixed transform pipeline and return bounded encoded bytes.

    Order is fixed and independent of argument order: EXIF orientation
    normalization, rotation, crop, resize. Multi-frame input is refused, so a
    caller can never silently receive the first frame of an animation.
    """

    if output_format not in IMAGE_OUTPUT_FORMATS:
        raise ImageContractError("image_output_format_unsupported")
    if not isinstance(rotate, int) or isinstance(rotate, bool):
        raise ImageContractError("image_rotate_invalid")

    payload = _validate_payload(data)
    source = _open_first_frame(payload)
    working: Image.Image | None = None
    encoded_stage: Image.Image | None = None
    try:
        _require_single_frame(source)

        icc_profile = _bounded_icc(source, preserve_icc)
        orientation = (
            _read_metadata(source, payload).orientation
            if normalize_orientation
            else None
        )

        # ``copy`` detaches the working image from the source decoder, so the
        # source handle can be released before the geometry work runs.
        working = source.copy()
        _close(source)
        source = None  # type: ignore[assignment]

        if normalize_orientation and orientation not in (None, 1):
            transposed = ImageOps.exif_transpose(working)
            if transposed is not working:
                _close(working)
                working = transposed

        if rotate % 360:
            rotated = working.rotate(rotate, expand=True, resample=_ROTATE_RESAMPLE)
            _close(working)
            working = rotated

        if crop is not None:
            _validate_crop(crop, working.width, working.height)
            cropped = working.crop(crop)
            _close(working)
            working = cropped

        if resize is not None:
            target = _validate_resize(resize)
            if working.size != target:
                resampled = working.resize(target, resample=_RESAMPLE)
                _close(working)
                working = resampled

        _check_pixels(working.width, working.height, output=True)

        # Mode normalization runs first because it is what resolves a palette
        # image's per-entry transparency into a real alpha band.
        encoded_stage = _to_output_mode(working, output_format)

        # ``copy``/``convert`` carry the decoder's ``info`` dict forward, and the
        # PNG encoder in particular falls back to ``im.info["icc_profile"]`` when
        # the caller passes no explicit profile. Dropping the dict is therefore
        # what actually enforces the sanitation contract; the only profile that
        # may reach an encoder is the one passed explicitly below.
        encoded_stage.info.clear()

        encoded = _encode(encoded_stage, output_format, icc_profile)
        return ImageOutput(
            data=encoded,
            format=output_format,
            width=encoded_stage.width,
            height=encoded_stage.height,
            icc_profile_preserved=icc_profile is not None,
        )
    finally:
        _close(source)
        _close(working)
        _close(encoded_stage)


def thumbnail_image(
    data: bytes,
    *,
    size: tuple[int, int] = (256, 256),
    output_format: Literal["PNG", "JPEG", "WEBP"] = "PNG",
    normalize_orientation: bool = True,
    preserve_icc: bool = False,
) -> ImageOutput:
    """Produce a preview that fits inside ``size`` while keeping aspect ratio.

    The image is only ever shrunk. An image already inside the box is still
    re-encoded, so the result remains deterministically sanitized.
    """

    if output_format not in IMAGE_OUTPUT_FORMATS:
        raise ImageContractError("image_output_format_unsupported")
    if not isinstance(size, tuple) or len(size) != 2:
        raise ImageContractError("image_resize_invalid")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in size):
        raise ImageContractError("image_resize_invalid")
    if size[0] <= 0 or size[1] <= 0:
        raise ImageContractError("image_resize_invalid")
    if size[0] * size[1] > MAX_IMAGE_PIXELS:
        raise ImageContractError("image_output_pixels_exceeded")

    payload = _validate_payload(data)
    image = _open_first_frame(payload)
    try:
        _require_single_frame(image)
        orientation = (
            _read_metadata(image, payload).orientation
            if normalize_orientation
            else None
        )
        # The pre-transpose geometry is what a viewer displays, so fit the
        # requested preview box against that display geometry.
        display_size = image.size[::-1] if orientation in {5, 6, 7, 8} else image.size
        target = _fit_within(display_size[0], display_size[1], size)
    finally:
        _close(image)

    return transform_image(
        payload,
        output_format=output_format,
        resize=target,
        normalize_orientation=normalize_orientation,
        preserve_icc=preserve_icc,
    )


def image_to_pdf(images: tuple[bytes, ...]) -> ImagePdfOutput:
    """Emit one new PDF from one or more admitted raster images.

    This is image-owned emission only: it does not parse, read, merge, split or
    transform an existing PDF. Each page uses normalized pixels, explicit white
    flattening for alpha, a fixed 150 DPI page-size policy, and bounded
    provenance. The caller is responsible for running the common intake gate
    before every payload reaches this helper.
    """

    if not images:
        raise ImageContractError("image_bytes_invalid")
    if len(images) > MAX_PDF_IMAGES:
        raise ImageContractError("image_pdf_count_exceeded")
    payloads = tuple(_validate_payload(image) for image in images)
    if sum(len(image) for image in payloads) > MAX_PDF_INPUT_BYTES:
        raise ImageContractError("image_pdf_input_bytes_exceeded")

    opened: list[Image.Image] = []
    normalized: list[Image.Image] = []
    pages: list[PdfPageProvenance] = []
    total_pixels = 0
    try:
        for index, payload in enumerate(payloads):
            source = _open_first_frame(payload)
            opened.append(source)
            _require_single_frame(source)
            total_pixels += source.width * source.height
            if total_pixels > MAX_PDF_TOTAL_PIXELS:
                raise ImageContractError("image_pdf_total_pixels_exceeded")

            orientation = _read_metadata(source, payload).orientation
            source_format = source.format or "UNKNOWN"
            source_dimensions = (source.width, source.height)
            page = ImageOps.exif_transpose(source)
            if page is source:
                page = source.copy()
            else:
                _close(source)
            page.info.clear()
            if _has_alpha(page):
                rgba = page.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, PDF_BACKGROUND_RGB)
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                _close(rgba)
                page.close()
                page = flattened
            elif page.mode != "RGB":
                converted = page.convert("RGB")
                page.close()
                page = converted
            normalized.append(page)
            pages.append(
                PdfPageProvenance(
                    page_number=index + 1,
                    source_image_index=index,
                    source_format=source_format,
                    source_dimensions=source_dimensions,
                    normalized_orientation=orientation not in (None, 1),
                )
            )

        output = BytesIO()
        try:
            normalized[0].save(
                output,
                format="PDF",
                save_all=True,
                append_images=normalized[1:],
                resolution=PDF_DPI,
            )
            encoded = output.getvalue()
        except Exception as exc:
            raise ImageContractError("image_decode_failed") from exc
        if not encoded:
            raise ImageContractError("image_decode_failed")
        if len(encoded) > MAX_PDF_OUTPUT_BYTES:
            raise ImageContractError("image_pdf_output_bytes_exceeded")
        return ImagePdfOutput(data=encoded, page_count=len(normalized), pages=tuple(pages))
    finally:
        for image in normalized:
            _close(image)
        for image in opened:
            _close(image)
