"""#3037 synthetic contract tests for the bounded Core image helper.

Every fixture here is generated in memory from a few dozen pixels, so the suite
stays fast and no repository file is read or written. There is deliberately no
committed binary fixture to keep the repository small and to prove the helper
never depends on a host path.
"""

from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image", reason="approved Pillow runtime is not installed")
ImageFile = pytest.importorskip(
    "PIL.ImageFile", reason="approved Pillow runtime is not installed"
)

import padiem_ai_core.image_helpers as helpers
from padiem_ai_core.image_helpers import (
    IMAGE_ERROR_CODES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_INSPECT_FRAMES,
    MAX_OUTPUT_BYTES,
    MAX_PDF_IMAGES,
    MAX_PDF_INPUT_BYTES,
    MAX_PDF_OUTPUT_BYTES,
    MAX_PDF_TOTAL_PIXELS,
    PDF_BACKGROUND_RGB,
    ImageContractError,
    ImagePdfOutput,
    image_to_pdf,
    inspect_image,
    sanitize_metadata,
    thumbnail_image,
    transform_image,
)

MODULE_PATH = Path(helpers.__file__)

#: A small opaque RGB source and a small RGBA source with a real alpha edge.
SMALL_RGB = (24, 17)
SMALL_RGBA = (24, 17)

_OUTPUT_FORMATS = ("PNG", "JPEG", "WEBP")
_INPUT_FORMATS = ("PNG", "JPEG", "WEBP")


def _rgb_image(size: tuple[int, int] = SMALL_RGB, color=(10, 120, 200)) -> Image.Image:
    return Image.new("RGB", size, color)


def _rgba_image(size: tuple[int, int] = SMALL_RGBA) -> Image.Image:
    """RGBA source with alpha 0 on the left column and 255 elsewhere."""

    image = Image.new("RGBA", size, (10, 120, 200, 255))
    for y in range(size[1]):
        image.putpixel((0, y), (10, 120, 200, 0))
    return image


def _encode(
    image: Image.Image,
    fmt: str,
    **kwargs: object,
) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _png(size: tuple[int, int] = SMALL_RGB, color=(10, 120, 200)) -> bytes:
    return _encode(_rgb_image(size, color), "PNG")


def _jpeg(size: tuple[int, int] = SMALL_RGB, **kwargs: object) -> bytes:
    return _encode(_rgb_image(size), "JPEG", quality=95, **kwargs)


def _webp(size: tuple[int, int] = SMALL_RGB) -> bytes:
    return _encode(_rgb_image(size), "WEBP")


def _exif_jpeg(orientation: int) -> bytes:
    exif = Image.Exif()
    exif[helpers._EXIF_TAG_ORIENTATION] = orientation
    return _encode(_rgb_image(), "JPEG", quality=95, exif=exif)


def _animated_gif(frames: int = 3, size: tuple[int, int] = (12, 9)) -> bytes:
    images = [
        _rgb_image(size, (index * 20 % 255, 30, 40)) for index in range(frames)
    ]
    buffer = BytesIO()
    images[0].save(
        buffer, format="GIF", save_all=True, append_images=images[1:], duration=40
    )
    return buffer.getvalue()


def _code(excinfo: pytest.ExceptionInfo[ImageContractError]) -> str:
    return str(excinfo.value)


# --------------------------------------------------------------------------
# Inspect
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", _INPUT_FORMATS)
def test_inspect_reports_static_frame_facts_per_input_format(fmt: str) -> None:
    source = {"PNG": _png, "JPEG": _jpeg, "WEBP": _webp}[fmt]()

    result = inspect_image(source)

    assert result.format == fmt
    assert (result.width, result.height) == SMALL_RGB
    assert result.frame_count == 1
    assert result.multi_frame is False
    assert result.channels >= 1
    assert result.safe_dict()["width"] == SMALL_RGB[0]


@pytest.mark.parametrize("fmt", _INPUT_FORMATS)
def test_inspect_projection_never_carries_payload_bytes(fmt: str) -> None:
    source = {"PNG": _png, "JPEG": _jpeg, "WEBP": _webp}[fmt]()

    projection = inspect_image(source).safe_dict()

    assert not any(isinstance(value, (bytes, bytearray)) for value in projection.values())
    assert set(projection) == {
        "format",
        "width",
        "height",
        "mode",
        "channels",
        "frame_count",
        "multi_frame",
        "has_exif",
        "has_gps",
        "orientation",
        "has_xmp",
        "has_icc_profile",
        "has_text_metadata",
    }


def test_inspect_reports_exif_orientation_and_gps_presence() -> None:
    exif = Image.Exif()
    exif[helpers._EXIF_TAG_ORIENTATION] = 6
    gps_ifd = {2: (51.0, 1.0, 0.0), 4: (6.0, 1.0, 0.0)}
    exif[helpers._EXIF_IFD_GPS] = gps_ifd
    source = _encode(_rgb_image(), "JPEG", quality=95, exif=exif)

    result = inspect_image(source)

    assert result.has_exif is True
    assert result.orientation == 6
    assert result.has_gps is True


def test_inspect_reports_animated_gif_within_the_hard_bound() -> None:
    result = inspect_image(_animated_gif(frames=3))

    assert result.format == "GIF"
    assert result.frame_count == 3
    assert result.multi_frame is True
    assert (result.width, result.height) == (12, 9)


def test_inspect_reports_text_metadata_presence() -> None:
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "padiem")
    source = _encode(_rgb_image(), "PNG", pnginfo=info)

    assert inspect_image(source).has_text_metadata is True


def test_inspect_reports_icc_profile_presence() -> None:
    source = _encode(_rgb_image(), "PNG", icc_profile=b"not-a-real-profile")

    assert inspect_image(source).has_icc_profile is True


# --------------------------------------------------------------------------
# Orientation normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [(1, SMALL_RGB), (3, SMALL_RGB), (6, SMALL_RGB[::-1]), (8, SMALL_RGB[::-1])],
)
def test_exif_orientation_normalization_swaps_axes_when_required(
    orientation: int, expected: tuple[int, int]
) -> None:
    source = _exif_jpeg(orientation)

    result = transform_image(source, output_format="PNG")

    assert (result.width, result.height) == expected


def test_orientation_normalization_can_be_declined() -> None:
    source = _exif_jpeg(6)

    result = transform_image(
        source, output_format="PNG", normalize_orientation=False
    )

    assert (result.width, result.height) == SMALL_RGB


def test_orientation_is_not_carried_into_the_output() -> None:
    result = transform_image(_exif_jpeg(6), output_format="JPEG")

    reopened = Image.open(BytesIO(result.data))
    try:
        assert reopened.getexif().get(helpers._EXIF_TAG_ORIENTATION) in (None, 1)
    finally:
        reopened.close()


# --------------------------------------------------------------------------
# Crop / resize / rotate
# --------------------------------------------------------------------------


@pytest.mark.parametrize("output_format", _OUTPUT_FORMATS)
def test_crop_produces_the_requested_rectangle(output_format: str) -> None:
    result = transform_image(
        _png(), output_format=output_format, crop=(2, 1, 18, 13)
    )

    assert (result.width, result.height) == (16, 12)
    assert result.format == output_format


@pytest.mark.parametrize("output_format", _OUTPUT_FORMATS)
def test_resize_produces_the_requested_size(output_format: str) -> None:
    result = transform_image(_png(), output_format=output_format, resize=(9, 7))

    assert (result.width, result.height) == (9, 7)


def test_rotation_by_ninety_swaps_axes_and_expands() -> None:
    result = transform_image(_png((30, 12)), output_format="PNG", rotate=90)

    assert (result.width, result.height) == (12, 30)


def test_rotation_by_zero_and_full_turns_are_identity() -> None:
    baseline = transform_image(_png(), output_format="PNG").data

    for angle in (0, 360, 720):
        assert (
            transform_image(_png(), output_format="PNG", rotate=angle).data == baseline
        )


def test_transform_order_is_orientation_then_rotate_then_crop_then_resize() -> None:
    # Stored pixels are 24x17 with orientation 6, so a viewer sees 17x24.
    # Rotating that display by 90 gives 24x17, and the crop is expressed in
    # those post-rotation coordinates.
    source = _exif_jpeg(6)

    result = transform_image(
        source, output_format="PNG", rotate=90, crop=(0, 0, 20, 15), resize=(5, 4)
    )

    assert (result.width, result.height) == (5, 4)


# --------------------------------------------------------------------------
# Format matrix and alpha
# --------------------------------------------------------------------------


@pytest.mark.parametrize("source_format", _INPUT_FORMATS)
@pytest.mark.parametrize("output_format", _OUTPUT_FORMATS)
def test_full_input_to_output_conversion_matrix(
    source_format: str, output_format: str
) -> None:
    source = {"PNG": _png, "JPEG": _jpeg, "WEBP": _webp}[source_format]()

    result = transform_image(source, output_format=output_format)

    assert result.format == output_format
    assert (result.width, result.height) == SMALL_RGB
    reopened = Image.open(BytesIO(result.data))
    try:
        assert reopened.format == output_format
    finally:
        reopened.close()


@pytest.mark.parametrize("output_format", ("PNG", "WEBP"))
def test_alpha_is_preserved_for_png_and_webp(output_format: str) -> None:
    source = _encode(_rgba_image(), "PNG")

    result = transform_image(source, output_format=output_format)

    reopened = Image.open(BytesIO(result.data))
    try:
        assert "A" in reopened.getbands()
        assert reopened.getpixel((0, 0))[3] == 0
        assert reopened.getpixel((5, 5))[3] == 255
    finally:
        reopened.close()


def test_jpeg_alpha_uses_the_deterministic_matte() -> None:
    source = _encode(_rgba_image(), "PNG")

    result = transform_image(source, output_format="JPEG")

    reopened = Image.open(BytesIO(result.data))
    try:
        assert "A" not in reopened.getbands()
        # The fully transparent pixel becomes the matte, not black. JPEG is
        # lossy, so the comparison allows the encoder's small rounding drift.
        pixel = reopened.convert("RGB").getpixel((0, 0))
        assert all(
            abs(actual - expected) <= 2
            for actual, expected in zip(pixel, helpers.JPEG_MATTE_RGB)
        ), pixel
    finally:
        reopened.close()


def test_palette_transparency_is_preserved_rather_than_dropped() -> None:
    palette_source = Image.new("P", (8, 8))
    palette_source.putpalette([0, 0, 0, 255, 255, 255] + [0] * (256 * 3 - 6))
    palette_source.info["transparency"] = 0
    source = _encode(palette_source, "PNG")

    result = transform_image(source, output_format="PNG")

    reopened = Image.open(BytesIO(result.data))
    try:
        assert "A" in reopened.getbands()
    finally:
        reopened.close()


def test_grayscale_source_converts_deterministically() -> None:
    source = _encode(Image.new("L", (10, 6), 128), "PNG")

    png_result = transform_image(source, output_format="PNG")
    webp_result = transform_image(source, output_format="WEBP")

    assert (png_result.width, png_result.height) == (10, 6)
    assert (webp_result.width, webp_result.height) == (10, 6)


# --------------------------------------------------------------------------
# Metadata sanitation
# --------------------------------------------------------------------------


def _metadata_heavy_png() -> bytes:
    from PIL import PngImagePlugin

    exif = Image.Exif()
    exif[helpers._EXIF_TAG_ORIENTATION] = 1
    exif[helpers._EXIF_IFD_GPS] = {2: (51.0, 1.0, 0.0)}
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "padiem-sensitive-text")
    return _encode(
        _rgb_image(),
        "PNG",
        exif=exif,
        pnginfo=info,
        icc_profile=b"untrusted-icc-bytes",
    )


def test_default_sanitation_removes_exif_gps_xmp_and_text() -> None:
    result = sanitize_metadata(_metadata_heavy_png(), output_format="PNG")

    reopened = Image.open(BytesIO(result.data))
    try:
        assert not reopened.getexif()
        assert "icc_profile" not in reopened.info
        assert "xmp" not in reopened.info
        assert not getattr(reopened, "text", {})
    finally:
        reopened.close()


def test_preserve_icc_copies_only_the_profile_and_still_removes_the_rest() -> None:
    result = sanitize_metadata(
        _metadata_heavy_png(), output_format="PNG", preserve_icc=True
    )

    reopened = Image.open(BytesIO(result.data))
    try:
        assert reopened.info.get("icc_profile") == b"untrusted-icc-bytes"
        assert not reopened.getexif()
        assert not getattr(reopened, "text", {})
    finally:
        reopened.close()
    assert result.icc_profile_preserved is True


def test_preserve_icc_reports_false_when_the_source_has_no_profile() -> None:
    result = sanitize_metadata(_png(), output_format="PNG", preserve_icc=True)

    assert result.icc_profile_preserved is False


def test_sanitation_is_the_default_for_transform_too() -> None:
    result = transform_image(_metadata_heavy_png(), output_format="PNG")

    reopened = Image.open(BytesIO(result.data))
    try:
        assert not reopened.getexif()
        assert "icc_profile" not in reopened.info
    finally:
        reopened.close()


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


@pytest.mark.parametrize("output_format", _OUTPUT_FORMATS)
def test_same_input_and_arguments_produce_identical_bytes(output_format: str) -> None:
    source = _png()

    first = transform_image(source, output_format=output_format, resize=(11, 9))
    second = transform_image(source, output_format=output_format, resize=(11, 9))

    assert first.data == second.data


def test_encoder_settings_are_fixed_constants() -> None:
    assert helpers._JPEG_QUALITY == 90
    assert helpers._WEBP_QUALITY == 80
    assert helpers._WEBP_METHOD == 6
    assert helpers._PNG_COMPRESS_LEVEL == 6
    assert helpers.JPEG_MATTE_RGB == (255, 255, 255)


# --------------------------------------------------------------------------
# Thumbnail
# --------------------------------------------------------------------------


@pytest.mark.parametrize("output_format", _OUTPUT_FORMATS)
def test_thumbnail_fits_inside_the_box_and_keeps_aspect_ratio(
    output_format: str,
) -> None:
    result = thumbnail_image(
        _png((200, 100)), size=(40, 40), output_format=output_format
    )

    assert result.width <= 40 and result.height <= 40
    assert (result.width, result.height) == (40, 20)


def test_thumbnail_never_enlarges_a_small_image() -> None:
    result = thumbnail_image(_png((20, 10)), size=(400, 400))

    assert (result.width, result.height) == (20, 10)


def test_thumbnail_measures_against_the_display_orientation() -> None:
    # Orientation 6 means the viewer sees 17x24, so a 10x40 box fits 10x14 of
    # the display. Fitting the stored 24x17 pixels instead would give 10x7.
    result = thumbnail_image(_exif_jpeg(6), size=(10, 40))

    assert (result.width, result.height) == (10, 14)


def test_thumbnail_still_sanitizes_metadata() -> None:
    result = thumbnail_image(_metadata_heavy_png(), size=(8, 8))

    reopened = Image.open(BytesIO(result.data))
    try:
        assert not reopened.getexif()
    finally:
        reopened.close()


# --------------------------------------------------------------------------
# Fail-closed bounds
# --------------------------------------------------------------------------


def test_empty_payload_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(b"")

    assert _code(excinfo) == "image_bytes_invalid"


def test_non_bytes_payload_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image("not bytes")  # type: ignore[arg-type]

    assert _code(excinfo) == "image_bytes_invalid"


def test_oversized_input_bytes_are_refused_before_decode(monkeypatch) -> None:
    opened: list[bytes] = []
    original_open = Image.open

    def spy(source, *args, **kwargs):  # pragma: no cover - must not be reached
        opened.append(bytes(source.getvalue()) if hasattr(source, "getvalue") else b"")
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(helpers.Image, "open", spy)
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_IMAGE_BYTES + 1))

    assert _code(excinfo) == "image_bytes_oversized"
    assert opened == []


def test_oversized_pixel_count_is_refused() -> None:
    # A tiny PNG header claiming an enormous canvas is refused on the declared
    # geometry, before any pixel is decoded.
    source = _png((1, 1))
    header = bytearray(source[:33])
    width = MAX_IMAGE_PIXELS + 1
    header[16:20] = width.to_bytes(4, "big")
    header[20:24] = (1).to_bytes(4, "big")

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(bytes(header) + source[33:])

    assert _code(excinfo) in {"image_pixels_exceeded", "image_decode_failed"}


def test_oversized_resize_target_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(
            _png(), output_format="PNG", resize=(MAX_IMAGE_PIXELS, MAX_IMAGE_PIXELS)
        )

    assert _code(excinfo) == "image_output_pixels_exceeded"


def test_oversized_output_bytes_are_refused(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "MAX_OUTPUT_BYTES", 8)
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png((32, 32), color=(7, 11, 13)), output_format="PNG")

    assert _code(excinfo) == "image_output_bytes_exceeded"


@pytest.mark.parametrize(
    ("crop",),
    [((0, 0, 999, 5),), ((0, 0, 5, 999),), ((10, 0, 4, 5),), ((-1, 0, 4, 5),)],
)
def test_invalid_crop_rectangles_are_refused(crop) -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png(), output_format="PNG", crop=crop)

    assert _code(excinfo) == "image_crop_invalid"


@pytest.mark.parametrize("resize", [(0, 5), (5, 0), (-3, 4)])
def test_nonpositive_resize_is_refused(resize) -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png(), output_format="PNG", resize=resize)

    assert _code(excinfo) == "image_resize_invalid"


def test_non_integer_resize_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png(), output_format="PNG", resize=(5.5, 4))  # type: ignore[arg-type]

    assert _code(excinfo) == "image_resize_invalid"


def test_non_integer_rotate_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png(), output_format="PNG", rotate=90.0)  # type: ignore[arg-type]

    assert _code(excinfo) == "image_rotate_invalid"


def test_unsupported_output_format_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_png(), output_format="PDF")  # type: ignore[arg-type]

    assert _code(excinfo) == "image_output_format_unsupported"


def test_unsupported_input_format_is_refused() -> None:
    # BMP is a real Pillow format and a real image, but it is outside the
    # supported set, so it must be refused rather than quietly accepted.
    source = _encode(_rgb_image(), "BMP")

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(source)

    assert _code(excinfo) == "image_format_unsupported"


def test_eps_input_is_refused_without_ghostscript() -> None:
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n%%EOF\n"

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(eps)

    assert _code(excinfo) == "image_format_unsupported"


def test_unknown_bytes_are_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(b"definitely not an image at all")

    assert _code(excinfo) == "image_decode_failed"


@pytest.mark.parametrize("keep", [0.8, 0.6, 0.3])
def test_truncated_input_fails_closed(keep: float) -> None:
    source = _png((64, 64), color=(120, 90, 200))
    truncated = source[: int(len(source) * keep)]

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(truncated)

    assert _code(excinfo) == "image_decode_failed"


def test_corrupt_mid_stream_png_fails_closed() -> None:
    source = bytearray(_png((64, 64), color=(200, 30, 90)))
    # Corrupt the compressed image data well past the signature and header.
    for offset in range(40, min(len(source) - 8, 120)):
        source[offset] ^= 0xFF

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(bytes(source))

    assert _code(excinfo) in {"image_decode_failed", "image_pixels_exceeded"}


def test_decompression_bomb_is_refused(monkeypatch) -> None:
    source = _png((64, 64))
    # Pillow's own threshold is lowered so a small fixture exercises the real
    # bomb path instead of needing a genuinely enormous image.
    monkeypatch.setattr(helpers.Image, "MAX_IMAGE_PIXELS", 16)

    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(source)

    assert _code(excinfo) in {"image_decompression_bomb", "image_pixels_exceeded"}


def test_pillow_bomb_exception_maps_to_the_stable_code(monkeypatch) -> None:
    def bomb(fp, *args, **kwargs):
        raise Image.DecompressionBombError("synthetic bomb")

    monkeypatch.setattr(helpers.Image, "open", bomb)
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(_png())

    assert _code(excinfo) == "image_decompression_bomb"


def test_pillow_bomb_warning_maps_to_the_stable_code(monkeypatch) -> None:
    def bomb(fp, *args, **kwargs):
        raise Image.DecompressionBombWarning("synthetic bomb warning")

    monkeypatch.setattr(helpers.Image, "open", bomb)
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(_png())

    assert _code(excinfo) == "image_decompression_bomb"


def test_frame_count_above_the_hard_bound_is_refused() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        inspect_image(_animated_gif(frames=MAX_INSPECT_FRAMES + 1))

    assert _code(excinfo) == "image_frame_count_exceeded"


def test_metadata_parse_failure_is_not_downgraded_to_no_metadata(monkeypatch) -> None:
    source = _png()
    original = Image.Image.getexif

    def boom(self):
        raise ValueError("synthetic metadata failure")

    monkeypatch.setattr(Image.Image, "getexif", boom)
    try:
        with pytest.raises(ImageContractError) as excinfo:
            inspect_image(source)
    finally:
        monkeypatch.setattr(Image.Image, "getexif", original)

    assert _code(excinfo) == "image_metadata_unreadable"


def test_icc_read_failure_is_reported_as_a_metadata_failure(monkeypatch) -> None:
    class _PoisonedInfo(dict):
        def get(self, key, default=None):
            if key == "icc_profile":
                raise ValueError("synthetic icc failure")
            return super().get(key, default)

    original_open = helpers._open_first_frame

    def poisoned_open(payload: bytes) -> Image.Image:
        image = original_open(payload)
        image.info = _PoisonedInfo(image.info)
        return image

    monkeypatch.setattr(helpers, "_open_first_frame", poisoned_open)
    with pytest.raises(ImageContractError) as excinfo:
        sanitize_metadata(_png(), output_format="PNG", preserve_icc=True)

    assert _code(excinfo) == "image_metadata_unreadable"


def test_truncated_tolerance_flag_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(helpers.ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    try:
        with pytest.raises(ImageContractError) as excinfo:
            inspect_image(_png())
    finally:
        monkeypatch.setattr(helpers.ImageFile, "LOAD_TRUNCATED_IMAGES", False)

    assert _code(excinfo) == "image_decode_failed"


def test_load_truncated_images_is_not_enabled_by_the_module() -> None:
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False
    assert "LOAD_TRUNCATED_IMAGES = True" not in MODULE_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Multi-frame refusal
# --------------------------------------------------------------------------


def test_transform_refuses_a_multiframe_payload() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        transform_image(_animated_gif(), output_format="PNG")

    assert _code(excinfo) == "image_multiframe_refused"


def test_thumbnail_refuses_a_multiframe_payload() -> None:
    with pytest.raises(ImageContractError) as excinfo:
        thumbnail_image(_animated_gif(), size=(8, 8))

    assert _code(excinfo) == "image_multiframe_refused"


def test_single_frame_gif_is_transformable() -> None:
    source = _encode(_rgb_image((12, 9)), "GIF")

    result = transform_image(source, output_format="PNG")

    assert (result.width, result.height) == (12, 9)


# --------------------------------------------------------------------------
# Contract shape
# --------------------------------------------------------------------------


def test_every_error_code_is_a_lowercase_declared_string() -> None:
    assert IMAGE_ERROR_CODES
    for code in IMAGE_ERROR_CODES:
        assert code == code.lower()
        assert " " not in code


def test_unknown_error_code_cannot_be_raised() -> None:
    with pytest.raises(ValueError):
        ImageContractError("not_a_declared_code")


def test_bounds_are_ordered_sensibly() -> None:
    assert 0 < MAX_IMAGE_BYTES
    assert 0 < MAX_OUTPUT_BYTES < MAX_IMAGE_BYTES
    assert 0 < MAX_IMAGE_PIXELS
    assert MAX_INSPECT_FRAMES >= 2


def test_module_calls_no_forbidden_host_capability() -> None:
    """No attribute or name the module actually resolves may be a host escape.

    The scan is on the parsed tree, not the raw text, because the module
    docstring legitimately *names* these things in order to exclude them.
    """

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    resolved: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            resolved.add(node.attr)
        elif isinstance(node, ast.Name):
            resolved.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            resolved.add(node.name)

    # Host-escape names. ``Image.open(BytesIO(...))`` is the in-memory decoder
    # and is allowed; filesystem/process/network escape names are absent.
    assert {
        "system",
        "popen",
        "Popen",
        "urlopen",
        "read",
        "write",
        "show",
        "grab",
        "grabScreen",
        "import_module",
    } & resolved == set()


def test_module_docstring_states_the_exclusions_it_is_tested_for() -> None:
    """The exclusions are documented, not merely absent."""

    source = MODULE_PATH.read_text(encoding="utf-8")

    for token in ("Image.show", "ImageGrab", "Ghostscript", "EPS"):
        assert token in source, token


def test_module_never_imports_a_filesystem_or_process_module() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for banned in ("os", "pathlib", "subprocess", "shutil", "tempfile", "requests", "httpx"):
        assert banned not in imported, banned


# --------------------------------------------------------------------------
# Image -> new PDF artifact
# --------------------------------------------------------------------------


def test_image_to_pdf_single_and_multiple_pages_preserve_source_order() -> None:
    from io import BytesIO as _BytesIO

    pdf = image_to_pdf((_png((20, 10), (255, 0, 0)), _jpeg((10, 20))))
    assert isinstance(pdf, ImagePdfOutput)
    assert pdf.data.startswith(b"%PDF-")
    assert pdf.page_count == 2
    assert [page.source_image_index for page in pdf.pages] == [0, 1]
    assert [page.source_format for page in pdf.pages] == ["PNG", "JPEG"]
    assert pdf.safe_dict()["page_count"] == 2
    assert "data" not in pdf.safe_dict()

    PdfReader = pytest.importorskip("pypdf.PdfReader")
    reader = PdfReader(_BytesIO(pdf.data))
    assert len(reader.pages) == 2


def test_image_to_pdf_normalizes_orientation_and_records_provenance() -> None:
    result = image_to_pdf((_exif_jpeg(6),))
    assert result.page_count == 1
    assert result.pages[0].source_dimensions == SMALL_RGB
    assert result.pages[0].normalized_orientation is True


def test_image_to_pdf_alpha_background_policy_is_explicit() -> None:
    assert PDF_BACKGROUND_RGB == (255, 255, 255)
    result = image_to_pdf((_encode(_rgba_image(), "PNG"),))
    assert result.page_count == 1
    assert result.pages[0].source_format == "PNG"


def test_image_to_pdf_empty_and_oversized_sequences_fail_closed() -> None:
    with pytest.raises(ImageContractError) as empty:
        image_to_pdf(())
    assert _code(empty) == "image_bytes_invalid"

    with pytest.raises(ImageContractError) as too_many:
        image_to_pdf(tuple(_png() for _ in range(MAX_PDF_IMAGES + 1)))
    assert _code(too_many) == "image_pdf_count_exceeded"

    with pytest.raises(ImageContractError) as invalid:
        image_to_pdf((b"not-an-image",))
    assert _code(invalid) == "image_decode_failed"


def test_image_to_pdf_total_bounds_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "MAX_PDF_INPUT_BYTES", 1)
    with pytest.raises(ImageContractError) as total_bytes:
        image_to_pdf((_png(),))
    assert _code(total_bytes) == "image_pdf_input_bytes_exceeded"

    monkeypatch.setattr(helpers, "MAX_PDF_INPUT_BYTES", MAX_PDF_INPUT_BYTES)
    monkeypatch.setattr(helpers, "MAX_PDF_TOTAL_PIXELS", 1)
    with pytest.raises(ImageContractError) as total_pixels:
        image_to_pdf((_png(),))
    assert _code(total_pixels) == "image_pdf_total_pixels_exceeded"


def test_image_to_pdf_output_bound_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "MAX_PDF_OUTPUT_BYTES", 8)
    with pytest.raises(ImageContractError) as excinfo:
        image_to_pdf((_png(),))
    assert _code(excinfo) == "image_pdf_output_bytes_exceeded"
