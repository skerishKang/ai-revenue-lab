"""#6724 2: the tutorial generator is deterministic and the recorder has a plan."""
from __future__ import annotations

import importlib.util
import json
import re
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
        self.files = generator.build(self.root / "docs")
        self.text = {
            path.name: path.read_text(encoding="utf-8")
            for path in self.files
            if path.name != "README.md"
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_scenario_becomes_a_deterministic_document(self):
        self.assertEqual(sorted(path.name for path in self.files), EXPECTED)
        again = generator.build(self.root / "again")
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
        for number in ("4단계", "5단계", "6단계"):
            section = _section(document, f"### {number}")
            self.assertIn(generator.PLACEHOLDER, section)
            self.assertNotIn("/step-", section)

    def test_account_only_scenarios_keep_the_screen_slot(self):
        for name in ("03-document-work.md", "05-account-deletion.md"):
            text = self.text[name]
            self.assertIn(generator.PLACEHOLDER, text)
            self.assertNotIn("/step-", text)
            self.assertNotIn("](", text)
            self.assertIn("아직 촬영하지 않았습니다", text)

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
        # The recorder must only promise scenes it actually drives.
        for entry in plan["scenes"]:
            guest = set(entry["guest_steps"])
            driven = {step["number"] for step in entry["capture"]}
            self.assertEqual(driven, guest, entry["scenario"])


if __name__ == "__main__":
    unittest.main()
