"""Bounded, opt-in Windows browser launch lifecycle. No URL/argv/identities."""
from __future__ import annotations

PHASES = frozenset({
    "exe_entry", "import_begin", "import_ok", "argv_parse_begin", "argv_parse_ok",
    "uri_accepted", "uri_rejected", "app_construct_begin", "app_construct_ok",
    "single_instance_begin", "single_instance_existing", "single_instance_owned",
    "existing_run_result", "signal_delivered", "signal_rejected",
    "tray_begin", "tray_created", "tray_run_enter", "tray_run_exit",
    "app_run_returned", "entry_exit", "exception",
})


def mark(phase: str, *, exit_code: int | None = None, exc: BaseException | None = None) -> None:
    """Fail-open diagnostic: fixed tokens ONLY, never exception text or argv."""
    try:
        import os
        from pathlib import Path
        import json
        from datetime import datetime, timezone
        if os.name != "nt" or phase not in PHASES:
            return
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            return
        root = Path(base) / "Padiem" / "ClawConnect"
        if not (root / "native-launch-diagnostics.enabled").is_file():
            return
        record = {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(), "phase": phase,
        }
        if type(exit_code) is int and -2147483648 <= exit_code <= 2147483647:
            record["exit_code"] = exit_code
        if exc is not None:
            # Only a hardcoded short class name, NEVER str(exc), traceback or repr.
            kind = type(exc).__name__
            record["exception_kind"] = kind if kind in {
                "ImportError", "ModuleNotFoundError", "OSError", "RuntimeError",
                "ValueError", "TypeError", "AssertionError", "PermissionError",
                "FileNotFoundError", "AttributeError", "SystemExit", "KeyboardInterrupt",
                "TimeoutError", "ConnectionError",
            } else "OtherException"
        data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        # Single short append protects prior stage evidence if the process dies.
        fd = os.open(str(root / "native-launch-diagnostics.jsonl"),
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except BaseException:
        # Diagnostic failure must never affect startup, single-instance, or tray.
        return
