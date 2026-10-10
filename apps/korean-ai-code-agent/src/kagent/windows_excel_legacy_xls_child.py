"""Bounded Windows COM child for read-only legacy .xls → PDF export.

Receives disposable parent-owned temporary files only. Never opens the user's
real source path or writes an XLSX in lieu of preserving the original .xls.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

from .windows_local_filesystem import MAX_SELECTED_ROOT_FILE_BYTES

OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def main(args: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    if len(argv) != 2 or os.name != "nt":
        return 2
    source, target = map(Path, argv)
    if (not source.is_absolute() or not target.is_absolute()
            or source.parent != target.parent
            or source.name != "source.xls" or target.name != "output.pdf"):
        return 2

    app = None
    workbook = None
    initialized = False
    try:
        if (not source.is_file()
                or not 8 < source.stat().st_size <= MAX_SELECTED_ROOT_FILE_BYTES):
            return 2
        with source.open("rb") as stream:
            if stream.read(8) != OLE2_SIGNATURE:
                return 2
        import pythoncom
        from win32com.client import DispatchEx

        pythoncom.CoInitialize()
        initialized = True
        app = DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        app.EnableEvents = False
        app.AutomationSecurity = 3  # VBA macros disabled
        workbook = app.Workbooks.Open(
            str(source), UpdateLinks=0, ReadOnly=True, AddToMru=False,
            IgnoreReadOnlyRecommended=True, Notify=False,
        )
        workbook.ExportAsFixedFormat(
            0, str(target), IncludeDocProperties=False, OpenAfterPublish=False,
        )
        return 0 if target.is_file() else 2
    except Exception:
        return 2  # Do not leak potentially sensitive path/COM errors
    finally:
        if workbook is not None:
            try:
                workbook.Close(SaveChanges=False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
