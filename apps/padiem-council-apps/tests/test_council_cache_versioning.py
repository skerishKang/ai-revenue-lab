"""2026-11-01: static asset content-hash versioning + cache headers.

배포 후에도 Cloudflare가 옛 JS·CSS를 최대 4시간 내보낸 일(11-01 실제 발생)을
막는 계약이다. 서빙되는 진입 HTML의 로컬 자산 참조는 전부 ``?v=<내용 해시>``
를 달고, 진입 HTML은 ``no-cache``, ``/static/*`` 은 1년 불변 캐시를 내보낸다.
내용이 바뀌면 URL이 바뀌므로 엣지 캐시가 새 배포를 가릴 수 없다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.asset_versions import (
    MAP_SCRIPT_ID,
    canonical_asset_bytes,
    compute_versions,
    short_hash,
    versioned_html,
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
INDEX = STATIC / "index.html"

VERSIONED_REF = re.compile(r'(?:href|src)="((?:\./|/)?static/[^"?]+)\?v=([0-9a-f]{8})"')


def test_every_local_static_reference_is_content_hashed():
    versions = compute_versions(STATIC)
    html = versioned_html(INDEX.read_text(encoding="utf-8"), versions)
    refs = VERSIONED_REF.findall(html)
    assert refs, "the served entry carries no versioned local asset"
    for url, digest in refs:
        rel = url.rsplit("/", 1)[-1]
        assert versions[rel] == digest, rel


def test_non_local_references_are_left_alone():
    versions = compute_versions(STATIC)
    out = versioned_html(INDEX.read_text(encoding="utf-8"), versions)
    # the host sheet (/padiem-themes.css) is not this app's asset to version
    assert "/padiem-themes.css?v=" not in out
    assert 'href="/padiem-themes.css"' in out


def test_versioning_is_idempotent():
    versions = compute_versions(STATIC)
    once = versioned_html(INDEX.read_text(encoding="utf-8"), versions)
    twice = versioned_html(once, versions)
    assert once == twice


def test_version_map_is_injected_for_the_dynamic_loaders():
    versions = compute_versions(STATIC)
    out = versioned_html(INDEX.read_text(encoding="utf-8"), versions)
    match = re.search(
        r'<script type="application/json" id="' + MAP_SCRIPT_ID + r'">(.*?)</script>',
        out, re.S)
    assert match, "the version map for the JS dynamic loaders is missing"
    carried = json.loads(match.group(1))
    for name in ("photo-resize.js", "pc-file-exchange.js", "pc-file-exchange.css"):
        expected = short_hash(canonical_asset_bytes((STATIC / name).read_bytes()))
        assert carried[name] == expected, name


def test_served_index_is_hashed_and_no_cache():
    client = TestClient(create_app())
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"
    versions = compute_versions(STATIC)
    refs = VERSIONED_REF.findall(res.text)
    assert refs, "the served entry carries no versioned local asset"
    for url, digest in refs:
        rel = url.rsplit("/", 1)[-1]
        assert versions[rel] == digest, rel
    assert MAP_SCRIPT_ID in res.text, "the version map must ride along for the JS loaders"


def test_static_answers_carry_the_long_immutable_cache():
    client = TestClient(create_app())
    for name in ("council-app.js", "council-app.css", "assets/speech-card.jpg"):
        res = client.get(f"/static/{name}")
        assert res.status_code == 200, name
        assert res.headers["cache-control"] == "public, max-age=31536000, immutable", name


def test_a_content_change_changes_the_version():
    html = INDEX.read_text(encoding="utf-8")
    before = versioned_html(html, {"council-app.js": "aaaaaaaa"})
    after = versioned_html(html, {"council-app.js": "bbbbbbbb"})
    assert "?v=aaaaaaaa" in before and "?v=aaaaaaaa" not in after
    assert "?v=bbbbbbbb" in after


def test_the_js_dynamic_loaders_use_the_served_map():
    js = (STATIC / "council-app.js").read_text(encoding="utf-8")
    assert "padiem-asset-versions" in js, "the JS never reads the served version map"
    assert js.count("versionedAsset(") >= 4, "photo-resize/pc-file-exchange must be versioned"
    for name in ("photo-resize.js", "pc-file-exchange.js", "pc-file-exchange.css"):
        assert f'./static/{name}"' in js, f"the bare local URL stays the fallback: {name}"


def test_the_bake_cli_is_idempotent():
    import subprocess
    import sys
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "static"
        shutil.copytree(STATIC, target)
        # The bake CLI must run in a fresh interpreter. Setting PYTHONPATH is not
        # enough: isolated interpreters (-E builds — the work PC's bundled python
        # is one, sys.flags.ignore_environment == 1) ignore the environment
        # entirely and safe-path builds skip cwd too, so `python -m
        # app.asset_versions` would import padiem-chat's editable `app` or fail
        # to find this one at all. The child is launched the flag-proof way: put
        # THIS app root at sys.path[0] before importing, then call the same
        # main() the ``python -m`` entry runs.
        bootstrap = ("import sys; sys.path.insert(0, sys.argv[1]); "
                     "from app.asset_versions import main; sys.exit(main(sys.argv[2:]))")
        script = [sys.executable, "-X", "utf8", "-c", bootstrap, str(APP_ROOT),
                  "--static-dir", str(target)]

        def run_cli(*extra):
            return subprocess.run(script + list(extra), cwd=str(APP_ROOT),
                                  capture_output=True, text=True, check=False)
        first = run_cli("--write")
        assert first.returncode == 0, first.stdout + first.stderr
        baked = (target / "index.html").read_text(encoding="utf-8")
        assert "?v=" in baked
        check = run_cli("--check")
        assert check.returncode == 0, check.stdout + check.stderr
        run_cli("--write")
        assert (target / "index.html").read_text(encoding="utf-8") == baked

def test_the_checked_in_entry_is_baked_and_current():
    """The production path serves this exact file verbatim: padiem-chat's
    local_cpython answers /apps/council/ with FileResponse(static/index.html)
    and a plain StaticFiles mount — nothing rewrites references there. So the
    checked-in entry must already carry the current content hashes; only the
    standalone app_factory entry rewrites at serve time. A static edit without
    a re-bake fails here, which is the contract that keeps every serving path
    (uvicorn app_factory, padiem-chat FileResponse, any static host) honest."""
    html = INDEX.read_text(encoding="utf-8")
    assert "?v=" in html, "the checked-in entry is not baked"
    assert MAP_SCRIPT_ID in html, "the checked-in entry carries no version map"
    drifted = versioned_html(html, compute_versions(STATIC))
    assert drifted == html, "baked hashes drifted from the current static files"
