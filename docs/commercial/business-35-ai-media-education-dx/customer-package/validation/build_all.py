#!/usr/bin/env python3
"""Deterministic build orchestrator for B35 customer package (Lane B, final).

Steps:
  0. materialize exact accepted Lane A source (git show 63adbefc:...) — fail-closed
  1. build PPTX/DOCX/XLSX via accepted-source-driven builders
  2. export PDFs (libreoffice when present, else deterministic fpdf2 fallback)
  3. render REAL PNG evidence (PyMuPDF pdf pages + openpyxl sheet renders)
  4. generate manifest with exact revision trace (requires GENERATOR_REVISION env)
  5. validate (fail-closed)

Deterministic: fixed timestamps, sorted file lists, no random.
GENERATOR_REVISION env (full 40-char generator code commit) is required for
step 4; pass it through from the caller.
"""

from pathlib import Path
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
PKG_ROOT = ROOT.parent


def run(cmd, env=None):
    print(f"> {' '.join(cmd)}")
    import os
    merged = dict(os.environ)
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    if env:
        merged.update(env)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=str(PKG_ROOT), env=merged)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    # Step 0: accepted source materialization (proves actual consumption)
    run([sys.executable, str(ROOT / "materialize_accepted_source.py")])

    # Step 1: builders
    for script in ["build_proposal_pptx.py", "build_one_page_pptx.py", "build_questionnaire_docx.py", "build_quote_xlsx.py"]:
        run([sys.executable, str(ROOT / script)])

    # Step 2: PDFs
    run([sys.executable, str(ROOT / "export_pdfs.py")])

    # Step 3: real renders
    run([sys.executable, str(ROOT / "render_artifacts.py")])

    # Step 4: manifest (GENERATOR_REVISION passed via environment)
    run([sys.executable, str(ROOT / "generate_manifest.py")])

    # Step 5: validate
    print("\n=== Validation ===")
    run([sys.executable, str(ROOT / "validate_customer_package.py")])


if __name__ == "__main__":
    main()
