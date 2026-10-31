"""#5484: the COM2 R2 object download must carry the Cloudflare credential.

The COM2 host's own Wrangler OAuth session is expired, so a direct
``wrangler r2 object get`` fails with an authentication error. The D1 export
and the inventory Worker already use the COM2 DPAPI secret store, so the object
download uses the same store: the credential is injected into the child
process environment only and never reaches the argument vector, the captured
output or a new plaintext file.

These tests use a Wrangler test double. They never reach Cloudflare, never
touch a production bucket and never hold a credential.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "r2_sync.py"


def _load():
    spec = importlib.util.spec_from_file_location("com2_r2_sync_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


r2_sync = _load()


def test_the_download_goes_through_the_dpapi_secret_store(tmp_path: Path) -> None:
    """With the store present the command is wrapped and stays credential-free."""

    store = tmp_path / "store.py"
    store.write_text("# test double\n", encoding="utf-8")
    original = r2_sync.DPAPI_STORE
    r2_sync.DPAPI_STORE = str(store)
    try:
        command = r2_sync.wrangler_command("r2", "object", "get", "bucket/key")
    finally:
        r2_sync.DPAPI_STORE = original

    assert command[0] == sys.executable
    assert command[1] == str(store)
    assert command[2] == "run"
    assert command[3] == r2_sync.WRANGLER
    assert command[4:] == ["r2", "object", "get", "bucket/key"]


def test_without_the_store_the_command_is_unchanged(tmp_path: Path) -> None:
    """A host without the store keeps the previous behaviour."""

    original = r2_sync.DPAPI_STORE
    r2_sync.DPAPI_STORE = str(tmp_path / "missing-store.py")
    try:
        command = r2_sync.wrangler_command("r2", "object", "get", "bucket/key")
    finally:
        r2_sync.DPAPI_STORE = original

    assert command == [r2_sync.WRANGLER, "r2", "object", "get", "bucket/key"]


def test_the_fetch_uses_the_store_wrapped_command(tmp_path: Path) -> None:
    """The download itself must use the wrapped command."""

    store = tmp_path / "store.py"
    store.write_text("# test double\n", encoding="utf-8")
    recorded: list[list[str]] = []
    original_store = r2_sync.DPAPI_STORE
    original_run = subprocess.run

    def recording_run(command, *args, **kwargs):
        recorded.append(list(command))
        # Produce the expected object so the verification can succeed.
        target = Path(command[-3])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"payload")
        return subprocess.CompletedProcess(command, 0, "", "")

    r2_sync.DPAPI_STORE = str(store)
    subprocess.run = recording_run
    try:
        result = r2_sync.fetch_one(
            "workspace",
            {"key": "object-key", "size": 7, "etag": ""},
            tmp_path / "blobs",
        )
    finally:
        subprocess.run = original_run
        r2_sync.DPAPI_STORE = original_store

    assert result["ok"] is True
    assert recorded, "the download must call wrangler"
    assert recorded[0][1] == str(store)
    assert recorded[0][2] == "run"
    assert "r2" in recorded[0] and "object" in recorded[0]
    # The credential never reaches the argument vector.
    assert not any("CLOUDFLARE_API_TOKEN" in part for part in recorded[0])


def test_the_diff_marker_contract_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The runner parses this exact DIFF line."""

    staging = tmp_path / "r2-staging"
    (staging / "incoming").mkdir(parents=True)
    (staging / "generations" / "gen-1").mkdir(parents=True)
    for label in r2_sync.BUCKETS:
        (staging / "incoming" / (label + ".json")).write_text(
            '{"objects": [{"key": "k1", "size": 3, "etag": "e"}]}', encoding="utf-8"
        )
    (staging / "generations" / "gen-1" / "manifest.json").write_text(
        '[{"bucket": "workspace", "key": "k1", "ok": true, "size": 3, "etag": "e", '
        '"sha256": "x", "file": "f", "origin": "base"}]', encoding="utf-8"
    )
    (staging / "current_generation.json").write_text(
        '{"generation": "gen-1"}', encoding="utf-8"
    )

    original = (
        r2_sync.STAGING,
        r2_sync.GENERATIONS,
        r2_sync.INCOMING,
        r2_sync.POINTER,
    )
    r2_sync.STAGING = staging
    r2_sync.GENERATIONS = staging / "generations"
    r2_sync.INCOMING = staging / "incoming"
    r2_sync.POINTER = staging / "current_generation.json"
    try:
        report = r2_sync.compute_diff("gen-1", r2_sync.generation_index("gen-1"))
        r2_sync.print_diff(report)
    finally:
        (
            r2_sync.STAGING,
            r2_sync.GENERATIONS,
            r2_sync.INCOMING,
            r2_sync.POINTER,
        ) = original

    printed = capsys.readouterr().out
    assert "DIFF workspace BASE_GEN=gen-1 REMOTE=1 BYTES=3 NEW=0 CHANGED=0 DELETED_REMOTE=0 UNCHANGED=1" in printed
