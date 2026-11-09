"""#7306: the COM2 P01 host binds the same durable Engine stores the Worker does.

The Worker composes three durable Engine stores over the ``ENGINE_IMAGE_STORE``,
``ENGINE_EVIDENCE_STORE`` and ``ENGINE_CONTINUATION`` D1 bindings
(``worker_identity.py``). The CPython host had one local engine database under
``PADIEM_ENGINE_LOCAL_DB`` but published it only as ``ENGINE_IDEMPOTENCY`` and
``ENGINE_CONNECTOR_GRANTS``, so the multimodal image byte store, the document
evidence store and the approval continuation store were absent and those lanes
failed closed on this host only.

These tests pin the name contract and the shared-database fact, and prove the
image byte store really admits and fetches over the host database.
"""
from __future__ import annotations

import asyncio
import ast
from pathlib import Path

from app.attachment_byte_store import (
    CloudflareD1ImageByteStore,
    ImageByteStoreError,
    ScopedImageByteStore,
)
from app.local_runtime import DB_PATH_ENV, _env_view, _local_bindings

ENGINE_DIR = Path(__file__).resolve().parents[1]
WORKER_SOURCE = (ENGINE_DIR / "worker_identity.py").read_text(encoding="utf-8")
RUNTIME_SOURCE = (ENGINE_DIR / "app/local_runtime.py").read_text(encoding="utf-8")

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082"
)


def _module_constants(source: str) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants[target.id] = node.value.value
    return constants


def test_the_host_binds_every_durable_store_the_worker_reads(tmp_path):
    constants = _module_constants(WORKER_SOURCE)
    required = {
        constants["ENGINE_IMAGE_STORE_BINDING"],
        constants["ENGINE_EVIDENCE_STORE_BINDING"],
        constants["ENGINE_CONTINUATION_BINDING_NAME"],
    }
    assert required == {
        "ENGINE_IMAGE_STORE",
        "ENGINE_EVIDENCE_STORE",
        "ENGINE_CONTINUATION",
    }

    bindings = _local_bindings({DB_PATH_ENV: str(tmp_path / "engine-7306.sqlite3")})
    for name in required:
        assert name in bindings, name
    # One host database answers every name: the same object, not three stores.
    assert bindings["ENGINE_IMAGE_STORE"] is bindings["ENGINE_IDEMPOTENCY"]
    assert bindings["ENGINE_EVIDENCE_STORE"] is bindings["ENGINE_IDEMPOTENCY"]
    assert bindings["ENGINE_CONTINUATION"] is bindings["ENGINE_IDEMPOTENCY"]


def test_the_worker_image_store_reads_the_same_binding_name():
    constants = _module_constants(WORKER_SOURCE)
    assert constants["ENGINE_IMAGE_STORE_BINDING"] == "ENGINE_IMAGE_STORE"
    assert 'ENGINE_IMAGE_STORE_BINDING = "ENGINE_IMAGE_STORE"' in WORKER_SOURCE
    for name in ("ENGINE_IMAGE_STORE", "ENGINE_EVIDENCE_STORE", "ENGINE_CONTINUATION"):
        assert f'bindings["{name}"] = database' in RUNTIME_SOURCE, name


def test_the_host_image_store_admits_and_fetches_over_the_local_database(tmp_path):
    env = _env_view({DB_PATH_ENV: str(tmp_path / "engine-7306.sqlite3")})
    store = CloudflareD1ImageByteStore(env.ENGINE_IMAGE_STORE)
    scoped = ScopedImageByteStore(port=store)

    async def run():
        record = await scoped.admit_image(
            data=PNG,
            media_type="image/png",
            app_id="padiem-chat",
            tenant_id="tenant-7306",
            subject_id="subject-7306",
        )
        fetched = await scoped.fetch_image(
            attachment_ref=record.attachment_ref,
            app_id="padiem-chat",
            tenant_id="tenant-7306",
            subject_id="subject-7306",
        )
        return record, fetched

    record, fetched = asyncio.run(run())
    assert record.byte_size == len(PNG)
    assert fetched is not None
    assert fetched[1] == PNG


def test_the_host_image_store_fails_closed_on_a_foreign_scope(tmp_path):
    env = _env_view({DB_PATH_ENV: str(tmp_path / "engine-7306.sqlite3")})
    scoped = ScopedImageByteStore(port=CloudflareD1ImageByteStore(env.ENGINE_IMAGE_STORE))

    async def run():
        record = await scoped.admit_image(
            data=PNG,
            media_type="image/png",
            app_id="padiem-chat",
            tenant_id="tenant-7306",
            subject_id="subject-7306",
        )
        try:
            await scoped.fetch_image(
                attachment_ref=record.attachment_ref,
                app_id="padiem-chat",
                tenant_id="other-tenant",
                subject_id="subject-7306",
            )
        except ImageByteStoreError as exc:
            return exc.code
        return None

    assert asyncio.run(run()) == "unauthorized"
