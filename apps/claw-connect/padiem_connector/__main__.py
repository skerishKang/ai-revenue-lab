"""PADIEM Connector command — no additional execution engine."""
import sys

if __name__ == "__main__":
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
