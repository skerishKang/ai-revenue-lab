"""Single bounded package-preserving HWPX mutation authority for Padiem AI Core.

Why this module exists
----------------------
``hwpx_package_serializer`` owns the writable HWPX subset. A package it creates
holds exactly ``mimetype`` plus ``Contents/section<N>.xml``, and its decoder
refuses anything outside that subset. That is the right authority for creating a
document, and it is why the accepted edit foundation proves source fidelity by
requiring ``serialize(deserialize(payload)) == payload`` before it will touch a
package: a package carrying a part the writer does not own is refused rather
than silently rewritten into something smaller.

A supplied template cannot be treated that way. It may carry parts this Core
subset will never model — an unrelated member, or a second section holding
structure the editable model refuses — and those parts must survive an edit
byte-for-byte instead of being canonicalized away. Losing them would destroy the
template the caller supplied.

What this module does
---------------------
It composes the authorities that already exist and owns no primitive of its own:

* Core's single archive gate, ``document_normalization.validate_ooxml_archive``,
  decides admission — path traversal, entry count, per-entry and total size,
  encryption and DTD — before any member is read;
* Core's single raw-member accessor,
  ``document_normalization.read_hwpx_package_members``, returns the admitted
  archive's member payloads in archive order;
* Core's single HWPX reader, ``document_normalization.parse_hwpx_sections``,
  supplies the structural facts, and
  ``document_normalization.hwpx_section_index`` is the reader's own predicate
  for locating a section part, so this module never restates the naming rule;
* Core's single section-XML producer,
  ``hwpx_package_serializer.serialize_hwpx_section_part``, produces the one
  member that is allowed to change;
* Core's single archive writer,
  private ``hwpx_package_serializer._assemble_hwpx_package_members`` seam rebuilds the
  archive from a preserved member sequence;
* the writable-subset judgement is the decoder's own, reached through
  ``hwpx_package_serializer.deserialize_hwpx_package``, so the mutator and the
  decoder can never disagree about what is editable.

What this module deliberately does NOT do
-----------------------------------------
* It parses no XML and walks no archive: this module owns no archive handle, no
  member enumeration, no XML parser and no admission gate of its own. Admission,
  reading and writing are all delegated, and a source scan over this file proves
  it.
* It cannot create a package. It requires an already admitted package, it
  requires the member name sequence to be preserved exactly, and it refuses a
  source whose member names repeat, because such an archive cannot be preserved
  unambiguously. A mutation of a package that does not exist is not expressible.
* No caller supplies raw XML, ZIP member bytes, a member name, an archive path,
  a relationship part, a compression flag or a parser choice. The caller
  supplies a zero-based section/paragraph address and replacement text only.
* No host filesystem read or write, no extraction, no network, no provider and
  no process surface exists here. Everything is in-memory bytes.
* No placeholder syntax, template field semantics, insert or delete, table,
  image, style or layout editing. This is a paragraph-text replacement slice.

Order of decisions
------------------
The source is admitted before the caller's instruction is judged, which is the
principle the accepted HWPX read and edit authorities already established. A
malformed or empty instruction therefore cannot return ahead of the gate that
inspects the source bytes:

1. source admission — archive gate, raw member sequence, structural parse;
2. instruction well-formedness — container, count bound, index types, negatives;
3. address resolvability — section present, paragraph in range, no duplicate;
4. target writability — the decoder's own judgement, over addressed sections only;
5. target byte-shape safety — the addressed part must already be canonical;
6. replacement text content — the single paragraph-text rule;
7. rewrite, assemble, then prove the preservation contract about the output.

The ordering is part of the contract, not an implementation detail.

The preservation contract
-------------------------
The addressed section members are the only members whose bytes may change. Every
other member's payload is copied verbatim, and the member name sequence is
preserved exactly. The output is re-entered through the same gate and the same
accessor before it is returned, so an unproven output is never handed back.

Whole-archive byte identity is not claimed and is not achievable: a
reconstructed archive carries its own local headers, compression records and
central directory. The claim made here is member-payload preservation, which is
the claim that matters for not destroying a supplied template.
"""

from __future__ import annotations

from dataclasses import dataclass

from .document_normalization import (
    HwpxPackageMember,
    extract_hwpx_text,
    hwpx_section_index,
    parse_hwpx_sections,
    read_hwpx_package_members,
    validate_ooxml_archive,
)
from .document_semantics import DocumentNormalizationError
from .hwpx_package_serializer import (
    HWPX_MEDIA_TYPE,
    HwpxPackageSection,
    _assemble_hwpx_package_members,
    deserialize_hwpx_package,
    serialize_hwpx_section_part,
    validate_hwpx_paragraph_text,
)

MAX_HWPX_MUTATIONS = 64

# The wrapper used only to offer one raw section part to the single decoder. It
# is an internal probe, never an output member name, and the decoder accepts it
# because it is the canonical first-section name the writer itself emits.
_PROBE_MEMBER_NAME = "Contents/section1.xml"

# The single decoder judges a *package*, not a part: it refuses a package whose
# text is entirely unreadable. A probe carrying only the addressed part would
# therefore apply that package-level rule as if it were a part-level rule, and a
# section whose own paragraphs are all blank would be refused even though the
# package it belongs to is readable — and even though the single writer can
# create exactly such a package. The probe therefore carries a constant readable
# companion section, so the decoder judges the addressed part instead of the
# probe's own emptiness. The companion exists only inside this wrapper and can
# never reach an output: the output is assembled from the source member
# sequence, which this module never adds to.
_PROBE_COMPANION_MEMBER_NAME = "Contents/section2.xml"
_PROBE_COMPANION_TEXT = "padiem-hwpx-mutation-probe"


@dataclass(frozen=True, slots=True)
class HwpxParagraphMutation:
    """One bounded paragraph-text replacement at a zero-based address.

    ``section_index`` is the zero-based position of the section in the ordered
    list the accepted reader produces (ascending section number), and
    ``paragraph_index`` is the zero-based position of the paragraph within that
    section. Both address spaces are the ones the accepted edit foundation
    already uses, so the same address means the same paragraph in either
    authority. The value carries no authority of its own — it enforces
    nothing — and :func:`mutate_hwpx_package_preserving_members` is the single
    place the contract is judged, so a malformed operation becomes one bounded
    refusal instead of an exception escaping an intermediate object.
    """

    section_index: int
    paragraph_index: int
    text: str


def _require_preservable_member_sequence(
    members: tuple[HwpxPackageMember, ...],
) -> None:
    """Refuse a source whose member sequence cannot be preserved unambiguously."""

    if not members:
        raise DocumentNormalizationError(
            "hwpx_mutation_member_set",
            "HWPX package has no members to preserve.",
        )
    names = [member.name for member in members]
    if len(set(names)) != len(names):
        raise DocumentNormalizationError(
            "hwpx_mutation_duplicate_member",
            "HWPX package repeats a member name and cannot be preserved unambiguously.",
        )


def _require_bounded_request(mutations: object) -> None:
    """Judge the instruction container before any address is looked at."""

    if not isinstance(mutations, tuple) or not mutations:
        raise DocumentNormalizationError(
            "hwpx_mutation_request",
            "HWPX mutation requires a non-empty tuple of paragraph mutations.",
        )
    if len(mutations) > MAX_HWPX_MUTATIONS:
        raise DocumentNormalizationError(
            "hwpx_mutation_limit",
            "HWPX mutation exceeds the bounded operation count.",
        )
    for mutation in mutations:
        if not isinstance(mutation, HwpxParagraphMutation):
            raise DocumentNormalizationError(
                "hwpx_mutation_request",
                "HWPX mutation operations must be HwpxParagraphMutation values.",
            )
        for value in (mutation.section_index, mutation.paragraph_index):
            # ``bool`` is an ``int`` subclass; an index is never a flag.
            if isinstance(value, bool) or not isinstance(value, int):
                raise DocumentNormalizationError(
                    "hwpx_mutation_index_type",
                    "HWPX mutation indexes must be integers.",
                )
            if value < 0:
                raise DocumentNormalizationError(
                    "hwpx_mutation_index_negative",
                    "HWPX mutation indexes are zero-based and cannot be negative.",
                )
        if not isinstance(mutation.text, str):
            raise DocumentNormalizationError(
                "hwpx_mutation_request",
                "HWPX mutation replacement text must be a string.",
            )


def _addressed_sections(
    mutations: tuple[HwpxParagraphMutation, ...],
    facts: dict[int, int],
) -> tuple[int, ...]:
    """Resolve every address against the reader's own structural facts.

    ``facts`` maps a zero-based section *position* to that section's paragraph
    count, taken from the single reader — not from a decode — so an address is
    judged before the section is required to be writable. Position is the
    ordering the reader itself produces (ascending section number), which is the
    same address space the accepted edit foundation uses.
    """

    seen: set[tuple[int, int]] = set()
    addressed: list[int] = []
    for mutation in mutations:
        target = (mutation.section_index, mutation.paragraph_index)
        if target in seen:
            # A repeated address is refused rather than resolved by request
            # order, so the result never depends on how the tuple was built.
            raise DocumentNormalizationError(
                "hwpx_mutation_duplicate_target",
                "HWPX mutation repeats an address.",
            )
        seen.add(target)
        paragraph_count = facts.get(mutation.section_index)
        if paragraph_count is None:
            raise DocumentNormalizationError(
                "hwpx_mutation_section_missing",
                "HWPX mutation addresses a section the package does not carry.",
            )
        if mutation.paragraph_index >= paragraph_count:
            raise DocumentNormalizationError(
                "hwpx_mutation_paragraph_missing",
                "HWPX mutation addresses a paragraph the section does not carry.",
            )
        if mutation.section_index not in addressed:
            addressed.append(mutation.section_index)
    return tuple(addressed)


def _decode_section(part: bytes) -> HwpxPackageSection:
    """Offer one raw section part to the single decoder and keep its model.

    The judgement is the decoder's, not a copy of it: the part is wrapped as a
    package by the single archive writer and decoded by the single decoder, so
    this module accepts exactly what the decoder accepts — including its
    refusals for tables, images, shapes, nested paragraphs, multiple run text
    nodes, a foreign section root and a carriage return.

    The wrapper carries a constant readable companion section because the
    decoder's readable-text rule is a package rule, not a part rule. Without it
    a section whose own paragraphs happen to be all blank — a shape the single
    writer itself produces — would be refused here as if the part were invalid.
    Only ``sections[0]``, the addressed part, is returned.
    """

    probe = _assemble_hwpx_package_members(
        (
            ("mimetype", HWPX_MEDIA_TYPE.encode("ascii")),
            (_PROBE_MEMBER_NAME, part),
            (
                _PROBE_COMPANION_MEMBER_NAME,
                serialize_hwpx_section_part((_PROBE_COMPANION_TEXT,)),
            ),
        )
    )
    return deserialize_hwpx_package(probe).sections[0]


def _intended_paragraphs(
    mutations: tuple[HwpxParagraphMutation, ...],
    models: dict[int, HwpxPackageSection],
) -> dict[int, tuple[str, ...]]:
    """Apply every addressed replacement to a copy of the decoded model."""

    intended: dict[int, tuple[str, ...]] = {}
    for mutation in mutations:
        current = intended.get(
            mutation.section_index, models[mutation.section_index].paragraphs
        )
        paragraphs = list(current)
        paragraphs[mutation.paragraph_index] = mutation.text
        intended[mutation.section_index] = tuple(paragraphs)
    return intended


def mutate_hwpx_package_preserving_members(
    payload: bytes,
    mutations: tuple[HwpxParagraphMutation, ...],
) -> bytes:
    """Replace addressed paragraph text, preserving every other member byte-for-byte.

    Returns in-memory ``application/hwp+zip`` bytes. Every refusal is a
    :class:`DocumentNormalizationError` carrying a bounded Core reason code, and
    no refusal message carries document text, raw XML, a member name taken from
    the document or a host path.

    The addressed section part must already be byte-identical to what the single
    section producer emits for its own decoded paragraphs. Without that
    requirement a structurally representable part carrying an attribute, a
    spacing or an equivalent alternative serialization would be rewritten into
    the canonical shape and lose it. With it, the only bytes the rewrite can
    introduce are the addressed paragraph texts.
    """

    # 1. Source admission. The gate runs inside the accessor, so a malformed,
    #    traversal-shaped, encrypted, DTD-carrying or oversized archive is
    #    refused before any member payload is handed to this module.
    members = read_hwpx_package_members(payload)
    _require_preservable_member_sequence(members)

    parsed = parse_hwpx_sections(payload)
    # An address is the zero-based position in the reader's own ordered section
    # list, which is the same address space the accepted edit foundation uses.
    facts = {position: len(section.paragraphs) for position, section in enumerate(parsed)}
    member_for_position: dict[int, HwpxPackageMember] = {}
    for position, section in enumerate(parsed):
        for member in members:
            if hwpx_section_index(member.name) == section.index:
                member_for_position[position] = member
                break
        else:  # pragma: no cover - the reader and the accessor saw one archive
            raise DocumentNormalizationError(
                "hwpx_mutation_member_set",
                "HWPX package section part could not be located in the member sequence.",
            )

    # 2. The instruction is judged only once the source has been admitted.
    _require_bounded_request(mutations)

    # 3. Addresses are resolved against the reader's facts.
    addressed = _addressed_sections(mutations, facts)

    # 4. Only an addressed section has to fit the writable subset. Every other
    #    member — including a section part this model cannot represent — is
    #    preserved verbatim instead of being decoded.
    models = {
        position: _decode_section(member_for_position[position].payload)
        for position in addressed
    }

    # 5. The addressed part must already be in the canonical byte shape, so the
    #    rewrite cannot silently normalize away something the model omits.
    for position in addressed:
        if member_for_position[position].payload != serialize_hwpx_section_part(
            models[position].paragraphs
        ):
            raise DocumentNormalizationError(
                "hwpx_mutation_target_not_canonical",
                "HWPX mutation target part is not in the canonical byte shape.",
            )

    # 6. The replacement text is judged by the single paragraph-text rule.
    for mutation in mutations:
        validate_hwpx_paragraph_text(mutation.text)

    # 7. Rewrite only the addressed members; copy every other payload verbatim.
    intended = _intended_paragraphs(mutations, models)
    targets = {
        member_for_position[position].name: intended[position] for position in intended
    }
    sequence: list[tuple[str, bytes]] = []
    for member in members:
        if member.name in targets:
            sequence.append((member.name, serialize_hwpx_section_part(targets[member.name])))
        else:
            sequence.append((member.name, member.payload))

    output = _assemble_hwpx_package_members(tuple(sequence))
    _verify_preservation(members, output, targets)
    return output


def _verify_preservation(
    source: tuple[HwpxPackageMember, ...],
    output: bytes,
    targets: dict[str, tuple[str, ...]],
) -> None:
    """Prove the preservation contract about this module's own output.

    The output re-enters the same gate and the same accessor the source went
    through, and is then checked member by member against the source sequence
    and against the intended target model. A mismatch raises instead of
    returning bytes whose provenance is unproven.
    """

    validate_ooxml_archive(output)
    rebuilt = read_hwpx_package_members(output)

    if [member.name for member in rebuilt] != [member.name for member in source]:
        raise DocumentNormalizationError(
            "hwpx_mutation_member_set",
            "HWPX mutation output changed the package member sequence.",
        )

    for original, produced in zip(source, rebuilt):
        if original.name in targets:
            continue
        if original.payload != produced.payload:
            raise DocumentNormalizationError(
                "hwpx_mutation_member_payload",
                "HWPX mutation output changed a member it had to preserve.",
            )

    for name, paragraphs in targets.items():
        produced = next(
            (member.payload for member in rebuilt if member.name == name),
            None,
        )
        if produced != serialize_hwpx_section_part(paragraphs):
            raise DocumentNormalizationError(
                "hwpx_mutation_target_drift",
                "HWPX mutation output does not carry the intended target paragraphs.",
            )
        # Read the target back through the decoder rather than trusting this
        # module's own byte comparison.
        if _decode_section(produced).paragraphs != paragraphs:
            raise DocumentNormalizationError(
                "hwpx_mutation_target_drift",
                "HWPX mutation output does not carry the intended target paragraphs.",
            )

    try:
        extract_hwpx_text(output)
    except DocumentNormalizationError as error:
        # A mutation may not leave the document unreadable through the accepted
        # authorities, so an unreadable result is a refusal, not a success.
        raise DocumentNormalizationError(
            "hwpx_mutation_output_unreadable",
            "HWPX mutation output is no longer readable text.",
        ) from error


__all__ = [
    "MAX_HWPX_MUTATIONS",
    "HwpxParagraphMutation",
    "mutate_hwpx_package_preserving_members",
]
