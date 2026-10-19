"""Private B14 registry contract: immutable pin, isolation and fail closed."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.pilot import model_registry_file
from app.pilot import private_runtime_registry as private

REGISTRY = Path(__file__).resolve().parents[1] / "app" / "pilot" / "b14_models.json"


class Blob:
    def __init__(self, content):
        self.content = content

    async def text(self):
        return self.content


class Bucket:
    def __init__(self, content):
        self.content = content
        self.reads = []

    async def get(self, key):
        self.reads.append(key)
        return Blob(self.content) if self.content is not None else None


@pytest.fixture(autouse=True)
def reset_marker(monkeypatch):
    monkeypatch.setattr(private, "_loaded_sha256", None)


@pytest.mark.asyncio
async def test_private_config_loads_exact_pinned_version_only_once(monkeypatch):
    source = REGISTRY.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    bucket = Bucket(source)
    installed = []
    monkeypatch.setattr(model_registry_file, "install_models", lambda data: installed.append(data))
    env = SimpleNamespace(
        B14_PRIVATE_REGISTRY_SHA256=digest, PADIEM_B14_PRIVATE_CONFIG=bucket
    )
    await private.ensure_private_registry(env)
    await private.ensure_private_registry(env)
    assert bucket.reads == ["registry/" + digest + ".json"]
    assert len(installed) == 1
    assert len(installed[0]["models"]) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_binding", "missing_object", "wrong_hash", "bad_pin"])
async def test_private_config_never_falls_back_on_missing_or_tampered_data(monkeypatch, case):
    source = REGISTRY.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode()).hexdigest()
    installed = []
    monkeypatch.setattr(model_registry_file, "install_models", lambda data: installed.append(data))
    kwargs = {"B14_PRIVATE_REGISTRY_SHA256": "INVALID" if case == "bad_pin" else digest}
    if case != "missing_binding":
        kwargs["PADIEM_B14_PRIVATE_CONFIG"] = Bucket(
            None if case == "missing_object" else source + " "
            if case == "wrong_hash" else source
        )
    with pytest.raises(private.PrivateRegistryUnavailable):
        await private.ensure_private_registry(SimpleNamespace(**kwargs))
    assert installed == []
    assert private._loaded_sha256 is None


@pytest.mark.asyncio
async def test_legacy_mode_is_untouched_without_private_pin(monkeypatch):
    monkeypatch.setattr(private, "_loaded_sha256", None)
    await private.ensure_private_registry(SimpleNamespace())
    assert private._loaded_sha256 is None
