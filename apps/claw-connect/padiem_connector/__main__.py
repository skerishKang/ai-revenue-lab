"""PADIEM Connector command — no additional execution engine."""
import sys

if __name__ == "__main__":
    if getattr(sys, "frozen", False) and sys.argv[1:] in (["-V"], ["--python-version"]):
        # The installed profile's executable is this standalone EXE, not
        # a system-wide Python executable. Support the existing -V probe.
        print(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        raise SystemExit(0)
    if getattr(sys, "frozen", False) and len(sys.argv) >= 3 and sys.argv[1] == "-c":
        # Compatibility with canonical P01-approved Windows Python argv. The
        # caller's execution authority remains the existing Resident grant;
        # this is only the bundled interpreter's command-line semantics.
        snippet = sys.argv[2]
        sys.argv = ["-c", *sys.argv[3:]]
        exec(compile(snippet, "<string>", "exec"), {"__name__": "__main__"})
        raise SystemExit(0)
    if getattr(sys, "frozen", False) and sys.argv[1:] == ["--resident-child"]:
        # Re-enter the very same EXE as the existing kagent Resident.  The
        # parent supplies a freshly revalidated canonical Broker environment.
        # The kagent package is bundled as internal source data, not fetched
        # from the host computer or downloaded at first run.
        from pathlib import Path
        package_root = Path(sys._MEIPASS)
        if not (package_root / "kagent" / "local_agent_resident_process.py").is_file():
            raise SystemExit(2)
        sys.path.insert(0, str(package_root))
        from kagent.local_agent_resident_process import main as resident_main
        raise SystemExit(resident_main())

    from claw_connect.__main__ import main
    raise SystemExit(main())
