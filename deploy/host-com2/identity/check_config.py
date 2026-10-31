"""Fail-closed staging identity preflight; never prints secret contents."""
import os
from pathlib import Path
import sqlite3

DATA = Path("/mnt/d/padiem/identity-staging")


def private_file(name):
    value = os.environ.get(name, "").strip()
    if not value:
        return False
    path = Path(value)
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            return False
        stat = path.stat()
        return not (os.name == "posix" and (stat.st_mode & 0o077 or stat.st_uid != os.geteuid())) and len(path.read_text(encoding="utf-8").strip()) >= 32
    except (OSError, UnicodeError):
        return False


def ready():
    if (os.environ.get("COM2_IDENTITY_AUTHORITY_FACTORY") != "authority_factory:create_authority"
        or os.environ.get("COM2_IDENTITY_DB_PATH") != str(DATA / "identity.sqlite3")
        or not DATA.is_dir() or not os.access(DATA, os.W_OK)
        or not all(private_file(name) for name in ("COM2_IDENTITY_LOOKUP_KEY_FILE", "COM2_IDENTITY_TICKET_KEY_FILE", "COM2_IDENTITY_RPC_SECRET_FILE"))):
        return False
    db = DATA / "identity.sqlite3"
    if db.is_symlink() or not db.is_file():
        return False
    try:
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {"canonical_identity_subject", "canonical_product_identity_link", "canonical_auth_session"}.issubset(names)
    except (OSError, sqlite3.Error):
        return False


if __name__ == "__main__":
    valid = ready()
    print("IDENTITY_STAGING_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
