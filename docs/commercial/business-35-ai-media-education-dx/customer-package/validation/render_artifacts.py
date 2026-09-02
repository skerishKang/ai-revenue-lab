#!/usr/bin/env python3
"""Render real visual evidence PNGs from the final artifacts (render-fidelity).

- PPTX/PDF/DOCX evidence: the final real-exported PDFs (proposal 10p /
  one-page / questionnaire) are rasterized page-by-page with PyMuPDF.
- XLSX evidence: the actual workbook is exported sheet-by-sheet to PDF by a
  REAL spreadsheet renderer (Excel COM preferred, LibreOffice Calc headless),
  preserving merges, fills, fonts, borders, column widths, row heights,
  conditional formatting, and print areas; each sheet PDF page is rasterized
  to PNG. Recreated Pillow tables are FORBIDDEN.

Fail-closed: when no real renderer is available, exit non-zero and report
REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING (or REAL_RENDER_EVIDENCE variant).
Placeholder/synthetic images are forbidden and never generated as substitute.
"""

from pathlib import Path
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from real_export import (  # noqa: E402
    REAL_EXPORT_DIR,
    RealExportUnavailable,
    export_xlsx_sheets_pdf,
    normalize_pdf_determinism,
    pdf_producer,
    write_provenance,
)

ROOT = Path(__file__).resolve().parent.parent

PDF_JOBS = [
    ("Business35_Master_Proposal_10p.pdf", "rendered", "proposal-%02d.png"),
    ("Business35_OnePage_Offer.pdf", "rendered", "onepage-%d.png"),
    ("Business35_Diagnostic_Questionnaire.pdf", "rendered", "questionnaire-%d.png"),
]

XLSX_NAME = "Business35_Pilot_Quote_Template.xlsx"
XLSX_SHEET_PDF = REAL_EXPORT_DIR / "quote-sheets.pdf"


def render_pdfs() -> list[str]:
    try:
        import fitz  # PyMuPDF: real PDF rasterization
    except Exception as e:
        print(f"REAL_RENDER_EVIDENCE=UNAVAILABLE_BLOCKING (PyMuPDF missing: {e})")
        raise SystemExit(1)
    made: list[str] = []
    zoom = 1.5  # deterministic scale
    mat = fitz.Matrix(zoom, zoom)
    for pdf_name, subdir, pattern in PDF_JOBS:
        src = ROOT / pdf_name
        if not src.is_file():
            print(f"REAL_RENDER_EVIDENCE=UNAVAILABLE_BLOCKING (missing {pdf_name})")
            raise SystemExit(1)
        doc = fitz.open(str(src))
        outdir = ROOT / subdir
        outdir.mkdir(parents=True, exist_ok=True)
        # Remove stale renders for this job so page-count changes cannot linger.
        for stale in outdir.glob(pattern.replace("%02d", "*").replace("%d", "*")):
            stale.unlink()
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat)
            dest = outdir / (pattern % i)
            pix.save(str(dest))
            made.append(f"{subdir}/{dest.name}")
            print(f"rendered {dest.name} from {pdf_name} page {i}/{doc.page_count}")
        doc.close()
    return made


def render_xlsx() -> list[str]:
    try:
        import fitz
    except Exception as e:
        print(f"REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING (PyMuPDF missing: {e})")
        raise SystemExit(1)
    src = ROOT / XLSX_NAME
    if not src.is_file():
        print(f"REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING (missing {XLSX_NAME})")
        raise SystemExit(1)
    REAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        exporter, sheets, pages = export_xlsx_sheets_pdf(src, XLSX_SHEET_PDF)
    except RealExportUnavailable as e:
        print(f"REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING ({e})")
        write_provenance(REAL_XLSX_RENDER="UNAVAILABLE_BLOCKING", XLSX_EXPORTER="NONE")
        raise SystemExit(1)
    normalize_pdf_determinism(XLSX_SHEET_PDF)
    producer = pdf_producer(XLSX_SHEET_PDF)
    low = producer.lower()
    if any(t in low for t in ("fpdf", "pyfpdf", "reportlab", "pypdf", "fitz", "mupdf", "pillow", "pil")):
        print(f"REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING (synthetic producer: {producer})")
        write_provenance(REAL_XLSX_RENDER="UNAVAILABLE_BLOCKING",
                         XLSX_EXPORTER="SYNTHETIC_REJECTED")
        raise SystemExit(1)
    outdir = ROOT / "xlsx-rendered"
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("*.png"):
        stale.unlink()
    zoom = 1.5
    mat = fitz.Matrix(zoom, zoom)
    made: list[str] = []
    doc = fitz.open(str(XLSX_SHEET_PDF))
    if doc.page_count != len(sheets):
        print(f"REAL_XLSX_RENDER=UNAVAILABLE_BLOCKING "
              f"(sheet/page mismatch: {len(sheets)} sheets vs {doc.page_count} pages)")
        write_provenance(REAL_XLSX_RENDER="UNAVAILABLE_BLOCKING",
                         XLSX_EXPORTER="SHEET_PAGE_MISMATCH")
        raise SystemExit(1)
    for sheet, page in zip(sheets, doc):
        pix = page.get_pixmap(matrix=mat)
        dest = outdir / (sheet.lower().replace(" ", "-") + ".png")
        pix.save(str(dest))
        made.append(f"xlsx-rendered/{dest.name}")
        print(f"rendered {dest.name} from real sheet export: {sheet} "
              f"({pix.width}x{pix.height})")
    doc.close()
    import hashlib
    sha = hashlib.sha256(XLSX_SHEET_PDF.read_bytes()).hexdigest()
    write_provenance(REAL_XLSX_RENDER="PASS", XLSX_EXPORTER=exporter,
                     XLSX_EXPORT_PDF_SHA256=sha,
                     XLSX_EXPORT_PDF_PRODUCER=producer,
                     XLSX_EXPORT_PDF_PAGES=pages)
    print(f"REAL_XLSX_RENDER=PASS via {exporter} ({len(sheets)} sheets)")
    return made


def main() -> int:
    made_pdf = render_pdfs()
    made_xlsx = render_xlsx()
    print(f"REAL_RENDER_EVIDENCE=AVAILABLE ({len(made_pdf)} pdf pages, {len(made_xlsx)} sheets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
