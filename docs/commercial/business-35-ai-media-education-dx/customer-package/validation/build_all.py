#!/usr/bin/env python3
"""Deterministic build orchestrator for B35 customer package (Lane B).

Steps:
  1. build PPTX/DOCX/XLSX via recovered builders
  2. export PDFs (libreoffice or reportlab fallback)
  3. render PNG evidence (Pillow placeholders)
  4. generate manifest with hashes

Deterministic: fixed timestamps, sorted file lists, no random.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PKG_ROOT = ROOT.parent

def run(cmd):
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

def main():
    # Step 1: builders
    for script in ["build_proposal_pptx.py", "build_one_page_pptx.py", "build_questionnaire_docx.py", "build_quote_xlsx.py"]:
        run([sys.executable, str(ROOT / script)])

    # Step 2: PDFs
    run([sys.executable, str(ROOT / "export_pdfs.py")])

    # Step 3: renders
    run([sys.executable, str(ROOT / "render_artifacts.py")])

    # Step 4: manifest
    run([sys.executable, str(ROOT / "generate_manifest.py")])

    # Step 5: validate
    print("\n=== Validation ===")
    run([sys.executable, str(ROOT / "validate_customer_package.py")])

if __name__ == "__main__":
    main()
