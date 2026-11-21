"""#8153 — PyMuPDF may not re-enter the repository's production code.

The scan-reading lane was the last production renderer that imported
PyMuPDF (AGPL, and absent on the COM2 host); it now goes through the shared
pypdfium2 renderer (#8129, #8156). This guard keeps it that way: every
production Python file must be free of PyMuPDF imports outside the PDF-writing
lanes that still need them, and the Chat app's production dependency list must
stay PyMuPDF-free.

The allowlisted files are PDF *writers* (the certified quote-PDF overlay and
the B66 worker renderer): pypdfium2 renders pages but cannot write these
documents, and replacing them means a new dependency — a decision outside this
guard's scope. Each one is asserted to exist so the allowlist cannot rot
quietly. The Chat dev extra still carries PyMuPDF for those writers and the
tests that exercise them; that declaration lives outside the production
dependency list this guard pins.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Every tree a shipped Python file can live in. New production trees must be
#: added here — a file the guard cannot see is a file PyMuPDF can re-enter.
PRODUCTION_ROOTS = (
    "apps/padiem-chat/app",
    "apps/padiem-ai-engine/app",
    "apps/claw-connect/claw_connect",
    "apps/korean-ai-code-agent/src",
    "apps/b66-pdf-renderer",
    "apps/b66-sol61-multipage",
    "packages",
)

#: Skipped everywhere: pytest modules and generated packaging metadata are not
#: production code, and the tests exercise PyMuPDF writers on purpose.
SKIPPED_PARTS = frozenset({"tests", "egg-info", ".venv"})

#: PDF writers, not renderers. Exact relative paths: a moved or renamed file
#: fails the existence assertion below instead of slipping out of the list.
WRITER_ALLOWLIST = (
    "apps/padiem-chat/app/b66_certified_pdf_renderer.py",
    "apps/b66-pdf-renderer/renderer.py",
)

#: A developer verification tool of the multipage app — runs on a workstation,
#: never shipped.
DEV_TOOL_ALLOWLIST = (
    "apps/b66-sol61-multipage/verify_right_border.py",
)

PYMUPDF_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:fitz|pymupdf)\b", re.MULTILINE)


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            raise AssertionError(f"production root disappeared: {root}")
        for path in base.rglob("*.py"):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if any(part in SKIPPED_PARTS for part in path.parts):
                continue
            files.append((relative, path))
    return files


def test_production_code_imports_no_pymupdf_outside_the_writer_lanes():
    offenders = []
    for relative, path in _production_python_files():
        if relative in WRITER_ALLOWLIST or relative in DEV_TOOL_ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if PYMUPDF_IMPORT.search(source):
            offenders.append(relative)
    assert offenders == [], (
        "PyMuPDF imports are only allowed in the PDF-writing lanes "
        f"{WRITER_ALLOWLIST}; found {offenders}. Rendering goes through "
        "app/document_page_render.py (pypdfium2, #8129) — see #8153."
    )


def test_the_writer_allowlist_still_points_at_real_files():
    for relative in (*WRITER_ALLOWLIST, *DEV_TOOL_ALLOWLIST):
        assert (REPO_ROOT / relative).is_file(), f"allowlist entry missing: {relative}"


def test_chat_production_dependencies_stay_pymupdf_free():
    pyproject = (REPO_ROOT / "apps/padiem-chat/pyproject.toml").read_text(encoding="utf-8")
    production = pyproject.split("[project.optional-dependencies]", 1)[0]
    assert "pymupdf" not in production.casefold(), (
        "PyMuPDF must not return to the Chat app's production dependency list: "
        "it is AGPL and absent on the COM2 host (#8153)."
    )


def test_the_scan_reading_path_carries_no_pymupdf_at_all():
    # The lane this issue was about, named file by file so the intent survives
    # refactors: rendering goes through document_page_render only.
    for relative in (
        "apps/padiem-chat/app/pdfmd_scan_ocr.py",
        "apps/padiem-chat/app/document_page_render.py",
        "apps/padiem-chat/app/document_convert_page_image.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert PYMUPDF_IMPORT.search(source) is None, relative
