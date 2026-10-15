"""#3580: opt-in, supervised Windows legacy XLS → PDF read-only renderer.

Does not infer user file selection, P01 approval, or upload authority. The
caller must already possess exact selected-root P01-authorized bytes. The
original OLE2 .xls is preserved; this renderer does not promise editable XLSX.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable

from .contracts import ContractError
from .windows_job_object import JobBoundProcess, launch_job_bound_process
from .windows_local_filesystem import MAX_SELECTED_ROOT_FILE_BYTES
from .windows_excel_legacy_xls_child import OLE2_SIGNATURE
from .supervised_windows_excel_pdf import (
    MAX_PDF_BYTES, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS,
)

_ALLOWED_ENV = frozenset({
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "PATH",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "USERNAME", "USERDOMAIN",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "PYTHONPATH",
    "PYTHONHOME", "VIRTUAL_ENV", "PYTHONIOENCODING", "PYTHONUTF8",
})


@dataclass(frozen=True)
class SupervisedWindowsLegacyXlsPdfRenderer:
    timeout_seconds: int = 45
    launcher: Callable[..., JobBoundProcess] = launch_job_bound_process

    def __post_init__(self) -> None:
        if (type(self.timeout_seconds) is not int
                or not MIN_TIMEOUT_SECONDS <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS
                or not callable(self.launcher)):
            raise ContractError("bounded trusted legacy XLS PDF renderer required")

    def render_xls_pdf(self, original_xls_bytes: bytes) -> bytes:
        if os.name != "nt":
            raise ContractError("legacy XLS PDF export is Windows-only")
        if (type(original_xls_bytes) is not bytes
                or not 8 < len(original_xls_bytes) <= MAX_SELECTED_ROOT_FILE_BYTES
                or not original_xls_bytes.startswith(OLE2_SIGNATURE)):
            raise ContractError("valid bounded P01-authorized legacy OLE2 XLS required")

        with tempfile.TemporaryDirectory(prefix="padiem-approved-legacy-xls-") as dirname:
            source = Path(dirname) / "source.xls"
            target = Path(dirname) / "output.pdf"
            source.write_bytes(original_xls_bytes)
            environment = {
                k: v for k, v in os.environ.items() if k.upper() in _ALLOWED_ENV
            }
            bound = None
            try:
                bound = self.launcher(
                    [sys.executable, "-m", "kagent.windows_excel_legacy_xls_child",
                     str(source), str(target)],
                    cwd=dirname, environment=environment,
                )
                try:
                    bound.process.communicate(timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired:
                    raise ContractError("legacy XLS PDF export timed out") from None
                if bound.process.returncode != 0 or not target.is_file():
                    raise ContractError("legacy XLS PDF export refused")
                if not 0 < target.stat().st_size <= MAX_PDF_BYTES:
                    raise ContractError("legacy XLS PDF exceeds canonical output bound")
                result = target.read_bytes()
                if not result.startswith(b"%PDF-") or b"%%EOF" not in result[-1024:]:
                    raise ContractError("legacy XLS PDF is invalid")
                return result
            except ContractError:
                raise
            except Exception:
                raise ContractError("legacy XLS PDF export failed") from None
            finally:
                if bound is not None:
                    try:
                        # The Job owns the child. COM may spawn an external
                        # Excel process, so complete orphan cleanup is NOT proven.
                        bound.job.terminate_tree()
                    except Exception:
                        pass
                    try:
                        if bound.process.poll() is None:
                            bound.process.kill()
                        bound.process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    try:
                        bound.job.close()
                    except Exception:
                        pass


PRODUCTION_LEGACY_XLS_RENDERER_ACTIVATED = False
