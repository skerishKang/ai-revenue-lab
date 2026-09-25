"""Single bounded PNG-canonical HWPX image insertion authority for Padiem AI Core.

Why this module exists
----------------------
``hwpx_package_serializer`` creates a package holding ``mimetype`` plus section
parts. It owns no ``content.hpf`` manifest and no binary data, so a picture
block — whose ``binaryItemIDRef`` names a manifest item — cannot be produced by
the from-scratch writer. This module is the one authority that closes that gap:
it inserts a picture into a package that already carries a manifest, which in
practice means a caller-supplied template.

The format decision this slice makes
------------------------------------
An embedded image is **always canonical PNG with media type ``image/png``**.
PNG and JPEG input are both admitted, and both go through Core's existing image
authority (:func:`padiem_ai_core.image_helpers.inspect_image` and
:func:`padiem_ai_core.image_helpers.transform_image`) before anything else
happens, so one Pillow decode/encode pipeline decides the pixels, the metadata
sanitation and the resulting dimensions. Direct JPEG embedding is deliberately
**not** supported: the available evidence disagrees with itself about the
canonical JPEG manifest spelling (``image/jpeg`` in one source, ``image/jpg`` in
a real-looking fixture), and a silent choice between them is exactly the kind of
unproven write-side contract this authority refuses to invent. A JPEG caller
gets a decoded, metadata-sanitized, orientation-normalized PNG instead.

What this module composes, and what it owns
-------------------------------------------
It owns no primitive. Every step is delegated to an authority that already
exists:

* admission and raw member reads —
  ``document_normalization.read_hwpx_package_members``, which runs the single
  archive gate;
* section structure and ordering — ``document_normalization.parse_hwpx_sections``,
  and the section-member naming rule through its own ``hwpx_section_index``
  predicate;
* image decode, orientation normalization, metadata sanitation and PNG encode —
  ``image_helpers``;
* the picture paragraph — ``hwpx_package_serializer.serialize_hwpx_picture_paragraph``,
  so an inserted picture is byte-identical to one this Core writes from scratch;
* the archive — the private
  ``hwpx_package_serializer._assemble_hwpx_package_members`` seam, so there is
  still exactly one member policy in Core.

It owns exactly two things, neither of which is a parser or a codec:

1. **Deterministic unused ``BIN####`` allocation.** The candidate id is decided
   by scanning every id-bearing source the package exposes — the member names,
   the ``content.hpf`` manifest bytes, the ``header.xml`` bytes and every
   section part's bytes — for the ``BIN`` + four ASCII digits token. The scan
   is deliberately a superset of the authoritative set: over-reporting a
   collision skips a technically free id, which is safe, while missing one would
   let an allocated id shadow a caller's existing image, which is not
   recoverable.
2. **Two anchored, additive byte splices.** One ``<opf:item>`` is inserted
   immediately before the manifest's single ``</opf:manifest>``, and one picture
   paragraph immediately before the section's single ``</hs:sec>``. Both anchors
   must be present exactly once and the manifest must declare the OPF namespace,
   or the insertion is refused. Nothing is re-serialized, so every byte the
   splices do not touch is preserved exactly — including namespace declarations,
   attribute order, metadata and whitespace that an XML round trip would
   rewrite.

What is deliberately out of scope
---------------------------------
* No second XML parser, no second image decoder, no second archive writer.
* No caller-supplied XML, member name, member path, relationship id, namespace
  id, shape id, style id, manifest id, package path, filesystem, subprocess,
  network or provider surface. A caller supplies a section position, image
  bytes and a draw extent, and nothing else.
* No direct JPEG embedding, and no image resize/crop/rotate as an editing
  feature, picture replacement, deletion, alignment or layout control.
* ``header.xml`` is *scanned* for id collisions but never written. The official
  read chain is ``hp:pic`` → ``hc:img/@binaryItemIDRef`` → manifest item →
  ``href``; no header ``binDataList`` participates, and no fixture in the
  available corpus carries one, so inventing one would be a second, unproven
  write-side contract.

The supported subset, stated exactly
------------------------------------
A source package is insertable when, and only when, it is admitted by the
single archive gate, carries at least one section part, carries exactly one
``Contents/content.hpf`` whose bytes contain the OPF namespace declaration and
exactly one ``</opf:manifest>``, and every addressed section part contains
exactly one ``</hs:sec>``. A package this Core created from scratch does not
carry a manifest, so it is not in this subset — which is why the from-scratch
writer refuses a picture block rather than emitting an unresolvable reference.

The readback contract
---------------------
The output re-enters the same archive gate and the same raw-member accessor. The
member-name sequence must be the source sequence plus exactly one new
``BinData`` member per insertion, and every member payload must match the
payload this module intended to write, byte for byte. Finally the inserted
picture blocks are read back through the single HWPX reader's fact layer
(``document_normalization.read_hwpx_section_facts``) rather than trusted from
this module's own bookkeeping, so the ids this module claims to have written are
the ids the reader actually finds. Anything that cannot be proven raises instead
of returning bytes with unproven provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .document_normalization import (
    MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES,
    HwpxPackageMember,
    extract_hwpx_text,
    hwpx_section_index,
    parse_hwpx_sections,
    read_hwpx_package_members,
    read_hwpx_section_facts,
    validate_ooxml_archive,
)
from .document_semantics import DocumentNormalizationError
from .hwpx_package_serializer import (
    HwpxPicture,
    _assemble_hwpx_package_members,
    serialize_hwpx_picture_paragraph,
)
from .image_helpers import ImageContractError, inspect_image, transform_image

#: Largest number of pictures one call may insert.
MAX_HWPX_IMAGE_INSERTIONS = 16

#: Input formats this authority admits. Both become canonical PNG on the way in.
HWPX_IMAGE_INPUT_FORMATS = ("png", "jpeg")

#: The one embedded media type this authority writes, and the one member
#: extension it derives from it. There is deliberately no JPEG counterpart.
HWPX_EMBEDDED_IMAGE_MEDIA_TYPE = "image/png"
HWPX_EMBEDDED_IMAGE_EXTENSION = "png"

#: The single manifest member name this authority reads and patches.
HWPX_MANIFEST_MEMBER = "Contents/content.hpf"

#: The member-name prefix embedded binary data lives under.
HWPX_BIN_DATA_PREFIX = "BinData/"

#: Largest canonical PNG this authority will embed. Derived from the archive
#: gate's own per-entry uncompressed bound: an image larger than this could not
#: be admitted back through the same gate, so embedding it would only produce a
#: package this Core would then refuse.
MAX_HWPX_IMAGE_BYTES = MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES

#: HWPUNIT per pixel used when the caller supplies no draw extent. 96 DPI is the
#: screen resolution the reference implementation's 14400-HWPUNIT default width
#: corresponds to. Fixed here so the same input always yields the same extent.
_HWPUNIT_PER_PIXEL = 75

#: The OWPML package namespace, required on the manifest root before this
#: authority will splice an ``<opf:item>`` into it.
_OPF_NAMESPACE = "http://www.idpf.org/2007/opf/"

_MANIFEST_CLOSE = b"</opf:manifest>"
_SECTION_CLOSE = b"</hs:sec>"

#: The one ``<opf:item>`` shape this authority writes. The id is Core-allocated,
#: the href is derived from that id by this module, and the media type is the
#: constant above — no caller input reaches any of the three. ``isEmbeded`` keeps
#: OWPML's single-``d`` spelling, which is the spelling the format uses.
_MANIFEST_ITEM = (
    '<opf:item id="{item_id}" href="BinData/{item_id}.{extension}"'
    ' media-type="{media_type}" isEmbeded="1"/>'
)

#: The collision token: ``BIN`` plus exactly four ASCII decimal digits. This is
#: the same shape ``document_normalization.is_hwpx_binary_item_id`` accepts, and
#: it is matched over raw bytes rather than parsed attributes on purpose — see
#: the module docstring.
_ID_TOKEN = re.compile(rb"BIN[0-9]{4}")


@dataclass(frozen=True, slots=True)
class HwpxImageInsertion:
    """One bounded request to embed one image into one section.

    ``section_index`` is the zero-based position of the section in the ordered
    list the single reader produces, which is the same address space
    :mod:`padiem_ai_core.hwpx_package_mutation` already uses. ``image`` is raw
    bytes in PNG or JPEG form; the format is *observed* through Core's image
    authority, never asserted by the caller, so a caller cannot claim one
    encoding and supply another. ``width_hwpunit``/``height_hwpunit`` are the
    draw extent in HWPUNIT (1/7200 inch); either or both may be left unset, in
    which case this module derives them from the decoded image's own pixel
    geometry. The value carries no authority of its own and enforces nothing.
    """

    section_index: int
    image: bytes = field(repr=False)
    width_hwpunit: int | None = None
    height_hwpunit: int | None = None


@dataclass(frozen=True, slots=True)
class HwpxImageInsertionReceipt:
    """Bounded, payload-free account of one completed insertion.

    ``binary_item_id_ref`` is the manifest item id the picture references, not
    a package path, so holding it grants no path authority. ``media_type`` is
    always :data:`HWPX_EMBEDDED_IMAGE_MEDIA_TYPE`: the receipt reports the
    canonical form, and ``source_format`` separately reports what the caller
    actually supplied, so a JPEG-in/PNG-out conversion is visible rather than
    silent. No field carries image bytes, XML, a member name or a host path.
    """

    section_index: int
    binary_item_id_ref: str
    media_type: str
    source_format: str
    width_hwpunit: int
    height_hwpunit: int
    width_px: int
    height_px: int
    image_bytes: int

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. Never contains the encoded image."""

        return {
            "section_index": self.section_index,
            "binary_item_id_ref": self.binary_item_id_ref,
            "media_type": self.media_type,
            "source_format": self.source_format,
            "width_hwpunit": self.width_hwpunit,
            "height_hwpunit": self.height_hwpunit,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "image_bytes": self.image_bytes,
        }


@dataclass(frozen=True, slots=True)
class _CanonicalImage:
    """One image after Core's image authority has accepted and re-encoded it."""

    png: bytes
    source_format: str
    width_px: int
    height_px: int


def _require_bounded_request(insertions: object) -> None:
    """Judge the instruction container and every field before any addressing."""

    if not isinstance(insertions, tuple) or not insertions:
        raise DocumentNormalizationError(
            "hwpx_image_request",
            "HWPX image insertion requires a non-empty tuple of insertions.",
        )
    if len(insertions) > MAX_HWPX_IMAGE_INSERTIONS:
        raise DocumentNormalizationError(
            "hwpx_image_limit",
            "HWPX image insertion exceeds the bounded insertion count.",
        )
    for insertion in insertions:
        if not isinstance(insertion, HwpxImageInsertion):
            raise DocumentNormalizationError(
                "hwpx_image_request",
                "HWPX image insertions must be HwpxImageInsertion values.",
            )
        # ``bool`` is an ``int`` subclass; an index is never a flag.
        if isinstance(insertion.section_index, bool) or not isinstance(insertion.section_index, int):
            raise DocumentNormalizationError(
                "hwpx_image_index_type",
                "HWPX image insertion section indexes must be integers.",
            )
        if insertion.section_index < 0:
            raise DocumentNormalizationError(
                "hwpx_image_index_negative",
                "HWPX image insertion section indexes are zero-based and cannot be negative.",
            )
        for value in (insertion.width_hwpunit, insertion.height_hwpunit):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise DocumentNormalizationError(
                    "hwpx_image_extent_type",
                    "HWPX image insertion extents must be integers.",
                )
        if not isinstance(insertion.image, (bytes, bytearray)):
            raise DocumentNormalizationError(
                "hwpx_image_request",
                "HWPX image insertion payloads must be bytes.",
            )


def _canonical_image(insertion: HwpxImageInsertion) -> _CanonicalImage:
    """Run one payload through Core's image authority and demand canonical PNG.

    Inspection runs first so a format this slice has not decided about — WEBP,
    GIF, a truncated PNG — is refused *before* the transform, and so the receipt
    can report the format the caller really supplied. The transform then does
    the only decode and the only encode in this module, with metadata removed
    and EXIF orientation applied, so two callers with the same bytes always get
    the same PNG.
    """

    payload = bytes(insertion.image)
    try:
        inspection = inspect_image(payload)
        if inspection.format.lower() not in HWPX_IMAGE_INPUT_FORMATS:
            raise DocumentNormalizationError(
                "hwpx_image_format_unsupported",
                "HWPX image insertion admits PNG and JPEG input only.",
            )
        if inspection.multi_frame:
            raise DocumentNormalizationError(
                "hwpx_image_multiframe_refused",
                "HWPX image insertion refuses a multi-frame image.",
            )
        output = transform_image(payload, output_format="PNG")
    except ImageContractError as error:
        # A Core image refusal is already a bounded, stable code. Carrying it
        # through unchanged keeps one vocabulary of image failure reasons
        # instead of wrapping every decode failure in a second one.
        raise DocumentNormalizationError(error.code, str(error)) from error

    png = output.data
    if len(png) > MAX_HWPX_IMAGE_BYTES:
        raise DocumentNormalizationError(
            "hwpx_image_bytes_limit",
            "Canonical HWPX image exceeds the per-entry size limit.",
        )
    return _CanonicalImage(
        png=png,
        source_format=inspection.format,
        width_px=output.width,
        height_px=output.height,
    )


def _draw_extent(insertion: HwpxImageInsertion, image: _CanonicalImage) -> tuple[int, int]:
    """Decide the draw extent, deriving whatever the caller left unset.

    With neither extent given the image is drawn at its own pixel size. With one
    extent given the other is derived from the source aspect ratio, so a caller
    can constrain a single axis without restating the ratio. The result is
    passed through the section producer's own picture bound before it is used,
    so this decision cannot exceed what the producer would accept.
    """

    if insertion.width_hwpunit is None and insertion.height_hwpunit is None:
        return (
            image.width_px * _HWPUNIT_PER_PIXEL,
            image.height_px * _HWPUNIT_PER_PIXEL,
        )
    if insertion.width_hwpunit is not None and insertion.height_hwpunit is not None:
        return insertion.width_hwpunit, insertion.height_hwpunit
    if insertion.width_hwpunit is not None:
        return (
            insertion.width_hwpunit,
            max(1, round(insertion.width_hwpunit * image.height_px / image.width_px)),
        )
    assert insertion.height_hwpunit is not None  # narrowed by the two branches above
    return (
        max(1, round(insertion.height_hwpunit * image.width_px / image.height_px)),
        insertion.height_hwpunit,
    )


def _used_id_tokens(members: tuple[HwpxPackageMember, ...]) -> set[str]:
    """Collect every ``BIN####`` token the package exposes, from all sources.

    Four sources are scanned, matching the four places a binary item id can
    already exist: member names (which carry the ``BinData`` stems), the manifest
    bytes, the header bytes, and every section part's bytes. The scan is a
    byte-level token match rather than an attribute walk on purpose — it needs no
    XML parser, it cannot be confused by entity encoding or attribute order, and
    it over-approximates. Over-approximating costs a skipped id;
    under-approximating would let an allocated id shadow a caller's existing
    image.
    """

    used: set[str] = set()
    for member in members:
        used.update(token.decode("ascii") for token in _ID_TOKEN.findall(member.name.encode("utf-8")))
        used.update(token.decode("ascii") for token in _ID_TOKEN.findall(member.payload))
    return used


def _allocate_item_ids(count: int, used: set[str]) -> tuple[str, ...]:
    """Return the lowest ``count`` unused ``BIN####`` ids, in order.

    Allocation starts at one and takes the first free integer, so the same
    package and the same request always produce the same ids, and inserting into
    a package that already carries ``BIN0001`` yields ``BIN0002`` rather than
    colliding. The search space is bounded by the ``BIN####`` grammar itself, so
    exhaustion is a refusal rather than an unbounded loop.
    """

    allocated: list[str] = []
    candidate = 1
    while len(allocated) < count:
        if candidate > 9999:
            raise DocumentNormalizationError(
                "hwpx_image_id_exhausted",
                "HWPX image insertion exhausted the binary item id space.",
            )
        item_id = f"BIN{candidate:04d}"
        if item_id not in used:
            allocated.append(item_id)
            used.add(item_id)
        candidate += 1
    return tuple(allocated)


def _require_manifest(members: tuple[HwpxPackageMember, ...]) -> HwpxPackageMember:
    """Locate the single manifest member this authority is able to patch.

    A package without a manifest is outside the supported subset and is refused
    rather than given one: creating ``content.hpf`` is the from-scratch writer's
    job, and that writer deliberately owns no binary data, so a manifest
    invented here would be a second package authority.
    """

    matches = [member for member in members if member.name == HWPX_MANIFEST_MEMBER]
    if not matches:
        raise DocumentNormalizationError(
            "hwpx_image_manifest_missing",
            "HWPX image insertion requires a package manifest.",
        )
    if len(matches) > 1:
        raise DocumentNormalizationError(
            "hwpx_image_manifest_ambiguous",
            "HWPX package repeats the manifest member and cannot be extended unambiguously.",
        )
    manifest = matches[0]
    # The splice writes an ``opf:``-prefixed element, so the prefix must be the
    # one bound to the package namespace. Without this the result would be
    # well-formed but meaningless, which is worse than a refusal.
    if f'xmlns:opf="{_OPF_NAMESPACE}"'.encode("ascii") not in manifest.payload:
        raise DocumentNormalizationError(
            "hwpx_image_manifest_unsupported",
            "HWPX package manifest does not declare the package namespace.",
        )
    if manifest.payload.count(_MANIFEST_CLOSE) != 1:
        raise DocumentNormalizationError(
            "hwpx_image_manifest_unsupported",
            "HWPX package manifest does not carry a single splice anchor.",
        )
    return manifest


def _splice_before(payload: bytes, anchor: bytes, addition: bytes) -> bytes:
    """Insert ``addition`` immediately before the single ``anchor`` occurrence.

    This is a byte splice, not a parse: it re-serializes nothing, so every byte
    the addition does not touch is preserved exactly. The anchor's uniqueness is
    the caller's precondition, checked before this is reached.
    """

    offset = payload.index(anchor)
    return payload[:offset] + addition + payload[offset:]


def _section_member_for(
    members: tuple[HwpxPackageMember, ...],
    section_number: int,
) -> HwpxPackageMember:
    """Find the member carrying one reader-reported section number."""

    for member in members:
        if hwpx_section_index(member.name) == section_number:
            return member
    raise DocumentNormalizationError(  # pragma: no cover - one archive, one reader
        "hwpx_image_member_set",
        "HWPX image insertion could not locate a section member.",
    )


def insert_hwpx_image(
    payload: bytes,
    insertions: tuple[HwpxImageInsertion, ...],
) -> tuple[bytes, tuple[HwpxImageInsertionReceipt, ...]]:
    """Embed canonical PNG images into an existing HWPX package.

    Returns in-memory ``application/hwp+zip`` bytes plus one bounded receipt per
    insertion, in request order. Every refusal is a
    :class:`DocumentNormalizationError` carrying a bounded Core reason code, and
    no refusal message carries image bytes, raw XML, a member name taken from
    the document or a host path.

    The order of decisions is part of the contract: the source is admitted before
    the caller's instruction is judged, so a malformed instruction cannot return
    ahead of the gate that inspects the source bytes.
    """

    # 1. Source admission. The gate runs inside the accessor, so a malformed,
    #    traversal-shaped, encrypted, DTD-carrying or oversized archive is
    #    refused before any member payload is handed to this module.
    members = read_hwpx_package_members(payload)
    if len({member.name for member in members}) != len(members):
        raise DocumentNormalizationError(
            "hwpx_image_duplicate_member",
            "HWPX package repeats a member name and cannot be extended unambiguously.",
        )

    # The reader's own ordered section list is the address space, the same one
    # the package-preserving mutator uses. The number, not the position, is what
    # the naming predicate recognizes, so both are carried.
    parsed = parse_hwpx_sections(payload)
    section_numbers = tuple(section.index for section in parsed)

    # 2. The instruction is judged only once the source has been admitted.
    _require_bounded_request(insertions)

    # 3. Addresses are resolved against the reader's facts.
    for insertion in insertions:
        if insertion.section_index >= len(parsed):
            raise DocumentNormalizationError(
                "hwpx_image_section_missing",
                "HWPX image insertion addresses a section the package does not carry.",
            )

    # 4. The manifest is the one member this authority patches, so its exact
    #    supported shape is established before any image is decoded.
    manifest = _require_manifest(members)

    # 5. Every image goes through Core's image authority first, so a malformed
    #    payload is refused before any package byte is produced.
    images = tuple(_canonical_image(insertion) for insertion in insertions)
    extents = tuple(
        _draw_extent(insertion, image)
        for insertion, image in zip(insertions, images, strict=True)
    )

    # 6. Ids are allocated once, deterministically, from the whole package.
    item_ids = _allocate_item_ids(len(insertions), _used_id_tokens(members))

    # 7. The picture paragraph comes from the section producer, so an inserted
    #    picture is byte-identical to one this Core writes from scratch, and the
    #    producer's own picture bound is the only extent rule there is.
    pictures = tuple(
        serialize_hwpx_picture_paragraph(
            HwpxPicture(
                binary_item_id_ref=item_id,
                width_hwpunit=width,
                height_hwpunit=height,
            )
        )
        for item_id, (width, height) in zip(item_ids, extents, strict=True)
    )

    # 8. Splice. One manifest item in total, and one picture paragraph per
    #    insertion into its own section part. Every other member is copied
    #    verbatim and the new binary members are appended in request order.
    manifest_items = b"".join(
        _MANIFEST_ITEM.format(
            item_id=item_id,
            extension=HWPX_EMBEDDED_IMAGE_EXTENSION,
            media_type=HWPX_EMBEDDED_IMAGE_MEDIA_TYPE,
        ).encode("utf-8")
        for item_id in item_ids
    )
    expected_payloads: dict[str, bytes] = {
        manifest.name: _splice_before(manifest.payload, _MANIFEST_CLOSE, manifest_items)
    }
    # Paragraphs addressed at the same section are gathered in request order and
    # spliced once, so a section's document order is the caller's order rather
    # than the reverse of it. Splicing one paragraph per insertion before the
    # same anchor would stack them in reverse.
    binary_members: list[tuple[str, bytes]] = []
    paragraphs_by_section: dict[str, list[bytes]] = {}
    for insertion, item_id, image, picture in zip(
        insertions, item_ids, images, pictures, strict=True
    ):
        section_member = _section_member_for(members, section_numbers[insertion.section_index])
        paragraphs_by_section.setdefault(section_member.name, []).append(picture)
        binary_members.append(
            (
                f"{HWPX_BIN_DATA_PREFIX}{item_id}.{HWPX_EMBEDDED_IMAGE_EXTENSION}",
                image.png,
            )
        )
    for member in members:
        paragraphs = paragraphs_by_section.get(member.name)
        if not paragraphs:
            continue
        if member.payload.count(_SECTION_CLOSE) != 1:
            raise DocumentNormalizationError(
                "hwpx_image_section_unsupported",
                "HWPX image insertion target section does not carry a single splice anchor.",
            )
        expected_payloads[member.name] = _splice_before(
            member.payload, _SECTION_CLOSE, b"".join(paragraphs)
        )

    sequence: list[tuple[str, bytes]] = [
        (member.name, expected_payloads.get(member.name, member.payload)) for member in members
    ]
    sequence.extend(binary_members)

    output = _assemble_hwpx_package_members(tuple(sequence))
    _verify_insertion(members, output, expected_payloads, binary_members, item_ids)
    return output, tuple(
        HwpxImageInsertionReceipt(
            section_index=insertion.section_index,
            binary_item_id_ref=item_id,
            media_type=HWPX_EMBEDDED_IMAGE_MEDIA_TYPE,
            source_format=image.source_format,
            width_hwpunit=width,
            height_hwpunit=height,
            width_px=image.width_px,
            height_px=image.height_px,
            image_bytes=len(image.png),
        )
        for insertion, item_id, image, (width, height) in zip(
            insertions, item_ids, images, extents, strict=True
        )
    )


def _verify_insertion(
    source: tuple[HwpxPackageMember, ...],
    output: bytes,
    expected_payloads: dict[str, bytes],
    binary_members: list[tuple[str, bytes]],
    item_ids: tuple[str, ...],
) -> None:
    """Prove the preservation and readback contracts about this module's output.

    The output re-enters the same gate and the same accessor the source went
    through. The member-name sequence must be the source sequence plus exactly
    the ``BinData`` members this module appended, and every member payload must
    equal the payload it intended to write — which for every untouched member is
    the source payload, byte for byte. Finally the inserted picture blocks are
    read back through the single HWPX reader's fact layer rather than trusted
    from this module's own bookkeeping, so the ids this module claims to have
    written are the ids the reader actually finds.
    """

    validate_ooxml_archive(output)
    rebuilt = read_hwpx_package_members(output)

    expected_sequence = [
        (member.name, expected_payloads.get(member.name, member.payload)) for member in source
    ] + binary_members
    if [(member.name, member.payload) for member in rebuilt] != expected_sequence:
        raise DocumentNormalizationError(
            "hwpx_image_member_set",
            "HWPX image insertion output does not carry the intended member sequence.",
        )

    facts = read_hwpx_section_facts(output)
    found = {
        block.picture.binary_item_id_ref
        for section in facts
        for block in section.blocks
        if block.kind == "picture" and block.picture is not None
    }
    for item_id in item_ids:
        if item_id not in found:
            raise DocumentNormalizationError(
                "hwpx_image_readback",
                "HWPX image insertion output does not read back as an embedded picture.",
            )

    try:
        extract_hwpx_text(output)
    except DocumentNormalizationError as error:
        # An insertion may not leave the document unreadable through the
        # accepted authorities, so an unreadable result is a refusal.
        raise DocumentNormalizationError(
            "hwpx_image_output_unreadable",
            "HWPX image insertion output is no longer readable text.",
        ) from error


__all__ = [
    "HWPX_BIN_DATA_PREFIX",
    "HWPX_EMBEDDED_IMAGE_EXTENSION",
    "HWPX_EMBEDDED_IMAGE_MEDIA_TYPE",
    "HWPX_IMAGE_INPUT_FORMATS",
    "HWPX_MANIFEST_MEMBER",
    "MAX_HWPX_IMAGE_BYTES",
    "MAX_HWPX_IMAGE_INSERTIONS",
    "HwpxImageInsertion",
    "HwpxImageInsertionReceipt",
    "insert_hwpx_image",
]
