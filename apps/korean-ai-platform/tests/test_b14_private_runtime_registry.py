"""Private B14 registry contract: immutable pin, isolation and fail closed.

#7241 3단계: the object a deployment pins is the *installed* document shape —
``install_document`` of the private registry — because the repository file is a
schema-shaped placeholder with no model, provider or host value. The bytes the
suite pins are therefore composed here from that same conversion of the
effective document, so no deployment value is written into this file.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from app.pilot import model_registry_file
from app.pilot import private_runtime_registry as private

from padiem_control_plane import models_registry


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


def _installed_document_text() -> str:
    """The private document in the shape the Worker installs, as JSON text.

    A pinned object is an ``install_document`` of a private registry (#6828),
    and the effective document of this process is the private registry the host
    reads. Converting it here keeps every identity in the registry, never in
    this file.
    """
    load = models_registry.load_snapshot()
    assert load.ready, load.code
    document = models_registry.install_document(load.registry)
    assert document["models"], "the effective document registers no model"
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


@pytest.mark.asyncio
async def test_private_config_loads_exact_pinned_version_only_once(monkeypatch):
    source = _installed_document_text()
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
    source = _installed_document_text()
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
