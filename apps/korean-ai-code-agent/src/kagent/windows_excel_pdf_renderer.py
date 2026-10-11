"""Opt-in Windows *interactive desktop* Excel PDF renderer for #3580.

Not a server/Worker renderer. The caller must already hold a valid, separately
approved P01 local task and must supervise this COM work in a bounded,
cancellable Windows child. Office itself can hang or display dialogs; no
unattended or production composition is enabled by this module.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .artifact_registration import MAX_ARTIFACT_SIZE_BYTES
from .contracts import ContractError
from .xlsx_fidelity_route import MAX_XLSX_BYTES, XlsxRoute, classify_xlsx

PRODUCTION_RENDERER_ACTIVATED = False


class WindowsInteractiveExcelPdfRenderer:
    """Real Excel PDF export, on disposable copies, no links or VBA macros.

    This adapter is intentionally *not* composed into the shipped runner:
    cancellation/timeouts, Office licensing/session and trusted P01 wiring
    remain duties of the resident process host.
    """

    def render_xlsx_pdf(self, source_bytes: bytes) -> bytes:
        if os.name != "nt":
            raise ContractError("interactive Windows Office renderer required")
        if type(source_bytes) is not bytes or not 0 < len(source_bytes) <= MAX_XLSX_BYTES:
            raise ContractError("bounded XLSX bytes required")
        if classify_xlsx(source_bytes, local_only=True).route is XlsxRoute.REJECT:
            raise ContractError("untrusted OOXML input refused before Office")
        try:
            import pythoncom
            from win32com.client import DispatchEx
        except ImportError:
            raise ContractError("trusted Windows Office dependencies are unavailable") from None

        with tempfile.TemporaryDirectory(prefix="padiem-office-render-") as tmp:
            source = Path(tmp) / "source.xlsx"
            target = Path(tmp) / "output.pdf"
            source.write_bytes(source_bytes)
            app = None
            workbook = None
            initialized = False
            try:
                pythoncom.CoInitialize()
                initialized = True
                app = DispatchEx("Excel.Application")  # new isolated Excel instance
                app.Visible = False
                app.DisplayAlerts = False
                app.AskToUpdateLinks = False
                app.EnableEvents = False
                app.AutomationSecurity = 3  # ForceDisable VBA
                workbook = app.Workbooks.Open(
                    str(source), UpdateLinks=0, ReadOnly=True,
                    AddToMru=False, IgnoreReadOnlyRecommended=True, Notify=False,
                )
                workbook.ExportAsFixedFormat(
                    0, str(target), IncludeDocProperties=False,
                    OpenAfterPublish=False,
                )
                if not target.is_file() or not 0 < target.stat().st_size <= MAX_ARTIFACT_SIZE_BYTES:
                    raise ContractError("Office PDF absent or exceeds canonical byte limit")
                result = target.read_bytes()
                if not result.startswith(b"%PDF-") or b"%%EOF" not in result[-1024:]:
                    raise ContractError("Office PDF signature invalid")
                return result
            except Exception:
                # Excel errors may include local paths. Never forward error text.
                raise ContractError("trusted interactive Excel PDF conversion failed") from None
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
                    pythoncom.CoUninitialize()
