"""#6724 2차: 튜토리얼 초안 생성기·가리기 시험.

브라우저를 띄우지 않고 순수 함수만 부른다. 문서는 실제 캡처 파일이 있을 때만
단계를 넣고, 실패한 흐름은 문서를 만들지 않는다(색인에만 "이번 실행 실패").

실행:
    python -m pytest .github/tests/test_daily_usage_tutorial_261112.py -q
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import daily_usage_browser_checks as checks  # noqa: E402


def _payload(verdict="PASS", captures=None, elapsed_ms=1500, entry_ms=700, answer_ms=600):
    return {
        "verdict": verdict,
        "captures": captures if captures is not None else [
            "browser_chat_01_open.png",
            "browser_chat_02_question.png",
            "browser_chat_03_answer.png",
        ],
        "elapsed_ms": elapsed_ms,
        "entry_ms": entry_ms,
        "answer_ms": answer_ms,
    }


class TutorialScriptTest(unittest.TestCase):
    def test_every_browser_flow_has_three_named_korean_steps(self):
        for flow in ("browser_chat", "browser_claw", "browser_shared_login"):
            steps = checks.TUTORIAL_STEPS[flow]
            self.assertEqual([step[0] for step in steps], [1, 2, 3], flow)
            for _, slug, title, description in steps:
                self.assertTrue(slug, flow)
                self.assertRegex(title, r"[가-힣]", flow)
                self.assertRegex(description, r"[가-힣]", flow)

    def test_stamp_only_flow_has_no_tutorial(self):
        self.assertNotIn("browser_stamp", checks.TUTORIAL_STEPS)


class TutorialMarkdownTest(unittest.TestCase):
    def test_markdown_lists_steps_images_and_elapsed(self):
        doc = checks.tutorial_markdown("browser_chat", "PASS", _payload()["captures"],
                                       1500, 700, 600)
        self.assertIsNotNone(doc)
        self.assertIn("# Chat으로 질문하고 답 받기", doc)
        self.assertIn("## 1. Chat 첫 화면", doc)
        self.assertIn("## 2. 질문 입력", doc)
        self.assertIn("## 3. 답변 표시", doc)
        self.assertIn("![질문 입력](./browser_chat_02_question.png)", doc)
        self.assertIn("전체: 1500 ms", doc)
        self.assertIn("화면 진입: 700 ms", doc)
        self.assertIn("질문에서 답까지: 600 ms", doc)

    def test_missing_capture_drops_that_step_only(self):
        doc = checks.tutorial_markdown(
            "browser_chat", "PASS", ["browser_chat_01_open.png"])
        self.assertIsNotNone(doc)
        self.assertIn("## 1. Chat 첫 화면", doc)
        self.assertNotIn("질문 입력", doc)
        self.assertNotIn("browser_chat_02_question.png", doc)

    def test_failed_flow_has_no_document(self):
        self.assertIsNone(checks.tutorial_markdown(
            "browser_chat", "FAIL", _payload(verdict="FAIL")["captures"]))

    def test_skipped_flow_has_no_document(self):
        self.assertIsNone(checks.tutorial_markdown(
            "browser_claw", "SKIPPED", ["browser_claw_01_open.png"]))


class WriteTutorialsTest(unittest.TestCase):
    def test_writes_docs_for_pass_and_only_a_line_for_fail(self):
        payloads = {
            "browser_chat": _payload(),
            "browser_claw": _payload(
                verdict="FAIL",
                captures=["browser_claw_01_open.png"],
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            written = checks.write_tutorials(payloads, out)
            self.assertIn("tutorial-browser_chat.md", written)
            self.assertNotIn("tutorial-browser_claw.md", written)
            self.assertIn("tutorial-index.md", written)
            self.assertTrue((out / "tutorial-browser_chat.md").is_file())
            self.assertFalse((out / "tutorial-browser_claw.md").exists())
            index = (out / "tutorial-index.md").read_text(encoding="utf-8")
            self.assertIn("(./tutorial-browser_chat.md)", index)
            self.assertIn("browser_claw: 이번 실행 실패", index)
            self.assertNotIn("tutorial-browser_claw.md", index)


class MaskScriptTest(unittest.TestCase):
    def test_mask_blurs_account_and_history_titles(self):
        script = checks._MASK_SCRIPT
        self.assertIn("blur(7px)", script)
        self.assertIn("accountName", script)
        self.assertIn("@", script)  # 이메일 모양 텍스트
        self.assertIn("#historyList .history-row", script)
        # 목록이 마스킹 뒤 늦게 그려져도 가려지도록 컨테이너 자체를 칠한다.
        self.assertIn("getElementById('historyList')", script)

    def test_mask_changes_appearance_only(self):
        script = checks._MASK_SCRIPT
        self.assertNotIn("display", script)
        self.assertNotIn("visibility", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
