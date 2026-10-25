"""#4434: the production Python-path editor and verifier for an approved XLSX copy.

``kagent.local_xlsx_revision_pdf`` already owns the revision *contract*: an
approved source handoff, a literal ``ReviewedCellRevision`` list, an editor port,
an independent verifier port and the canonical artifact/lineage registration.
Only the ports were missing a real implementation, so this module supplies
exactly those two and nothing else.

Why a surgical OOXML edit instead of a workbook round-trip
----------------------------------------------------------
The reviewed Python behaviour is "replace the value of these exact cells and
change nothing else". A full workbook re-save would re-emit every part, silently
drop cached values, restyle sheets and rewrite the theme — a fidelity loss the
repository's own ``classify_xlsx`` already refuses to convert. Copying every
member byte-for-byte and rewriting only the sheet parts that hold a target cell
keeps formulas, merged ranges, print settings, styles, theme and every untouched
cell exactly as they were, which is what the independent verifier can then prove.

Where the Python path stops
---------------------------
Any workbook that contains a formula (``<f>`` in a sheet, or a calculation chain)
is refused with ``OfficeFidelityRequired``. Replacing an input value makes the
cached results of dependent formulas stale, and only the real Office engine can
recalculate them, so those workbooks belong to the existing
``windows_excel_pdf_renderer`` / ``supervised_windows_excel_pdf`` path instead of
being quietly mis-edited here. ``classify_xlsx`` stays the untrusted-input gate:
its ``REJECT`` route is refused before any byte is touched.

This module performs no file I/O, no network, and no authorization. The caller is
the trusted local host that already holds the P01-approved read of the workcopy.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import re
from typing import Iterable
import zipfile
import xml.etree.ElementTree as ET

from .contracts import ContractError
from .local_xlsx_revision_pdf import ReviewedCellRevision
from .xlsx_fidelity_route import MAX_XML_BYTES, XlsxRoute, classify_xlsx

SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKBOOK_PART = "xl/workbook.xml"
WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"
CALC_CHAIN_PART = "xl/calcchain.xml"
_SHARED_PREFIX = re.compile(r"^xl/(?:sharedStrings|sharedstrings)\.xml$")

PYTHON_VALUE_PATH_IMPLEMENTED = True
ORIGINAL_BYTES_NEVER_REWRITTEN = True
FORMULA_WORKBOOKS_ROUTED_TO_OFFICE = True
RAW_PATH_OR_NETWORK_ACCESS = False


class OfficeFidelityRequired(ContractError):
    """The workbook needs the existing Office/Local Runner path, not Python."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"office_fidelity_required:{reason}")
        self.route_reason = reason


#: A workbook part is untrusted input even after ``classify_xlsx`` passes it.
#: ElementTree expands entities and follows internal DTD subsets, so a part that
#: declares a DTD or an entity is refused before parsing, and no part larger than
#: the classifier's own XML bound reaches a parser at all.
_FORBIDDEN_XML_MARKERS = (b"<!DOCTYPE", b"<!doctype", b"<!ENTITY", b"<!entity")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml_part(data: bytes, *, part_name: str) -> ET.Element:
    if not isinstance(data, bytes) or not data:
        raise ContractError(f"workbook part {part_name} is empty")
    if len(data) > MAX_XML_BYTES:
        raise ContractError(f"workbook part {part_name} exceeds the XML bound")
    if any(marker in data for marker in _FORBIDDEN_XML_MARKERS):
        raise ContractError(f"workbook part {part_name} declares a DTD or entity")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ContractError(f"workbook part {part_name} is not valid XML") from exc


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for item in element:
        if item.tag == f"{{{SHEET_NS}}}{name}":
            return item
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in element if item.tag == f"{{{SHEET_NS}}}{name}"]


@dataclass(frozen=True, slots=True)
class _SheetCell:
    ref: str
    type: str
    value: str


class _WorkbookParts:
    """Bounded read of the parts this edit needs, from already-approved bytes."""

    def __init__(self, data: bytes) -> None:
        try:
            self._archive = zipfile.ZipFile(io.BytesIO(data), mode="r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ContractError("workbook could not be opened") from exc
        self.names = list(self._archive.namelist())
        if len(set(self.names)) != len(self.names):
            raise ContractError("workbook contains duplicate parts")

    def read(self, name: str) -> bytes:
        try:
            return self._archive.read(name)
        except (KeyError, OSError) as exc:
            raise ContractError(f"workbook part {name} is unavailable") from exc

    def info(self, name: str) -> zipfile.ZipInfo:
        try:
            return self._archive.getinfo(name)
        except KeyError as exc:
            raise ContractError(f"workbook part {name} is unavailable") from exc

    def close(self) -> None:
        self._archive.close()

    def sheet_part_for(self, sheet_name: str) -> str:
        root = _parse_xml_part(self.read(WORKBOOK_PART), part_name=WORKBOOK_PART)
        relationships = {
            item.attrib.get("Id"): item.attrib.get("Target")
            for item in _parse_xml_part(self.read(WORKBOOK_RELS_PART), part_name=WORKBOOK_RELS_PART)
            if item.tag == f"{{{PACKAGE_REL_NS}}}Relationship"
        }
        for sheet in root.iter(f"{{{SHEET_NS}}}sheet"):
            if sheet.attrib.get("name") != sheet_name:
                continue
            target = relationships.get(sheet.attrib.get(f"{{{REL_NS}}}id"))
            if not isinstance(target, str) or not target:
                raise ContractError("worksheet relationship is unresolvable")
            if "\\" in target or ":" in target or any(
                part == ".." for part in target.replace("/", "\\").split("\\")
            ):
                # Only two shapes are legal inside a package: a part name that
                # starts at the package root, or one relative to xl/workbook.xml.
                raise ContractError("worksheet relationship escapes the package")
            if target.startswith("/"):
                name = target.lstrip("/")
            else:
                name = target if target.startswith("xl/") else "xl/" + target.lstrip("./")
            if name not in self.names:
                raise ContractError("worksheet part is missing from the workbook")
            return name
        raise ContractError("requested worksheet does not exist")

    def shared_strings(self) -> tuple[str, ...]:
        for name in self.names:
            if not _SHARED_PREFIX.match(name):
                continue
            root = _parse_xml_part(self.read(name), part_name=name)
            return tuple(
                "".join(part.text or "" for part in _children(item, "t"))
                if _child(item, "t") is not None else
                "".join(part.text or "" for si in _children(item, "r") for part in _children(si, "t"))
                for item in _children(root, "si")
            )
        return ()

    def has_formula(self) -> bool:
        if CALC_CHAIN_PART in self.names:
            return True
        for name in self.names:
            if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                continue
            for item in _parse_xml_part(self.read(name), part_name=name).iter():
                if _local(item.tag) == "f":
                    return True
        return False

    def cell_of(self, sheet_part: str, ref: str, shared: tuple[str, ...]) -> _SheetCell:
        root = _parse_xml_part(self.read(sheet_part), part_name=sheet_part)
        for cell in root.iter(f"{{{SHEET_NS}}}c"):
            if cell.attrib.get("r") != ref:
                continue
            return _read_cell(cell, shared)
        raise ContractError(f"cell {ref} does not exist in the approved worksheet")


def _read_cell(cell: ET.Element, shared: tuple[str, ...]) -> _SheetCell:
    ref = cell.attrib.get("r") or ""
    kind = cell.attrib.get("t") or "n"
    if kind == "inlineStr":
        node = _child(cell, "is")
        return _SheetCell(ref, kind, "".join(p.text or "" for p in _children(node, "t")) if node else "")
    value = _child(cell, "v")
    raw = value.text if value is not None else None
    if kind == "s":
        index_text = (raw or "").strip()
        if not index_text.isdigit() or int(index_text) >= len(shared):
            raise ContractError("shared string cell reference is invalid")
        return _SheetCell(ref, kind, shared[int(index_text)])
    if kind in ("n", "str"):
        return _SheetCell(ref, kind, raw or "")
    raise ContractError(f"cell {ref} type {kind} is outside the reviewed value path")


class PythonXlsxValueCopyEditor:
    """Replace literal cell values in an approved copy; change nothing else."""

    def revise_xlsx_copy(
        self, source_bytes: bytes, edits: tuple[ReviewedCellRevision, ...]
    ) -> bytes:
        if not isinstance(source_bytes, bytes) or not source_bytes:
            raise ContractError("approved workbook bytes are required")
        edits = _validated_edits(edits)
        decision = classify_xlsx(source_bytes, local_only=True)
        if decision.route is XlsxRoute.REJECT:
            raise ContractError(f"untrusted workbook refused: {decision.reason}")

        source = _WorkbookParts(source_bytes)
        try:
            if source.has_formula():
                raise OfficeFidelityRequired("cached formula results would go stale")
            shared = source.shared_strings()
            targets: dict[str, list[ReviewedCellRevision]] = {}
            for edit in edits:
                part = source.sheet_part_for(edit.sheet_name)
                cell = source.cell_of(part, edit.cell, shared)
                _require_previous_value(edit, cell)
                targets.setdefault(part, []).append(edit)
            return _rewrite_parts(source, targets)
        finally:
            source.close()


def _validated_edits(edits: Iterable[ReviewedCellRevision]) -> tuple[ReviewedCellRevision, ...]:
    items = tuple(edits)
    if not items or any(not isinstance(item, ReviewedCellRevision) for item in items):
        raise ContractError("at least one reviewed cell revision is required")
    keys = {(item.sheet_name, item.cell) for item in items}
    if len(keys) != len(items):
        raise ContractError("duplicate reviewed cell revision")
    return items


def _require_previous_value(edit: ReviewedCellRevision, cell: _SheetCell) -> None:
    if type(edit.previous_value) is int:
        try:
            observed: float | str = float(cell.value)
        except ValueError:
            observed = cell.value
        matches = observed == float(edit.previous_value)
    else:
        matches = cell.value == edit.previous_value
    if not matches:
        raise ContractError(
            f"cell {cell.ref} no longer holds the reviewed previous value"
        )


def _set_cell_value(cell: ET.Element, replacement: str | int) -> None:
    for name in ("v", "is", "f"):
        for node in _children(cell, name):
            cell.remove(node)
    if type(replacement) is int:
        cell.attrib.pop("t", None)
        value = ET.SubElement(cell, f"{{{SHEET_NS}}}v")
        value.text = str(replacement)
        return
    if type(replacement) is not str:
        raise ContractError("reviewed replacement must be literal text or integer")
    cell.set("t", "inlineStr")
    node = ET.SubElement(cell, f"{{{SHEET_NS}}}is")
    text = ET.SubElement(node, f"{{{SHEET_NS}}}t")
    text.text = replacement
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _rewrite_parts(
    source: _WorkbookParts, targets: dict[str, list[ReviewedCellRevision]]
) -> bytes:
    ET.register_namespace("", SHEET_NS)
    ET.register_namespace("r", REL_NS)
    shared = source.shared_strings()
    rewritten: dict[str, bytes] = {}
    for part, edits in targets.items():
        root = _parse_xml_part(source.read(part), part_name=part)
        by_ref = {
            cell.attrib.get("r"): cell
            for cell in root.iter(f"{{{SHEET_NS}}}c")
            if cell.attrib.get("r")
        }
        for edit in edits:
            _set_cell_value(by_ref[edit.cell], edit.replacement_value)
        rewritten[part] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as output:
        for name in source.names:
            info = source.info(name)
            data = rewritten.get(name, source.read(name))
            entry = zipfile.ZipInfo(name, date_time=info.date_time)
            entry.compress_type = info.compress_type
            entry.external_attr = info.external_attr
            output.writestr(entry, data)
    return buffer.getvalue()


class IndependentZipXlsxRevisionVerifier:
    """Prove, from the two byte blobs alone, that only reviewed edits happened."""

    def verify_only_reviewed_edits(
        self,
        source_bytes: bytes,
        revised_bytes: bytes,
        edits: tuple[ReviewedCellRevision, ...],
    ) -> bool:
        if not isinstance(source_bytes, bytes) or not isinstance(revised_bytes, bytes):
            return False
        edits = tuple(edits)
        if not edits or any(not isinstance(item, ReviewedCellRevision) for item in edits):
            return False
        for data in (source_bytes, revised_bytes):
            if classify_xlsx(data, local_only=True).route is XlsxRoute.REJECT:
                return False

        source = _WorkbookParts(source_bytes)
        revised = _WorkbookParts(revised_bytes)
        try:
            if sorted(source.names) != sorted(revised.names):
                return False
            if source.has_formula() or revised.has_formula():
                return False
            shared_source, shared_revised = source.shared_strings(), revised.shared_strings()
            expected_parts: dict[str, set[str]] = {}
            for edit in edits:
                expected_parts.setdefault(source.sheet_part_for(edit.sheet_name), set()).add(edit.cell)
            changed = [
                name for name in source.names
                if source.read(name) != revised.read(name)
            ]
            if sorted(changed) != sorted(expected_parts):
                return False

            by_sheet: dict[tuple[str, str], ReviewedCellRevision] = {}
            for edit in edits:
                part = source.sheet_part_for(edit.sheet_name)
                by_sheet[(part, edit.cell)] = edit

            for part, refs in expected_parts.items():
                before = _cells_of(source.read(part), shared_source)
                after = _cells_of(revised.read(part), shared_revised)
                if set(before) != set(after):
                    return False
                for ref, value in before.items():
                    if ref in refs:
                        continue
                    if value != after[ref]:
                        return False
                for ref in refs:
                    revision = by_sheet[(part, ref)]
                    if not _replacement_matches(after[ref], revision.replacement_value):
                        return False
            return True
        except (ContractError, ET.ParseError, zipfile.BadZipFile, KeyError, ValueError):
            return False
        finally:
            source.close()
            revised.close()


def _cells_of(sheet_xml: bytes, shared: tuple[str, ...]) -> dict[str, str]:
    root = _parse_xml_part(sheet_xml, part_name="worksheet")
    cells: dict[str, str] = {}
    for cell in root.iter(f"{{{SHEET_NS}}}c"):
        ref = cell.attrib.get("r")
        if not ref:
            continue
        cells[ref] = _read_cell(cell, shared).value
    return cells


def _replacement_matches(observed: str, replacement: str | int) -> bool:
    if type(replacement) is int:
        return observed == str(replacement)
    return observed == replacement
