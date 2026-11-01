"""Convert an owner's workbook in an isolated LibreOffice profile."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .storage import FileError


def convert(payload: bytes) -> bytes:
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        raise FileError("xlsx_pdf_unavailable", 503)
    with tempfile.TemporaryDirectory(prefix="padiem-quote-pdf-") as tmp:
        root = Path(tmp)
        source = root / "quote.xlsx"
        source.write_bytes(payload)
        profile = (root / "profile").as_uri()
        try:
            result = subprocess.run(
                [binary, "-env:UserInstallation=" + profile, "--headless",
                 "--convert-to", "pdf:calc_pdf_Export", "--outdir", str(root), str(source)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=90, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise FileError("xlsx_pdf_conversion_failed", 503) from None
        target = root / "quote.pdf"
        if result.returncode != 0 or not target.is_file():
            raise FileError("xlsx_pdf_conversion_failed", 503)
        data = target.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise FileError("xlsx_pdf_conversion_failed", 503)
        return data
