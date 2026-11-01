"""#5937: the 의원3종 entry is served from the Chat Worker's own origin path.

`apps/padiem-council-apps/static/` stays the single source of truth (LOCAL 2 owns
it). The Chat deploy assembles it into the generated bundle that Cloudflare's
Assets binding uploads, so `https://chat.padiem.net/apps/council/` serves the app
without copying a file into `apps/padiem-chat/**`, without a second Worker and
without a route in the Chat ASGI app.

These tests pin the parts that a live 404 would otherwise be the only way to
find: the staged layout has to match the app's own URL layout, because the entry
page references its assets relatively (`./static/council-app.css`), so one wrong
directory level renders a page with no CSS and no JS.
"""

from __future__ import annotations

from functools import lru_cache
import importlib.util
from pathlib import Path
import re
import shutil

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
COUNCIL_STATIC = REPO / "apps/padiem-council-apps" / "static"

spec = importlib.util.spec_from_file_location(
    "b62_app_entry_staging", ROOT / "scripts" / "build_b66_worker_dependencies.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

ENTRY_PREFIX = "apps/council"
#: The app's own layout (app/app_factory.py): the entry page is served at "/" and
#: everything else under "/static/*". Under the Chat prefix that is the whole static
#: tree - since #6065 S6 it also carries the design's photography and self-hosted
#: faces, so the list is written out rather than derived: an unexpected file reaching
#: the bundle has to fail here, not appear in Production.
STAGED_PATHS = {
    f"{ENTRY_PREFIX}/static/assets/ATTRIBUTION.md",
    f"{ENTRY_PREFIX}/static/assets/fonts/LICENSE-MaruBuri-NAVER.txt",
    f"{ENTRY_PREFIX}/static/assets/fonts/LICENSE-PlayfairDisplay-OFL-1.1.txt",
    f"{ENTRY_PREFIX}/static/assets/fonts/LICENSE-Pretendard-OFL-1.1.txt",
    f"{ENTRY_PREFIX}/static/assets/fonts/MaruBuri-Bold.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/MaruBuri-Regular.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/PlayfairDisplay-Bold-latin.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/Pretendard-Bold.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/Pretendard-Medium.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/Pretendard-Regular.woff2",
    f"{ENTRY_PREFIX}/static/assets/fonts/Pretendard-SemiBold.woff2",
    f"{ENTRY_PREFIX}/static/assets/IMAGE-SLOTS.md",
    f"{ENTRY_PREFIX}/static/assets/meeting-card.jpg",
    f"{ENTRY_PREFIX}/static/assets/parliament-fr-hero.jpg",
    f"{ENTRY_PREFIX}/static/assets/parliament-hero.jpg",
    f"{ENTRY_PREFIX}/static/assets/parliament-uk-hero.jpg",
    f"{ENTRY_PREFIX}/static/assets/parliament-us-hero.jpg",
    f"{ENTRY_PREFIX}/static/assets/sns-card.jpg",
    f"{ENTRY_PREFIX}/static/assets/speech-card.jpg",
    f"{ENTRY_PREFIX}/static/council-app.css",
    f"{ENTRY_PREFIX}/static/council-app.js",
    # 2026-11-01: the council app ships its own browser photo resizer and its
    # own copy of the PC file exchange (same rule as this app's copies).
    f"{ENTRY_PREFIX}/static/pc-file-exchange.css",
    f"{ENTRY_PREFIX}/static/pc-file-exchange.js",
    f"{ENTRY_PREFIX}/static/photo-resize.js",
    # 2026-11-01: #6589 builds the 한글(HWPX)·워드(DOCX) downloads in the browser,
    # so the export module is a real app asset the entry loads on demand.
    f"{ENTRY_PREFIX}/static/document-export.js",
    # 2026-11-02: #6620 — 축사·SNS 참고 글 'PC에서 가져오기'가 문서를 tus로 올리므로
    # 의원 앱이 Chat과 같은 업로드 모듈 사본을 싣는다.
    f"{ENTRY_PREFIX}/static/project-file-upload.js",
    f"{ENTRY_PREFIX}/static/tus-upload.js",
    f"{ENTRY_PREFIX}/index.html",
}

@lru_cache(maxsize=None)
def staged_map() -> dict[str, Path]:
    bundle = builder.APP_ENTRY_BUNDLES[0]
    return builder.app_entry_files(Path(bundle["source"]), bundle["prefix"],
                                   bundle["entry"], bundle["required"])


def test_council_entry_maps_to_the_url_the_entry_page_references() -> None:
    assert staged_map().keys() == STAGED_PATHS
    # The source of truth is the app's directory, never a copy inside the Chat app.
    assert staged_map()[f"{ENTRY_PREFIX}/index.html"] == COUNCIL_STATIC / "index.html"


def test_no_app_file_is_duplicated_into_the_chat_static_tree() -> None:
    for name in ("council-app.js", "council-app.css"):
        assert not (ROOT / "static" / name).exists(), f"{name} must stay in the app"
    assert not (ROOT / "static" / ENTRY_PREFIX).exists(), (
        "a committed copy under apps/padiem-chat/static would be a second source of truth"
    )


def test_entry_page_root_absolute_chat_references_exist() -> None:
    """The entry borrows Chat's design system by reference, so a Chat rename or
    deletion must fail CI here rather than serve the app without its tokens."""
    html = (COUNCIL_STATIC / "index.html").read_text(encoding="utf-8")
    borrowed = re.findall(r'href="(/[^"?#]+\.(?:css|js))"', html)
    assert borrowed, "the entry must borrow a Chat stylesheet rather than restate tokens"
    for reference in borrowed:
        assert (ROOT / "static" / reference.lstrip("/")).is_file(), reference
    # The Google entry is the server's own route, not a static asset.
    factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    for target in re.findall(r'href="(/auth/[^"]+)"', html):
        assert f'Route("{target.split("?")[0]}"' in factory, target


def test_every_relative_reference_of_the_entry_page_resolves_in_the_staged_tree() -> None:
    html = (COUNCIL_STATIC / "index.html").read_text(encoding="utf-8")
    # Only the same-directory relative form matters: "/" would be a second
    # authority path and "../" would leave the entry directory.
    references = re.findall(r'(?:src|href)="(\./[^"]+)"', html)
    assert references, "the entry page must load its own css/js"
    destinations = staged_map()
    for reference in references:
        # 2026-11-01: the entry's local references carry a ?v=<content hash>
        # (council PR #6574). The query picks a version, not a path — the staged
        # tree, and the Assets/StaticFiles serving it, key on the bare path.
        served = reference[len("./"):].split("?", 1)[0]
        assert f"{ENTRY_PREFIX}/{served}" in destinations, (
            f"{reference} is referenced by the page but staged nowhere, so it would 404")
    # Measured live 2026-10-27: href="../" on this page resolved to /apps/ (404),
    # because the entry sits two levels down. Navigation out of the entry must be
    # root-absolute to stay depth-independent.
    escaping = re.findall(r'(?:src|href)="(\.\./[^"]*)"', html)
    assert escaping == [], f"references leaving the entry directory: {escaping}"


def test_generated_bundle_stages_the_app_byte_for_byte(tmp_path) -> None:
    app_root = tmp_path / "chat"
    (app_root / "app").mkdir(parents=True)
    (app_root / "static").mkdir()
    (app_root / "worker.py").write_bytes(b"worker\n")
    (app_root / "static" / "index.html").write_bytes(b"<main>chat</main>\n")

    result = builder.generate_runtime(app_root)
    runtime = Path(result["runtime"])
    assert result["app_entry_paths"] == sorted(f"static/{p}" for p in STAGED_PATHS)
    for staged, source in staged_map().items():
        copied = runtime / "static" / staged
        assert copied.is_file(), staged
        assert copied.read_bytes() == source.read_bytes(), staged
    # Chat's own entry is untouched by the staging.
    assert (runtime / "static" / "index.html").read_bytes() == b"<main>chat</main>\n"


def test_staging_refreshes_from_the_app_source_on_every_build(tmp_path, monkeypatch) -> None:
    app_static = tmp_path / "app-static"
    app_static.mkdir()
    (app_static / "index.html").write_bytes(b"<main>one</main>\n")
    (app_static / "council-app.js").write_bytes(b"one\n")
    (app_static / "council-app.css").write_bytes(b"one\n")
    monkeypatch.setattr(builder, "APP_ENTRY_BUNDLES", (
        {"app": "council", "source": app_static, "prefix": ENTRY_PREFIX,
         "entry": "index.html",
         "required": ("index.html", "council-app.js", "council-app.css")},
    ))
    app_root = tmp_path / "chat"
    (app_root / "app").mkdir(parents=True)
    (app_root / "static").mkdir()
    (app_root / "worker.py").write_bytes(b"worker\n")
    (app_root / "static" / "index.html").write_bytes(b"<main>chat</main>\n")

    runtime = Path(builder.generate_runtime(app_root)["runtime"])
    staged_css = runtime / "static" / f"{ENTRY_PREFIX}/static/council-app.css"
    assert staged_css.read_bytes() == b"one\n"
    # The app edits its own file; the next build must carry it, with nothing in
    # apps/padiem-chat/** to update in step.
    (app_static / "council-app.css").write_bytes(b"two\n")
    builder.generate_runtime(app_root)
    assert staged_css.read_bytes() == b"two\n"


def test_app_entry_must_not_overwrite_a_chat_asset(tmp_path, monkeypatch) -> None:
    app_static = tmp_path / "app-static"
    app_static.mkdir()
    (app_static / "index.html").write_bytes(b"<main>app</main>\n")
    monkeypatch.setattr(builder, "APP_ENTRY_BUNDLES", (
        {"app": "council", "source": app_static, "prefix": "admin",
         "entry": "index.html", "required": ("index.html",)},
    ))
    runtime = tmp_path / "runtime"
    (runtime / "static" / "admin").mkdir(parents=True)
    (runtime / "static" / "admin" / "index.html").write_bytes(b"<main>chat admin</main>\n")
    try:
        builder.stage_app_entries(runtime)
    except ValueError as error:
        assert "overwrite a Chat asset" in str(error)
    else:
        raise AssertionError("an app entry that shadows a Chat asset must fail the build")


def test_incomplete_or_missing_app_source_fails_the_build(tmp_path, monkeypatch) -> None:
    app_static = tmp_path / "app-static"
    app_static.mkdir()
    (app_static / "index.html").write_bytes(b"<main>app</main>\n")
    monkeypatch.setattr(builder, "APP_ENTRY_BUNDLES", (
        {"app": "council", "source": app_static, "prefix": ENTRY_PREFIX,
         "entry": "index.html", "required": ("index.html", "council-app.js")},
    ))
    try:
        builder.stage_app_entries(tmp_path / "runtime")
    except ValueError as error:
        assert "incomplete" in str(error), error
    else:
        raise AssertionError("a missing app file must fail the build closed")

    monkeypatch.setitem(builder.APP_ENTRY_BUNDLES[0], "source", app_static.parent / "gone")
    try:
        builder.stage_app_entries(tmp_path / "runtime")
    except ValueError as error:
        assert "directory is missing" in str(error), error
    else:
        raise AssertionError("an absent app source must fail the build closed")


def test_entry_is_never_mounted_as_a_second_asgi_path() -> None:
    """The Chat Worker keeps a runtime StaticFiles mount for its own directory,
    but an app prefix mounted there would resolve differently locally and in the
    deployed bundle. Assets is the only serving path for the entry."""
    factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert "padiem-council-apps" not in factory
    assert f'Mount("/{ENTRY_PREFIX}"' not in factory


def test_assets_are_uploaded_from_the_generated_bundle() -> None:
    """The pairing that lets the entry reach Production at all.

    `base_dir` is applied to `main` but NOT to `[assets] directory`: measured on the
    2026-10-27 deploy, `directory = "static"` made wrangler read
    `apps/padiem-chat/static` (162 entries = 158 files + 4 directories), so a file the
    build staged into the generated bundle was uploaded neither as an Asset nor as a
    Python module (that bundle carries .html only). The two paths must name the same
    tree, resolved the way wrangler resolves it.
    """
    import tomllib

    config = tomllib.loads((ROOT / "wrangler.toml").read_text(encoding="utf-8"))
    assert config["base_dir"] == builder.RUNTIME_DIRECTORY
    assert config["assets"]["directory"] == f"{builder.RUNTIME_DIRECTORY}/static"
    assert config["assets"]["binding"] == "ASSETS"
    assert (ROOT / config["assets"]["directory"]).as_posix().endswith(
        f"{builder.RUNTIME_DIRECTORY}/static")


def test_generated_bundle_is_a_superset_of_the_source_assets(tmp_path) -> None:
    """Pointing Assets at the bundle may not drop one existing Chat asset: every file
    under apps/padiem-chat/static must reach the bundle byte for byte, entry included."""
    import hashlib

    def listing(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()
        }

    source_static = ROOT / "static"
    app_root = tmp_path / "chat"
    (app_root / "app").mkdir(parents=True)
    (app_root / "worker.py").write_bytes(b"worker\n")
    shutil.copytree(source_static, app_root / "static")

    runtime = Path(builder.generate_runtime(app_root)["runtime"])
    source, generated = listing(source_static), listing(runtime / "static")
    assert source, "the Chat assets must be enumerable"
    assert set(source) <= set(generated), sorted(set(source) - set(generated))
    assert all(generated[name] == digest for name, digest in source.items())
    assert set(generated) - set(source) == STAGED_PATHS


def test_the_staged_tree_serves_the_entry_page_at_its_ordered_path(tmp_path) -> None:
    """Real request/response over the same static-serving machinery Chat uses
    (`StaticFiles(html=True)`), so a wrong directory level is caught here instead
    of as an unstyled page in Production."""
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_bytes(b"<main>chat</main>\n")
    staged = builder.stage_app_entries(tmp_path)
    assert set(staged) == {f"static/{p}" for p in STAGED_PATHS}

    app = Starlette(routes=[])
    app.mount("/", StaticFiles(directory=str(tmp_path / "static"), html=True))
    client = TestClient(app)

    entry = client.get(f"/{ENTRY_PREFIX}/")
    assert entry.status_code == 200, entry.status_code
    assert "PADIEM 의원3종" in entry.text
    for reference in re.findall(r'(?:src|href)="(\./[^"]+)"', entry.text):
        url = f"/{ENTRY_PREFIX}/{reference[len('./'):]}"
        asset = client.get(url)
        assert asset.status_code == 200, f"{url} -> {asset.status_code}"
    # the sheet's own url() targets are the photography and the faces; a path one directory
    # level off paints an unstyled page in Production and 404s here
    css = client.get(f"/{ENTRY_PREFIX}/static/council-app.css")
    assert css.status_code == 200
    sheet_urls = [target for target in re.findall(r'url\(\s*"([^"]+)"', css.text)
                  if not target.startswith("data:")]
    assert len(sheet_urls) >= 10, len(sheet_urls)
    for target in sheet_urls:
        url = f"/{ENTRY_PREFIX}/static/{target[len('./'):]}"
        asset = client.get(url)
        assert asset.status_code == 200, f"{url} -> {asset.status_code}"
    # Chat's own surface is unchanged by the entry.
    assert client.get("/").status_code == 200
