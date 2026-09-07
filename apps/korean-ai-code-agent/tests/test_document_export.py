from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from kagent.cli import main, parser
from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
from kagent.document_export import (
    HWPX_EXPORT_DECISION,
    LEGACY_HWP_EXPORT_DECISION,
    SUPPORTED_DOCUMENT_FORMATS,
    DocumentExportError,
    escape_xml,
    export_outcome_to_file,
    generate_docx_bytes,
)
from kagent.draft_flow import run_draft_command
from kagent.order_flow import run_order_command
from kagent.p01_adapter import ClawOrchestrationOutcome


class StubAdapter:
    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or ["초안 응답"])
        self.call_count = 0

    async def execute(self, run):
        self.call_count += 1
        run.transition(ClawRunStatus.PREPARING, summary="준비")
        run.transition(ClawRunStatus.RUNNING, summary="실행")
        run.transition(ClawRunStatus.COMPLETED, summary="완료")
        ans = self.answers.pop(0) if self.answers else "초안 응답"
        return ClawOrchestrationOutcome(
            projection=RunProjection(
                run_id=run.run_id,
                task_id=run.intent.task_id,
                status=ClawRunStatus.COMPLETED,
                execution_mode=ExecutionMode.LOCAL,
            ),
            answer=ans,
            p01_run_id=f"stub_run_{self.call_count:03d}",
            p01_event_count=1,
        )


class DocumentExportTests(unittest.TestCase):
    def test_xml_escaping(self) -> None:
        self.assertEqual(escape_xml("일반 텍스트"), "일반 텍스트")
        self.assertEqual(escape_xml("<tag> & 'quote' \"double\""), "&lt;tag&gt; &amp; &apos;quote&apos; &quot;double&quot;")

    def test_generate_docx_bytes_valid_ooxml(self) -> None:
        raw_bytes = generate_docx_bytes(
            title="견적서 초안 보고서",
            metadata_fields=[("저장소", "test/repo"), ("거래처", "㈜한빛상사")],
            section_title="견적서 초안 (DRAFT)",
            body_text="견적서 내용 본문입니다.\n특이조건: 부가세 별도.",
            table_headers=("품명", "수량", "단가", "금액"),
            table_rows=[("산업용 팬", "3", "500000", "1500000"), ("합계", "", "", "1500000")],
            footer_text="검증 완료 푸터",
        )
        self.assertTrue(len(raw_bytes) > 0)

        # Verify as valid zip package
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
            namelist = zf.namelist()
            self.assertIn("[Content_Types].xml", namelist)
            self.assertIn("_rels/.rels", namelist)
            self.assertIn("word/document.xml", namelist)

            doc_xml = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("견적서 초안 보고서", doc_xml)
            self.assertIn("㈜한빛상사", doc_xml)
            self.assertIn("산업용 팬", doc_xml)
            self.assertIn("1500000", doc_xml)
            self.assertIn("부가세 별도.", doc_xml)

    def test_export_outcome_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            md_out = tmp / "draft.md"
            docx_out = tmp / "draft.docx"

            # 1. MD format
            export_outcome_to_file(
                out_path=md_out,
                file_format="md",
                title="제목",
                metadata_fields=[("키", "값")],
                section_title="섹션",
                body_text="본문",
                items=[("아이템", "1", "100", "100")],
                total="100",
                markdown_fallback_text="# 마크다운 내용\n",
            )
            self.assertTrue(md_out.exists())
            self.assertEqual(md_out.read_text(encoding="utf-8"), "# 마크다운 내용\n")

            # 2. DOCX format
            export_outcome_to_file(
                out_path=docx_out,
                file_format="docx",
                title="제목",
                metadata_fields=[("키", "값")],
                section_title="섹션",
                body_text="본문",
                items=[("아이템", "1", "100", "100")],
                total="100",
                markdown_fallback_text="# 마크다운 내용\n",
            )
            self.assertTrue(docx_out.exists())
            with zipfile.ZipFile(docx_out, "r") as zf:
                self.assertIn("word/document.xml", zf.namelist())

            # 3. HWPX documented decision fails closed
            with self.assertRaises(DocumentExportError) as ctx:
                export_outcome_to_file(
                    out_path=tmp / "draft.hwpx",
                    file_format="hwpx",
                    title="제목",
                    metadata_fields=[],
                    section_title="섹션",
                    body_text="본문",
                    items=[],
                    total="0",
                    markdown_fallback_text="",
                )
            self.assertIn("HWPX export is deferred", ctx.exception.safe_message)

            # 4. Legacy HWP fails closed
            with self.assertRaises(DocumentExportError) as ctx:
                export_outcome_to_file(
                    out_path=tmp / "draft.hwp",
                    file_format="hwp",
                    title="제목",
                    metadata_fields=[],
                    section_title="섹션",
                    body_text="본문",
                    items=[],
                    total="0",
                    markdown_fallback_text="",
                )
            self.assertIn("legacy HWP binary format is unsupported", ctx.exception.safe_message)

    def test_cli_parser_format_flag(self) -> None:
        p = parser()
        args = p.parse_args(["repo", "draft", "input.md", "--doc-type", "견적서", "--format", "docx"])
        self.assertEqual(args.doc_format, "docx")

        args = p.parse_args(["repo", "order", "quote.md", "--accept", "--format", "hwpx"])
        self.assertEqual(args.doc_format, "hwpx")

    def test_draft_flow_docx_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "context.md").write_text("# 거래\n품목: 기기 1대 1000원\n", encoding="utf-8")
            out_docx = repo / "out.docx"
            phase1_ans = "품목:\n- 품명: 기기 | 수량: 1 | 단가: 1000\n"
            adapter = StubAdapter(answers=[phase1_ans, "초안 작성 완료"])

            code = run_draft_command(
                repo,
                "context.md",
                "견적서",
                adapter=adapter,
                out_path=out_docx,
                doc_format="docx",
            )
            self.assertEqual(code, 0)
            self.assertTrue(out_docx.exists())
            with zipfile.ZipFile(out_docx, "r") as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("견적서 초안", doc_xml)
                self.assertIn("초안 작성 완료", doc_xml)

    def test_order_flow_docx_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            quote_content = (
                "# 견적서 보고서\n\n"
                "## 산출 근거 (플로우 계산)\n\n"
                "| 품명 | 수량 | 단가 | 금액 |\n"
                "|---|---|---|---|\n"
                "| 기기 | 2 | 5000 | 10000 |\n"
                "| 합계 | | | 10000 |\n"
            )
            (repo / "quote.md").write_text(quote_content, encoding="utf-8")
            out_docx = repo / "order.docx"
            adapter = StubAdapter(answers=["발주서 초안 완료"])

            code = run_order_command(
                repo,
                "quote.md",
                accept=True,
                adapter=adapter,
                out_path=out_docx,
                doc_format="docx",
            )
            self.assertEqual(code, 0)
            self.assertTrue(out_docx.exists())
            with zipfile.ZipFile(out_docx, "r") as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("발주서/판매오더", doc_xml)
                self.assertIn("기기", doc_xml)
                self.assertIn("10000", doc_xml)

    def test_documented_decisions_constants(self) -> None:
        self.assertEqual(HWPX_EXPORT_DECISION, "DOCUMENTED_DECISION")
        self.assertEqual(LEGACY_HWP_EXPORT_DECISION, "UNSUPPORTED_BINARY_HWP_NON_GOAL")


if __name__ == "__main__":
    unittest.main()
