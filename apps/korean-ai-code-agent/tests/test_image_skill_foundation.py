from __future__ import annotations

from io import BytesIO
import unittest

from PIL import Image

from kagent.image_skill import (
    ImageSkillError,
    image_inspect,
    image_thumbnail,
    image_to_pdf,
    image_transform,
)


def image_bytes(fmt: str, *, size=(12, 8), exif_orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (10, 20, 30))
    out = BytesIO()
    if fmt == "JPEG":
        if exif_orientation is not None:
            exif = Image.Exif()
            exif[274] = exif_orientation
            image.save(out, format=fmt, exif=exif, quality=90)
        else:
            image.save(out, format=fmt, quality=90)
    else:
        image.save(out, format=fmt)
    return out.getvalue()


class ImageSkillFoundationTests(unittest.TestCase):
    def test_inspect_supported_formats(self):
        for fmt, name in (("PNG", "x.png"), ("JPEG", "x.jpg"), ("WEBP", "x.webp")):
            with self.subTest(fmt=fmt):
                result = image_inspect(image_bytes(fmt), filename=name)
                self.assertEqual(result.inspection.format, fmt)
                self.assertEqual((result.inspection.width, result.inspection.height), (12, 8))
                self.assertFalse(result.inspection.multi_frame)

    def test_exif_orientation_is_observable_and_normalized(self):
        source = image_bytes("JPEG", exif_orientation=6)
        inspected = image_inspect(source, filename="oriented.jpg")
        self.assertTrue(inspected.inspection.has_exif)
        self.assertEqual(inspected.inspection.orientation, 6)
        output = image_transform(source, filename="oriented.jpg", output_format="PNG")
        self.assertEqual(output.format, "PNG")
        self.assertEqual((output.width, output.height), (8, 12))

    def test_crop_resize_and_conversion_matrix(self):
        source = image_bytes("PNG")
        cropped = image_transform(source, filename="x.png", output_format="JPEG", crop=(1, 1, 9, 7), resize=(4, 3))
        self.assertEqual(cropped.format, "JPEG")
        self.assertEqual((cropped.width, cropped.height), (4, 3))
        webp = image_transform(source, filename="x.png", output_format="WEBP", resize=(6, 4))
        self.assertEqual(webp.format, "WEBP")

    def test_metadata_is_sanitized_by_default(self):
        image = Image.new("RGB", (4, 4), (1, 2, 3))
        exif = Image.Exif()
        exif[274] = 1
        out = BytesIO()
        image.save(out, format="JPEG", exif=exif, quality=90)
        result = image_transform(out.getvalue(), filename="meta.jpg", output_format="PNG")
        clean = Image.open(BytesIO(result.data))
        self.assertFalse(clean.getexif())
        self.assertNotIn("icc_profile", clean.info)

    def test_fail_closed_cases(self):
        source = image_bytes("PNG")
        with self.assertRaises(ImageSkillError):
            image_transform(source, filename="x.png", output_format="PNG", crop=(0, 0, 99, 8))
        with self.assertRaises(ImageSkillError):
            image_transform(source, filename="x.png", output_format="PNG", resize=(0, 4))
        with self.assertRaises(ImageSkillError):
            image_inspect(b"not an image", filename="x.png")
        with self.assertRaises(ImageSkillError):
            image_transform(source, filename="x.png", output_format="PDF")  # type: ignore[arg-type]

    def test_gif_multiframe_inspect_and_transform_refusal(self):
        frames = [Image.new("RGB", (4, 4), (i, i, i)) for i in (1, 2)]
        out = BytesIO()
        frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:])
        data = out.getvalue()
        inspected = image_inspect(data, filename="x.gif")
        self.assertTrue(inspected.inspection.multi_frame)
        with self.assertRaises(ImageSkillError):
            image_transform(data, filename="x.gif", output_format="PNG")

    def test_thumbnail_is_bounded(self):
        result = image_thumbnail(image_bytes("PNG", size=(100, 50)), filename="x.png", size=(20, 20))
        self.assertLessEqual(result.width, 20)
        self.assertLessEqual(result.height, 20)

    def test_image_to_pdf_uses_intake_and_preserves_order(self):
        result = image_to_pdf(
            (("first.png", image_bytes("PNG", size=(20, 10))), ("second.jpg", image_bytes("JPEG", size=(10, 20))))
        )
        self.assertTrue(result.data.startswith(b"%PDF-"))
        self.assertEqual(result.page_count, 2)
        self.assertEqual([page.source_image_index for page in result.pages], [0, 1])

    def test_image_to_pdf_rejects_non_tuple_sequence(self):
        with self.assertRaises(ImageSkillError):
            image_to_pdf([])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
