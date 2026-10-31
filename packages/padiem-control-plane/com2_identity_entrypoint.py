"""Loopback COM2 entrypoint; requires an explicitly configured canonical authority."""
import importlib
import os
from pathlib import Path

from com2_identity_rpc_ingress import create_app


def build_app():
    target = os.environ.get("COM2_IDENTITY_AUTHORITY_FACTORY", "").strip()
    secret_path = os.environ.get("COM2_IDENTITY_RPC_SECRET_FILE", "").strip()
    if target.count(":") != 1 or not secret_path:
        raise RuntimeError("canonical identity factory and RPC secret file required")
    module_name, factory_name = target.split(":")
    if not module_name or not factory_name or module_name.startswith("."):
        raise RuntimeError("invalid canonical identity factory")
    factory = getattr(importlib.import_module(module_name), factory_name)
    authority = factory()
    secret = Path(secret_path).read_text(encoding="utf-8").strip()
    return create_app(authority=authority, secret=secret)
