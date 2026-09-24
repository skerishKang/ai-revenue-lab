"""#2937/#2962/#2972/#2989: bounded native HWPX Skill facade.

Surfaces: inspect / read / validate / create / edit / insert_table / template_fill.

This module is a facade and receipt layer over authorities that already exist
and are already accepted. It introduces no ZIP walker, no XML parser, no
serializer, no host filesystem write or extraction, no network/provider call
and no new runtime dependency.

Composition order (the common gate always runs first)::

    raw HWPX bytes
    -> kagent.file_intake_safety.inspect_file()      (#2824 common gate)
    -> truthful HWPX_CANDIDATE (content, never extension-only)
    -> kagent.document_intake.intake_document()      (routing + isolated Core parse)
    -> bounded HWPX Skill receipt

``hwpx.create`` composes those same accepted authorities in the other
direction::

    bounded structured content (Core HwpxPackageContent, #2941 model)
    -> padiem_ai_core.hwpx_package_serializer.serialize_hwpx_package()
    -> in-memory HWPX bytes (never written to the host filesystem)
    -> inspect_file()      (the common gate must return HWPX_CANDIDATE)
    -> hwpx_validate()     (existing validate authority)
    -> hwpx_read()         (existing read authority)
    -> exact round-trip text equality
    -> bounded create receipt + in-memory artifact

``hwpx.edit`` (#2972) composes the same accepted authorities over an existing
package::

    caller filename + HWPX bytes + zero-based paragraph replacements
    -> inspect_file()                            (common gate, HWPX_CANDIDATE)
    -> deserialize_hwpx_package()                (single structured decoder)
    -> serialize_hwpx_package(source) == input   (canonical-lossless gate)
    -> bounded replacement targets validated
    -> serialize_hwpx_package(edited model)      (single byte producer)
    -> inspect_file() / hwpx_validate() / hwpx_read() on the output
    -> deserialize_hwpx_package() on the output
    -> structured equality with the intended model
    -> bounded edit receipt + in-memory artifact

The edit foundation remains narrow: paragraph replacement uses an exact
zero-based section/paragraph address only. Bounded table insertion is a separate
operation over the same reserved edit capability and canonical block model; it
adds no table edit/delete, row/column mutation, image, style or layout authority,
no second parser and no second byte producer.

``hwpx.insert_table`` (#3034) accepts only a bounded rectangular rows request and
an exact zero-based section/block insertion position::

    caller filename + HWPX bytes + section_index + block_index + rows
    -> inspect_file()                            (common gate, HWPX_CANDIDATE)
    -> deserialize_hwpx_package()                (single structured decoder)
    -> canonical source byte round trip
    -> bounded request validation
    -> one table block inserted into the ordered Core model
    -> serialize_hwpx_package()                  (single byte producer)
    -> inspect_file() / hwpx_validate() / hwpx_read() on the output
    -> deserialize_hwpx_package() and exact placement/preservation proof
    -> bounded insert_table receipt + in-memory artifact

``hwpx.template_fill`` (#2989) is the first bounded template-fill facade. It
reuses the single #2979 package-preserving mutation authority so a supplied
template survives byte-for-byte::

    caller filename + HWPX template bytes + field mapping
    -> inspect_file()                            (common gate, HWPX_CANDIDATE)
    -> mutate_hwpx_package_preserving_members()  (#2979 single mutator authority)
    -> inspect_file() / hwpx_validate() / hwpx_read() on the output
    -> deserialize_hwpx_package() on the output
    -> structured equality with the intended filled model
    -> bounded template_fill receipt + in-memory artifact

The smallest deterministic placeholder grammar
---------------------------------------------
No canonical placeholder grammar existed before this child, so the smallest one
that is deterministic and testable is defined here and nowhere else. It is a
scanner rule, not a document-wide templating language:

* A placeholder is exactly ``{{`` + field name + ``}}``. Both delimiters are
  literal and fixed; there is no alternative delimiter, no configurable
  syntax, no whitespace-padded form, no nesting and no recursive expansion.
* A field name is one or more characters from a tiny class: a Unicode
  alphanumeric character (Hangul, Latin or digit, so a Korean business
  template may name a field in Korean) or ``_``, ``.`` or ``-``. The class
  excludes whitespace, both delimiters and every control character, so a field
  name can never carry or terminate its own token. A field name is
  case-sensitive and one to :data:`MAX_TEMPLATE_FIELD_NAME_CHARS` characters
  long.
* ``{{`` and ``}}`` are individual literal characters. A ``{{`` whose body
  does not satisfy the field-name rule is decoration, not a placeholder, and is
  copied through verbatim. There is no escaping rule and no escape sequence,
  because one would enlarge the grammar without a product need.
* There is no partial fill: either every named field is substituted or the
  whole request is refused with no artifact, so a filled document can never
  contain a half-substituted placeholder.
* A field name is replaced by its value everywhere it appears. A template
  whose paragraph repeats one field name is filled deterministically, because
  the second appearance resolves to the same value instead of being treated as
  ambiguous.

Grammar bound: this is a bounded first slice over ordinary paragraph text
only. It is explicitly **not** a document-wide templating language: no
conditionals, no loops, no partial inclusion, no format specifiers and no
region or block markers.

Authority boundaries
--------------------
- ``inspect_file`` remains the single archive/path/expansion/MIME gate
  (``SECOND_ARCHIVE_GATE_AUTHORITY=0``).
- Core ``extract_hwpx_text`` (via ``intake_document``'s isolated parser
  boundary) remains the single HWPX text parser
  (``SECOND_HWPX_PARSER_AUTHORITY=0``, ``SECOND_XML_AUTHORITY=0``).
- Core ``serialize_hwpx_package`` remains the single HWPX byte producer
  (``SINGLE_HWPX_SERIALIZER_AUTHORITY=YES``,
  ``SECOND_HWPX_SERIALIZER_AUTHORITY=0``). The facade accepts only the
  structured ``HwpxPackageContent`` model: raw XML, ZIP member names, archive
  paths, namespace URIs, mimetype content, compression choice and serializer
  limits all stay outside caller authority, and no XML or ZIP assembly exists
  here.
- Core ``mutate_hwpx_package_preserving_members`` (#2979) remains the single
  package-preserving mutation authority and the single template-fill mutator.
  ``hwpx.template_fill`` composes it and adds no archive walker, no member
  enumeration, no XML parser and no second byte producer of its own
  (``PACKAGE_PRESERVATION_AUTHORITY_REUSED=YES``,
  ``SECOND_HWPX_MUTATOR_AUTHORITY=0``).
- ``CREATE_SUCCESS_REQUIRES_ROUNDTRIP=YES``: generated bytes are reported as
  success only after the common gate admitted them as ``HWPX_CANDIDATE``, the
  existing validate and read authorities accepted them, and the readback text
  equals the requested text exactly. A refusal at any stage fails closed with
  a bounded reason code and never falls back to another format.
- ``TEMPLATE_FILL_SUCCESS_REQUIRES_PRESERVATION=YES``: filled bytes are
  reported as success only after the common gate admitted the output as
  ``HWPX_CANDIDATE``, the existing validate and read authorities accepted it,
  the output was re-decoded and matched the intended filled model paragraph by
  paragraph, and every non-target member payload was proven byte-identical to
  the supplied template.
- The file extension is advisory; admission requires the gate's
  ``HWPX_CANDIDATE`` decision (``DIRECT_EXTENSION_AUTHORITY=NO``).
- Receipts expose bounded metadata and bounded reason vocabulary only: never
  raw ZIP member names, raw XML, payload bytes or host paths. The create
  artifact, which does carry the generated bytes for artifact handoff, stays
  outside the public projection, and no host filesystem write happens at all.

Capability mapping uses existing reserved ids — no Skill Registry edit:
``hwpx.inspect`` foundation is served under ``CAPABILITY_FILE_INSPECT``
(``file.inspect``), ``hwpx.read`` under ``CAPABILITY_HWPX_READ``,
``hwpx.validate`` under ``CAPABILITY_HWPX_VALIDATE``, ``hwpx.create`` under
``CAPABILITY_HWPX_CREATE``, both ``hwpx.edit`` and bounded
``hwpx.insert_table`` under ``CAPABILITY_HWPX_EDIT``, and
``hwpx.template_fill`` under the already reserved
``CAPABILITY_HWPX_TEMPLATE_FILL``.

Scope honesty (#2825 parent remains OPEN): ``hwpx.create`` is a foundation over
bounded plain section/paragraph text, ``hwpx.edit`` is a foundation over
bounded paragraph replacement, ``hwpx.insert_table`` inserts one bounded
rectangular Core table block at an exact section/block position, and
``hwpx.template_fill`` is a foundation over the smallest deterministic
placeholder grammar defined above. None implements paragraph/section insert or
delete, existing-table edit/delete, row/column mutation, image insertion, style
or layout editing, or legacy HWP conversion; none produces style- or
specification-complete HWPX; and none enables document export
(``HWPX_FULL_SPEC_SUPPORT=NO``, ``DOCUMENT_EXPORT_HWPX_ENABLED=NO``).
Validation scope stays package gate admission plus Core text extraction
(``VALIDATION_SCOPE_GATE_AND_TEXT``); full HWPX specification conformance is
never claimed (``full_spec_support_claimed=False`` on every validate receipt).
"""

from __future__ import annotations

from dataclasses import dataclass

from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.hwpx_package_mutation import (
    HwpxParagraphMutation,
    mutate_hwpx_package_preserving_members,
)
from padiem_ai_core.hwpx_package_serializer import (
    MAX_HWPX_TABLE_CELLS,
    MAX_HWPX_TABLE_COLUMNS,
    MAX_HWPX_TABLE_ROWS,
    HwpxPackageContent,
    HwpxPackageSection,
    HwpxSectionBlock,
    HwpxTable,
    HwpxTableCell,
    deserialize_hwpx_package,
    serialize_hwpx_package,
    validate_hwpx_paragraph_text,
)

from .claw_skill_registry import (
    CAPABILITY_FILE_INSPECT,
    CAPABILITY_HWPX_CREATE,
    CAPABILITY_HWPX_EDIT,
    CAPABILITY_HWPX_READ,
    CAPABILITY_HWPX_TEMPLATE_FILL,
    CAPABILITY_HWPX_VALIDATE,
)
from .document_intake import intake_document
from .document_parser_contract import is_bounded_reason_code
from .file_intake_safety import (
    DetectedFormat,
    FileIntakeResult,
    inspect_file,
    sanitize_filename,
)

__all__ = [
    "ACCEPTANCE",
    "DEFAULT_CREATE_FILENAME",
    "HWPX_MEDIA_TYPE",
    "HWPX_SUFFIX",
    "MAX_CREATE_FILENAME_CHARS",
    "MAX_EDIT_OPERATIONS",
    "MAX_TEMPLATE_FIELDS",
    "MAX_TEMPLATE_FIELD_NAME_CHARS",
    "PLACEHOLDER_CLOSE",
    "PLACEHOLDER_OPEN",
    "REASON_CONTENT_MISMATCH",
    "REASON_CREATE_GATE_REJECTED",
    "REASON_CREATE_READBACK_REJECTED",
    "REASON_CREATE_ROUNDTRIP_MISMATCH",
    "REASON_CREATE_SERIALIZER_REJECTED",
    "REASON_CREATE_VALIDATE_REJECTED",
    "REASON_EDIT_DUPLICATE_TARGET",
    "REASON_EDIT_GATE_REJECTED",
    "REASON_EDIT_INDEX_NEGATIVE",
    "REASON_EDIT_OPERATIONS_INVALID",
    "REASON_EDIT_OPERATIONS_LIMIT",
    "REASON_EDIT_OPERATION_SHAPE",
    "REASON_EDIT_OUTPUT_COUNT_DRIFT",
    "REASON_EDIT_OUTPUT_GATE_REJECTED",
    "REASON_EDIT_OUTPUT_NON_TARGET_DRIFT",
    "REASON_EDIT_OUTPUT_READBACK_REJECTED",
    "REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH",
    "REASON_EDIT_OUTPUT_VALIDATE_REJECTED",
    "REASON_EDIT_PARAGRAPH_OUT_OF_RANGE",
    "REASON_EDIT_SECTION_OUT_OF_RANGE",
    "REASON_EDIT_SERIALIZER_REJECTED",
    "REASON_EDIT_SOURCE_DECODER_REJECTED",
    "REASON_EDIT_SOURCE_NOT_CANONICAL",
    "REASON_EDIT_TEXT_REJECTED",
    "REASON_INSERT_TABLE_BLOCK_INDEX_NEGATIVE",
    "REASON_INSERT_TABLE_BLOCK_OUT_OF_RANGE",
    "REASON_INSERT_TABLE_CELL_LIMIT",
    "REASON_INSERT_TABLE_CELL_TEXT_REJECTED",
    "REASON_INSERT_TABLE_COLUMN_LIMIT",
    "REASON_INSERT_TABLE_GATE_REJECTED",
    "REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT",
    "REASON_INSERT_TABLE_OUTPUT_DECODER_REJECTED",
    "REASON_INSERT_TABLE_OUTPUT_GATE_REJECTED",
    "REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT",
    "REASON_INSERT_TABLE_OUTPUT_READBACK_REJECTED",
    "REASON_INSERT_TABLE_OUTPUT_ROUNDTRIP_MISMATCH",
    "REASON_INSERT_TABLE_OUTPUT_TABLE_MISMATCH",
    "REASON_INSERT_TABLE_OUTPUT_VALIDATE_REJECTED",
    "REASON_INSERT_TABLE_REQUEST_SHAPE",
    "REASON_INSERT_TABLE_ROWS_EMPTY",
    "REASON_INSERT_TABLE_ROWS_RAGGED",
    "REASON_INSERT_TABLE_ROW_LIMIT",
    "REASON_INSERT_TABLE_SECTION_INDEX_NEGATIVE",
    "REASON_INSERT_TABLE_SECTION_OUT_OF_RANGE",
    "REASON_INSERT_TABLE_SERIALIZER_REJECTED",
    "REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED",
    "REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL",
    "REASON_INTAKE_REJECTED",
    "REASON_TEMPLATE_FIELDS_INVALID",
    "REASON_TEMPLATE_FIELDS_LIMIT",
    "REASON_TEMPLATE_FIELD_DUPLICATE",
    "REASON_TEMPLATE_FIELD_NAME_INVALID",
    "REASON_TEMPLATE_FIELD_UNUSED",
    "REASON_TEMPLATE_FIELD_VALUE_INVALID",
    "REASON_TEMPLATE_FIELD_VALUE_REJECTED",
    "REASON_TEMPLATE_GATE_REJECTED",
    "REASON_TEMPLATE_OUTPUT_COUNT_DRIFT",
    "REASON_TEMPLATE_OUTPUT_GATE_REJECTED",
    "REASON_TEMPLATE_OUTPUT_MEMBER_DRIFT",
    "REASON_TEMPLATE_OUTPUT_READBACK_REJECTED",
    "REASON_TEMPLATE_OUTPUT_ROUNDTRIP_MISMATCH",
    "REASON_TEMPLATE_OUTPUT_VALIDATE_REJECTED",
    "REASON_TEMPLATE_SOURCE_DECODER_REJECTED",
    "REASON_TEMPLATE_SOURCE_NOT_CANONICAL",
    "REASON_TEMPLATE_TARGET_UNSUPPORTED",
    "REASON_TEMPLATE_UNFILLED_FIELD",
    "STATUS_OK",
    "STATUS_REFUSED",
    "VALIDATION_SCOPE_GATE_AND_TEXT",
    "VALIDATION_STATUS_EDIT_NOT_RUN",
    "VALIDATION_STATUS_EDIT_OK",
    "VALIDATION_STATUS_EDIT_OPERATIONS_REFUSED",
    "VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH",
    "VALIDATION_STATUS_EDIT_OUTPUT_REFUSED",
    "VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED",
    "VALIDATION_STATUS_EDIT_SOURCE_NOT_CANONICAL",
    "VALIDATION_STATUS_EDIT_SOURCE_REFUSED",
    "VALIDATION_STATUS_GATE_REFUSED",
    "VALIDATION_STATUS_INSERT_TABLE_NOT_RUN",
    "VALIDATION_STATUS_INSERT_TABLE_OK",
    "VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH",
    "VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED",
    "VALIDATION_STATUS_INSERT_TABLE_REQUEST_REFUSED",
    "VALIDATION_STATUS_INSERT_TABLE_SERIALIZER_REFUSED",
    "VALIDATION_STATUS_INSERT_TABLE_SOURCE_NOT_CANONICAL",
    "VALIDATION_STATUS_INSERT_TABLE_SOURCE_REFUSED",
    "VALIDATION_STATUS_NOT_RUN",
    "VALIDATION_STATUS_READBACK_REFUSED",
    "VALIDATION_STATUS_ROUNDTRIP_MISMATCH",
    "VALIDATION_STATUS_ROUNDTRIP_OK",
    "VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH",
    "VALIDATION_STATUS_TEMPLATE_FILL_NOT_RUN",
    "VALIDATION_STATUS_TEMPLATE_FILL_OK",
    "VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED",
    "VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED",
    "VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED",
    "VALIDATION_STATUS_VALIDATE_REFUSED",
    "HwpxCreateArtifact",
    "HwpxCreateReceipt",
    "HwpxCreateResult",
    "HwpxEditArtifact",
    "HwpxEditReceipt",
    "HwpxEditResult",
    "HwpxGateMetadata",
    "HwpxInsertTableArtifact",
    "HwpxInsertTableReceipt",
    "HwpxInsertTableResult",
    "HwpxInspectReceipt",
    "HwpxParagraphReplacement",
    "HwpxReadReceipt",
    "HwpxTableInsertionRequest",
    "HwpxTemplateFillArtifact",
    "HwpxTemplateFillReceipt",
    "HwpxTemplateFillResult",
    "HwpxValidateReceipt",
    "REASON_HWpx_ROUTE_REQUIRED",
    "hwpx_create",
    "hwpx_edit",
    "hwpx_insert_table",
    "hwpx_inspect",
    "hwpx_read",
    "hwpx_template_fill",
    "hwpx_validate",
]

HWPX_MEDIA_TYPE = "application/hwp+zip"
HWPX_SUFFIX = ".hwpx"

STATUS_OK = "ok"
STATUS_REFUSED = "refused"

REASON_CONTENT_MISMATCH = "content_mismatch"
REASON_HWpx_ROUTE_REQUIRED = "hwpx_route_required"
REASON_INTAKE_REJECTED = "intake_rejected"

#: Bounded ``hwpx.create`` refusal vocabulary. Each code names the stage that
#: refused; the underlying bounded code of that stage travels in the receipt
#: ``note``, never as free text.
REASON_CREATE_SERIALIZER_REJECTED = "create_serializer_rejected"
REASON_CREATE_GATE_REJECTED = "create_gate_rejected"
REASON_CREATE_VALIDATE_REJECTED = "create_validate_rejected"
REASON_CREATE_READBACK_REJECTED = "create_readback_rejected"
REASON_CREATE_ROUNDTRIP_MISMATCH = "create_roundtrip_mismatch"

#: Post-create verification outcome. ``roundtrip_ok`` is the only value that
#: may accompany a successful create: the common gate admitted the generated
#: package, the existing validate and read authorities accepted it, and the
#: readback text matched the requested text exactly.
VALIDATION_STATUS_ROUNDTRIP_OK = "roundtrip_ok"
VALIDATION_STATUS_NOT_RUN = "not_run"
VALIDATION_STATUS_GATE_REFUSED = "gate_refused"
VALIDATION_STATUS_VALIDATE_REFUSED = "validate_refused"
VALIDATION_STATUS_READBACK_REFUSED = "readback_refused"
VALIDATION_STATUS_ROUNDTRIP_MISMATCH = "roundtrip_mismatch"

_CREATE_VALIDATION_STATUSES = frozenset(
    {
        VALIDATION_STATUS_ROUNDTRIP_OK,
        VALIDATION_STATUS_NOT_RUN,
        VALIDATION_STATUS_GATE_REFUSED,
        VALIDATION_STATUS_VALIDATE_REFUSED,
        VALIDATION_STATUS_READBACK_REFUSED,
        VALIDATION_STATUS_ROUNDTRIP_MISMATCH,
    }
)

#: Presentation metadata only, and the fallback whenever a caller-supplied
#: name projects onto nothing safe. Nothing here is a package authority.
DEFAULT_CREATE_STEM = "padiem-document"
DEFAULT_CREATE_FILENAME = f"{DEFAULT_CREATE_STEM}{HWPX_SUFFIX}"

#: The sanitizer's sentinel for a name that projected onto no safe character.
_SANITIZED_EMPTY_NAME = "unnamed"

#: Mirrors the Core document-name bound the isolated parser envelope enforces
#: (``padiem_ai_core.document_normalization.MAX_DOCUMENT_NAME_CHARS``). A
#: longer name would be a programmer error at that envelope, so the facade
#: projects every suggested name below this bound. ``test_hwpx_skill_create``
#: asserts this stays at or below the Core value instead of trusting a copy.
MAX_CREATE_FILENAME_CHARS = 120

#: The only validation claim this foundation makes: the common gate admitted
#: the package and the existing Core parser produced (or refused) text.
VALIDATION_SCOPE_GATE_AND_TEXT = "gate_admission_and_text_extraction"

#: One ``hwpx.edit`` request carries at most this many replacements. The bound
#: is explicit and small so an edit stays a bounded operation over an already
#: canonical package rather than a document rewrite.
MAX_EDIT_OPERATIONS = 64

#: Bounded ``hwpx.edit`` refusal vocabulary. Each code names the stage that
#: refused; that stage's own bounded code travels in the receipt ``note``.
REASON_EDIT_OPERATIONS_INVALID = "edit_operations_invalid"
REASON_EDIT_OPERATIONS_LIMIT = "edit_operations_limit"
REASON_EDIT_OPERATION_SHAPE = "edit_operation_shape"
REASON_EDIT_INDEX_NEGATIVE = "edit_index_negative"
REASON_EDIT_SECTION_OUT_OF_RANGE = "edit_section_out_of_range"
REASON_EDIT_PARAGRAPH_OUT_OF_RANGE = "edit_paragraph_out_of_range"
REASON_EDIT_DUPLICATE_TARGET = "edit_duplicate_target"
REASON_EDIT_TEXT_REJECTED = "edit_text_rejected"
REASON_EDIT_GATE_REJECTED = "edit_gate_rejected"
REASON_EDIT_SOURCE_DECODER_REJECTED = "edit_source_decoder_rejected"
REASON_EDIT_SOURCE_NOT_CANONICAL = "edit_source_not_canonical"
REASON_EDIT_SERIALIZER_REJECTED = "edit_serializer_rejected"
REASON_EDIT_OUTPUT_GATE_REJECTED = "edit_output_gate_rejected"
REASON_EDIT_OUTPUT_VALIDATE_REJECTED = "edit_output_validate_rejected"
REASON_EDIT_OUTPUT_READBACK_REJECTED = "edit_output_readback_rejected"
REASON_EDIT_OUTPUT_COUNT_DRIFT = "edit_output_count_drift"
REASON_EDIT_OUTPUT_NON_TARGET_DRIFT = "edit_output_non_target_drift"
REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH = "edit_output_roundtrip_mismatch"

#: Post-edit verification outcome. ``structured_roundtrip_ok`` is the only
#: value that may accompany a successful edit: the output package was decoded
#: again and matched the intended edited model paragraph by paragraph.
VALIDATION_STATUS_EDIT_OK = "structured_roundtrip_ok"
VALIDATION_STATUS_EDIT_NOT_RUN = "not_run"
VALIDATION_STATUS_EDIT_SOURCE_REFUSED = "source_refused"
VALIDATION_STATUS_EDIT_SOURCE_NOT_CANONICAL = "source_not_canonical"
VALIDATION_STATUS_EDIT_OPERATIONS_REFUSED = "operations_refused"
VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED = "serializer_refused"
VALIDATION_STATUS_EDIT_OUTPUT_REFUSED = "output_refused"
VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH = "output_mismatch"

_EDIT_VALIDATION_STATUSES = frozenset(
    {
        VALIDATION_STATUS_EDIT_OK,
        VALIDATION_STATUS_EDIT_NOT_RUN,
        VALIDATION_STATUS_EDIT_SOURCE_REFUSED,
        VALIDATION_STATUS_EDIT_SOURCE_NOT_CANONICAL,
        VALIDATION_STATUS_EDIT_OPERATIONS_REFUSED,
        VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED,
        VALIDATION_STATUS_EDIT_OUTPUT_REFUSED,
        VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
    }
)

REASON_INSERT_TABLE_GATE_REJECTED = "insert_table_gate_rejected"
REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED = "insert_table_source_decoder_rejected"
REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL = "insert_table_source_not_canonical"
REASON_INSERT_TABLE_REQUEST_SHAPE = "insert_table_request_shape"
REASON_INSERT_TABLE_SECTION_INDEX_NEGATIVE = "insert_table_section_index_negative"
REASON_INSERT_TABLE_BLOCK_INDEX_NEGATIVE = "insert_table_block_index_negative"
REASON_INSERT_TABLE_SECTION_OUT_OF_RANGE = "insert_table_section_out_of_range"
REASON_INSERT_TABLE_BLOCK_OUT_OF_RANGE = "insert_table_block_out_of_range"
REASON_INSERT_TABLE_ROWS_EMPTY = "insert_table_rows_empty"
REASON_INSERT_TABLE_ROWS_RAGGED = "insert_table_rows_ragged"
REASON_INSERT_TABLE_ROW_LIMIT = "insert_table_row_limit"
REASON_INSERT_TABLE_COLUMN_LIMIT = "insert_table_column_limit"
REASON_INSERT_TABLE_CELL_LIMIT = "insert_table_cell_limit"
REASON_INSERT_TABLE_CELL_TEXT_REJECTED = "insert_table_cell_text_rejected"
REASON_INSERT_TABLE_SERIALIZER_REJECTED = "insert_table_serializer_rejected"
REASON_INSERT_TABLE_OUTPUT_GATE_REJECTED = "insert_table_output_gate_rejected"
REASON_INSERT_TABLE_OUTPUT_VALIDATE_REJECTED = "insert_table_output_validate_rejected"
REASON_INSERT_TABLE_OUTPUT_READBACK_REJECTED = "insert_table_output_readback_rejected"
REASON_INSERT_TABLE_OUTPUT_DECODER_REJECTED = "insert_table_output_decoder_rejected"
REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT = "insert_table_output_count_drift"
REASON_INSERT_TABLE_OUTPUT_TABLE_MISMATCH = "insert_table_output_table_mismatch"
REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT = "insert_table_output_non_target_drift"
REASON_INSERT_TABLE_OUTPUT_ROUNDTRIP_MISMATCH = "insert_table_output_roundtrip_mismatch"

VALIDATION_STATUS_INSERT_TABLE_OK = "insert_table_roundtrip_ok"
VALIDATION_STATUS_INSERT_TABLE_NOT_RUN = "not_run"
VALIDATION_STATUS_INSERT_TABLE_SOURCE_REFUSED = "source_refused"
VALIDATION_STATUS_INSERT_TABLE_SOURCE_NOT_CANONICAL = "source_not_canonical"
VALIDATION_STATUS_INSERT_TABLE_REQUEST_REFUSED = "request_refused"
VALIDATION_STATUS_INSERT_TABLE_SERIALIZER_REFUSED = "serializer_refused"
VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED = "output_refused"
VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH = "output_mismatch"

_INSERT_TABLE_VALIDATION_STATUSES = frozenset(
    {
        VALIDATION_STATUS_INSERT_TABLE_OK,
        VALIDATION_STATUS_INSERT_TABLE_NOT_RUN,
        VALIDATION_STATUS_INSERT_TABLE_SOURCE_REFUSED,
        VALIDATION_STATUS_INSERT_TABLE_SOURCE_NOT_CANONICAL,
        VALIDATION_STATUS_INSERT_TABLE_REQUEST_REFUSED,
        VALIDATION_STATUS_INSERT_TABLE_SERIALIZER_REFUSED,
        VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED,
        VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
    }
)

#: Canonical serializer refusals that a replacement text can cause. The source
#: model was already proven to serialize into the exact input bytes, so one of
#: these after a replacement is attributable to the replacement text alone.
_EDIT_TEXT_LEVEL_SERIALIZE_CODES = frozenset(
    {
        "hwpx_serialize_control_char",
        "hwpx_serialize_paragraph_text_limit",
        "hwpx_serialize_paragraph_limit",
        "hwpx_serialize_text_limit",
        "hwpx_serialize_empty",
    }
)

#: The smallest deterministic placeholder grammar (#2989). A placeholder is
#: exactly these two literal delimiters around a bounded field name. There is
#: no alternative delimiter, no whitespace-padded form, no nesting and no
#: escape sequence; ``{{`` is only a placeholder opener when the text that
#: follows it satisfies :data:`_TEMPLATE_FIELD_NAME_CHARS`.
PLACEHOLDER_OPEN = "{{"
PLACEHOLDER_CLOSE = "}}"

#: A field name is one or more characters from a deliberately tiny class: a
#: Unicode alphanumeric character (so Hangul, Latin and digit field names all
#: work in a Korean business template) or one of these three punctuation
#: characters. The class excludes whitespace, both delimiters and every control
#: character, so a field name can never carry or terminate its own token and
#: the scan stays deterministic.
_TEMPLATE_FIELD_NAME_EXTRA_CHARS = frozenset("_.-")


def _is_field_name_char(character: str) -> bool:
    """True exactly when ``character`` may appear inside a field name."""

    return character.isalnum() or character in _TEMPLATE_FIELD_NAME_EXTRA_CHARS

#: One template_fill request names at most this many distinct fields. The bound
#: is explicit and small so a fill stays a bounded operation over an ordinary
#: document rather than a data load.
MAX_TEMPLATE_FIELDS = 64

#: A field name is at most this many characters. Bounded so a placeholder
#: cannot be used to smuggle an arbitrarily long token through the grammar.
MAX_TEMPLATE_FIELD_NAME_CHARS = 64

#: Bounded ``hwpx.template_fill`` refusal vocabulary. Each code names the stage
#: that refused; that stage's own bounded code travels in the receipt ``note``.
REASON_TEMPLATE_FIELDS_INVALID = "template_fields_invalid"
REASON_TEMPLATE_FIELDS_LIMIT = "template_fields_limit"
REASON_TEMPLATE_FIELD_NAME_INVALID = "template_field_name_invalid"
REASON_TEMPLATE_FIELD_VALUE_INVALID = "template_field_value_invalid"
REASON_TEMPLATE_FIELD_DUPLICATE = "template_field_duplicate"
REASON_TEMPLATE_UNFILLED_FIELD = "template_unfilled_field"
REASON_TEMPLATE_FIELD_UNUSED = "template_field_unused"
REASON_TEMPLATE_GATE_REJECTED = "template_gate_rejected"
REASON_TEMPLATE_SOURCE_DECODER_REJECTED = "template_source_decoder_rejected"
REASON_TEMPLATE_SOURCE_NOT_CANONICAL = "template_source_not_canonical"
REASON_TEMPLATE_TARGET_UNSUPPORTED = "template_target_unsupported"
REASON_TEMPLATE_FIELD_VALUE_REJECTED = "template_field_value_rejected"
REASON_TEMPLATE_OUTPUT_GATE_REJECTED = "template_output_gate_rejected"
REASON_TEMPLATE_OUTPUT_VALIDATE_REJECTED = "template_output_validate_rejected"
REASON_TEMPLATE_OUTPUT_READBACK_REJECTED = "template_output_readback_rejected"
REASON_TEMPLATE_OUTPUT_COUNT_DRIFT = "template_output_count_drift"
REASON_TEMPLATE_OUTPUT_MEMBER_DRIFT = "template_output_member_drift"
REASON_TEMPLATE_OUTPUT_ROUNDTRIP_MISMATCH = "template_output_roundtrip_mismatch"

#: Post-fill verification outcome. ``filled_roundtrip_ok`` is the only value
#: that may accompany a successful fill: the output package was re-decoded,
#: matched the intended filled model paragraph by paragraph, and every
#: non-target member was proven byte-identical to the supplied template.
VALIDATION_STATUS_TEMPLATE_FILL_OK = "filled_roundtrip_ok"
VALIDATION_STATUS_TEMPLATE_FILL_NOT_RUN = "not_run"
VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED = "source_refused"
VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED = "request_refused"
VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED = "output_refused"
VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH = "output_mismatch"

_TEMPLATE_FILL_VALIDATION_STATUSES = frozenset(
    {
        VALIDATION_STATUS_TEMPLATE_FILL_OK,
        VALIDATION_STATUS_TEMPLATE_FILL_NOT_RUN,
        VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED,
        VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED,
        VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
    }
)

ACCEPTANCE: dict[str, str] = {
    "HWPX_INSPECT_FOUNDATION": "PASS",
    "HWPX_READ_FOUNDATION": "PASS",
    "HWPX_VALIDATE_FOUNDATION": "PASS",
    "HWPX_CREATE_FOUNDATION": "PASS",
    "COMMON_FILE_INTAKE_GATE_REUSED": "YES",
    "DIRECT_EXTENSION_AUTHORITY": "NO",
    "SINGLE_HWPX_SERIALIZER_AUTHORITY": "YES",
    "CORE_HWPX_SERIALIZER_REUSED": "YES",
    "CREATE_SUCCESS_REQUIRES_ROUNDTRIP": "YES",
    "SECOND_HWPX_PARSER_AUTHORITY": "0",
    "SECOND_HWPX_SERIALIZER_AUTHORITY": "0",
    "SECOND_ARCHIVE_GATE_AUTHORITY": "0",
    "SECOND_XML_AUTHORITY": "0",
    "SECOND_SKILL_REGISTRY_AUTHORITY": "0",
    "CALLER_RAW_XML_INPUT": "0",
    "CALLER_ZIP_MEMBER_INPUT": "0",
    "CALLER_MEMBER_NAME_INPUT": "0",
    "CALLER_HOST_PATH_AUTHORITY": "0",
    "HOST_FS_EXTRACTION": "0",
    "HOST_FS_WRITE": "0",
    "RAW_XML_PUBLIC_OUTPUT": "0",
    "PAYLOAD_PUBLIC_OUTPUT": "0",
    "ZIP_MEMBER_PUBLIC_OUTPUT": "0",
    "HOST_PATH_PUBLIC_OUTPUT": "0",
    "UNSUPPORTED_FEATURES_EXPLICIT": "YES",
    "NEW_RUNTIME_DEPENDENCY": "0",
    "NETWORK_CALLS": "0",
    "PROVIDER_CALLS": "0",
    "EXTERNAL_SEND": "0",
    "PRODUCTION_MUTATION": "0",
    # Create exists as a bounded plain-text foundation only: full create,
    # specification completeness and document export stay unclaimed.
    "HWPX_CREATE": "FOUNDATION_ONLY",
    "HWPX_FULL_SPEC_SUPPORT": "NO",
    "DOCUMENT_EXPORT_HWPX_ENABLED": "NO",
    # Edit exists as a bounded paragraph-replacement foundation only (#2972):
    # no insert/delete, no template fill, no table/image/style/layout edit.
    "HWPX_EDIT_FOUNDATION": "PASS",
    "HWPX_EDIT": "FOUNDATION_ONLY",
    "PARAGRAPH_TEXT_REPLACE": "PASS",
    "HWPX_INSERT_TABLE_FACADE": "PASS",
    "TABLE_INSERT": "PASS",
    "TABLE_INSERT_SCOPE": "BOUNDED_CANONICAL_BLOCK_SUBSET",
    "TABLE_INSERT_UNDER_HWPX_EDIT": "YES",
    "CORE_HWPX_DECODER_REUSED": "YES",
    "CAPABILITY_HWPX_EDIT_REUSED": "YES",
    "EXISTING_HWPX_VALIDATE_REUSED": "YES",
    "SOURCE_CANONICAL_BYTE_ROUNDTRIP_REQUIRED": "YES",
    "LOSSY_SOURCE_CANONICALIZATION": "0",
    "UNSUPPORTED_SOURCE_FAILS_CLOSED": "YES",
    "EDIT_SUCCESS_REQUIRES_STRUCTURED_ROUNDTRIP": "YES",
    "NON_TARGET_PARAGRAPHS_PRESERVED": "YES",
    "SECTION_COUNT_PRESERVED": "YES",
    "PARAGRAPH_COUNT_PRESERVED": "YES",
    "PARTIAL_EDIT_OUTPUT": "0",
    # Template fill (#2989) is a bounded foundation over the smallest
    # deterministic placeholder grammar, composing the #2979
    # package-preserving mutation authority. It is not a full templating
    # capability and claims no insert of any kind.
    "HWPX_TEMPLATE_FILL_FOUNDATION": "PASS",
    # #2989's bounded template_fill slice itself satisfies its acceptance
    # contract. PASS is intentionally scoped by the next key; it is not a
    # claim of table/image/style/full-spec templating support.
    "HWPX_TEMPLATE_FILL": "PASS",
    "HWPX_TEMPLATE_FILL_SCOPE": "BOUNDED_FOUNDATION",
    "PLACEHOLDER_GRAMMAR_CANONICAL": "SMALLEST_DETERMINISTIC",
    "PACKAGE_PRESERVATION_AUTHORITY_REUSED": "YES",
    "SINGLE_HWPX_MUTATOR_AUTHORITY": "YES",
    "SECOND_HWPX_MUTATOR_AUTHORITY": "0",
    "ALL_NON_TARGET_MEMBERS_BYTE_IDENTICAL": "YES",
    "MEMBER_NAME_SET_UNCHANGED": "YES",
    "UNRELATED_PACKAGE_PART_LOSS": "0",
    "TEMPLATE_FILL_SUCCESS_REQUIRES_PRESERVATION": "YES",
    "PARAGRAPH_INSERT": "NOT_CLAIMED",
    "PARAGRAPH_DELETE": "NOT_CLAIMED",
    "SECTION_INSERT": "NOT_CLAIMED",
    "SECTION_DELETE": "NOT_CLAIMED",
    "TABLE_EDIT": "NOT_CLAIMED",
    "TABLE_DELETE": "NOT_CLAIMED",
    "ROW_COLUMN_MUTATION": "NOT_CLAIMED",
    "IMAGE_INSERT": "NOT_CLAIMED",
    "IMAGE_EDIT": "NOT_CLAIMED",
    "STYLE_EDIT": "NOT_CLAIMED",
    "LAYOUT_FIDELITY": "NOT_CLAIMED",
}


def _require_receipt_fields(status: str, reason_code: str) -> None:
    if status not in (STATUS_OK, STATUS_REFUSED):
        raise ValueError("hwpx_skill: receipt status must be ok or refused")
    if not is_bounded_reason_code(reason_code):
        raise ValueError("hwpx_skill: receipt reason_code must be a bounded identifier")
    if status == STATUS_OK and reason_code != "ok":
        raise ValueError("hwpx_skill: an ok receipt must carry reason_code ok")
    if status == STATUS_REFUSED and reason_code == "ok":
        raise ValueError("hwpx_skill: a refused receipt must not claim reason ok")


@dataclass(frozen=True, slots=True)
class HwpxGateMetadata:
    """Bounded projection of the common gate result.

    Mirrors ``FileIntakeResult.safe_dict`` minus the filename: media type,
    byte size, archive counts, depth, mismatch/encrypted/safety state only.
    Never contains entry names, entry contents, raw bytes or any path.
    """

    decision: str
    reason_code: str
    detected_format: str
    detected_media_type: str
    extension_media_type: str | None
    mismatch: bool
    encrypted: bool
    byte_size: int
    archive_entry_count: int
    archive_uncompressed_bytes: int
    archive_depth: int
    safe_to_parse: bool
    hwpx_candidate: bool

    def __post_init__(self) -> None:
        if not is_bounded_reason_code(self.reason_code):
            raise ValueError("hwpx_skill: gate reason_code must be a bounded identifier")

    @classmethod
    def from_gate(cls, gate: FileIntakeResult) -> HwpxGateMetadata:
        return cls(
            decision=gate.decision.value,
            reason_code=gate.reason_code,
            detected_format=gate.detected_format.value,
            detected_media_type=gate.detected_media_type,
            extension_media_type=gate.extension_media_type,
            mismatch=gate.mismatch,
            encrypted=gate.encrypted,
            byte_size=gate.raw_bytes,
            archive_entry_count=gate.archive_entry_count,
            archive_uncompressed_bytes=gate.archive_uncompressed_bytes,
            archive_depth=gate.archive_depth_reached,
            safe_to_parse=gate.safe_to_parse,
            hwpx_candidate=gate.detected_format is DetectedFormat.HWPX_CANDIDATE,
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "detected_format": self.detected_format,
            "detected_media_type": self.detected_media_type,
            "extension_media_type": self.extension_media_type,
            "mismatch": self.mismatch,
            "encrypted": self.encrypted,
            "byte_size": self.byte_size,
            "archive_entry_count": self.archive_entry_count,
            "archive_uncompressed_bytes": self.archive_uncompressed_bytes,
            "archive_depth": self.archive_depth,
            "safe_to_parse": self.safe_to_parse,
            "hwpx_candidate": self.hwpx_candidate,
        }


@dataclass(frozen=True, slots=True)
class HwpxInspectReceipt:
    """Bounded hwpx.inspect result over the common gate only (no parser run)."""

    status: str
    capability_id: str
    reason_code: str
    gate: HwpxGateMetadata

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "gate": self.gate.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class HwpxReadReceipt:
    """Bounded hwpx.read result: extracted text on success, note/reason only on refusal."""

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    text: str | None

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.status == STATUS_OK and self.text is None:
            raise ValueError("hwpx_skill: an ok read receipt must carry text")
        if self.status == STATUS_REFUSED and self.text is not None:
            raise ValueError("hwpx_skill: a refused read receipt must not carry text")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class HwpxValidateReceipt:
    """Bounded hwpx.validate result: gate metadata + parse outcome, scope-explicit.

    ``full_spec_support_claimed`` is always False: this foundation validates
    package admission and text extraction only, and never silently claims that
    every HWPX construct is supported.
    """

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    scope: str
    full_spec_support_claimed: bool
    text_present: bool
    gate: HwpxGateMetadata

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.scope != VALIDATION_SCOPE_GATE_AND_TEXT:
            raise ValueError("hwpx_skill: scope must stay at gate admission and text extraction")
        if self.full_spec_support_claimed:
            raise ValueError("hwpx_skill: full HWPX spec support is never claimed")
        if self.status == STATUS_OK and not self.text_present:
            raise ValueError("hwpx_skill: an ok validate receipt must report text_present")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "scope": self.scope,
            "full_spec_support_claimed": self.full_spec_support_claimed,
            "text_present": self.text_present,
            "gate": self.gate.to_public_dict(),
        }


def _gate_refusal(gate: FileIntakeResult) -> str | None:
    """Bounded stage-one refusal code, or None once HWPX_CANDIDATE is confirmed."""

    if not gate.safe_to_parse:
        return gate.reason_code
    if gate.detected_format is not DetectedFormat.HWPX_CANDIDATE:
        return REASON_CONTENT_MISMATCH
    return None


def hwpx_inspect(filename: str, payload: bytes) -> HwpxInspectReceipt:
    """Bounded HWPX inspection over the common gate. Runs no parser.

    Admits only a truthful ``HWPX_CANDIDATE``: content decides, the
    extension stays advisory. Refusals carry the gate's bounded reason code
    or ``content_mismatch`` with the detected format in the gate metadata.
    """

    gate = inspect_file(filename, payload)
    metadata = HwpxGateMetadata.from_gate(gate)
    refusal = _gate_refusal(gate)
    if refusal is None:
        return HwpxInspectReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_FILE_INSPECT,
            reason_code="ok",
            gate=metadata,
        )
    return HwpxInspectReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_FILE_INSPECT,
        reason_code=refusal,
        gate=metadata,
    )


def hwpx_read(filename: str, payload: bytes) -> HwpxReadReceipt:
    """Bounded HWPX text extraction.

    Runs the common gate first, requires ``HWPX_CANDIDATE``, then reuses
    ``intake_document`` (which re-runs the same gate before its isolated Core
    parse). Refusals surface a bounded reason code plus, when the refusal came
    from the existing intake/parser layer, that layer's existing bounded note.
    """

    gate = inspect_file(filename, payload)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return HwpxReadReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code=refusal,
            note=None,
            text=None,
        )

    intake = intake_document(filename, payload)
    if intake is None:
        return HwpxReadReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code=REASON_HWpx_ROUTE_REQUIRED,
            note=None,
            text=None,
        )
    if intake.text is not None:
        return HwpxReadReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_READ,
            reason_code="ok",
            note=None,
            text=intake.text,
        )
    return HwpxReadReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_HWPX_READ,
        reason_code=REASON_INTAKE_REJECTED,
        note=intake.note,
        text=None,
    )


def hwpx_validate(filename: str, payload: bytes) -> HwpxValidateReceipt:
    """Bounded HWPX validation receipt: gate result composed with parser result.

    Malformed, encrypted, unsafe-path, archive-bomb, mimetype-mismatch and
    missing section/package cases remain refusals at the gate stage. An
    admitted package that the Core parser rejects (corrupt section XML, no
    extractable text) is refused with the existing bounded intake note.
    Scope stays ``gate_admission_and_text_extraction``; full specification
    conformance is never claimed.
    """

    gate = inspect_file(filename, payload)
    metadata = HwpxGateMetadata.from_gate(gate)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return HwpxValidateReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_VALIDATE,
            reason_code=refusal,
            note=None,
            scope=VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=False,
            gate=metadata,
        )

    read = hwpx_read(filename, payload)
    if read.status == STATUS_OK:
        return HwpxValidateReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_VALIDATE,
            reason_code="ok",
            note=None,
            scope=VALIDATION_SCOPE_GATE_AND_TEXT,
            full_spec_support_claimed=False,
            text_present=read.text is not None and read.text != "",
            gate=metadata,
        )
    return HwpxValidateReceipt(
        status=STATUS_REFUSED,
        capability_id=CAPABILITY_HWPX_VALIDATE,
        reason_code=read.reason_code,
        note=read.note,
        scope=VALIDATION_SCOPE_GATE_AND_TEXT,
        full_spec_support_claimed=False,
        text_present=False,
        gate=metadata,
    )


# --------------------------------------------------------------------------
# hwpx.create (#2962): bounded structured content through the Core serializer
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HwpxCreateReceipt:
    """Bounded ``hwpx.create`` projection.

    On success it reports presentation metadata plus the post-create
    verification outcome; on refusal every artifact-derived field is ``None``,
    so a refused create can never be read as a handoff. It carries bounded
    metadata and bounded reason vocabulary only — never payload bytes, raw
    XML, ZIP member names or host paths. The generated bytes live in
    :class:`HwpxCreateArtifact`, which stays outside the public projection.
    """

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    media_type: str | None
    suggested_filename: str | None
    byte_size: int | None
    section_count: int | None
    paragraph_count: int | None
    validation_status: str

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.validation_status not in _CREATE_VALIDATION_STATUSES:
            raise ValueError("hwpx_skill: create validation_status must be bounded")
        if self.note is not None and not is_bounded_reason_code(self.note):
            raise ValueError("hwpx_skill: a create note must be a bounded identifier")

        if self.status == STATUS_OK:
            if self.validation_status != VALIDATION_STATUS_ROUNDTRIP_OK:
                raise ValueError("hwpx_skill: an ok create must have verified its round trip")
            if self.note is not None:
                raise ValueError("hwpx_skill: an ok create receipt carries no note")
            if self.media_type != HWPX_MEDIA_TYPE:
                raise ValueError("hwpx_skill: an ok create must report the HWPX media type")
            if not isinstance(self.suggested_filename, str) or not (
                self.suggested_filename.endswith(HWPX_SUFFIX)
            ):
                raise ValueError("hwpx_skill: an ok create name must end with the canonical suffix")
            if not isinstance(self.byte_size, int) or self.byte_size <= 0:
                raise ValueError("hwpx_skill: an ok create must report a positive byte size")
            if not isinstance(self.section_count, int) or self.section_count <= 0:
                raise ValueError("hwpx_skill: an ok create must report its section count")
            if not isinstance(self.paragraph_count, int) or self.paragraph_count <= 0:
                raise ValueError("hwpx_skill: an ok create must report its paragraph count")
            return

        if self.validation_status == VALIDATION_STATUS_ROUNDTRIP_OK:
            raise ValueError("hwpx_skill: a refused create must not claim a verified round trip")
        if any(
            value is not None
            for value in (
                self.media_type,
                self.suggested_filename,
                self.byte_size,
                self.section_count,
                self.paragraph_count,
            )
        ):
            raise ValueError("hwpx_skill: a refused create receipt carries no artifact metadata")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "media_type": self.media_type,
            "suggested_filename": self.suggested_filename,
            "byte_size": self.byte_size,
            "section_count": self.section_count,
            "paragraph_count": self.paragraph_count,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class HwpxCreateArtifact:
    """In-memory create artifact for artifact handoff.

    This is the only place a created package's bytes exist. It is deliberately
    separate from :class:`HwpxCreateReceipt` so no public projection can carry
    the payload, and nothing here is written to the host filesystem.
    """

    payload: bytes
    media_type: str
    suggested_filename: str
    byte_size: int
    section_count: int
    paragraph_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("hwpx_skill: a create artifact requires bounded bytes")
        if self.media_type != HWPX_MEDIA_TYPE:
            raise ValueError("hwpx_skill: a create artifact must be the HWPX media type")
        if not isinstance(self.suggested_filename, str) or not (
            self.suggested_filename.endswith(HWPX_SUFFIX)
        ):
            raise ValueError("hwpx_skill: a create artifact name must use the canonical suffix")
        if self.byte_size != len(self.payload):
            raise ValueError("hwpx_skill: a create artifact byte size must match its payload")
        if self.section_count <= 0 or self.paragraph_count <= 0:
            raise ValueError("hwpx_skill: a create artifact must report its bounded counts")


@dataclass(frozen=True, slots=True)
class HwpxCreateResult:
    """One create outcome: the public receipt plus, on success only, the bytes.

    ``to_public_dict`` delegates to the receipt, so the public projection of a
    create is exactly the bounded receipt and can never include the payload.
    A successful receipt always carries its artifact and a refused receipt
    never does, which keeps "no artifact" and "no success" the same fact.
    """

    receipt: HwpxCreateReceipt
    artifact: HwpxCreateArtifact | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == STATUS_OK and self.artifact is None:
            raise ValueError("hwpx_skill: an ok create result must carry its artifact")
        if self.receipt.status != STATUS_OK and self.artifact is not None:
            raise ValueError("hwpx_skill: a refused create result must not carry an artifact")

    def to_public_dict(self) -> dict[str, object]:
        return self.receipt.to_public_dict()


def _bounded_note(value: object) -> str | None:
    """A bounded identifier or ``None``; free text never reaches a receipt."""

    return value if is_bounded_reason_code(value) else None


def _expected_readback_text(content: HwpxPackageContent) -> str:
    """The exact text the existing Core reader must return for this content.

    Mirrors the accepted Core HWPX projection: within a section, non-empty
    paragraph values joined by a newline and stripped; empty sections dropped;
    sections joined by a newline and stripped. It is only consulted after the
    canonical serializer accepted the model, so the structure is bounded.
    """

    sections: list[str] = []
    for section in content.sections:
        section_text = "\n".join(text for text in section.paragraphs if text).strip()
        if section_text:
            sections.append(section_text)
    return "\n".join(sections).strip()


def _suggested_filename(filename: str | None) -> str:
    """Project a caller-supplied name onto a flat, bounded ``.hwpx`` name.

    Presentation metadata only. The canonical sanitizer removes separators,
    traversal and control material, a trailing extension is replaced by the
    canonical ``.hwpx`` suffix, and a name that projects onto nothing safe
    falls back to the fixed default. Nothing is written to the host.
    """

    if not isinstance(filename, str) or not filename.strip():
        return DEFAULT_CREATE_FILENAME
    safe = sanitize_filename(filename, max_bytes=MAX_CREATE_FILENAME_CHARS - len(HWPX_SUFFIX))
    stem = safe.rsplit(".", 1)[0] if "." in safe else safe
    stem = stem.strip(" .")
    if not stem or stem == _SANITIZED_EMPTY_NAME:
        return DEFAULT_CREATE_FILENAME
    return f"{stem}{HWPX_SUFFIX}"


def _create_refusal(
    reason_code: str,
    *,
    note: str | None,
    validation_status: str,
) -> HwpxCreateResult:
    return HwpxCreateResult(
        receipt=HwpxCreateReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_CREATE,
            reason_code=reason_code,
            note=note,
            media_type=None,
            suggested_filename=None,
            byte_size=None,
            section_count=None,
            paragraph_count=None,
            validation_status=validation_status,
        ),
        artifact=None,
    )


def hwpx_create(
    content: HwpxPackageContent,
    *,
    filename: str | None = None,
) -> HwpxCreateResult:
    """Create bounded HWPX bytes from structured content, verified end to end.

    The only accepted input is the Core ``HwpxPackageContent`` model (sections
    of plain paragraph strings) and the only byte producer is the canonical
    Core serializer, so a caller never reaches raw XML, ZIP member names,
    archive paths, namespaces, mimetype content or serializer limits. Success
    is reported only after the generated bytes passed the common intake gate
    as ``HWPX_CANDIDATE``, the existing validate and read authorities accepted
    them, and the readback text matched the requested text exactly. Every
    other outcome is a bounded refusal with no artifact and no fallback
    format.

    ``filename`` is optional presentation metadata and never a package or host
    authority: it is sanitized onto a flat bounded name ending in ``.hwpx``,
    and an unusable name falls back to the fixed default.
    """

    try:
        payload = serialize_hwpx_package(content)
    except DocumentNormalizationError as error:
        return _create_refusal(
            REASON_CREATE_SERIALIZER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_NOT_RUN,
        )
    if not isinstance(payload, bytes) or not payload:
        # Defence in depth: a serializer that returns no bounded byte string
        # can never produce a create success.
        return _create_refusal(
            REASON_CREATE_SERIALIZER_REJECTED,
            note=None,
            validation_status=VALIDATION_STATUS_NOT_RUN,
        )

    expected_text = _expected_readback_text(content)
    name = _suggested_filename(filename)

    gate = inspect_file(name, payload)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return _create_refusal(
            REASON_CREATE_GATE_REJECTED,
            note=_bounded_note(refusal),
            validation_status=VALIDATION_STATUS_GATE_REFUSED,
        )

    validation = hwpx_validate(name, payload)
    if validation.status != STATUS_OK:
        return _create_refusal(
            REASON_CREATE_VALIDATE_REJECTED,
            note=_bounded_note(validation.reason_code),
            validation_status=VALIDATION_STATUS_VALIDATE_REFUSED,
        )

    read = hwpx_read(name, payload)
    if read.status != STATUS_OK:
        return _create_refusal(
            REASON_CREATE_READBACK_REJECTED,
            note=_bounded_note(read.reason_code),
            validation_status=VALIDATION_STATUS_READBACK_REFUSED,
        )
    if read.text != expected_text:
        return _create_refusal(
            REASON_CREATE_ROUNDTRIP_MISMATCH,
            note=None,
            validation_status=VALIDATION_STATUS_ROUNDTRIP_MISMATCH,
        )

    section_count = len(content.sections)
    paragraph_count = sum(len(section.paragraphs) for section in content.sections)
    artifact = HwpxCreateArtifact(
        payload=payload,
        media_type=HWPX_MEDIA_TYPE,
        suggested_filename=name,
        byte_size=len(payload),
        section_count=section_count,
        paragraph_count=paragraph_count,
    )
    return HwpxCreateResult(
        receipt=HwpxCreateReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_CREATE,
            reason_code="ok",
            note=None,
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename=name,
            byte_size=len(payload),
            section_count=section_count,
            paragraph_count=paragraph_count,
            validation_status=VALIDATION_STATUS_ROUNDTRIP_OK,
        ),
        artifact=artifact,
    )


# --------------------------------------------------------------------------
# hwpx.edit (#2972): bounded paragraph replacement over the canonical decoder
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HwpxParagraphReplacement:
    """One zero-based paragraph replacement request.

    ``section_index`` and ``paragraph_index`` address the decoded canonical
    model directly and are both **zero-based**: section 0 is the first section
    part and paragraph 0 is the first paragraph inside that section. ``text``
    is the complete replacement text for that paragraph, not a fragment and
    not a search pattern.

    This shape deliberately carries caller data and enforces nothing itself:
    :func:`hwpx_edit` is the single place the bounded edit contract is judged.
    A malformed request — a ``bool`` index, a negative index, a target outside
    the decoded model, a duplicate target, text the canonical serializer
    refuses — is therefore answered with one bounded refusal receipt instead of
    an exception from an intermediate object, which keeps "invalid" and "no
    output" the same fact.
    """

    section_index: int
    paragraph_index: int
    text: str


@dataclass(frozen=True, slots=True)
class HwpxEditReceipt:
    """Bounded ``hwpx.edit`` projection.

    On success it reports presentation metadata, the preserved structure
    counts, how many replacements were applied and the post-edit verification
    outcome. On refusal every artifact-derived field is ``None``, so a refused
    edit can never be read as a handoff. It carries bounded metadata and
    bounded reason vocabulary only — never payload bytes, raw XML, ZIP member
    names, host paths, or any part of the original or replacement document
    text. The edited bytes live in :class:`HwpxEditArtifact`, which stays
    outside the public projection.
    """

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    media_type: str | None
    suggested_filename: str | None
    byte_size: int | None
    section_count: int | None
    paragraph_count: int | None
    replacement_count: int | None
    validation_status: str

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.validation_status not in _EDIT_VALIDATION_STATUSES:
            raise ValueError("hwpx_skill: edit validation_status must be bounded")
        if self.note is not None and not is_bounded_reason_code(self.note):
            raise ValueError("hwpx_skill: an edit note must be a bounded identifier")

        if self.status == STATUS_OK:
            if self.validation_status != VALIDATION_STATUS_EDIT_OK:
                raise ValueError("hwpx_skill: an ok edit must verify its structured round trip")
            if self.note is not None:
                raise ValueError("hwpx_skill: an ok edit receipt carries no note")
            if self.media_type != HWPX_MEDIA_TYPE:
                raise ValueError("hwpx_skill: an ok edit must report the HWPX media type")
            if not isinstance(self.suggested_filename, str) or not (
                self.suggested_filename.endswith(HWPX_SUFFIX)
            ):
                raise ValueError("hwpx_skill: an ok edit name must end with the canonical suffix")
            if not isinstance(self.byte_size, int) or self.byte_size <= 0:
                raise ValueError("hwpx_skill: an ok edit must report a positive byte size")
            if not isinstance(self.section_count, int) or self.section_count <= 0:
                raise ValueError("hwpx_skill: an ok edit must report its section count")
            if not isinstance(self.paragraph_count, int) or self.paragraph_count <= 0:
                raise ValueError("hwpx_skill: an ok edit must report its paragraph count")
            if not isinstance(self.replacement_count, int) or self.replacement_count <= 0:
                raise ValueError("hwpx_skill: an ok edit must report its replacement count")
            return

        if self.validation_status == VALIDATION_STATUS_EDIT_OK:
            raise ValueError("hwpx_skill: a refused edit must not claim a verified round trip")
        if any(
            value is not None
            for value in (
                self.media_type,
                self.suggested_filename,
                self.byte_size,
                self.section_count,
                self.paragraph_count,
                self.replacement_count,
            )
        ):
            raise ValueError("hwpx_skill: a refused edit receipt carries no artifact metadata")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "media_type": self.media_type,
            "suggested_filename": self.suggested_filename,
            "byte_size": self.byte_size,
            "section_count": self.section_count,
            "paragraph_count": self.paragraph_count,
            "replacement_count": self.replacement_count,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class HwpxEditArtifact:
    """In-memory edit artifact for artifact handoff.

    This is the only place an edited package's bytes exist. It is deliberately
    separate from :class:`HwpxEditReceipt` so no public projection can carry
    the payload, and nothing here is written to the host filesystem.
    """

    payload: bytes
    media_type: str
    suggested_filename: str
    byte_size: int
    section_count: int
    paragraph_count: int
    replacement_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("hwpx_skill: an edit artifact requires bounded bytes")
        if self.media_type != HWPX_MEDIA_TYPE:
            raise ValueError("hwpx_skill: an edit artifact must be the HWPX media type")
        if not isinstance(self.suggested_filename, str) or not (
            self.suggested_filename.endswith(HWPX_SUFFIX)
        ):
            raise ValueError("hwpx_skill: an edit artifact name must use the canonical suffix")
        if self.byte_size != len(self.payload):
            raise ValueError("hwpx_skill: an edit artifact byte size must match its payload")
        if self.section_count <= 0 or self.paragraph_count <= 0:
            raise ValueError("hwpx_skill: an edit artifact must report its bounded counts")
        if self.replacement_count <= 0:
            raise ValueError("hwpx_skill: an edit artifact must report its replacements")


@dataclass(frozen=True, slots=True)
class HwpxEditResult:
    """One edit outcome: the public receipt plus, on success only, the bytes.

    ``to_public_dict`` delegates to the receipt, so the public projection of an
    edit is exactly the bounded receipt and can never include the payload. A
    successful receipt always carries its artifact and a refused receipt never
    does, which keeps "no artifact" and "no success" the same fact.
    """

    receipt: HwpxEditReceipt
    artifact: HwpxEditArtifact | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == STATUS_OK and self.artifact is None:
            raise ValueError("hwpx_skill: an ok edit result must carry its artifact")
        if self.receipt.status != STATUS_OK and self.artifact is not None:
            raise ValueError("hwpx_skill: a refused edit result must not carry an artifact")

    def to_public_dict(self) -> dict[str, object]:
        return self.receipt.to_public_dict()


def _edit_refusal(
    reason_code: str,
    *,
    note: str | None,
    validation_status: str,
) -> HwpxEditResult:
    return HwpxEditResult(
        receipt=HwpxEditReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_EDIT,
            reason_code=reason_code,
            note=note,
            media_type=None,
            suggested_filename=None,
            byte_size=None,
            section_count=None,
            paragraph_count=None,
            replacement_count=None,
            validation_status=validation_status,
        ),
        artifact=None,
    )


def _operation_shape_refusal(
    operations: tuple[HwpxParagraphReplacement, ...],
) -> str | None:
    """First bounded refusal for the request's own shape, or None once it is shaped.

    ``bool`` is rejected explicitly even though it is an ``int`` subclass in
    Python, so ``True`` can never address paragraph 1.
    """

    for operation in operations:
        if not isinstance(operation, HwpxParagraphReplacement):
            return REASON_EDIT_OPERATION_SHAPE
        if not isinstance(operation.section_index, int) or isinstance(
            operation.section_index, bool
        ):
            return REASON_EDIT_OPERATION_SHAPE
        if not isinstance(operation.paragraph_index, int) or isinstance(
            operation.paragraph_index, bool
        ):
            return REASON_EDIT_OPERATION_SHAPE
        if not isinstance(operation.text, str):
            return REASON_EDIT_OPERATION_SHAPE
        if operation.section_index < 0 or operation.paragraph_index < 0:
            return REASON_EDIT_INDEX_NEGATIVE
    return None


def _operation_target_refusal(
    operations: tuple[HwpxParagraphReplacement, ...],
    source: HwpxPackageContent,
) -> str | None:
    """First bounded refusal for an address or duplicate, or None once all targets fit.

    Targets are judged against the decoded source model, so an index that no
    section or paragraph occupies is refused before any edit is applied, and a
    repeated target is refused rather than resolved by request order.
    """

    seen: set[tuple[int, int]] = set()
    for operation in operations:
        if operation.section_index >= len(source.sections):
            return REASON_EDIT_SECTION_OUT_OF_RANGE
        paragraphs = source.sections[operation.section_index].paragraphs
        if operation.paragraph_index >= len(paragraphs):
            return REASON_EDIT_PARAGRAPH_OUT_OF_RANGE
        target = (operation.section_index, operation.paragraph_index)
        if target in seen:
            return REASON_EDIT_DUPLICATE_TARGET
        seen.add(target)
    return None


def _edited_model(
    source: HwpxPackageContent,
    operations: tuple[HwpxParagraphReplacement, ...],
) -> HwpxPackageContent:
    """Apply validated replacements, preserving section and paragraph counts."""

    replacements = {
        (operation.section_index, operation.paragraph_index): operation.text
        for operation in operations
    }
    sections: list[HwpxPackageSection] = []
    for section_index, section in enumerate(source.sections):
        paragraphs = tuple(
            replacements.get((section_index, paragraph_index), text)
            for paragraph_index, text in enumerate(section.paragraphs)
        )
        sections.append(HwpxPackageSection(paragraphs=paragraphs))
    return HwpxPackageContent(sections=tuple(sections))


def hwpx_edit(
    filename: str,
    payload: bytes,
    operations: tuple[HwpxParagraphReplacement, ...],
) -> HwpxEditResult:
    """Replace bounded paragraph text in an existing canonical HWPX package.

    Composition order, with the common gate always first::

        caller filename + package bytes + zero-based replacement operations
        -> inspect_file()                     (common gate must admit HWPX_CANDIDATE)
        -> deserialize_hwpx_package()         (the single structured decoder)
        -> source is proven canonical-lossless (serialize(source) == input bytes)
        -> the request container, count bound, index types and addresses judged
        -> replacements applied to the model
        -> serialize_hwpx_package()           (the single byte producer)
        -> inspect_file() / hwpx_validate() / hwpx_read() on the output
        -> deserialize_hwpx_package() on the output
        -> structured equality with the intended edited model
        -> bounded edit receipt + in-memory artifact

    The ordering is part of the contract, not an implementation detail: the
    common file-intake authority and the canonical-source proof decide first,
    and the request's own shape is judged only after the source has been
    admitted. A malformed or empty operation request therefore cannot return
    ahead of the gate that inspects the source bytes.

    The source-fidelity gate is what keeps this foundation honest: a package
    whose decoded model does not serialize back into the exact input bytes is
    refused instead of being silently canonicalized into something the writer
    owns. That deliberately restricts editing to the canonical subset the
    current serializer already round-trips.

    Success is proven by the structured model, never by flattened text alone:
    the read authority must succeed, but two different structures can flatten
    to the same text, so the proof is that the re-decoded output equals the
    intended model at every address — every non-target paragraph unchanged,
    every target paragraph exactly the requested text, and both counts
    preserved. Any failure at any stage is a bounded refusal with no artifact
    and no fallback format.

    ``filename`` is used for the common gate and, sanitized onto a flat
    bounded name ending in ``.hwpx``, as presentation metadata. It is never a
    package or host authority.
    """

    # The common intake gate is the first decision authority: the source is
    # admitted (or refused) before any request-shaped validation is judged, so
    # a malformed or empty operation request can never return ahead of the
    # archive/path/expansion gate.
    gate = inspect_file(filename, payload)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return _edit_refusal(
            REASON_EDIT_GATE_REJECTED,
            note=_bounded_note(refusal),
            validation_status=VALIDATION_STATUS_EDIT_SOURCE_REFUSED,
        )

    try:
        source = deserialize_hwpx_package(payload)
    except DocumentNormalizationError as error:
        return _edit_refusal(
            REASON_EDIT_SOURCE_DECODER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_EDIT_SOURCE_REFUSED,
        )

    try:
        canonical_source = serialize_hwpx_package(source)
    except DocumentNormalizationError:
        return _edit_refusal(
            REASON_EDIT_SOURCE_NOT_CANONICAL,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_SOURCE_NOT_CANONICAL,
        )
    if canonical_source != payload:
        return _edit_refusal(
            REASON_EDIT_SOURCE_NOT_CANONICAL,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_SOURCE_NOT_CANONICAL,
        )

    # Only now is the request itself judged. The source authorities above have
    # already admitted the package, so the container shape, the count bound,
    # the index types and the addresses are validated against a source that is
    # known to be a canonical, decodable, byte-stable HWPX package.
    if not isinstance(operations, tuple) or not operations:
        return _edit_refusal(
            REASON_EDIT_OPERATIONS_INVALID,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_NOT_RUN,
        )
    if len(operations) > MAX_EDIT_OPERATIONS:
        return _edit_refusal(
            REASON_EDIT_OPERATIONS_LIMIT,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_NOT_RUN,
        )

    shape_refusal = _operation_shape_refusal(operations)
    if shape_refusal is not None:
        return _edit_refusal(
            shape_refusal,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_OPERATIONS_REFUSED,
        )

    target_refusal = _operation_target_refusal(operations, source)
    if target_refusal is not None:
        return _edit_refusal(
            target_refusal,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_OPERATIONS_REFUSED,
        )

    intended = _edited_model(source, operations)

    try:
        edited = serialize_hwpx_package(intended)
    except DocumentNormalizationError as error:
        # The source model was just proven to serialize into the exact input
        # bytes, so a refusal here can only have been introduced by a
        # replacement text. Text-level codes are reported as such; anything
        # else stays a serializer refusal.
        code = getattr(error, "code", None)
        if code in _EDIT_TEXT_LEVEL_SERIALIZE_CODES:
            return _edit_refusal(
                REASON_EDIT_TEXT_REJECTED,
                note=_bounded_note(code),
                validation_status=VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED,
            )
        return _edit_refusal(
            REASON_EDIT_SERIALIZER_REJECTED,
            note=_bounded_note(code),
            validation_status=VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED,
        )
    if not isinstance(edited, bytes) or not edited:
        return _edit_refusal(
            REASON_EDIT_SERIALIZER_REJECTED,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_SERIALIZER_REFUSED,
        )

    name = _suggested_filename(filename)

    output_gate = inspect_file(name, edited)
    output_gate_refusal = _gate_refusal(output_gate)
    if output_gate_refusal is not None:
        return _edit_refusal(
            REASON_EDIT_OUTPUT_GATE_REJECTED,
            note=_bounded_note(output_gate_refusal),
            validation_status=VALIDATION_STATUS_EDIT_OUTPUT_REFUSED,
        )

    validation = hwpx_validate(name, edited)
    if validation.status != STATUS_OK:
        return _edit_refusal(
            REASON_EDIT_OUTPUT_VALIDATE_REJECTED,
            note=_bounded_note(validation.reason_code),
            validation_status=VALIDATION_STATUS_EDIT_OUTPUT_REFUSED,
        )

    read = hwpx_read(name, edited)
    if read.status != STATUS_OK:
        return _edit_refusal(
            REASON_EDIT_OUTPUT_READBACK_REJECTED,
            note=_bounded_note(read.reason_code),
            validation_status=VALIDATION_STATUS_EDIT_OUTPUT_REFUSED,
        )

    try:
        decoded = deserialize_hwpx_package(edited)
    except DocumentNormalizationError:
        return _edit_refusal(
            REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
        )

    if len(decoded.sections) != len(intended.sections):
        return _edit_refusal(
            REASON_EDIT_OUTPUT_COUNT_DRIFT,
            note=None,
            validation_status=VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
        )
    for section_index, section in enumerate(intended.sections):
        if len(decoded.sections[section_index].paragraphs) != len(section.paragraphs):
            return _edit_refusal(
                REASON_EDIT_OUTPUT_COUNT_DRIFT,
                note=None,
                validation_status=VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
            )

    targets = {(operation.section_index, operation.paragraph_index) for operation in operations}
    for section_index, section in enumerate(source.sections):
        for paragraph_index, text in enumerate(section.paragraphs):
            if (section_index, paragraph_index) in targets:
                continue
            if decoded.sections[section_index].paragraphs[paragraph_index] != text:
                return _edit_refusal(
                    REASON_EDIT_OUTPUT_NON_TARGET_DRIFT,
                    note=None,
                    validation_status=VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
                )
    for operation in operations:
        decoded_text = decoded.sections[operation.section_index].paragraphs[
            operation.paragraph_index
        ]
        if decoded_text != operation.text:
            return _edit_refusal(
                REASON_EDIT_OUTPUT_ROUNDTRIP_MISMATCH,
                note=None,
                validation_status=VALIDATION_STATUS_EDIT_OUTPUT_MISMATCH,
            )

    section_count = len(intended.sections)
    paragraph_count = sum(len(section.paragraphs) for section in intended.sections)
    replacement_count = len(operations)
    artifact = HwpxEditArtifact(
        payload=edited,
        media_type=HWPX_MEDIA_TYPE,
        suggested_filename=name,
        byte_size=len(edited),
        section_count=section_count,
        paragraph_count=paragraph_count,
        replacement_count=replacement_count,
    )
    return HwpxEditResult(
        receipt=HwpxEditReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_EDIT,
            reason_code="ok",
            note=None,
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename=name,
            byte_size=len(edited),
            section_count=section_count,
            paragraph_count=paragraph_count,
            replacement_count=replacement_count,
            validation_status=VALIDATION_STATUS_EDIT_OK,
        ),
        artifact=artifact,
    )


# --------------------------------------------------------------------------
# hwpx.template_fill (#2989): smallest deterministic grammar over the #2979
# package-preserving mutation authority
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HwpxTemplateFillReceipt:
    """Bounded ``hwpx.template_fill`` projection.

    On success it reports presentation metadata, the preserved structure
    counts and how many distinct fields were substituted, plus the post-fill
    verification outcome. On refusal every artifact-derived field is ``None``,
    so a refused fill can never be read as a handoff. It carries bounded
    metadata and bounded reason vocabulary only — never payload bytes, raw
    XML, ZIP member names, host paths, or any part of the template or field
    values. The filled bytes live in :class:`HwpxTemplateFillArtifact`, which
    stays outside the public projection.
    """

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    media_type: str | None
    suggested_filename: str | None
    byte_size: int | None
    section_count: int | None
    paragraph_count: int | None
    filled_field_count: int | None
    validation_status: str

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.validation_status not in _TEMPLATE_FILL_VALIDATION_STATUSES:
            raise ValueError("hwpx_skill: template_fill validation_status must be bounded")
        if self.note is not None and not is_bounded_reason_code(self.note):
            raise ValueError("hwpx_skill: a template_fill note must be a bounded identifier")

        if self.status == STATUS_OK:
            if self.validation_status != VALIDATION_STATUS_TEMPLATE_FILL_OK:
                raise ValueError(
                    "hwpx_skill: an ok template_fill must verify its preservation contract"
                )
            if self.note is not None:
                raise ValueError("hwpx_skill: an ok template_fill receipt carries no note")
            if self.media_type != HWPX_MEDIA_TYPE:
                raise ValueError("hwpx_skill: an ok template_fill must report the HWPX media type")
            if not isinstance(self.suggested_filename, str) or not (
                self.suggested_filename.endswith(HWPX_SUFFIX)
            ):
                raise ValueError(
                    "hwpx_skill: an ok template_fill name must end with the canonical suffix"
                )
            if not isinstance(self.byte_size, int) or self.byte_size <= 0:
                raise ValueError("hwpx_skill: an ok template_fill must report a positive byte size")
            if not isinstance(self.section_count, int) or self.section_count <= 0:
                raise ValueError("hwpx_skill: an ok template_fill must report its section count")
            if not isinstance(self.paragraph_count, int) or self.paragraph_count <= 0:
                raise ValueError("hwpx_skill: an ok template_fill must report its paragraph count")
            if not isinstance(self.filled_field_count, int) or self.filled_field_count <= 0:
                raise ValueError(
                    "hwpx_skill: an ok template_fill must report its filled field count"
                )
            return

        if self.validation_status == VALIDATION_STATUS_TEMPLATE_FILL_OK:
            raise ValueError(
                "hwpx_skill: a refused template_fill must not claim a verified fill"
            )
        if any(
            value is not None
            for value in (
                self.media_type,
                self.suggested_filename,
                self.byte_size,
                self.section_count,
                self.paragraph_count,
                self.filled_field_count,
            )
        ):
            raise ValueError(
                "hwpx_skill: a refused template_fill receipt carries no artifact metadata"
            )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "media_type": self.media_type,
            "suggested_filename": self.suggested_filename,
            "byte_size": self.byte_size,
            "section_count": self.section_count,
            "paragraph_count": self.paragraph_count,
            "filled_field_count": self.filled_field_count,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class HwpxTemplateFillArtifact:
    """In-memory template-fill artifact for artifact handoff.

    This is the only place a filled package's bytes exist. It is deliberately
    separate from :class:`HwpxTemplateFillReceipt` so no public projection can
    carry the payload, and nothing here is written to the host filesystem.
    """

    payload: bytes
    media_type: str
    suggested_filename: str
    byte_size: int
    section_count: int
    paragraph_count: int
    filled_field_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("hwpx_skill: a template_fill artifact requires bounded bytes")
        if self.media_type != HWPX_MEDIA_TYPE:
            raise ValueError("hwpx_skill: a template_fill artifact must be the HWPX media type")
        if not isinstance(self.suggested_filename, str) or not (
            self.suggested_filename.endswith(HWPX_SUFFIX)
        ):
            raise ValueError(
                "hwpx_skill: a template_fill artifact name must use the canonical suffix"
            )
        if self.byte_size != len(self.payload):
            raise ValueError("hwpx_skill: a template_fill artifact byte size must match its payload")
        if self.section_count <= 0 or self.paragraph_count <= 0:
            raise ValueError("hwpx_skill: a template_fill artifact must report its bounded counts")
        if self.filled_field_count <= 0:
            raise ValueError("hwpx_skill: a template_fill artifact must report its filled fields")


@dataclass(frozen=True, slots=True)
class HwpxTemplateFillResult:
    """One template-fill outcome: the public receipt plus, on success, the bytes.

    ``to_public_dict`` delegates to the receipt, so the public projection of a
    fill is exactly the bounded receipt and can never include the payload. A
    successful receipt always carries its artifact and a refused receipt never
    does, which keeps "no artifact" and "no success" the same fact.
    """

    receipt: HwpxTemplateFillReceipt
    artifact: HwpxTemplateFillArtifact | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == STATUS_OK and self.artifact is None:
            raise ValueError("hwpx_skill: an ok template_fill result must carry its artifact")
        if self.receipt.status != STATUS_OK and self.artifact is not None:
            raise ValueError("hwpx_skill: a refused template_fill result must not carry an artifact")

    def to_public_dict(self) -> dict[str, object]:
        return self.receipt.to_public_dict()


def _template_fill_refusal(
    reason_code: str,
    *,
    note: str | None,
    validation_status: str,
) -> HwpxTemplateFillResult:
    return HwpxTemplateFillResult(
        receipt=HwpxTemplateFillReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
            reason_code=reason_code,
            note=note,
            media_type=None,
            suggested_filename=None,
            byte_size=None,
            section_count=None,
            paragraph_count=None,
            filled_field_count=None,
            validation_status=validation_status,
        ),
        artifact=None,
    )


def _is_template_field_name(value: object) -> bool:
    """True exactly when ``value`` satisfies the smallest placeholder grammar."""

    if not isinstance(value, str) or not value:
        return False
    if len(value) > MAX_TEMPLATE_FIELD_NAME_CHARS:
        return False
    return all(_is_field_name_char(character) for character in value)


def _template_field_refusal(fields: object) -> str | None:
    """First bounded refusal for the field mapping's own shape, or None.

    Judged in a fixed order — container, count bound, per-entry key/value
    types, field-name grammar, duplicate key — so the reported code does not
    depend on dict iteration order for a mapping that is wrong in more than one
    way. Duplicate keys can only be expressed by passing a sequence of pairs;
    a plain mapping cannot repeat a key, so a repeated name there is refused
    explicitly rather than silently deduplicated.
    """

    if isinstance(fields, dict):
        items = tuple(fields.items())
    elif isinstance(fields, tuple):
        items = fields
    else:
        return REASON_TEMPLATE_FIELDS_INVALID
    if not items:
        return REASON_TEMPLATE_FIELDS_INVALID
    if len(items) > MAX_TEMPLATE_FIELDS:
        return REASON_TEMPLATE_FIELDS_LIMIT

    for entry in items:
        if not isinstance(entry, tuple) or len(entry) != 2:
            return REASON_TEMPLATE_FIELDS_INVALID

    names: list[str] = []
    for name, value in items:
        if not isinstance(value, str):
            return REASON_TEMPLATE_FIELD_VALUE_INVALID
        if not _is_template_field_name(name):
            return REASON_TEMPLATE_FIELD_NAME_INVALID
        if name in names:
            return REASON_TEMPLATE_FIELD_DUPLICATE
        names.append(name)
    return None


def _placeholder_spans(text: str) -> tuple[tuple[int, int, str], ...]:
    """Locate every grammar-satisfying placeholder in ``text``, left to right.

    Returns ``(start, end, field_name)`` spans where ``end`` is exclusive. A
    ``{{`` that is not followed by a valid field name and a closing ``}}`` is
    left alone and scanned past as ordinary decoration. A ``{{`` whose body
    *starts* like a field name but never closes is likewise not a placeholder:
    the scan continues from the body, so such text can never swallow a later
    real placeholder.
    """

    spans: list[tuple[int, int, str]] = []
    length = len(text)
    position = 0
    while position < length:
        start = text.find(PLACEHOLDER_OPEN, position)
        if start == -1:
            break
        body = start + len(PLACEHOLDER_OPEN)
        end = body
        while end < length and _is_field_name_char(text[end]):
            end += 1
        if end == body or not text.startswith(PLACEHOLDER_CLOSE, end):
            # Not a placeholder. Resume after the opener so the body is still
            # available to a later match instead of being consumed.
            position = body
            continue
        close = end + len(PLACEHOLDER_CLOSE)
        spans.append((start, close, text[body:end]))
        position = close
    return tuple(spans)


def _substitute_placeholders(text: str, values: dict[str, str]) -> str:
    """Replace every placeholder whose field name the mapping knows.

    A placeholder whose field name is absent is left verbatim; the caller
    inspects the result and refuses the whole fill if any named field was not
    substituted, so a partial fill is never returned.
    """

    spans = _placeholder_spans(text)
    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end, name in spans:
        pieces.append(text[cursor:start])
        pieces.append(values[name] if name in values else text[start:end])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _scan_template(
    source: HwpxPackageContent,
) -> tuple[tuple[int, int, str, tuple[tuple[int, int, str], ...]], ...]:
    """Every paragraph that carries at least one placeholder, in address order.

    Returns ``(section_index, paragraph_index, text, spans)``. A paragraph with
    no placeholder is not addressed at all, so it is never rewritten.
    """

    addressed: list[tuple[int, int, str, tuple[tuple[int, int, str], ...]]] = []
    for section_index, section in enumerate(source.sections):
        for paragraph_index, text in enumerate(section.paragraphs):
            spans = _placeholder_spans(text)
            if spans:
                addressed.append((section_index, paragraph_index, text, spans))
    return tuple(addressed)


def hwpx_template_fill(
    filename: str,
    payload: bytes,
    fields: object,
) -> HwpxTemplateFillResult:
    """Fill the smallest deterministic placeholder grammar in an HWPX template.

    Composition order, with the common gate always first::

        caller filename + template bytes + field mapping
        -> inspect_file()                            (common gate, HWPX_CANDIDATE)
        -> deserialize_hwpx_package()                (the single structured decoder)
        -> the field mapping container, count, names and values judged
        -> placeholder scan + deterministic substitution -> addressed mutations
        -> mutate_hwpx_package_preserving_members()  (the #2979 single mutator)
        -> inspect_file() / hwpx_validate() / hwpx_read() on the output
        -> deserialize_hwpx_package() on the output
        -> structured equality with the intended filled model
        -> bounded template_fill receipt + in-memory artifact

    The ordering is part of the contract: the common file-intake authority
    decides first, and the request is judged only after the source has been
    admitted.

    Why the mutator, and not the edit path: ``hwpx.edit`` proves source
    fidelity by requiring ``serialize(deserialize(payload)) == payload``, so a
    template carrying an unrelated member can never satisfy it. A template is
    allowed to carry exactly that — ``version.xml``, or a part this Core subset
    will never model — and it must survive byte-for-byte. This facade therefore
    does **not** impose a whole-package canonical gate. It delegates the
    canonical judgement to the mutator, which requires only the *addressed*
    section part to already be in the canonical byte shape and copies every
    other member verbatim. Duplicating that gate here would reject the very
    template shape this capability exists to serve, and re-asserting the
    mutator's own preservation proof here would be a second archive accessor.

    A fill is all-or-nothing: every named field must appear in the template and
    every placeholder must resolve to a supplied field, otherwise the whole
    request is refused with no artifact. Success additionally requires the
    re-decoded output to equal the intended filled model at every address and
    every non-target member to be byte-identical to the template.

    ``filename`` is used for the common gate and, sanitized onto a flat bounded
    name ending in ``.hwpx``, as presentation metadata. It is never a package
    or host authority.
    """

    # 1. The common intake gate is the first decision authority.
    gate = inspect_file(filename, payload)
    refusal = _gate_refusal(gate)
    if refusal is not None:
        return _template_fill_refusal(
            REASON_TEMPLATE_GATE_REJECTED,
            note=_bounded_note(refusal),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED,
        )

    # 2. The single structured decoder must accept the template. This is the
    #    stage that answers "unsupported paragraph structure": a template whose
    #    section holds a construct the editable model refuses is declined here
    #    rather than being silently filled around.
    #
    #    No whole-package canonical gate is imposed here, deliberately. See the
    #    docstring: a template may carry a member this Core subset does not
    #    model, and the mutator is the authority that judges canonicality of the
    #    addressed part while preserving the rest.
    try:
        source = deserialize_hwpx_package(payload)
    except DocumentNormalizationError as error:
        return _template_fill_refusal(
            REASON_TEMPLATE_SOURCE_DECODER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED,
        )

    # 3. Only now is the request judged, against an admitted source.
    field_refusal = _template_field_refusal(fields)
    if field_refusal is not None:
        return _template_fill_refusal(
            field_refusal,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )
    if isinstance(fields, dict):
        items = tuple(fields.items())
    else:
        items = fields  # type: ignore[assignment]
    values = {name: value for name, value in items}

    # 4. Address every paragraph that actually carries a placeholder. A
    #    paragraph without one is never rewritten, so its bytes cannot change.
    addressed = _scan_template(source)
    if not addressed:
        # Nothing to fill: there is no addressed placeholder and therefore
        # nothing to prove about the output.
        return _template_fill_refusal(
            REASON_TEMPLATE_UNFILLED_FIELD,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )

    # The deterministic all-or-nothing policy, judged in both directions:
    # every field the template names must be supplied, and every field that is
    # supplied must be used. A one-sided check would let a typo in a field name
    # pass silently in one of the two directions.
    named_fields = {name for _, _, _, spans in addressed for _, _, name in spans}
    if not named_fields.issubset(values.keys()):
        return _template_fill_refusal(
            REASON_TEMPLATE_UNFILLED_FIELD,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )
    if not set(values.keys()).issubset(named_fields):
        return _template_fill_refusal(
            REASON_TEMPLATE_FIELD_UNUSED,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )

    mutations = [
        HwpxParagraphMutation(
            section_index=section_index,
            paragraph_index=paragraph_index,
            text=_substitute_placeholders(text, values),
        )
        for section_index, paragraph_index, text, _spans in addressed
    ]

    # 5. Reuse the single package-preserving mutation authority. It owns the
    #    archive gate, the member accessor, the member-name sequence and the
    #    byte-for-byte preservation proof; this facade adds none of them.
    try:
        filled = mutate_hwpx_package_preserving_members(payload, tuple(mutations))
    except DocumentNormalizationError as error:
        code = getattr(error, "code", None)
        if code in _EDIT_TEXT_LEVEL_SERIALIZE_CODES:
            return _template_fill_refusal(
                REASON_TEMPLATE_FIELD_VALUE_REJECTED,
                note=_bounded_note(code),
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
            )
        if code == "hwpx_unsupported_structure":
            # The mutator decodes the addressed part through the single
            # decoder, so a structure the editable model refuses is reported as
            # an unsupported target rather than as a value problem.
            return _template_fill_refusal(
                REASON_TEMPLATE_TARGET_UNSUPPORTED,
                note=_bounded_note(code),
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
            )
        if code == "hwpx_mutation_target_not_canonical":
            return _template_fill_refusal(
                REASON_TEMPLATE_SOURCE_NOT_CANONICAL,
                note=_bounded_note(code),
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_SOURCE_REFUSED,
            )
        return _template_fill_refusal(
            REASON_TEMPLATE_FIELD_VALUE_REJECTED,
            note=_bounded_note(code),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )
    if not isinstance(filled, bytes) or not filled:
        return _template_fill_refusal(
            REASON_TEMPLATE_FIELD_VALUE_REJECTED,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_REQUEST_REFUSED,
        )

    name = _suggested_filename(filename)

    # 6. Re-enter the accepted Skill authorities on the output.
    output_gate = inspect_file(name, filled)
    output_gate_refusal = _gate_refusal(output_gate)
    if output_gate_refusal is not None:
        return _template_fill_refusal(
            REASON_TEMPLATE_OUTPUT_GATE_REJECTED,
            note=_bounded_note(output_gate_refusal),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED,
        )

    validation = hwpx_validate(name, filled)
    if validation.status != STATUS_OK:
        return _template_fill_refusal(
            REASON_TEMPLATE_OUTPUT_VALIDATE_REJECTED,
            note=_bounded_note(validation.reason_code),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED,
        )

    read = hwpx_read(name, filled)
    if read.status != STATUS_OK:
        return _template_fill_refusal(
            REASON_TEMPLATE_OUTPUT_READBACK_REJECTED,
            note=_bounded_note(read.reason_code),
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OUTPUT_REFUSED,
        )

    # 7. The proof is the structured model, never flattened text alone.
    try:
        decoded = deserialize_hwpx_package(filled)
    except DocumentNormalizationError:
        return _template_fill_refusal(
            REASON_TEMPLATE_OUTPUT_ROUNDTRIP_MISMATCH,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
        )

    if len(decoded.sections) != len(source.sections):
        return _template_fill_refusal(
            REASON_TEMPLATE_OUTPUT_COUNT_DRIFT,
            note=None,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
        )
    for section_index, section in enumerate(source.sections):
        if len(decoded.sections[section_index].paragraphs) != len(section.paragraphs):
            return _template_fill_refusal(
                REASON_TEMPLATE_OUTPUT_COUNT_DRIFT,
                note=None,
                validation_status=VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
            )

    replacements = {
        (mutation.section_index, mutation.paragraph_index): mutation.text
        for mutation in mutations
    }
    for section_index, section in enumerate(source.sections):
        for paragraph_index, text in enumerate(section.paragraphs):
            target = (section_index, paragraph_index)
            expected = replacements.get(target, text)
            if decoded.sections[section_index].paragraphs[paragraph_index] != expected:
                if target in replacements:
                    return _template_fill_refusal(
                        REASON_TEMPLATE_OUTPUT_ROUNDTRIP_MISMATCH,
                        note=None,
                        validation_status=VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
                    )
                return _template_fill_refusal(
                    REASON_TEMPLATE_OUTPUT_MEMBER_DRIFT,
                    note=None,
                    validation_status=VALIDATION_STATUS_TEMPLATE_FILL_MISMATCH,
                )

    # 8. Non-target member preservation is deliberately NOT re-asserted here.
    #    #2979's mutator proves it about its own output through the single
    #    archive gate and the single raw-member accessor before it returns;
    #    re-checking it here would mean this facade owns a second archive
    #    accessor. ``test_hwpx_skill_template_fill`` asserts the contract
    #    against the mutator's output through the Core accessor, which is where
    #    a test may legitimately look.

    section_count = len(source.sections)
    paragraph_count = sum(len(section.paragraphs) for section in source.sections)
    filled_field_count = len(named_fields)
    artifact = HwpxTemplateFillArtifact(
        payload=filled,
        media_type=HWPX_MEDIA_TYPE,
        suggested_filename=name,
        byte_size=len(filled),
        section_count=section_count,
        paragraph_count=paragraph_count,
        filled_field_count=filled_field_count,
    )
    return HwpxTemplateFillResult(
        receipt=HwpxTemplateFillReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_TEMPLATE_FILL,
            reason_code="ok",
            note=None,
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename=name,
            byte_size=len(filled),
            section_count=section_count,
            paragraph_count=paragraph_count,
            filled_field_count=filled_field_count,
            validation_status=VALIDATION_STATUS_TEMPLATE_FILL_OK,
        ),
        artifact=artifact,
    )


@dataclass(frozen=True, slots=True)
class HwpxTableInsertionRequest:
    """Bounded rows and exact zero-based insertion position for one table."""

    section_index: int
    block_index: int
    rows: object


@dataclass(frozen=True, slots=True)
class HwpxInsertTableReceipt:
    """Bounded receipt for the ``hwpx.insert_table`` facade."""

    status: str
    capability_id: str
    reason_code: str
    note: str | None
    media_type: str | None
    suggested_filename: str | None
    byte_size: int | None
    section_count: int | None
    paragraph_count: int | None
    table_count: int | None
    inserted_row_count: int | None
    inserted_column_count: int | None
    validation_status: str

    def __post_init__(self) -> None:
        _require_receipt_fields(self.status, self.reason_code)
        if self.validation_status not in _INSERT_TABLE_VALIDATION_STATUSES:
            raise ValueError("hwpx_skill: insert_table validation_status must be bounded")
        if self.note is not None and not is_bounded_reason_code(self.note):
            raise ValueError("hwpx_skill: an insert_table note must be a bounded identifier")
        if self.status == STATUS_OK:
            if self.validation_status != VALIDATION_STATUS_INSERT_TABLE_OK:
                raise ValueError("hwpx_skill: an ok insert_table must verify its structured readback")
            if self.note is not None:
                raise ValueError("hwpx_skill: an ok insert_table receipt carries no note")
            if self.media_type != HWPX_MEDIA_TYPE:
                raise ValueError("hwpx_skill: an ok insert_table must report the HWPX media type")
            if not isinstance(self.suggested_filename, str) or not self.suggested_filename.endswith(
                HWPX_SUFFIX
            ):
                raise ValueError("hwpx_skill: an ok insert_table name must use the canonical suffix")
            if not isinstance(self.byte_size, int) or self.byte_size <= 0:
                raise ValueError("hwpx_skill: an ok insert_table must report a positive byte size")
            if not isinstance(self.section_count, int) or self.section_count <= 0:
                raise ValueError("hwpx_skill: an ok insert_table must report its section count")
            if not isinstance(self.paragraph_count, int) or self.paragraph_count < 0:
                raise ValueError("hwpx_skill: an ok insert_table must report its paragraph count")
            if not isinstance(self.table_count, int) or self.table_count <= 0:
                raise ValueError("hwpx_skill: an ok insert_table must report its table count")
            if not isinstance(self.inserted_row_count, int) or self.inserted_row_count <= 0:
                raise ValueError("hwpx_skill: an ok insert_table must report its row count")
            if not isinstance(self.inserted_column_count, int) or self.inserted_column_count <= 0:
                raise ValueError("hwpx_skill: an ok insert_table must report its column count")
            return
        if self.validation_status == VALIDATION_STATUS_INSERT_TABLE_OK:
            raise ValueError("hwpx_skill: a refused insert_table must not claim a verified readback")
        if any(
            value is not None
            for value in (
                self.media_type,
                self.suggested_filename,
                self.byte_size,
                self.section_count,
                self.paragraph_count,
                self.table_count,
                self.inserted_row_count,
                self.inserted_column_count,
            )
        ):
            raise ValueError("hwpx_skill: a refused insert_table receipt carries no artifact metadata")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "capability_id": self.capability_id,
            "reason_code": self.reason_code,
            "note": self.note,
            "media_type": self.media_type,
            "suggested_filename": self.suggested_filename,
            "byte_size": self.byte_size,
            "section_count": self.section_count,
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "inserted_row_count": self.inserted_row_count,
            "inserted_column_count": self.inserted_column_count,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True, slots=True)
class HwpxInsertTableArtifact:
    """In-memory artifact for one verified table insertion."""

    payload: bytes
    media_type: str
    suggested_filename: str
    byte_size: int
    section_count: int
    paragraph_count: int
    table_count: int
    inserted_row_count: int
    inserted_column_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("hwpx_skill: an insert_table artifact requires bounded bytes")
        if self.media_type != HWPX_MEDIA_TYPE:
            raise ValueError("hwpx_skill: an insert_table artifact must be HWPX")
        if not isinstance(self.suggested_filename, str) or not self.suggested_filename.endswith(
            HWPX_SUFFIX
        ):
            raise ValueError("hwpx_skill: an insert_table artifact name must use the canonical suffix")
        if self.byte_size != len(self.payload):
            raise ValueError("hwpx_skill: an insert_table artifact byte size must match its payload")
        if self.section_count <= 0 or self.paragraph_count < 0 or self.table_count <= 0:
            raise ValueError("hwpx_skill: an insert_table artifact must report bounded structure counts")
        if self.inserted_row_count <= 0 or self.inserted_column_count <= 0:
            raise ValueError("hwpx_skill: an insert_table artifact must report its table shape")


@dataclass(frozen=True, slots=True)
class HwpxInsertTableResult:
    """One insert_table outcome with bytes present only on success."""

    receipt: HwpxInsertTableReceipt
    artifact: HwpxInsertTableArtifact | None = None

    def __post_init__(self) -> None:
        if self.receipt.status == STATUS_OK and self.artifact is None:
            raise ValueError("hwpx_skill: an ok insert_table result must carry an artifact")
        if self.receipt.status != STATUS_OK and self.artifact is not None:
            raise ValueError("hwpx_skill: a refused insert_table result must not carry an artifact")

    def to_public_dict(self) -> dict[str, object]:
        return self.receipt.to_public_dict()


def _insert_table_refusal(
    reason_code: str,
    *,
    note: str | None,
    validation_status: str,
) -> HwpxInsertTableResult:
    return HwpxInsertTableResult(
        receipt=HwpxInsertTableReceipt(
            status=STATUS_REFUSED,
            capability_id=CAPABILITY_HWPX_EDIT,
            reason_code=reason_code,
            note=note,
            media_type=None,
            suggested_filename=None,
            byte_size=None,
            section_count=None,
            paragraph_count=None,
            table_count=None,
            inserted_row_count=None,
            inserted_column_count=None,
            validation_status=validation_status,
        ),
        artifact=None,
    )


def _section_blocks(section: HwpxPackageSection) -> tuple[HwpxSectionBlock, ...]:
    if section.blocks:
        return section.blocks
    return tuple(HwpxSectionBlock("paragraph", text=text) for text in section.paragraphs)


def _insert_table_request_refusal(
    request: object,
    source: HwpxPackageContent,
) -> str | None:
    if not isinstance(request, HwpxTableInsertionRequest):
        return REASON_INSERT_TABLE_REQUEST_SHAPE
    if not isinstance(request.section_index, int) or isinstance(request.section_index, bool):
        return REASON_INSERT_TABLE_REQUEST_SHAPE
    if not isinstance(request.block_index, int) or isinstance(request.block_index, bool):
        return REASON_INSERT_TABLE_REQUEST_SHAPE
    if request.section_index < 0:
        return REASON_INSERT_TABLE_SECTION_INDEX_NEGATIVE
    if request.block_index < 0:
        return REASON_INSERT_TABLE_BLOCK_INDEX_NEGATIVE
    if request.section_index >= len(source.sections):
        return REASON_INSERT_TABLE_SECTION_OUT_OF_RANGE
    if not isinstance(request.rows, (tuple, list)):
        return REASON_INSERT_TABLE_REQUEST_SHAPE
    if not request.rows:
        return REASON_INSERT_TABLE_ROWS_EMPTY
    rows = tuple(request.rows)
    if len(rows) > MAX_HWPX_TABLE_ROWS:
        return REASON_INSERT_TABLE_ROW_LIMIT
    for row in rows:
        if not isinstance(row, (tuple, list)) or not row or not all(
            isinstance(text, str) for text in row
        ):
            return REASON_INSERT_TABLE_REQUEST_SHAPE
    widths = {len(row) for row in rows}
    if len(widths) != 1 or 0 in widths:
        return REASON_INSERT_TABLE_ROWS_RAGGED
    column_count = next(iter(widths))
    if column_count > MAX_HWPX_TABLE_COLUMNS:
        return REASON_INSERT_TABLE_COLUMN_LIMIT
    if len(rows) * column_count > MAX_HWPX_TABLE_CELLS:
        return REASON_INSERT_TABLE_CELL_LIMIT
    for row in rows:
        for text in row:
            try:
                validate_hwpx_paragraph_text(text)
            except DocumentNormalizationError:
                return REASON_INSERT_TABLE_CELL_TEXT_REJECTED
    section = source.sections[request.section_index]
    if request.block_index > len(_section_blocks(section)):
        return REASON_INSERT_TABLE_BLOCK_OUT_OF_RANGE
    return None


def _insert_table_model(
    source: HwpxPackageContent,
    request: HwpxTableInsertionRequest,
) -> tuple[HwpxPackageContent, HwpxTable]:
    rows = tuple(tuple(text for text in row) for row in request.rows)
    table = HwpxTable(tuple(tuple(HwpxTableCell(text) for text in row) for row in rows))
    inserted = HwpxSectionBlock("table", table=table)
    sections: list[HwpxPackageSection] = []
    for section_index, section in enumerate(source.sections):
        if section_index != request.section_index:
            sections.append(section)
            continue
        blocks = _section_blocks(section)
        blocks = blocks[: request.block_index] + (inserted,) + blocks[request.block_index :]
        sections.append(
            HwpxPackageSection(
                paragraphs=tuple(
                    block.text for block in blocks if block.kind == "paragraph"
                ),
                blocks=blocks,
            )
        )
    return HwpxPackageContent(sections=tuple(sections)), table


def _table_count(content: HwpxPackageContent) -> int:
    return sum(
        block.kind == "table"
        for section in content.sections
        for block in _section_blocks(section)
    )


def hwpx_insert_table(
    filename: str,
    payload: bytes,
    request: HwpxTableInsertionRequest,
) -> HwpxInsertTableResult:
    """Insert one bounded Core table block into a canonical HWPX package.

    The common gate runs before request validation. The source is decoded and
    required to reserialize to the exact input bytes before its section/block
    address is used. The inserted table is then proven at the exact requested
    position while every non-target section and block remains unchanged.
    """

    gate = inspect_file(filename, payload)
    gate_refusal = _gate_refusal(gate)
    if gate_refusal is not None:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_GATE_REJECTED,
            note=_bounded_note(gate_refusal),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SOURCE_REFUSED,
        )

    try:
        source = deserialize_hwpx_package(payload)
    except DocumentNormalizationError as error:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_SOURCE_DECODER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SOURCE_REFUSED,
        )

    try:
        canonical_source = serialize_hwpx_package(source)
    except DocumentNormalizationError:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SOURCE_NOT_CANONICAL,
        )
    if canonical_source != payload:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_SOURCE_NOT_CANONICAL,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SOURCE_NOT_CANONICAL,
        )

    request_refusal = _insert_table_request_refusal(request, source)
    if request_refusal is not None:
        return _insert_table_refusal(
            request_refusal,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_REQUEST_REFUSED,
        )

    intended, inserted_table = _insert_table_model(source, request)
    inserted_block = intended.sections[request.section_index].blocks[request.block_index]
    try:
        inserted_payload = serialize_hwpx_package(intended)
    except DocumentNormalizationError as error:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_SERIALIZER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SERIALIZER_REFUSED,
        )
    if not isinstance(inserted_payload, bytes) or not inserted_payload:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_SERIALIZER_REJECTED,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_SERIALIZER_REFUSED,
        )

    name = _suggested_filename(filename)
    output_gate = inspect_file(name, inserted_payload)
    output_gate_refusal = _gate_refusal(output_gate)
    if output_gate_refusal is not None:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_GATE_REJECTED,
            note=_bounded_note(output_gate_refusal),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED,
        )

    validation = hwpx_validate(name, inserted_payload)
    if validation.status != STATUS_OK:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_VALIDATE_REJECTED,
            note=_bounded_note(validation.reason_code),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED,
        )

    read = hwpx_read(name, inserted_payload)
    if read.status != STATUS_OK:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_READBACK_REJECTED,
            note=_bounded_note(read.reason_code),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_REFUSED,
        )

    try:
        decoded = deserialize_hwpx_package(inserted_payload)
    except DocumentNormalizationError as error:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_DECODER_REJECTED,
            note=_bounded_note(getattr(error, "code", None)),
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
        )

    if len(decoded.sections) != len(source.sections) or _table_count(decoded) != _table_count(
        source
    ) + 1:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
        )
    if sum(len(section.paragraphs) for section in decoded.sections) != sum(
        len(section.paragraphs) for section in source.sections
    ):
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
        )
    for section_index, section in enumerate(decoded.sections):
        if section_index != request.section_index and section != source.sections[section_index]:
            return _insert_table_refusal(
                REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT,
                note=None,
                validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
            )

    source_blocks = _section_blocks(source.sections[request.section_index])
    decoded_blocks = _section_blocks(decoded.sections[request.section_index])
    if len(decoded_blocks) != len(source_blocks) + 1:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_COUNT_DRIFT,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
        )
    for output_index, block in enumerate(decoded_blocks):
        if output_index == request.block_index:
            if block != inserted_block:
                return _insert_table_refusal(
                    REASON_INSERT_TABLE_OUTPUT_TABLE_MISMATCH,
                    note=None,
                    validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
                )
            continue
        source_index = output_index if output_index < request.block_index else output_index - 1
        if source_index >= len(source_blocks) or block != source_blocks[source_index]:
            return _insert_table_refusal(
                REASON_INSERT_TABLE_OUTPUT_NON_TARGET_DRIFT,
                note=None,
                validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
            )
    if decoded != intended:
        return _insert_table_refusal(
            REASON_INSERT_TABLE_OUTPUT_ROUNDTRIP_MISMATCH,
            note=None,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OUTPUT_MISMATCH,
        )

    section_count = len(decoded.sections)
    paragraph_count = sum(len(section.paragraphs) for section in decoded.sections)
    table_count = _table_count(decoded)
    inserted_row_count = len(inserted_table.rows)
    inserted_column_count = len(inserted_table.rows[0])
    artifact = HwpxInsertTableArtifact(
        payload=inserted_payload,
        media_type=HWPX_MEDIA_TYPE,
        suggested_filename=name,
        byte_size=len(inserted_payload),
        section_count=section_count,
        paragraph_count=paragraph_count,
        table_count=table_count,
        inserted_row_count=inserted_row_count,
        inserted_column_count=inserted_column_count,
    )
    return HwpxInsertTableResult(
        receipt=HwpxInsertTableReceipt(
            status=STATUS_OK,
            capability_id=CAPABILITY_HWPX_EDIT,
            reason_code="ok",
            note=None,
            media_type=HWPX_MEDIA_TYPE,
            suggested_filename=name,
            byte_size=len(inserted_payload),
            section_count=section_count,
            paragraph_count=paragraph_count,
            table_count=table_count,
            inserted_row_count=inserted_row_count,
            inserted_column_count=inserted_column_count,
            validation_status=VALIDATION_STATUS_INSERT_TABLE_OK,
        ),
        artifact=artifact,
    )

