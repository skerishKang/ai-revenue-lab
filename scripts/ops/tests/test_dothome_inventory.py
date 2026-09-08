from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "dothome_inventory.py"


def _load():
    spec = importlib.util.spec_from_file_location("dothome_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX_HTML = """<!doctype html>
<html>
<head>
<link rel="stylesheet" href="css/site.css">
<script src="js/app.js"></script>
</head>
<body>
<img src="img/logo.png" srcset="img/logo.png 1x, img/logo@2x.png 2x">
<a href="https://example.com">external</a>
</body>
</html>
"""

SITE_CSS = "body { background: url(../img/bg.jpg); }\n"


def _build_sample_tree(root: Path) -> None:
    (root / "css").mkdir()
    (root / "js").mkdir()
    (root / "img").mkdir()
    (root / "video").mkdir()
    (root / "audio").mkdir()
    (root / "download").mkdir()
    (root / "dist" / "assets").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "backup" / "img").mkdir(parents=True)
    (root / "docs" / "copy").mkdir(parents=True)

    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "css" / "site.css").write_text(SITE_CSS, encoding="utf-8")
    (root / "js" / "app.js").write_text("console.log('landing');\n", encoding="utf-8")
    (root / "img" / "logo.png").write_bytes(b"PNG-LOGO")
    (root / "img" / "bg.jpg").write_bytes(b"JPG-BACKGROUND")

    (root / "video" / "intro.mp4").write_bytes(b"V" * (12 * 1024 * 1024))
    (root / "download" / "legacy-site.zip").write_bytes(b"Z" * (11 * 1024 * 1024))
    (root / "dist" / "old-bundle.js").write_bytes(b"var legacy = 1;\n")
    (root / "dist" / "assets" / "app.abc123.js").write_bytes(b"var hashed = 1;\n")
    (root / "node_modules" / "pkg" / "index.js").write_bytes(b"module.exports = 1;\n")

    (root / "backup" / "img" / "bg.jpg").write_bytes(b"JPG-BACKGROUND")
    (root / "docs" / "readme.txt").write_bytes(b"mirror notes\n")
    (root / "docs" / "copy" / "readme.txt").write_bytes(b"mirror notes\n")
    (root / "audio" / "chime.mp3").write_bytes(b"ID3-chime")


@pytest.fixture()
def sample_root(tmp_path: Path) -> Path:
    root = tmp_path / "dothome-mirror"
    root.mkdir()
    _build_sample_tree(root)
    return root


def test_inventory_reports_total_size_and_directory_summary(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    assert report["mode"] == "REPORT_ONLY"
    assert report["summary"]["files_scanned"] == 14
    assert report["summary"]["total_bytes"] == sum(
        path.stat().st_size for path in sample_root.rglob("*") if path.is_file()
    )
    directory_sizes = {row["path"]: row["bytes"] for row in report["directories"]}
    assert directory_sizes["video"] == 12 * 1024 * 1024
    assert directory_sizes["download"] == 11 * 1024 * 1024
    assert directory_sizes["."] == report["summary"]["total_bytes"]
    largest_after_root = [row["path"] for row in report["directories"] if row["path"] != "."][0]
    assert largest_after_root == "video"


def test_large_files_are_detected_above_threshold(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root, large_file_bytes=10 * 1024 * 1024)

    large = {row["path"] for row in report["large_files"]}
    assert large == {"download/legacy-site.zip", "video/intro.mp4"}
    assert report["summary"]["large_files"] == 2


def test_archives_are_detected(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    assert [row["path"] for row in report["archives"]] == ["download/legacy-site.zip"]
    assert report["archives"][0]["kind"] == "archive"


def test_video_audio_and_image_are_detected(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    kinds = {row["path"]: row["kind"] for row in report["media"]}
    assert kinds["video/intro.mp4"] == "video"
    assert kinds["audio/chime.mp3"] == "audio"
    assert kinds["img/logo.png"] == "image"
    assert kinds["backup/img/bg.jpg"] == "image"
    assert report["summary"]["media_files"] == 5


def test_old_build_and_junk_directories_are_detected(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    kinds = {row["path"]: row["kind"] for row in report["old_directories"]}
    assert kinds["dist"] == "build_output"
    assert kinds["node_modules"] == "junk"
    assert kinds["backup"] == "junk"
    assert report["summary"]["old_directories"] == 3


def test_duplicate_files_are_grouped_by_hash(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    groups = {tuple(group["paths"]): group for group in report["duplicates"]}
    assert ("docs/copy/readme.txt", "docs/readme.txt") in groups
    assert ("backup/img/bg.jpg", "img/bg.jpg") in groups

    group = groups[("docs/copy/readme.txt", "docs/readme.txt")]
    assert group["method"] == "sha256"
    assert group["extra_copies"] == 1
    assert group["reclaimable_bytes"] == len(b"mirror notes\n")


def test_landing_document_and_references_are_detected(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    assert report["landing"]["documents"] == ["index.html"]
    protected = set(report["landing"]["protected"])
    assert {
        "index.html",
        "css/site.css",
        "js/app.js",
        "img/logo.png",
        "img/bg.jpg",
    } <= protected
    assert "https://example.com" not in protected
    assert "img/logo@2x.png" not in protected


def test_landing_files_are_never_delete_candidates(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    candidates = {row["path"] for row in report["delete_candidates"]}
    for protected in report["landing"]["protected"]:
        assert protected not in candidates

    # A protected duplicate copy is never proposed; only the unprotected copy is.
    assert "backup/img/bg.jpg" in candidates
    assert "img/bg.jpg" not in candidates


def test_delete_candidates_cover_archives_media_old_dirs_and_duplicates(sample_root: Path) -> None:
    inventory = _load()
    report = inventory.scan(sample_root)

    candidates = {row["path"]: row for row in report["delete_candidates"]}
    assert "archive" in candidates["download/legacy-site.zip"]["categories"]
    assert "media" in candidates["video/intro.mp4"]["categories"]
    assert "old_directory" in candidates["dist/old-bundle.js"]["categories"]
    assert "old_directory" in candidates["node_modules/pkg/index.js"]["categories"]
    assert "duplicate" in candidates["docs/copy/readme.txt"]["categories"]

    assert report["summary"]["reclaimable_bytes"] == sum(
        row["bytes"] for row in report["delete_candidates"]
    )
    assert report["safety"]["delete_performed"] == "NO"


def test_scan_never_mutates_the_tree(sample_root: Path) -> None:
    inventory = _load()

    before = sorted(
        (path.relative_to(sample_root).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in sample_root.rglob("*")
        if path.is_file()
    )
    inventory.scan(sample_root)
    after = sorted(
        (path.relative_to(sample_root).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in sample_root.rglob("*")
        if path.is_file()
    )

    assert before == after
    assert sample_root.joinpath("index.html").read_text(encoding="utf-8") == INDEX_HTML


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "   ",
        "relative/mirror",
        "/",
        str(Path.home()),
        str(Path.home().parent),
    ],
)
def test_dangerous_roots_are_rejected(candidate: str) -> None:
    inventory = _load()
    with pytest.raises(inventory.InventoryError):
        inventory.validate_root(candidate)


def test_filesystem_anchor_root_is_rejected(tmp_path: Path) -> None:
    inventory = _load()
    anchor = str(Path(tmp_path).anchor)
    with pytest.raises(inventory.InventoryError) as caught:
        inventory.validate_root(anchor)
    assert "ROOT_IS_FILESYSTEM_ROOT" in str(caught.value)


def test_missing_root_and_file_root_are_rejected(tmp_path: Path) -> None:
    inventory = _load()
    with pytest.raises(inventory.InventoryError) as missing:
        inventory.validate_root(tmp_path / "does-not-exist")
    assert "ROOT_MISSING" in str(missing.value)

    target = tmp_path / "a-file.txt"
    target.write_text("not a directory", encoding="utf-8")
    with pytest.raises(inventory.InventoryError) as not_dir:
        inventory.validate_root(target)
    assert "ROOT_NOT_DIRECTORY" in str(not_dir.value)


def test_symlinks_are_recorded_and_not_followed(tmp_path: Path) -> None:
    inventory = _load()
    root = tmp_path / "mirror"
    (root / "real").mkdir(parents=True)
    (root / "real" / "inside.txt").write_bytes(b"inside")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside of the mirror")

    try:
        os.symlink(outside, root / "linked")
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation is not permitted in this environment")

    report = inventory.scan(root)

    assert report["symlinks_skipped"] == ["linked"]
    assert [row["path"] for row in report["directories"] if row["path"] == "linked"] == []
    assert "linked/secret.txt" not in {row["path"] for row in report["directories"]}
    assert report["summary"]["files_scanned"] == 1


def test_report_is_deterministic(sample_root: Path) -> None:
    inventory = _load()
    first = inventory.scan(sample_root)
    second = inventory.scan(sample_root)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_cli_writes_json_and_markdown_reports(sample_root: Path, tmp_path: Path) -> None:
    inventory = _load()
    out_json = tmp_path / "reports" / "inventory.json"
    out_md = tmp_path / "reports" / "inventory.md"

    exit_code = inventory.main(
        [
            "--root",
            str(sample_root),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--quota-mb",
            "1024",
        ]
    )

    assert exit_code == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["summary"]["quota_bytes"] == 1024 * 1024 * 1024
    assert payload["safety"]["network_calls"] == 0

    markdown = out_md.read_text(encoding="utf-8")
    assert "MODE" in markdown or "REPORT_ONLY" in markdown
    assert "Delete candidates" in markdown
    assert sample_root.joinpath("index.html").read_text(encoding="utf-8") == INDEX_HTML


def test_cli_rejects_dangerous_root_with_exit_code_2(capsys) -> None:
    inventory = _load()
    exit_code = inventory.main(["--root", str(Path.home())])
    assert exit_code == 2
    assert "DOTHOME_INVENTORY_ERROR=" in capsys.readouterr().err


def test_source_uses_no_network_deletion_or_credential_material() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "import socket",
        "import urllib",
        "urllib.request",
        "http.client",
        "urlopen",
        "ftplib",
        "import requests",
        "import httpx",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.rename",
        "shutil.rmtree",
        "shutil.move",
        ".unlink(",
        ".rmdir(",
        "os.environ",
        "getenv",
        "password",
        "passwd",
    )
    for token in forbidden:
        assert token not in source, f"forbidden token present: {token}"
