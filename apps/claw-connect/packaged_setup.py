"""Single-EXE Windows setup for the already built PADIEM Connector payload.

This is only the installer bootstrap, not a second agent/runtime/login.
No system Python is required on customer PCs.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile, BadZipFile


def main() -> int:
    parser = argparse.ArgumentParser(prog="PADIEM Connector Setup")
    parser.add_argument("--verify-only", action="store_true", help="verify embedded payload; no install/registry changes")
    options = parser.parse_args()
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    payload = bundled / "connector-payload.zip"
    installer = bundled / "install-standalone.ps1"
    if not payload.is_file() or not installer.is_file():
        print("Installer payload is incomplete.", file=sys.stderr)
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="padiem-connector-setup-") as tmp:
            target = Path(tmp)
            with ZipFile(payload, "r") as archive:
                entries = archive.infolist()
                # Fail closed on path traversal, symlinks, duplicate names,
                # or an unexpectedly large decompressed payload.
                seen: set[str] = set()
                total = 0
                for entry in entries:
                    rel = Path(entry.filename.replace("\\", "/"))
                    normalized = rel.as_posix().casefold()
                    if (rel.is_absolute() or ".." in rel.parts or
                        normalized in seen or "\x00" in entry.filename or
                        (entry.external_attr >> 16) & 0o170000 == 0o120000):
                        print("Unsafe bundled file layout.", file=sys.stderr)
                        return 2
                    seen.add(normalized)
                    total += entry.file_size
                    if total > 120 * 1024 * 1024:
                        print("Bundled payload exceeds supported size.", file=sys.stderr)
                        return 2
                archive.extractall(target)
            exe = target / "padiem-connector.exe"
            resident = target / "_internal" / "kagent" / "local_agent_resident_process.py"
            if not exe.is_file() or not resident.is_file():
                print("Bundled Connector or Resident missing.", file=sys.stderr)
                return 2
            if options.verify_only:
                print("Payload verified: canonical Resident and Connector present.")
                return 0

            completed = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-File", str(installer),
                    "-BundleRoot", str(target),
                ],
                check=False,
            )
            return completed.returncode
    except (OSError, BadZipFile, ValueError, subprocess.SubprocessError):
        print("Setup failed while extracting or installing Connector.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
