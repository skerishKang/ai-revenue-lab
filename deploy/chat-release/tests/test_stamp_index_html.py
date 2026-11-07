"""The asset stamper contracts: stamp a COPY, version every local reference,
leave external/data references and the repository file alone.

release_chat.ps1 stamps the deploy copy of index.html with the 8-char release
sha (wrangler --assets override) and the pages build reuses stampIndexHtml on
dist/; both depend on this CLI, so the tests drive the real Node process.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.resolve().parents[2]
STAMPER = HERE.parent / "stamp_index_html.mjs"
REPO_INDEX = REPO / "apps" / "padiem-chat" / "static" / "index.html"

VERSION = "ab12cd34"


def _node():
    import shutil as _shutil
    exe = _shutil.which("node") or _shutil.which("node.exe")
    if exe is None:
        raise unittest.SkipTest("no node runtime on this runner")
    return exe


def _run(*args):
    return subprocess.run(
        [_node(), str(STAMPER), *args], capture_output=True, text=True, timeout=120,
    )


class StampIndexHtmlContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stamp-index-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dir = self.tmp / "static"
        # The tree pass stamps JS/CSS literals too, so the fixture is the
        # whole static tree, not just the shell.
        shutil.copytree(REPO / "apps" / "padiem-chat" / "static", self.dir)
        self.index = self.dir / "index.html"

    def local_references(self, html):
        import re
        return [value for _tag, _quote, value in re.findall(
            r"(<(?:script|link)\b[^>]*?\b(?:src|href)=)([\"'])([^\"']+?)\2",
            html, flags=re.IGNORECASE)]

    def repo_file(self, *parts):
        return REPO.joinpath("apps", "padiem-chat", "static", *parts)

    def test_stamp_versions_every_local_reference_and_keeps_the_repo_file(self):
        repo_before = REPO_INDEX.read_bytes()
        result = _run(str(self.dir), VERSION)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("STAMPED=", result.stdout)
        self.assertIn("ASSET_REFS=", result.stdout)

        html = self.index.read_text(encoding="utf-8")
        refs = self.local_references(html)
        self.assertGreater(len(refs), 50, "the shell carries ~90 local asset references")
        local = [value for value in refs if not value.startswith(("data:", "http:", "https:", "//"))]
        self.assertTrue(local, "index.html references local assets")
        for value in local:
            self.assertTrue(value.endswith(f"?v={VERSION}"), value)
        # External references stay exactly as written.
        for value in refs:
            if value.startswith(("data:", "http:", "https:", "//")):
                self.assertNotIn("?v=", value, value)
        # The repository original is untouched.
        self.assertEqual(REPO_INDEX.read_bytes(), repo_before)
        self.assertNotIn("?v=", REPO_INDEX.read_text(encoding="utf-8"))

    def test_js_literals_that_load_static_files_carry_the_same_version(self):
        _run(str(self.dir), VERSION)
        stamped = {
            name: self.dir.joinpath(name).read_text(encoding="utf-8")
            for name in ("a11y.js", "theme-init.js", "util-pdfmd.js",
                         "b66-quote-runtime.js", "claw-web-xlsx-sources.js",
                         "claw-push.js", "message-lifecycle.js",
                         "product-capabilities.js")
        }
        self.assertIn(f'interactionPolish.src = "./interaction-polish.js?v={VERSION}"',
                      stamped["a11y.js"])
        self.assertIn(f'motion.src="./conversation-motion.js?v={VERSION}"',
                      stamped["theme-init.js"])
        self.assertIn(f'gl.href="./padiem-glass.css?v={VERSION}"', stamped["theme-init.js"])
        self.assertIn(f'const PC_EXCHANGE_SCRIPT = "./pc-file-exchange.js?v={VERSION}"',
                      stamped["b66-quote-runtime.js"])
        self.assertIn(f'const PADIEM_PUSH_SW_PATH = "/push-sw.js?v={VERSION}"',
                      stamped["claw-push.js"])
        self.assertIn(f'link.href = "./capability-presentation.css?v={VERSION}"',
                      stamped["message-lifecycle.js"])
        self.assertIn(f'link.href = "./mode-presentation.css?v={VERSION}"',
                      stamped["product-capabilities.js"])
        # The dedupe querySelector must gain the same version as the
        # assignment or the stylesheet would be re-injected on every call.
        dedupe = stamped["util-pdfmd.js"]
        self.assertEqual(dedupe.count(f'"./pc-file-exchange.css?v={VERSION}"'), 2,
                         "querySelector check and href assignment must agree")
        self.assertIn(f'script.src = "./pc-file-exchange.js?v={VERSION}"', dedupe)
        # API-only files carry no asset literals and stay byte-identical.
        for name in ("chat-transport.js", "locale.js"):
            self.assertEqual(
                self.dir.joinpath(name).read_bytes(),
                self.repo_file(name).read_bytes(), name,
            )

    def test_css_imports_and_urls_carry_the_same_version(self):
        _run(str(self.dir), VERSION)
        cinematic = self.dir.joinpath("padiem-cinematic-chat.css").read_text(encoding="utf-8")
        for name in ("padiem-foundation", "padiem-surfaces", "padiem-editorial", "padiem-rich",
                     "padiem-first-use", "padiem-bright-readability",
                     "padiem-glass-brand-polish", "padiem-glass-gutter-alignment"):
            self.assertIn(f"@import url('./{name}.css?v={VERSION}')", cinematic, name)
        sidebar = self.dir.joinpath("sidebar-utility.css").read_text(encoding="utf-8")
        self.assertIn(f'@import url("./accessibility-polish.css?v={VERSION}")', sidebar)
        portrait = self.dir.joinpath("padiem-glass-portrait.css").read_text(encoding="utf-8")
        self.assertEqual(portrait.count(f'url("./assets/padiem-glass-female.jpg?v={VERSION}")'), 2)
        self.assertIn(f'url("./assets/padiem-glass-male.jpg?v={VERSION}")', portrait)
        self.assertIn(f'url("./assets/padiem-glass-female-shell.jpg?v={VERSION}")', portrait)
        # External CDN imports and comment examples without a real target file
        # stay exactly as written.
        foundation = self.dir.joinpath("padiem-foundation.css").read_text(encoding="utf-8")
        self.assertNotIn("?v=", foundation)
        glass = self.dir.joinpath("padiem-glass.css").read_text(encoding="utf-8")
        self.assertNotIn("?v=", glass)
        self.assertIn('url("./assets/your-image.webp")', glass)

    def test_stamped_javascript_still_parses(self):
        """The stamped deploy copies must stay valid JavaScript: node --check
        every .js the tree pass rewrote, plus the major entries, so a regex
        slip in the literal stamper can never ship a broken app.js."""
        _run(str(self.dir), VERSION)
        major = ("app.js", "locale.js", "chat-transport.js")
        for js in sorted(self.dir.rglob("*.js")):
            relative = js.relative_to(self.dir).as_posix()
            repo_counterpart = self.repo_file(relative)
            changed = (not repo_counterpart.exists()
                       or js.read_bytes() != repo_counterpart.read_bytes())
            if not (changed or relative in major):
                continue
            result = subprocess.run(
                [_node(), "--check", str(js)], capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, f"{relative}: {result.stderr[-500:]}")
        # The rewrite actually touched the lazy loaders this guards.
        self.assertTrue(
            self.dir.joinpath("a11y.js").read_bytes()
            != self.repo_file("a11y.js").read_bytes(),
            "a11y.js must be among the stamped files",
        )

    def test_restamping_the_same_version_is_idempotent(self):
        self.assertEqual(_run(str(self.dir), VERSION).returncode, 0)
        first = self.index.read_bytes()
        self.assertEqual(_run(str(self.dir), VERSION).returncode, 0)
        self.assertEqual(self.index.read_bytes(), first)

    def test_check_passes_when_stamped_and_fails_when_not(self):
        self.assertEqual(_run("--check", str(self.dir), VERSION).returncode, 2)
        self.assertEqual(_run(str(self.dir), VERSION).returncode, 0)
        self.assertEqual(_run("--check", str(self.dir), VERSION).returncode, 0)

    def test_rejects_an_unsafe_version_and_a_missing_file(self):
        bad = _run(str(self.dir), 'x"><script>')
        self.assertNotEqual(bad.returncode, 0)
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertNotEqual(_run(str(empty), VERSION).returncode, 0)

    def test_release_script_stamps_a_copy_and_ships_it(self):
        """The release wiring: stamp the extracted copy, ship it via the
        wrangler --assets override, pin the step 5 hashes to it, and feed the
        pages build the same version — the repository static tree is never
        the stamp target."""
        text = (HERE.parent / "release_chat.ps1").read_text(encoding="utf-8")
        self.assertIn("stamp_index_html.mjs", text)
        # The extracted pages build imports the stamper from deploy/; the
        # running script ships its own copy into the extraction (the archive
        # pins the SHA, which carries no stamper until this PR is on main).
        self.assertIn('Copy-Item $Script:Stamper (Join-Path $tmpRoot "deploy/chat-release/stamp_index_html.mjs") -Force', text)
        self.assertIn("Copy-Item $shaStaticDir $stampStaticDir -Recurse", text)
        self.assertIn("& node $Script:Stamper $stampStaticDir $assetVersion", text)
        self.assertIn("wrangler deploy --keep-vars --assets $stampStaticDir", text)
        self.assertIn("Join-Path $stampStaticDir $asset", text)
        self.assertIn("$env:PADIEM_ASSET_VERSION = $assetVersion", text)
        self.assertNotIn("& node $Script:Stamper $staticDir", text)


if __name__ == "__main__":
    unittest.main()
