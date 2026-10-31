"""Fail-closed staging preflight; print no values."""
import os
from pathlib import Path
import sys

DATA = Path("/mnt/d/padiem/broker-staging")


def private_file(name):
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    path = Path(value)
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            return None
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        if resolved.is_relative_to(DATA.resolve()) or (os.name == "posix" and (stat.st_mode & 0o077 or stat.st_uid != os.geteuid())):
            return None
        content = resolved.read_text(encoding="utf-8").strip()
        return content if len(content) >= 32 else None
    except (OSError, ValueError, UnicodeError):
        return None


def pepper_ready():
    return not os.environ.get("LOCAL_AGENT_BROKER_PEPPER", "").strip() and private_file("LOCAL_AGENT_BROKER_PEPPER_FILE") is not None


def ready():
    return (pepper_ready() and private_file("PADIEM_BROKER_RPC_INGRESS_SECRET_FILE") is not None
            and not os.environ.get("PADIEM_BROKER_RPC_INGRESS_SECRET", "").strip()
            and bool(os.environ.get("LOCAL_AGENT_BROKER_AUTHORITY_REF", "").strip())
            and os.environ.get("PADIEM_BROKER_DB_PATH") == str(DATA / "broker.sqlite3")
            and DATA.is_dir() and os.access(DATA, os.W_OK))


if __name__ == "__main__":
    valid = pepper_ready() if sys.argv[1:] == ["--pepper-only"] else ready()
    print("BROKER_STAGING_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
