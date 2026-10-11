"""Embed the CGI source font families without a platform font fallback.

The reference exporter truncates TrueType advances to integer PDF widths at
1000 units/em.  ``FontMetrics.width`` follows that same convention and does not
apply kerning: the renderer owns source ``TJ`` adjustments and text transforms.
The embedded TrueType outlines, hint programs and original units/em remain
unchanged by the PDF width conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from fontTools import subset
from fontTools.ttLib import TTFont
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


_FONT_SOURCES = {
    "Gulim": ("gulim.ttc", 0),
    "GulimChe": ("gulim.ttc", 1),
    "MalgunGothic": ("malgun.ttf", None),
    "MalgunGothicBold": ("malgunbd.ttf", None),
}


@dataclass(frozen=True)
class FontMetrics:
    """Metrics for the exact glyph coverage embedded in a PDF font.

    Widths use fontsize 1.  ``encode`` returns two-byte CIDs equal to Unicode
    BMP code points; the font's explicit CIDToGIDMap maps them to subset glyphs.
    A caller must embed all required strings together before rendering them.
    """

    family: str
    source: str
    source_sha256: str
    face_index: int | None
    units_per_em: int
    widths: Mapping[int, int]
    outline_advances: Mapping[int, int]
    glyph_ids: Mapping[int, int]
    subset_sha256: str

    def _codepoints(self, text: str) -> list[int]:
        codepoints = _bmp_codepoints(text)
        for codepoint in codepoints:
            if codepoint not in self.widths:
                raise ValueError(
                    f"{self.family} was not embedded with U+{codepoint:04X}; "
                    "embed the complete text coverage before rendering"
                )
        return codepoints

    def width(self, text: str) -> float:
        """Return the emitted PDF advance in em, with no implicit kerning."""
        return sum(self.widths[c] for c in self._codepoints(text)) / 1000

    def outline_width(self, text: str) -> float:
        """Return the unrounded original TrueType advance in em."""
        return sum(self.outline_advances[c] for c in self._codepoints(text)) / self.units_per_em

    def encode(self, text: str) -> bytes:
        """Encode supported text as Identity-H two-byte CIDs."""
        self._codepoints(text)
        return text.encode("utf-16-be")

    @property
    def metadata(self) -> dict:
        return {
            "family": self.family,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "face_index": self.face_index,
            "units_per_em": self.units_per_em,
            "subset_sha256": self.subset_sha256,
            "coverage": sorted(self.widths),
            "pdf_width_convention": "truncate_hmtx_to_1000_units_per_em",
            "kerning": "renderer_explicit_TJ_only",
        }


def _bmp_codepoints(text: str) -> list[int]:
    if not isinstance(text, str):
        raise TypeError("Font text must be a Unicode string")
    result = []
    for character in text:
        codepoint = ord(character)
        if codepoint > 0xFFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError(f"Non-BMP or surrogate text U+{codepoint:04X} is unsupported")
        result.append(codepoint)
    return result


def _stream(writer: PdfWriter, data: bytes, **entries: int) -> IndirectObject:
    stream = DecodedStreamObject()
    stream.set_data(data)
    for key, value in entries.items():
        stream[NameObject("/" + key)] = NumberObject(value)
    return writer._add_object(stream.flate_encode())


def _to_unicode(codepoints: list[int]) -> bytes:
    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /CGI-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]
    for start in range(0, len(codepoints), 100):
        group = codepoints[start : start + 100]
        lines.append(f"{len(group)} beginbfchar")
        lines.extend(f"<{c:04X}> <{c:04X}>" for c in group)
        lines.append("endbfchar")
    lines.extend(["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"])
    return ("\n".join(lines) + "\n").encode("ascii")


def _pdf_widths(widths: Mapping[int, int]) -> ArrayObject:
    # Group adjacent CIDs into PDF's [first [width ...]] form.
    result = ArrayObject()
    previous = None
    group = None
    for codepoint in sorted(widths):
        if previous is None or codepoint != previous + 1:
            group = ArrayObject()
            result.extend([NumberObject(codepoint), group])
        group.append(NumberObject(widths[codepoint]))
        previous = codepoint
    return result


def embed_font(
    writer: PdfWriter,
    font_name: str,
    text: str,
    font_directory: str | Path = "C:/Windows/Fonts",
) -> tuple[IndirectObject, FontMetrics]:
    """Embed an exact supported source font for the supplied text coverage.

    Missing font files, a different collection face, absent glyphs and non-BMP
    text fail explicitly.  Font coverage and subset naming are deterministic
    for the same source font bytes and set of input characters.
    """
    if font_name not in _FONT_SOURCES:
        raise ValueError(f"Unsupported source font family: {font_name}")
    codepoints = sorted(set(_bmp_codepoints(text)) | {0x20})
    filename, face_index = _FONT_SOURCES[font_name]
    source_path = Path(font_directory) / filename
    source_bytes = source_path.read_bytes()
    source_hash = sha256(source_bytes).hexdigest()
    font = TTFont(
        BytesIO(source_bytes),
        fontNumber=face_index if face_index is not None else -1,
        recalcTimestamp=False,
    )
    try:
        actual_name = font["name"].getDebugName(6)
        if actual_name != font_name:
            raise ValueError(
                f"Source font identity mismatch: expected {font_name}, found {actual_name}"
            )
        cmap = font.getBestCmap()
        missing = [c for c in codepoints if c not in cmap or cmap[c] == ".notdef"]
        if missing:
            missing_names = ", ".join(f"U+{c:04X}" for c in missing)
            raise ValueError(f"{font_name} has no source glyph for {missing_names}")
        units_per_em = font["head"].unitsPerEm
        advances = {c: font["hmtx"][cmap[c]][0] for c in codepoints}
        widths = {c: advances[c] * 1000 // units_per_em for c in codepoints}
        font_bbox = [
            int(getattr(font["head"], key) * 1000 / units_per_em)
            for key in ("xMin", "yMin", "xMax", "yMax")
        ]
        ascent = int(font["OS/2"].sTypoAscender * 1000 / units_per_em)
        descent = int(font["OS/2"].sTypoDescender * 1000 / units_per_em)
        italic_angle = int(font["post"].italicAngle)

        options = subset.Options()
        options.hinting = True
        options.recalc_timestamp = False
        options.canonical_order = True
        # These tables are absent from all four reference PDF font programs.
        # In particular, bitmap strikes/gasp must not add a different raster
        # policy, and layout tables must not introduce implicit kerning/shaping.
        options.drop_tables += [
            "EBDT", "EBLC", "EBSC", "gasp", "GSUB", "GPOS", "GDEF",
            "JSTF", "kern", "MATH", "vhea", "vmtx", "meta", "MERG",
        ]
        options.name_IDs = [1, 2, 3, 4, 5, 6]
        options.name_languages = [0x409]
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=codepoints)
        subsetter.subset(font)
        glyph_ids = {c: font.getGlyphID(font.getBestCmap()[c]) for c in codepoints}
        font_buffer = BytesIO()
        font.save(font_buffer, reorderTables=True)
        subset_bytes = font_buffer.getvalue()
    finally:
        font.close()

    subset_hash = sha256(subset_bytes).hexdigest()
    # PDF subset tags must be six uppercase letters. Include the font source
    # fingerprint so a changed installed font never reuses a prior identity.
    identity = f"{font_name}:{source_hash}:" + ",".join(map(str, codepoints))
    tag_digest = sha256(identity.encode("ascii")).digest()
    tag = "".join(chr(ord("A") + byte % 26) for byte in tag_digest[:6])
    base_name = NameObject(f"/{tag}+{font_name}")
    descriptor = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/FontDescriptor"),
            NameObject("/FontName"): base_name,
            NameObject("/Flags"): NumberObject(32),
            NameObject("/FontBBox"): ArrayObject([NumberObject(v) for v in font_bbox]),
            NameObject("/ItalicAngle"): NumberObject(italic_angle),
            NameObject("/Ascent"): NumberObject(ascent),
            NameObject("/Descent"): NumberObject(descent),
            NameObject("/CapHeight"): NumberObject(0),
            NameObject("/StemV"): NumberObject(0),
            NameObject("/FontFile2"): _stream(writer, subset_bytes, Length1=len(subset_bytes)),
        }
    )
    cid_to_gid = bytearray((max(codepoints) + 1) * 2)
    for codepoint, glyph_id in glyph_ids.items():
        cid_to_gid[codepoint * 2 : codepoint * 2 + 2] = glyph_id.to_bytes(2, "big")
    descendant = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/CIDFontType2"),
            NameObject("/BaseFont"): base_name,
            NameObject("/CIDSystemInfo"): DictionaryObject(
                {
                    NameObject("/Registry"): TextStringObject("Adobe"),
                    NameObject("/Ordering"): TextStringObject("Identity"),
                    NameObject("/Supplement"): NumberObject(0),
                }
            ),
            NameObject("/FontDescriptor"): writer._add_object(descriptor),
            NameObject("/DW"): NumberObject(1000),
            NameObject("/W"): _pdf_widths(widths),
            NameObject("/CIDToGIDMap"): _stream(writer, bytes(cid_to_gid)),
        }
    )
    type_zero = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): base_name,
            NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
            NameObject("/ToUnicode"): _stream(writer, _to_unicode(codepoints)),
        }
    )
    reference = writer._add_object(type_zero)
    metrics = FontMetrics(
        family=font_name,
        source=str(source_path.resolve()),
        source_sha256=source_hash,
        face_index=face_index,
        units_per_em=units_per_em,
        widths=MappingProxyType(widths),
        outline_advances=MappingProxyType(advances),
        glyph_ids=MappingProxyType(glyph_ids),
        subset_sha256=subset_hash,
    )
    return reference, metrics
