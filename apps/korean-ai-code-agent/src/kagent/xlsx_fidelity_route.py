"""Fail-closed XLSX fidelity routing for #3580.

Does not convert any workbook or claim Google Sheets feature equivalence.
Produces a conservative *routing decision* only; a Sheets working copy may be
used after a separately verified conversion/fidelity gate. Source-only, no
filesystem, network or provider authority. Local-only inputs require the
existing Desktop/Local Runner: cloud routes NEVER read user-local paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import io
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_XLSX_BYTES = 8 * 1024 * 1024
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_UNCOMPRESSED_TOTAL = 24 * 1024 * 1024
MAX_FILES = 128
MAX_COMPRESSION_RATIO = 150
SHEET_PATTERN = re.compile(r"^xl/worksheets/sheet[1-9]\d{0,3}\.xml$")
BLOCKED_PARTS = (
    "xl/vba", "xl/externallinks/", "xl/drawings/", "xl/charts/",
    "xl/pivot", "xl/embeddings/", "xl/activex/", "xl/media/",
    "xl/printersettings/", "xl/ctrlprops/", "xl/connections",
    "xl/comments", "xl/threadedcomments", "customxml/",
)
BLOCKED_XML_TAGS = frozenset({
    "f", "mergeCells", "conditionalFormatting", "dataValidation",
    "drawing", "legacyDrawing", "picture", "oleObjects", "extLst",
    "autoFilter", "tableParts", "sheetProtection", "pageSetup",
    "pageMargins", "printOptions", "rowBreaks", "colBreaks",
    "hyperlinks", "pivotTable", "definedNames", "externalReferences",
})


class XlsxRoute(str, Enum):
    REJECT = "reject_untrusted_xlsx"
    OFFICE_FALLBACK = "office_ephemeral_or_desktop_fallback"
    NATIVE_CANDIDATE_REQUIRES_PROOF = "google_sheets_candidate_requires_conversion_proof"


@dataclass(frozen=True, slots=True)
class XlsxRouteDecision:
    route: XlsxRoute
    reason: str
    execution_target: str
    preserves_original: bool = True
    google_conversion_verified: bool = False
    output_fidelity_verified: bool = False

    @property
    def may_automatically_convert(self) -> bool:
        return False

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-xlsx-safe-route.v1",
            "route": self.route.value,
            "reason": self.reason,
            "execution_target": self.execution_target,
            "original_preserved": self.preserves_original,
            "auto_google_conversion": False,
            "fidelity_verified": False,
            "raw_workbook_bytes": False,
        }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_root(file: zipfile.ZipFile, name: str) -> ET.Element:
    info = file.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise ValueError("XML part exceeds bounded size")
    return ET.fromstring(file.read(name))


def _decision(route: XlsxRoute, reason: str, local_only: bool) -> XlsxRouteDecision:
    if route is XlsxRoute.REJECT:
        target = "none"
    elif local_only:
        target = "padiem_desktop_local_runner"
    elif route is XlsxRoute.OFFICE_FALLBACK:
        target = "ephemeral_office_renderer"
    else:
        target = "google_workspace_after_explicit_verified_conversion"
    return XlsxRouteDecision(route, reason, target)


def classify_xlsx(data: bytes, *, local_only: bool = False) -> XlsxRouteDecision:
    """Classify bounded XLSX content without extraction or conversion.

    No model-supplied risk override; suspected corruption/zipbomb rejects.
    Advanced Office constructs are fidelity-sensitive and need an Office
    renderer. Even simple XML is a *candidate* only, not an approved import.
    """
    if not isinstance(local_only, bool):
        return _decision(XlsxRoute.REJECT, "invalid_locality", False)
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_XLSX_BYTES:
        return _decision(XlsxRoute.REJECT, "invalid_or_oversize_input", local_only)
    if not data.startswith(b"PK\x03\x04"):
        return _decision(XlsxRoute.REJECT, "not_ooxml_zip", local_only)
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            infos = zf.infolist()
            if not 1 <= len(infos) <= MAX_FILES:
                return _decision(XlsxRoute.REJECT, "part_count_exceeds_bound", local_only)
            names = set()
            total = 0
            advanced = False
            for info in infos:
                name = info.filename
                if (not name or name.startswith("/") or "\\" in name
                        or any(part in ("", ".", "..") for part in name.split("/"))
                        or "\x00" in name
                        or name.casefold() in names
                        or info.flag_bits & 1
                        or info.is_dir()):
                    return _decision(XlsxRoute.REJECT, "unsafe_archive_member", local_only)
                names.add(name.casefold())
                total += info.file_size
                if total > MAX_UNCOMPRESSED_TOTAL or info.file_size > MAX_UNCOMPRESSED_TOTAL:
                    return _decision(XlsxRoute.REJECT, "archive_expansion_exceeds_bound", local_only)
                if info.file_size > MAX_XML_BYTES and name.endswith((".xml", ".rels")):
                    return _decision(XlsxRoute.REJECT, "oversize_xml_member", local_only)
                if info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO:
                    return _decision(XlsxRoute.REJECT, "archive_compression_ratio", local_only)
                lowered = name.casefold()
                if any(lowered.startswith(prefix) for prefix in BLOCKED_PARTS):
                    advanced = True
                if lowered in ("xl/styles.xml", "xl/calcchain.xml", "xl/theme/theme1.xml"):
                    advanced = True

            required = {"[content_types].xml", "_rels/.rels", "xl/workbook.xml"}
            if not required.issubset(names):
                return _decision(XlsxRoute.REJECT, "not_a_supported_workbook", local_only)
            sheets = [x.filename for x in infos if SHEET_PATTERN.fullmatch(x.filename)]
            if not sheets:
                return _decision(XlsxRoute.REJECT, "workbook_has_no_simple_sheets", local_only)
            if len(sheets) > 10:
                advanced = True
            for name in ("[Content_Types].xml", "xl/workbook.xml", *sheets):
                root = _xml_root(zf, name)
                for item in root.iter():
                    tag = _local(item.tag)
                    if tag in BLOCKED_XML_TAGS or (
                        tag == "c" and item.attrib.get("s", "0") != "0"
                    ):
                        advanced = True
            # Every one of these outcomes preserves the XLSX as source.
            if advanced:
                return _decision(XlsxRoute.OFFICE_FALLBACK,
                                 "fidelity_sensitive_workbook_features", local_only)
            return _decision(XlsxRoute.NATIVE_CANDIDATE_REQUIRES_PROOF,
                             "simple_structure_requires_conversion_and_fidelity_proof", local_only)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, ET.ParseError, KeyError):
        return _decision(XlsxRoute.REJECT, "invalid_or_untrusted_ooxml", local_only)
