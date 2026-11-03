"""#6724 2: the tutorial generator is deterministic and the recorder has a plan."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
REPO = TOOL_DIR.parents[1]
GENERATOR = TOOL_DIR / "build_tutorials.py"
CAPTURE = TOOL_DIR / "capture_guest_scenes.py"
HELP = REPO / "apps" / "padiem-chat" / "static" / "help.html"
PAGES = REPO / "apps" / "padiem-chat" / "static" / "help-tutorials"
HELP_LINK = 'href="./help-tutorials/index.html"'

sys.path.insert(0, str(TOOL_DIR))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generator = _load("build_tutorials", GENERATOR)
capture = _load("capture_guest_scenes", CAPTURE)

EXPECTED = [
    "01-first-visit.md",
    "02-pc-connection.md",
    "03-document-work.md",
    "04-bookai.md",
    "05-account-deletion.md",
    "07-external-ai-connect.md",
    "README.md",
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _section(document: str, heading: str) -> str:
    """One step section, up to the next heading or the media section."""

    start = document.index(heading) + len(heading)
    rest = document[start:]
    cuts = [rest.index(marker) for marker in ("### ", "\n## ", "\n---") if marker in rest]
    return rest[: min(cuts)] if cuts else rest


class GeneratedTutorials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # ``shots=None``: these tests never need the 1 MB recordings, only the
        # text the screenplays and the pages share.
        self.pages = self.root / "pages"
        self.files = generator.build(self.root / "docs", self.pages, None)
        self.text = {
            path.name: path.read_text(encoding="utf-8")
            for path in self.files
            if path.name != "README.md"
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_scenario_becomes_a_deterministic_document(self):
        documents = sorted(path.name for path in self.files if path.suffix == ".md")
        self.assertEqual(documents, EXPECTED)
        again = generator.build(self.root / "again", self.root / "again-pages", None)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.files},
            {path.name: path.read_bytes() for path in again},
        )
        self.assertIn("# ① 처음 온 사람", self.text["01-first-visit.md"])
        self.assertIn("**이렇게 해요:**", self.text["01-first-visit.md"])
        self.assertIn("**이렇게 보여요:**", self.text["01-first-visit.md"])

    def test_developer_vocabulary_never_reaches_the_reader(self):
        forbidden = (
            r"(?<![0-9])504(?![0-9])",
            r"(?<![A-Za-z])ms(?![A-Za-z])",
            r"\bGET\b",
            r"\bHTTP\b",
            r"\bJSON\b",
            r"\bAPI\b",
            "authenticated",
            "storage-state",
            "레인",
            "세션",
            "채트",
        )
        for name, text in self.text.items():
            for pattern in forbidden:
                self.assertIsNone(
                    re.search(pattern, text), f"{name} still contains {pattern!r}"
                )

    def test_account_steps_are_a_placeholder_not_an_invented_screen(self):
        document = self.text["01-first-visit.md"]
        step_one, rest = document.split("### 2단계", 1)
        self.assertNotIn(generator.PLACEHOLDER, step_one)
        self.assertIn(
            "asset://chat-tutorial/01-first-visit/step-01.png", step_one
        )
        # Step 4 was recorded with the owner's signed-in session; 5-6 stay slots.
        fourth = _section(document, "### 4단계")
        self.assertIn("step-04.png", fourth)
        self.assertNotIn(generator.PLACEHOLDER, fourth)
        for number in ("5단계", "6단계"):
            section = _section(document, f"### {number}")
            self.assertIn(generator.PLACEHOLDER, section)
            self.assertNotIn("/step-", section)

    def test_account_only_scenarios_keep_the_screen_slot(self):
        text = self.text["03-document-work.md"]
        self.assertIn(generator.PLACEHOLDER, text)
        self.assertNotIn("/step-", text)
        self.assertNotIn("](", text)
        self.assertIn("아직 촬영하지 않았습니다", text)
        # 05 steps 1-2 are recorded; step 3 (취소) is still a slot.
        five = self.text["05-account-deletion.md"]
        self.assertIn("step-01.png", five)
        self.assertIn("step-02.png", five)
        self.assertIn(generator.PLACEHOLDER, _section(five, "### 3단계"))

    def test_every_captured_step_ships_its_image(self):
        documents = generator.load_scenarios()
        assets = PAGES / "assets"
        present = (
            {path.relative_to(assets).as_posix() for path in assets.rglob("*.webp")}
            if assets.is_dir()
            else set()
        )
        self.assertTrue(generator.expected_assets(documents) <= present)
        for document in documents:
            page = (PAGES / f"{document['number']}-{document['slug']}.html").read_text(
                encoding="utf-8"
            )
            for step in document["steps"]:
                if step["number"] not in document["captured"]:
                    continue
                self.assertIn(f"step-{step['number']:02d}.webp", page, document["key"])
                self.assertNotIn(step["number"], document["guest"])

    def test_media_is_referenced_by_key_not_by_relative_path(self):
        document = self.text["04-bookai.md"]
        self.assertIn("asset://chat-tutorial/04-bookai/step-01.png", document)
        self.assertIn("asset://chat-tutorial/04-bookai/captions.vtt", document)
        self.assertNotRegex(document, r"!\[[^\]]*\]\((?!asset://)")

    def test_disaster_recovery_stays_out_of_the_user_help(self):
        for name, text in self.text.items():
            self.assertNotIn("06-disaster-recovery", text, name)
        self.assertNotIn("06-disaster-recovery.md", (self.root / "docs" / "README.md").read_text(encoding="utf-8"))

    def test_help_page_comparison_quotes_really_exist(self):
        help_text = _normalize(HELP.read_text(encoding="utf-8"))
        self.assertTrue(any(quote for _, quote, _ in generator.HELP_COMPARISON))
        for tutorial_phrase, quote, verdict in generator.HELP_COMPARISON:
            self.assertTrue(tutorial_phrase and verdict)
            if quote is not None:
                self.assertIn(_normalize(quote), help_text, tutorial_phrase)


class CommittedPages(unittest.TestCase):
    """What the repository ships, checked against the screenplays."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_committed_pages_match_the_screenplays(self):
        pages = self.root / "pages"
        generator.build(self.root / "docs", pages, None)
        for name in sorted(generator.expected_pages(generator.load_scenarios())):
            self.assertEqual((pages / name).read_bytes(), (PAGES / name).read_bytes(), name)

    def test_every_guest_step_has_one_image_within_the_size_budget(self):
        documents = generator.load_scenarios()
        assets = PAGES / "assets"
        present = {path.relative_to(assets).as_posix() for path in assets.rglob("*.webp")}
        self.assertEqual(present, generator.expected_assets(documents))
        self.assertGreater(len(present), 0)
        for name in sorted(present):
            size = (assets / name).stat().st_size
            self.assertGreater(size, 0, name)
            self.assertLessEqual(size, generator.MAX_IMAGE_BYTES, name)

    def test_pages_reference_their_images_and_the_help_page(self):
        for document in generator.load_scenarios():
            page = (PAGES / f"{document['number']}-{document['slug']}.html").read_text(
                encoding="utf-8"
            )
            self.assertIn('href="../help.html"', page, document["key"])
            self.assertIn('href="./index.html"', page, document["key"])
            # Same stylesheets as help.html: one theme, one place to change it.
            self.assertIn('href="../styles.css"', page, document["key"])
            self.assertIn('href="../help.css"', page, document["key"])
            self.assertIn('href="./tutorial.css"', page, document["key"])
            self.assertIn(
                'name="viewport" content="width=device-width, initial-scale=1"',
                page,
                document["key"],
            )
            self.assertNotIn("<script", page, document["key"])
            for number in document["guest"]:
                source = f"./assets/{document['key']}/step-{number:02d}.webp"
                self.assertIn(source, page, document["key"])
                self.assertTrue((PAGES / source[2:]).is_file(), source)

    def test_account_steps_keep_the_placeholder_on_the_page(self):
        page = (PAGES / "03-document-work.html").read_text(encoding="utf-8")
        self.assertIn(generator.PLACEHOLDER, page)
        self.assertNotIn("/step-", page)
        self.assertIn("아직 촬영하지 않았습니다", page)

    def test_video_slot_names_the_base_url_variable(self):
        page = (PAGES / "04-bookai.html").read_text(encoding="utf-8")
        self.assertIn("영상 준비 중", page)
        self.assertIn(generator.VIDEO_KEY_ENV, page)
        # No empty player: the recordings are not in the repository.
        self.assertNotIn("<video", page)
        self.assertNotIn(".webm\"", page)

    def test_check_flags_page_and_image_drift(self):
        docs, pages = self.root / "docs", self.root / "pages"
        generator.build(docs, pages, None)
        self.assertTrue(
            any(name.startswith("image:") for name in generator.check(docs, pages))
        )
        shutil.copytree(PAGES / "assets", pages / "assets")
        self.assertEqual(generator.check(docs, pages), [])

        page = pages / "04-bookai.html"
        page.write_text(
            page.read_text(encoding="utf-8").replace("영상 준비 중", "영상"), encoding="utf-8"
        )
        (pages / "assets" / "04-bookai" / "step-01.webp").unlink()
        (pages / "assets" / "99-extra").mkdir()
        (pages / "assets" / "99-extra" / "step-01.webp").write_bytes(b"not-an-image")
        (pages / "99-extra.html").write_text("x", encoding="utf-8")
        stale = generator.check(docs, pages)
        self.assertIn("page:04-bookai.html", stale)
        self.assertIn("image:04-bookai/step-01.webp", stale)
        self.assertIn("orphan_image:99-extra/step-01.webp", stale)
        self.assertIn("orphan_page:99-extra.html", stale)

    def test_the_published_pages_never_say_채트(self):
        texts = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(PAGES.glob("*.html"))
        }
        texts["README.md"] = (
            REPO / "docs" / "help" / "tutorials" / "README.md"
        ).read_text(encoding="utf-8")
        for name, text in texts.items():
            self.assertNotIn("채트", text, name)

    def test_the_external_ai_tutorial_keeps_the_pending_marker(self):
        help_text = HELP.read_text(encoding="utf-8")
        self.assertIn(f"<!-- {generator.PENDING_MARK}", help_text)
        readme = (REPO / "docs" / "help" / "tutorials" / "README.md").read_text(encoding="utf-8")
        self.assertIn(generator.PENDING_MARK, readme)
        page = (PAGES / "07-external-ai-connect.html").read_text(encoding="utf-8")
        self.assertIn(generator.PLACEHOLDER, page)
        self.assertNotIn("/step-", page)
        self.assertIn('href="../help.html#external-ai"', page)

    def test_the_account_tutorial_points_at_the_help_section(self):
        page = (PAGES / "05-account-deletion.html").read_text(encoding="utf-8")
        self.assertIn('href="../help.html#account"', page)
        document = (
            REPO / "docs" / "help" / "tutorials" / "05-account-deletion.md"
        ).read_text(encoding="utf-8")
        self.assertIn("#account", document)
        help_text = HELP.read_text(encoding="utf-8")
        self.assertIn('id="account"', help_text)
        self.assertIn('href="#account"', help_text)

    def test_the_help_page_links_to_the_tutorials_once(self):
        self.assertEqual(HELP.read_text(encoding="utf-8").count(HELP_LINK), 1)
        self.assertTrue((PAGES / "index.html").is_file())

    def test_the_ci_gate_commands_pass(self):
        # The workflow runs exactly these; a failure here is a red PR gate.
        done = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=str(REPO), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("tutorials_up_to_date", done.stdout)


class RecorderPlan(unittest.TestCase):
    def test_vtt_cues_follow_the_step_offsets(self):
        vtt = capture.build_vtt(
            [
                {"offset_ms": 0, "caption": "첫 화면에서 무엇을 물어볼지 시작해요."},
                {"offset_ms": 7500, "caption": "게스트 상태를 확인해요."},
            ]
        )
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:00.000 --> 00:00:07.500", vtt)
        self.assertIn("00:00:07.500 --> 00:00:12.500", vtt)
        self.assertIn("게스트 상태를 확인해요.", vtt)

    def test_dry_run_lists_steps_without_a_browser(self):
        done = subprocess.run(
            [sys.executable, str(CAPTURE), "--dry-run"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        plan = json.loads(done.stdout)
        self.assertEqual(plan["account_env"], "PADIEM_LIVE_STORAGE_STATE")
        self.assertIs(plan["account_env_set"], False)
        by_slug = {entry["scenario"]: entry for entry in plan["scenes"]}
        self.assertEqual(
            list(by_slug),
            [
                "01-first-visit",
                "02-pc-connection",
                "03-document-work",
                "04-bookai",
                "05-account-deletion",
                "07-external-ai-connect",
            ],
        )
        self.assertEqual(by_slug["01-first-visit"]["guest_steps"], [1, 2, 3])
        self.assertEqual(by_slug["01-first-visit"]["account_steps"], [4, 5, 6])
        self.assertEqual(
            [step["number"] for step in by_slug["01-first-visit"]["capture"]], [1, 2, 3]
        )
        self.assertEqual(
            [step["number"] for step in by_slug["04-bookai"]["capture"]], [1, 3]
        )
        self.assertEqual(by_slug["03-document-work"]["capture"], [])
        self.assertEqual(by_slug["05-account-deletion"]["capture"], [])
        # The external-AI connection has only signed-in steps, so it is never
        # recorded as a guest scene.
        self.assertEqual(by_slug["07-external-ai-connect"]["capture"], [])
        # The recorder must only promise scenes it actually drives.
        for entry in plan["scenes"]:
            guest = set(entry["guest_steps"])
            driven = {step["number"] for step in entry["capture"]}
            self.assertEqual(driven, guest, entry["scenario"])


if __name__ == "__main__":
    unittest.main()
