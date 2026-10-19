"""#3580: bounded, opt-in Windows Excel PDF export in a Job-bound child.

Only an already P01-approved selected-root source may call this renderer.
The resident thread never runs Excel COM directly. The child has no device
credential, Claw conversation token, Google Drive OAuth or network intent.
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
from .xlsx_fidelity_route import MAX_XLSX_BYTES, XlsxRoute, classify_xlsx

MAX_PDF_BYTES = 8 * 1024 * 1024
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class SupervisedWindowsExcelPdfRenderer:
    """Confinement and timeout for a single approved Excel export invocation.

    The process is placed in an existing kill-on-close Windows Job before
    resumption. Excel COM can launch out-of-process via the COM service; its
    separate process lifetime requires interactive-Office operational proof
    before activation. This renderer is NOT automatically composed.
    """

    timeout_seconds: int = 45
    launcher: Callable[..., JobBoundProcess] = launch_job_bound_process

    def __post_init__(self) -> None:
        if (type(self.timeout_seconds) is not int
                or not MIN_TIMEOUT_SECONDS <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS
                or not callable(self.launcher)):
            raise ContractError("bounded supervised Windows Excel configuration required")

    def render_xlsx_pdf(self, source_bytes: bytes) -> bytes:
        if os.name != "nt":
            raise ContractError("supervised Excel export is Windows-only")
        if (type(source_bytes) is not bytes
                or not 0 < len(source_bytes) <= min(MAX_XLSX_BYTES, 8 * 1024 * 1024)
                or classify_xlsx(source_bytes, local_only=True).route is XlsxRoute.REJECT):
            raise ContractError("valid bounded P01-selected XLSX content required")
        with tempfile.TemporaryDirectory(prefix="padiem-approved-office-") as dirname:
            root = Path(dirname)
            source = root / "source.xlsx"
            target = root / "output.pdf"
            source.write_bytes(source_bytes)
            # Use the current approved Python environment, but no shell, no
            # input from stdin, no inherited provider secrets or Drive tokens.
            # User profile/environment required by Office COM is intentionally
            # kept to the OS (rather than inventing a second Office server).
            # Strict allowlist: no inherited OAuth, model tokens, broker
            # device credential or arbitrary operator/cloud environment.
            _allowed_environment = {
                "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "PATH",
                "APPDATA", "LOCALAPPDATA", "USERPROFILE", "USERNAME",
                "USERDOMAIN", "PROGRAMFILES", "PROGRAMFILES(X86)",
                "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
                "HOMEDRIVE", "HOMEPATH", "PYTHONPATH", "PYTHONHOME",
                "VIRTUAL_ENV", "PYTHONIOENCODING", "PYTHONUTF8",
            }
            safe_environment = {
                k: v for k, v in os.environ.items()
                if k.upper() in _allowed_environment
            }
            bound = None
            try:
                bound = self.launcher(
                    [sys.executable, "-m", "kagent.windows_excel_pdf_child",
                     str(source), str(target)],
                    cwd=dirname, environment=safe_environment,
                )
                try:
                    stdout, stderr = bound.process.communicate(
                        timeout=self.timeout_seconds,
                    )
                except subprocess.TimeoutExpired:
                    raise ContractError("supervised Excel export timed out") from None
                if bound.process.returncode != 0:
                    raise ContractError("supervised Excel conversion refused")
                if not target.is_file():
                    raise ContractError("supervised Excel PDF was not created")
                if not 0 < target.stat().st_size <= MAX_PDF_BYTES:
                    raise ContractError("supervised Excel PDF exceeds output bound")
                pdf = target.read_bytes()
                if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:
                    raise ContractError("invalid Excel PDF export signature")
                del stdout, stderr
                return pdf
            except ContractError:
                raise
            except Exception:
                raise ContractError("supervised Excel conversion failed") from None
            finally:
                if bound is not None:
                    try:
                        # Kill-on-close job cleanup even on successful exit.
                        # This cannot claim that COM-owned external Excel has
                        # been killed; live interactive proof still required.
                        bound.job.terminate_tree()
                    except Exception:
                        pass
                    try:
                        bound.process.kill() if bound.process.poll() is None else None
                        bound.process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    try:
                        bound.job.close()
                    except Exception:
                        pass


PRODUCTION_SUPERVISED_EXCEL_COM_ACTIVATED = False
