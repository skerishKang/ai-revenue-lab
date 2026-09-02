#!/usr/bin/env python3
"""Deterministic OOXML post-processing for Lane B builders.

python-pptx / python-docx / openpyxl embed the current wall-clock time in
ZIP entry headers when saving. Content XML is already deterministic (fixed
core properties), so this module rewrites the container with a fixed entry
timestamp, preserving entry order, compression, and payload bytes.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

FIXED_DATE_TIME = (2026, 9, 3, 0, 0, 0)
FIXED_W3CDTF = "2026-09-03T00:00:00Z"


def _scrub_core_xml(data: bytes) -> bytes:
    """Pin dcterms created/modified inner text (openpyxl rewrites modified
    with now()). Attributes and namespace declarations are preserved."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    text = re.sub(r"(<dcterms:created[^>]*>).*?(</dcterms:created>)",
                  rf"\g<1>{FIXED_W3CDTF}\g<2>",
                  text, flags=re.DOTALL)
    text = re.sub(r"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
                  rf"\g<1>{FIXED_W3CDTF}\g<2>",
                  text, flags=re.DOTALL)
    return text.encode("utf-8")


def normalize_ooxml(path: Path | str) -> None:
    path = Path(path)
    with zipfile.ZipFile(str(path), "r") as zin:
        entries = []
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _scrub_core_xml(data)
            entries.append((info.filename, info.compress_type, data))
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for filename, compress_type, data in entries:
            info = zipfile.ZipInfo(filename, date_time=FIXED_DATE_TIME)
            info.compress_type = compress_type
            info.create_system = 0
            zout.writestr(info, data)
    print(f"normalized {Path(path).name} ({len(entries)} zip entries, fixed timestamp)")


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        normalize_ooxml(arg)
