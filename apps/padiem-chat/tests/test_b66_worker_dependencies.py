from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import tomllib

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "b66_worker_dependencies", APP_ROOT / "scripts" / "build_b66_worker_dependencies.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def worker_lock() -> dict:
    return tomllib.loads((APP_ROOT / "pylock.toml").read_text(encoding="utf-8"))


def test_host_and_worker_pin_same_reviewed_pymupdf_version():
    versions = builder.validate_lock(worker_lock())
    host = tomllib.loads((APP_ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = [package for package in host["package"] if package["name"] == "pymupdf"]
    assert [package["version"] for package in packages] == [versions["pymupdf"]]


@pytest.mark.parametrize("field", ["hash", "url", "version"])
def test_changed_wasm_artifact_is_rejected_before_install(tmp_path, monkeypatch, field):
    lock = deepcopy(worker_lock())
    package = next(p for p in lock["packages"] if p["name"] == "pymupdf")
    if field == "version":
        package["version"] = "1.26.4"
    elif field == "url":
        package["wheels"][0]["url"] = "https://example.invalid/unreviewed.whl"
    else:
        package["wheels"][0]["hashes"]["sha256"] = "0" * 64
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: pytest.fail("install ran"))
    with pytest.raises(ValueError):
        builder.validate_lock(lock)


def test_existing_output_is_preserved(tmp_path):
    marker = tmp_path / "existing"
    marker.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="new or empty"):
        builder.require_fresh_output(tmp_path)
    assert marker.read_bytes() == b"preserve"


def test_pywrangler_marker_only_handoff_is_consumed(tmp_path):
    output = tmp_path / "python_modules"
    output.mkdir()
    (output / ".synced").write_text("1.17.7\n", encoding="utf-8")
    (output / "pyvenv.cfg").write_text("", encoding="utf-8")
    assert builder.consume_pywrangler_placeholder(output) is True
    assert list(output.iterdir()) == []


def test_pywrangler_handoff_with_extra_file_is_preserved(tmp_path):
    output = tmp_path / "python_modules"
    output.mkdir()
    (output / ".synced").write_text("1.17.7\n", encoding="utf-8")
    (output / "pyvenv.cfg").write_text("", encoding="utf-8")
    extra = output / "user-file"
    extra.write_bytes(b"preserve")
    assert builder.consume_pywrangler_placeholder(output) is False
    assert extra.read_bytes() == b"preserve"


def test_local_builds_use_staging_without_existing_build_metadata(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    metadata = source / "tracked.egg-info"
    metadata.mkdir()
    marker = metadata / "SOURCES.txt"
    marker.write_text("original", encoding="utf-8")
    (source / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    lock = tmp_path / "pylock.toml"
    lock.write_text('[[packages]]\nname = "example"\ndirectory = { path = "source" }\n')
    staging = tmp_path / "staging"
    staging.mkdir()
    staged_lock = builder.stage_local_packages(lock, staging)
    staged = tomllib.loads(staged_lock.read_text())["packages"][0]["directory"]["path"]
    assert Path(staged).is_relative_to(staging)
    assert (Path(staged) / "pyproject.toml").is_file()
    assert not (Path(staged) / "tracked.egg-info").exists()
    assert marker.read_text() == "original"


def test_runtime_copy_is_byte_identical_and_refreshes_from_canonical_source(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "static").mkdir()
    (tmp_path / "worker.py").write_bytes(b"worker-one\r\n")
    source = tmp_path / "app" / "renderer.py"
    source.write_bytes(b"renderer-one\r\n")
    static_source = tmp_path / "static" / "index.html"
    static_source.write_bytes(b"<main>one</main>\r\n")
    result = builder.generate_runtime(tmp_path)
    copied = tmp_path / builder.RUNTIME_DIRECTORY / "app" / "renderer.py"
    static_copy = tmp_path / builder.RUNTIME_DIRECTORY / "static" / "index.html"
    assert result["byte_identical"] is True
    assert copied.read_bytes() == source.read_bytes()
    assert static_copy.read_bytes() == static_source.read_bytes()
    source.write_bytes(b"renderer-two\n")
    static_source.write_bytes(b"<main>two</main>\n")
    builder.generate_runtime(tmp_path)
    assert copied.read_bytes() == source.read_bytes()
    assert static_copy.read_bytes() == static_source.read_bytes()


def test_unmarked_generated_runtime_is_preserved(tmp_path):
    output = tmp_path / builder.RUNTIME_DIRECTORY
    output.mkdir()
    marker = output / "user-file"
    marker.write_bytes(b"keep")
    with pytest.raises(ValueError, match="unmarked"):
        builder.generate_runtime(tmp_path)
    assert marker.read_bytes() == b"keep"


def test_symlink_output_is_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")
    with pytest.raises(ValueError, match="symlink or junction"):
        builder.require_fresh_output(link / "vendor")
