"""Compose the unchanged canonical Identity DO over the broker SQLite adapter."""
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from identity_authority_worker import CanonicalIdentityDurableObject
from storage import SqLiteDurableStorage


def create_authority():
    db_path = os.environ.get("COM2_IDENTITY_DB_PATH", "").strip()
    lookup_file = os.environ.get("COM2_IDENTITY_LOOKUP_KEY_FILE", "").strip()
    ticket_file = os.environ.get("COM2_IDENTITY_TICKET_KEY_FILE", "").strip()
    if not db_path or not Path(db_path).is_file() or not lookup_file or not ticket_file:
        raise RuntimeError("existing identity database and key files required")
    # Never bootstrap a fresh identity authority from an empty file.
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as probe:
        names = {row[0] for row in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"canonical_identity_subject", "canonical_product_identity_link", "canonical_auth_session"}
    if not required.issubset(names):
        raise RuntimeError("existing canonical identity schema required")
    lookup = Path(lookup_file).read_text(encoding="utf-8").strip()
    ticket = Path(ticket_file).read_text(encoding="utf-8").strip()
    env = SimpleNamespace(
        CONTROL_PLANE_IDENTITY_LOOKUP_KEY=lookup,
        GOOGLE_CONNECT_TICKET_KEY=ticket,
        CONTROL_PLANE_ALLOWED_PRODUCTS="b62,b54-padiem-claw,lovetree-4-0",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED=os.environ.get("CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED", "false"),
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED=os.environ.get("CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED", "false"),
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED=os.environ.get("CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED", "false"),
    )
    storage = SqLiteDurableStorage.open(db_path)
    try:
        return CanonicalIdentityDurableObject(SimpleNamespace(storage=storage), env)
    except BaseException:
        storage.close()
        raise
