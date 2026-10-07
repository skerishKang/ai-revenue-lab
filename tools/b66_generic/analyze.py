# -*- coding: utf-8 -*-
"""B66 generic source analyzer (template-agnostic).

READ-ONLY. Produces two evidence JSONs from a source pair:

    analyze.py --xlsx <path> --pdf <path> --outdir <dir>

    <outdir>/xlsx_analysis.json   workbook/sheet/cell/merge/drawing/VML facts
    <outdir>/pdf_analysis.json    page geometry, per-char text spans, images,
                                  vector drawing ops

This module contains NO template-specific, customer-specific or document-specific
literal. Everything it emits is a raw observation of the input files; semantic
role assignment happens later in the generic compiler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def col_to_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(idx: int) -> str:
    letters, n = "", idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _resolve_mc_children(container) -> list:
    """Expand mc:AlternateContent to its Fallback branch (Excel-applied branch).

    HanCell/Excel save styles.xml with AlternateContent wrappers; the Fallback
    branch is what Excel actually applies, so style indices must be counted with
    those children inlined (#3535 lesson).
    """
    out = []
    for child in container:
        tag = child.tag.split("}")[-1]
        if tag == "AlternateContent":
            fb = child.find(f"{{{NS['mc']}}}Fallback")
            if fb is not None:
                out.extend(_resolve_mc_children(fb))
        else:
            out.append(child)
    return out


# ──────────────────── bounded archive policy (#3679) ────────────────────
#
# Every value below is the canonical OOXML/archive bound already enforced by
# ``padiem_ai_core.document_normalization`` (#3637) and by
# ``kagent.file_intake_safety.FileIntakePolicy`` (#2824). The names mirror Core's on purpose, and
# ``tests/test_b66_generic_archive_bounds.py`` asserts them against **this checkout's** Core and
# KAgent through a subprocess pinned with ``PYTHONPATH`` + ``PYTHONNOUSERSITE=1``, so the mirror
# cannot drift into a second, looser archive authority and cannot satisfy the check with a foreign
# editable install.
#
# The analyzer cannot import Core directly: ``test_b66_generic_compile.py`` runs this file as a bare
# script (``[sys.executable, "…/analyze.py", …]``) with no install step, so a hard Core import would
# be an undeclared runtime dependency for a tool that is deliberately stdlib-only.
MAX_BINARY_DOCUMENT_BYTES = 2 * 1024 * 1024          # Core MAX_BINARY_DOCUMENT_BYTES
MAX_OOXML_ENTRIES = 256                              # Core MAX_OOXML_ENTRIES
MAX_OOXML_MEMBER_NAME_CHARS = 255                    # Core MAX_OOXML_MEMBER_NAME_CHARS
MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES = 1 * 1024 * 1024  # Core MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES
MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024  # Core MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES
#: ``FileIntakePolicy.max_expansion_ratio``. A declared uncompressed size is a claim, not a bound, so
#: the compressed -> uncompressed ratio is capped independently of the byte ceilings above.
MAX_EXPANSION_RATIO = 200.0

# ``MAX_SUPPORTED_ARCHIVE_DEPTH`` is 4 in the Product gate. This tool opens exactly one archive and
# never constructs a ZipFile from a member's bytes -- embedded archives are hashed as media, not
# parsed -- so its nested depth is 0 by construction.

#: Mirrored from ``kagent.file_intake_safety``, which mirrors the same POSIX stat constants.
_S_IFMT = 0o170000
_S_IFLNK = getattr(stat, "S_IFLNK", 0o120000)


class ArchivePolicyError(RuntimeError):
    """A refusal to read an archive, carrying Core's code vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _safe_ooxml_member(name: object) -> bool:
    """Mirror of Core's single path-safety predicate. Do not widen it here."""

    if not isinstance(name, str) or not name:
        return False
    if "\\" in name or name.startswith("/") or "//" in name:
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    return all(part not in {"", ".", ".."} for part in PurePosixPath(name).parts)


def _is_link_entry(info) -> bool:
    """Mirror of ``kagent.file_intake_safety._is_link_entry``; its semantics, no new rule.

    The central directory carries the member's POSIX mode in the high half of ``external_attr``. A
    symlink entry is refused at admission whether or not this tool ever extracts to a filesystem: a
    link entry in an archive is itself the defect.
    """

    return ((info.external_attr >> 16) & _S_IFMT) == _S_IFLNK


def aggregate_expansion_violation(
    total_uncompressed: int, total_compressed: int, *, limit: float = MAX_EXPANSION_RATIO
) -> bool:
    """``kagent.file_intake_safety`` aggregate check: declared bytes over compressed bytes.

    Kept separate from the walk so it is directly testable. With the per-entry check below in force
    this is defensive rather than reachable -- the aggregate is the weighted mean of per-entry
    ratios, so it cannot exceed the largest one -- which is precisely why KAgent states the per-entry
    check "is what stops a bomb entry being diluted by padding".
    """

    return total_compressed > 0 and (total_uncompressed / total_compressed) > limit


def bounded_read_zip_member(archive, member, *, max_bytes: int) -> bytes:
    """Read one member with the *inflate work* bounded, rather than the result truncated.

    ``ZipFile.read`` and an unsized ``ZipExtFile.read`` decompress the entire deflate stream and only
    afterwards cut the result to the declared size, so an archive declaring a small size over a large
    compressed stream is amplified before any metadata bound can apply. Passing an explicit length
    through the streaming API caps the real inflate work at ``min(file_size, max_bytes)``; a
    well-formed member still reads byte-identically, which is what keeps evidence hashes stable.
    """

    info = member if isinstance(member, zipfile.ZipInfo) else archive.getinfo(member)
    limit = min(info.file_size, max_bytes)
    try:
        with archive.open(info) as handle:
            data = handle.read(limit + 1)
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as exc:
        # A member whose real bytes do not match its own declared metadata is a malformed archive,
        # not a readable one: fail closed with a code instead of surfacing a raw traceback.
        raise ArchivePolicyError("ooxml_malformed", "OOXML archive member is unreadable.") from exc
    if len(data) > limit:
        raise ArchivePolicyError("ooxml_entry_size", "OOXML archive entry exceeds the size limit.")
    return data


def _reject_dtd(payload: bytes, name: str) -> None:
    """Core's rule, applied at admission to every XML and relationship part, used or not."""

    if b"<!doctype" in payload.lower():
        raise ArchivePolicyError("ooxml_dtd_rejected", "DTDs are not supported in OOXML documents.")


class BoundedOOXML:
    """A ZIP archive whose central directory has been judged before any member is read.

    Checks run over every member up front, and the parsed directory is reused for each read, so a
    read is an already-admitted lookup rather than a fresh act of trust.
    """

    def __init__(self, archive, infos_by_name):
        self._archive = archive
        self._infos = infos_by_name

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self) -> None:
        self._archive.close()

    def names(self) -> list:
        return sorted(self._infos)

    def has(self, name: str) -> bool:
        return name in self._infos

    def read(self, name: str, *, max_bytes: int = MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES) -> bytes:
        info = self._infos.get(name)
        if info is None:
            raise ArchivePolicyError("ooxml_malformed", "Required OOXML member is missing.")
        return bounded_read_zip_member(self._archive, info, max_bytes=max_bytes)

    def read_xml(self, name: str, *, max_bytes: int = MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES):
        """Bounded read, then DTD rejection, then parse -- the order Core uses.

        The byte cap is what makes an XML failure cheap: the part is already in bounded memory
        before a parser touches it.
        """

        data = self.read(name, max_bytes=max_bytes)
        _reject_dtd(data, name)
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise ArchivePolicyError("ooxml_invalid_xml", "Invalid OOXML XML part.") from exc


def open_bounded_ooxml(path: Path) -> tuple:
    """Bounded raw input plus a fully pre-validated archive.

    Returns ``(raw_bytes, BoundedOOXML)``: the raw bytes are the evidence hash input, and they are
    read through the same ceiling, so a source too large to admit is also never materialized.

    The walk order is KAgent's (#2824) with Core's (#3637) DTD step folded in, and every check
    applies to **every** member of the central directory, not only the ones this analyzer happens to
    read: path safety, exact-duplicate filename, link entry, encryption, per-entry size, degenerate
    compressed size, per-entry expansion ratio, running uncompressed total, then a bounded read plus
    DTD rejection for each XML/`.rels` part. After the walk, the aggregate expansion ratio. Precedence
    is fixed by tests, so an archive violating two rules at once has one predictable outcome.
    """

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ArchivePolicyError("ooxml_archive_size", "Source workbook is unreadable.") from exc
    if not size or size > MAX_BINARY_DOCUMENT_BYTES:
        raise ArchivePolicyError("ooxml_archive_size", "OOXML archive size is out of bounds.")

    with path.open("rb") as handle:
        # Read in chunks and stop past the ceiling: ``handle.read(bound + 1)`` would pre-allocate the
        # whole 2 MiB for a workbook that is a few kilobytes, which is exactly the kind of silent
        # pre-payment a bound is supposed to prevent.
        chunks = []
        seen = 0
        while seen <= MAX_BINARY_DOCUMENT_BYTES:
            want = min(64 * 1024, MAX_BINARY_DOCUMENT_BYTES + 1 - seen)
            part = handle.read(want)
            if not part:
                break
            chunks.append(part)
            seen += len(part)
        raw = b"".join(chunks)
    if len(raw) > MAX_BINARY_DOCUMENT_BYTES:
        raise ArchivePolicyError("ooxml_archive_size", "OOXML archive size is out of bounds.")

    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ArchivePolicyError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc

    try:
        infos = archive.infolist()
        if len(infos) > MAX_OOXML_ENTRIES:
            raise ArchivePolicyError("ooxml_entry_count", "OOXML archive contains too many entries.")

        infos_by_name: dict = {}
        total_uncompressed = 0
        total_compressed = 0
        for info in infos:
            name = info.filename
            if len(name) > MAX_OOXML_MEMBER_NAME_CHARS or not _safe_ooxml_member(name):
                raise ArchivePolicyError(
                    "ooxml_unsafe_path", "OOXML archive contains an unsafe member path."
                )
            if name in infos_by_name:
                raise ArchivePolicyError(
                    "ooxml_duplicate_member", "Duplicate OOXML member names are ambiguous."
                )
            infos_by_name[name] = info
            if _is_link_entry(info):
                raise ArchivePolicyError(
                    "ooxml_link_entry", "Link entries are not permitted in OOXML archives."
                )
            if info.flag_bits & 0x1:
                raise ArchivePolicyError(
                    "ooxml_encrypted", "Encrypted OOXML entries are not supported."
                )
            if info.file_size > MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES:
                raise ArchivePolicyError(
                    "ooxml_entry_size", "OOXML archive entry exceeds the size limit."
                )
            if info.compress_size <= 0 and info.file_size > 0:
                raise ArchivePolicyError(
                    "ooxml_compressed_size_invalid",
                    "OOXML entry declares no compressed size for non-empty content.",
                )
            if info.file_size > 0 and (
                info.file_size / max(1, info.compress_size)
            ) > MAX_EXPANSION_RATIO:
                raise ArchivePolicyError(
                    "ooxml_expansion_ratio", "OOXML entry expansion ratio exceeds the limit."
                )
            total_uncompressed += info.file_size
            total_compressed += max(0, info.compress_size)
            if total_uncompressed > MAX_OOXML_TOTAL_UNCOMPRESSED_BYTES:
                raise ArchivePolicyError(
                    "ooxml_total_size", "OOXML archive exceeds the total uncompressed size limit."
                )
            lowered = name.lower()
            if lowered.endswith(".xml") or lowered.endswith(".rels"):
                _reject_dtd(
                    bounded_read_zip_member(
                        archive, info, max_bytes=MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES
                    ),
                    name,
                )
    except ArchivePolicyError:
        archive.close()
        raise
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as exc:
        archive.close()
        raise ArchivePolicyError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc

    # Checked after the walk so it sees the whole directory, exactly as KAgent's budget does.
    if aggregate_expansion_violation(total_uncompressed, total_compressed):
        archive.close()
        raise ArchivePolicyError(
            "ooxml_expansion_ratio", "OOXML archive aggregate expansion ratio exceeds the limit."
        )

    return raw, BoundedOOXML(archive, infos_by_name)


# ────────────────────────────── XLSX ──────────────────────────────

def analyze_xlsx(path: Path) -> dict:
    """Analyze one workbook, guaranteeing the archive handle closes on every exit path.

    Refusals raised by the gate happen before an archive exists; once one is open, an XML error, an
    optional drawing route or any later step must not leak its file handle.
    """

    data, zf = open_bounded_ooxml(path)
    try:
        return _analyze_xlsx(data, path, zf)
    finally:
        zf.close()


def _analyze_xlsx(data: bytes, path: Path, zf) -> dict:
    nsm = {"m": NS["main"]}
    names = zf.names()

    wb = zf.read_xml("xl/workbook.xml")
    sheets = [{"name": s.get("name"), "sheet_id": s.get("sheetId"),
               "rel_id": s.get("{%s}id" % NS["r"])}
              for s in wb.findall(".//m:sheet", nsm)]
    defined_names = [{"name": d.get("name"), "value": (d.text or "").strip()}
                     for d in wb.findall(".//m:definedNames/m:definedName", nsm)]

    rels = zf.read_xml("xl/_rels/workbook.xml.rels")
    relmap = {r.get("Id"): r.get("Target") for r in rels}

    shared = []
    if "xl/sharedStrings.xml" in names:
        ss = zf.read_xml("xl/sharedStrings.xml")
        for si in ss.findall("m:si", nsm):
            shared.append("".join(t.text or "" for t in si.findall(".//m:t", nsm)))

    styles_root = zf.read_xml("xl/styles.xml")
    fonts = []
    for f in _resolve_mc_children(styles_root.find("m:fonts", nsm)):
        nm = f.find("m:name", nsm); sz = f.find("m:sz", nsm)
        b = f.find("m:b", nsm); col = f.find("m:color", nsm)
        fonts.append({"name": nm.get("val") if nm is not None else None,
                      "size": float(sz.get("val")) if sz is not None else None,
                      "bold": b is not None,
                      "color": (col.get("rgb") or col.get("theme")) if col is not None else None})
    numfmts = {}
    nfc = styles_root.find("m:numFmts", nsm)
    if nfc is not None:
        for nf in _resolve_mc_children(nfc):
            numfmts[nf.get("numFmtId")] = nf.get("formatCode")
    cellxfs = []
    for xf in _resolve_mc_children(styles_root.find("m:cellXfs", nsm)):
        al = xf.find("m:alignment", nsm)
        cellxfs.append({
            "num_fmt_id": int(xf.get("numFmtId", "0")),
            "font_id": int(xf.get("fontId", "0")),
            "fill_id": int(xf.get("fillId", "0")),
            "border_id": int(xf.get("borderId", "0")),
            "alignment": ({"horizontal": al.get("horizontal"), "vertical": al.get("vertical"),
                           "wrap_text": al.get("wrapText") == "1",
                           "shrink_to_fit": al.get("shrinkToFit") == "1"}
                          if al is not None else {}),
        })

    sheets_out = {}
    for sh in sheets:
        target = relmap.get(sh["rel_id"])
        if not target:
            continue
        ws = "xl/" + target.lstrip("/")
        if ws not in names:
            ws = "xl/worksheets/" + Path(target).name
        if ws not in names:
            continue
        root = zf.read_xml(ws)
        dim = root.find("m:dimension", nsm)
        cells = {}
        for row in root.find("m:sheetData", nsm):
            rnum = int(row.get("r"))
            for c in row.findall("m:c", nsm):
                ref = c.get("r")
                letters = re.match(r"([A-Z]+)", ref).group(1)
                t = c.get("t", "n")
                v_el = c.find("m:v", nsm); f_el = c.find("m:f", nsm)
                raw = v_el.text if v_el is not None else None
                formula = ("=" + f_el.text) if (f_el is not None and f_el.text) else None
                if t == "s" and raw is not None:
                    raw = shared[int(raw)]
                elif t == "n" and raw is not None and re.match(r"^-?\d+$", raw):
                    raw = int(raw)
                elif t == "n" and raw is not None:
                    try:
                        raw = float(raw)
                    except ValueError:
                        pass
                cells[ref] = {"coord": ref, "col": col_to_index(letters), "row": rnum,
                              "value": raw, "formula": formula,
                              "style_id": int(c.get("s", "0"))}
        merges = [m.get("ref") for m in root.findall(".//m:mergeCell", nsm)]
        rows = {}
        for row in root.find("m:sheetData", nsm):
            rnum = int(row.get("r"))
            ht = row.get("ht")
            rows[rnum] = {"height_pt": float(ht) if ht else None,
                          "custom_height": row.get("customHeight") == "1",
                          "hidden": row.get("hidden") == "1"}
        cols = {}
        for c in root.findall(".//m:cols/m:col", nsm):
            if c.get("min") is None or c.get("max") is None:
                continue
            cmin, cmax = int(c.get("min")), int(c.get("max"))
            w = c.get("width")
            for i in range(cmin, cmax + 1):
                cols[index_to_col(i - 1)] = {
                    "width_units": float(w) if w else None,
                    "custom_width": c.get("customWidth") == "1",
                    "hidden": c.get("hidden") == "1"}
        ps = root.find("m:pageSetup", nsm)
        pm = root.find("m:pageMargins", nsm)
        page = {
            "paper_size": ps.get("paperSize") if ps is not None else None,
            "orientation": ps.get("orientation") if ps is not None else None,
            "scale": ps.get("scale") if ps is not None else None,
            "fit_to_width": ps.get("fitToWidth") if ps is not None else None,
            "fit_to_height": ps.get("fitToHeight") if ps is not None else None,
            "margins_pt": ({k: round(float(pm.get(k)) * 72, 3)
                            for k in ("left", "right", "top", "bottom", "header", "footer")}
                           if pm is not None else {}),
        }
        sheets_out[sh["name"]] = {
            "dimension": dim.get("ref") if dim is not None else None,
            "cells": dict(sorted(cells.items())),
            "merges": merges, "rows": rows, "columns": dict(sorted(cols.items())),
            "page": page,
        }

    # drawings (images with anchors)
    drawing_images = []
    for dn in sorted(n for n in names if re.match(r"xl/drawings/drawing\d+\.xml$", n)):
        relpath = f"xl/drawings/_rels/{Path(dn).name}.rels"
        drels = {}
        if relpath in names:
            for rel in zf.read_xml(relpath):
                drels[rel.get("Id")] = rel.get("Target")
        droot = zf.read_xml(dn)
        for anchor in droot:
            pic = anchor.find(".//xdr:pic", NS)
            if pic is None:
                continue
            blip = pic.find(".//a:blip", NS)
            embed = blip.get("{%s}embed" % NS["r"]) if blip is not None else None
            media = drels.get(embed, "").replace("../", "xl/")
            nm = pic.find(".//xdr:cNvPr", NS)

            def cellpos(el):
                if el is None:
                    return None
                return {"col": int(el.find("xdr:col", NS).text),
                        "col_off_emu": int(el.find("xdr:colOff", NS).text),
                        "row": int(el.find("xdr:row", NS).text),
                        "row_off_emu": int(el.find("xdr:rowOff", NS).text)}
            drawing_images.append({
                "drawing": dn, "name": nm.get("name") if nm is not None else None,
                "media": media, "embed_rid": embed,
                "from": cellpos(anchor.find("xdr:from", NS)),
                "to": cellpos(anchor.find("xdr:to", NS)),
                "sha256": sha256_bytes(zf.read(media)) if media in names else None})

    # VML shapes (camera / linked picture)
    vml_shapes = []
    for vn in [n for n in names if n.endswith(".vml")]:
        txt = zf.read(vn).decode("utf-8", "ignore")
        for sm in re.finditer(r'<v:shape id="([^"]+)"[^>]*>((?:(?!</v:shape>).)*)</v:shape>', txt, re.S):
            sid, body = sm.group(1), sm.group(2)
            am = re.search(r"<x:Anchor>([^<]*)</x:Anchor>", body)
            fm = re.search(r"<x:FmlaPict>([^<]*)</x:FmlaPict>", body)
            rm = re.search(r'<v:imagedata o:relid="(rId\d+)"', body)
            vml_shapes.append({"file": vn, "shape_id": sid,
                               "anchor_raw": am.group(1) if am else None,
                               "fmla_pict": fm.group(1) if fm else None,
                               "is_camera": "<x:Camera" in body,
                               "imagedata_relid": rm.group(1) if rm else None})

    result = {
        "source": {"path": str(path), "sha256": sha256_bytes(data), "size": len(data)},
        "workbook": {"sheets": sheets, "defined_names": defined_names},
        "sheet_names": [s["name"] for s in sheets],
        "sheets": sheets_out,
        "styles": {"fonts": fonts, "cellxfs": cellxfs, "numfmts_custom": numfmts},
        "drawing_images": drawing_images,
        "vml_shapes": vml_shapes,
    }
    return result


# ────────────────────────────── PDF ──────────────────────────────

def analyze_pdf(path: Path) -> dict:
    import fitz
    data = path.read_bytes()
    doc = fitz.open(path)
    pages = []
    font_buffers = {}
    for pno, page in enumerate(doc):
        page_fonts = []
        for xref, ext, ftype, basefont, name, encoding, referencer in page.get_fonts(full=True):
            page_fonts.append({"xref": xref, "ext": ext, "type": ftype,
                               "basefont": basefont, "ref_name": name})
            if xref not in font_buffers:
                try:
                    _bn, ext2, ftype2, buf = doc.extract_font(xref)
                    font_buffers[str(xref)] = {"basefont": basefont, "ext": ext2,
                                               "type": ftype2,
                                               "sha256": sha256_bytes(buf) if buf else None,
                                               "size": len(buf) if buf else 0}
                except Exception:
                    pass
        raw = page.get_text("rawdict",
                            flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES)
        spans = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                if line.get("wmode", 0) != 0:
                    continue
                for span in line.get("spans", []):
                    chars = [{"c": ch["c"],
                              "origin": [round(v, 2) for v in ch["origin"]],
                              "bbox": [round(v, 2) for v in ch["bbox"]]}
                             for ch in span.get("chars", [])]
                    if not chars:
                        continue
                    spans.append({"font": span["font"], "size": round(span["size"], 3),
                                  "flags": span["flags"], "color": span["color"],
                                  "bbox": [round(v, 2) for v in span["bbox"]],
                                  "text": "".join(c["c"] for c in chars),
                                  "chars": chars, "page": pno})
        images = []
        for entry in page.get_images(full=True):
            xref, smask, pw, ph = entry[0], entry[1], entry[2], entry[3]
            rects = page.get_image_rects(xref)
            base = doc.extract_image(xref)
            smask_bytes = None
            if smask:
                sm = doc.extract_image(smask)
                smask_bytes = {"xref": smask, "ext": sm["ext"],
                               "sha256": sha256_bytes(sm["image"])}
            images.append({"xref": xref, "smask_xref": smask, "has_alpha": smask > 0,
                           "pixel_w": pw, "pixel_h": ph, "ext": base["ext"],
                           "sha256": sha256_bytes(base["image"]),
                           "bboxes": [[round(v, 2) for v in r] for r in rects],
                           "smask_bytes": smask_bytes, "page": pno})
        ops = []
        for d in page.get_drawings():
            ops.append({
                "type": d.get("type"),
                "rect": [round(v, 2) for v in d["rect"]],
                "fill": d.get("fill"), "color": d.get("color"), "width": d.get("width"),
                "even_odd": d.get("even_odd"),
                "fill_opacity": d.get("fill_opacity"),
                "stroke_opacity": d.get("stroke_opacity"),
                "items": [{"op": it[0],
                           "points": [round(v, 2) for pt in it[1:]
                                      if isinstance(pt, (tuple, list)) for v in pt],
                           "rect": ([round(v, 2) for v in it[1]]
                                    if it[0] == "re" and len(it) > 1 else None)}
                          for it in d.get("items", [])],
                "page": pno})
        pages.append({"index": pno,
                      "width_pt": round(page.rect.width, 3),
                      "height_pt": round(page.rect.height, 3),
                      "mediabox": [round(v, 2) for v in page.mediabox],
                      "text_spans": spans, "images": images, "drawings": ops,
                      "page_fonts": page_fonts})
    result = {"source": {"path": str(path), "sha256": sha256_bytes(data), "size": len(data)},
              "page_count": doc.page_count, "pages": pages, "fonts_declared": font_buffers}
    doc.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="B66 generic source analyzer")
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        x = analyze_xlsx(Path(a.xlsx))
    except ArchivePolicyError as exc:
        # Fail closed with a machine-readable classification. Nothing downstream may treat a
        # refusal as an empty analysis: no evidence JSON is written and the exit code is non-zero.
        print(f"REFUSED {exc.code}", file=sys.stderr)
        raise SystemExit(1)
    (outdir / "xlsx_analysis.json").write_text(
        json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
    p = analyze_pdf(Path(a.pdf))
    (outdir / "pdf_analysis.json").write_text(
        json.dumps(p, ensure_ascii=False), encoding="utf-8")
    print("written:", outdir / "xlsx_analysis.json", outdir / "pdf_analysis.json")
    print("sheets:", x["sheet_names"], "| pages:", p["page_count"])


if __name__ == "__main__":
    main()
