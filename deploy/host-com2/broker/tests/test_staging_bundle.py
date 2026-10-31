"""Source-only bundle checks: no systemd, installation, services or real secrets."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
HOST = ROOT / "deploy/host-com2"
BASH = str(Path(shutil.which("git")).resolve().parent.parent / "bin" / "bash.exe") if os.name == "nt" else "bash"


def load(kind):
    spec = importlib.util.spec_from_file_location("staging_" + kind, HOST / kind / "check_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("kind", "port"), [("broker", 8799), ("identity", 8802)])
def test_templates_loopback_default_dry_run_and_scripts(kind, port):
    directory = HOST / kind
    unit = (directory / f"padiem-{kind}-staging.service").read_text()
    assert f"--host 127.0.0.1 --port {port}" in unit
    assert "--host 0.0.0.0" not in unit
    assert "ExecCondition=" in unit
    for name in ("install", "start", "stop", "status"):
        path = directory / f"{name}-staging.sh"
        assert b"\r" not in path.read_bytes()
        subprocess.run([BASH, "-n", str(path)], check=True)
    result = subprocess.run([BASH, str(directory / "install-staging.sh")], check=True, capture_output=True, text=True)
    assert "_STAGING_INSTALL=DRY_RUN" in result.stdout
    assert "START_SERVICE=NO" in result.stdout
    assert "ENABLE_SERVICE=NO" in result.stdout


def test_broker_pepper_validation_and_data_separation(tmp_path, monkeypatch):
    mod = load("broker")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(mod, "DATA", data)
    secret = tmp_path / "pepper"
    secret.write_text("p" * 40)
    secret.chmod(0o600)
    monkeypatch.setenv("LOCAL_AGENT_BROKER_PEPPER_FILE", str(secret))
    monkeypatch.delenv("LOCAL_AGENT_BROKER_PEPPER", raising=False)
    assert mod.pepper_ready()
    proof = tmp_path / "proof"
    proof.write_text("s" * 40)
    proof.chmod(0o600)
    monkeypatch.setenv("PADIEM_BROKER_RPC_INGRESS_SECRET_FILE", str(proof))
    monkeypatch.delenv("PADIEM_BROKER_RPC_INGRESS_SECRET", raising=False)
    monkeypatch.setenv("PADIEM_BROKER_DB_PATH", str(data / "broker.sqlite3"))
    monkeypatch.setenv("LOCAL_AGENT_BROKER_AUTHORITY_REF", "staging")
    assert mod.ready()
    monkeypatch.setenv("PADIEM_BROKER_DB_PATH", str(tmp_path / "outside.db"))
    assert not mod.ready()
    monkeypatch.setenv("LOCAL_AGENT_BROKER_PEPPER", "inline forbidden")
    assert not mod.pepper_ready()
    monkeypatch.delenv("LOCAL_AGENT_BROKER_PEPPER")
    inside = data / "pepper"
    inside.write_text("p" * 40)
    inside.chmod(0o600)
    monkeypatch.setenv("LOCAL_AGENT_BROKER_PEPPER_FILE", str(inside))
    assert not mod.pepper_ready()
    if os.name == "posix":
        secret.chmod(0o644)
        monkeypatch.setenv("LOCAL_AGENT_BROKER_PEPPER_FILE", str(secret))
        assert not mod.pepper_ready()


def test_identity_requires_existing_canonical_database(tmp_path, monkeypatch):
    mod = load("identity")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setenv("COM2_IDENTITY_AUTHORITY_FACTORY", "authority_factory:create_authority")
    monkeypatch.setenv("COM2_IDENTITY_DB_PATH", str(data / "identity.sqlite3"))
    for name in ("COM2_IDENTITY_LOOKUP_KEY_FILE", "COM2_IDENTITY_TICKET_KEY_FILE", "COM2_IDENTITY_RPC_SECRET_FILE"):
        file = tmp_path / name
        file.write_text("s" * 40)
        file.chmod(0o600)
        monkeypatch.setenv(name, str(file))
    assert not mod.ready()
    with sqlite3.connect(data / "identity.sqlite3") as db:
        for table in ("canonical_identity_subject", "canonical_product_identity_link", "canonical_auth_session"):
            db.execute("CREATE TABLE " + table + " (id TEXT)")
    assert mod.ready()
    monkeypatch.setenv("COM2_IDENTITY_AUTHORITY_FACTORY", "unknown:factory")
    assert not mod.ready()
