#!/usr/bin/env python3
"""Export PPTX/DOCX to PDF via REAL document renderers only (render-fidelity).

- Proposal PPTX / OnePage PPTX -> PowerPoint COM or LibreOffice Impress headless
- Questionnaire DOCX -> Word COM or LibreOffice Writer headless

Independently recomposed fallback PDFs (fpdf2-style) are FORBIDDEN here: the
PDF must be the editable source rendered by its native engine so W4 can judge
layout fidelity (including 16:9 slide geometry preservation).

Fail-closed: when no real exporter exists, exit non-zero with
REAL_DOCUMENT_EXPORT=UNAVAILABLE_BLOCKING. Provenance is recorded to
validation/.real_export/provenance.json and embedded into the manifest.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from real_export import (  # noqa: E402
    REAL_EXPORT_DIR,
    RealExportUnavailable,
    export_docx_to_pdf,
    export_pptx_to_pdf,
    normalize_pdf_determinism,
    pdf_producer,
    write_provenance,
)

ROOT = Path(__file__).resolve().parent.parent

JOBS = [
    ("pptx", ROOT / "Business35_Master_Proposal_10p.pptx", ROOT / "Business35_Master_Proposal_10p.pdf"),
    ("pptx", ROOT / "Business35_OnePage_Offer_Source.pptx", ROOT / "Business35_OnePage_Offer.pdf"),
    ("docx", ROOT / "Business35_Diagnostic_Questionnaire.docx", ROOT / "Business35_Diagnostic_Questionnaire.pdf"),
]


def main() -> int:
    REAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    producers: dict[str, str] = {}
    exporters: list[str] = []
    try:
        for kind, src, dst in JOBS:
            if not src.is_file():
                raise RealExportUnavailable(f"source artifact missing: {src.name}")
            if kind == "pptx":
                exporter = export_pptx_to_pdf(src, dst)
            else:
                exporter = export_docx_to_pdf(src, dst)
            normalize_pdf_determinism(dst)
            prod = pdf_producer(dst)
            producers[dst.name] = prod
            exporters.append(exporter)
            print(f"real-exported {dst.name} from {src.name} via {exporter} "
                  f"(producer: {prod}, bytes: {dst.stat().st_size})")
    except RealExportUnavailable as e:
        print(f"REAL_DOCUMENT_EXPORT=UNAVAILABLE_BLOCKING ({e})")
        write_provenance(REAL_DOCUMENT_EXPORT="UNAVAILABLE_BLOCKING",
                         DOCUMENT_EXPORTER="NONE")
        return 1
    # Exporter family must be real (native engine), never synthetic.
    for name, prod in producers.items():
        low = prod.lower()
        if any(t in low for t in ("fpdf", "pyfpdf", "reportlab", "pypdf", "fitz", "mupdf", "pillow", "pil")):
            print(f"REAL_DOCUMENT_EXPORT=UNAVAILABLE_BLOCKING (synthetic producer for {name}: {prod})")
            write_provenance(REAL_DOCUMENT_EXPORT="UNAVAILABLE_BLOCKING",
                             DOCUMENT_EXPORTER="SYNTHETIC_REJECTED")
            return 1
        if not any(t in low for t in ("microsoft", "libreoffice", "office")):
            print(f"REAL_DOCUMENT_EXPORT=UNAVAILABLE_BLOCKING (unrecognized producer for {name}: {prod})")
            write_provenance(REAL_DOCUMENT_EXPORT="UNAVAILABLE_BLOCKING",
                             DOCUMENT_EXPORTER="UNRECOGNIZED")
            return 1
    exporter_label = exporters[0] if len(set(exporters)) == 1 else " + ".join(sorted(set(exporters)))
    write_provenance(REAL_DOCUMENT_EXPORT="PASS",
                     DOCUMENT_EXPORTER=exporter_label,
                     PDF_PRODUCERS=producers)
    print(f"REAL_DOCUMENT_EXPORT=PASS via {exporter_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
