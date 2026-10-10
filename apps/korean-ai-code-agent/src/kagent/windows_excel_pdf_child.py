"""Windows-only supervised Excel COM child for one bounded approved source.

Never an HTTP server. Takes only parent-owned temporary source/PDF locations,
exposes no credential or stdout file bytes and propagates no COM exception text.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

from .contracts import ContractError
from .windows_excel_pdf_renderer import WindowsInteractiveExcelPdfRenderer
from .xlsx_fidelity_route import MAX_XLSX_BYTES


def main(args: list[str] | None = None) -> int:
    arguments = list(args if args is not None else sys.argv[1:])
    if len(arguments) != 2 or os.name != "nt":
        return 2
    source, destination = map(Path, arguments)
    if (not source.is_absolute() or not destination.is_absolute()
            or source.name != "source.xlsx" or destination.name != "output.pdf"
            or source.parent != destination.parent):
        return 2
    try:
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_XLSX_BYTES:
            return 2
        payload = source.read_bytes()
        result = WindowsInteractiveExcelPdfRenderer().render_xlsx_pdf(payload)
        destination.write_bytes(result)
        return 0
    except (ContractError, OSError):
        # Office COM and file paths may be sensitive; no exception details.
        return 2
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
