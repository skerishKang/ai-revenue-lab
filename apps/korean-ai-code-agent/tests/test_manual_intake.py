# apps/korean-ai-code-agent/tests/test_manual_intake.py
import io
import unittest
import zipfile

from kagent.manual_intake import (
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
    ManualIntakeRouter,
    ManualIntakeSafetyDecision,
    ContractError,
)
from kagent.document_export import DocumentExportError


class TestManualIntakeContracts(unittest.TestCase):
    def setUp(self):
        self.router = ManualIntakeRouter()

    def test_all_channels_supported(self):
        channels = [
            ManualIntakeChannel.KAKAO,
            ManualIntakeChannel.SMS,
            ManualIntakeChannel.EMAIL,
            ManualIntakeChannel.TELEGRAM,
            ManualIntakeChannel.DISCORD,
            ManualIntakeChannel.OTHER,
        ]
        for ch in channels:
            req = ManualIntakeRequest(
                request_id=f"req-{ch.value}-01",
                workspace_id="ws-test-01",
                channel=ch,
                action=ManualIntakeAction.QUOTE_DRAFT,
                raw_content="안녕하세요 견적 요청드립니다. 품목: 서버 1대 1,000,000원",
            )
            res = self.router.process(req)
            self.assertEqual(res.channel, ch)
            self.assertEqual(res.action, ManualIntakeAction.QUOTE_DRAFT)
            self.assertIn("견적서 초안", res.title)

    def test_connectorless_execution(self):
        req = ManualIntakeRequest(
            request_id="req-sms-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.SMS,
            action=ManualIntakeAction.ORDER_DRAFT,
            raw_content="발주서 요청합니다. 품목: 모니터 2대 단가 250,000원",
        )
        res = self.router.process(req)
        safe = res.safe_dict()
        self.assertFalse(safe["connector_required"])
        self.assertFalse(safe["raw_input_trusted_as_memory"])
        self.assertTrue(safe["memory_update_requires_user_approval"])

    def test_untrusted_memory_boundary(self):
        req = ManualIntakeRequest(
            request_id="req-email-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.EMAIL,
            action=ManualIntakeAction.EXTRACT_CANDIDATES,
            raw_content="고객사: 테크코프\n대표: 홍길동\n연락처: 010-1234-5678\n이메일: test@example.com",
            sender_hint="테크코프",
        )
        res = self.router.process(req)
        self.assertFalse(res.safety_decision.raw_input_trusted_as_memory)
        self.assertTrue(res.safety_decision.memory_update_requires_user_approval)
        self.assertGreater(len(res.memory_proposals), 0)
        for proposal in res.memory_proposals:
            self.assertEqual(proposal["type"], "organization_candidate")
            self.assertEqual(proposal["name"], "테크코프")
            self.assertEqual(proposal["source_channel"], "email")

    def test_empty_input_rejected_or_bounded(self):
        with self.assertRaises(ContractError):
            ManualIntakeRequest(
                request_id="req-empty-01",
                workspace_id="ws-test-01",
                channel=ManualIntakeChannel.KAKAO,
                action=ManualIntakeAction.QUOTE_DRAFT,
                raw_content="   ",
            )

    def test_quote_draft_action_with_docx_artifact(self):
        req = ManualIntakeRequest(
            request_id="req-docx-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.KAKAO,
            action=ManualIntakeAction.QUOTE_DRAFT,
            raw_content="견적 요청서\n공급받는자: 주식회사 테크\n품목: 클라우드 서버 2식 단가 500,000원",
            requested_format="docx",
        )
        res = self.router.process(req)
        self.assertEqual(res.action, ManualIntakeAction.QUOTE_DRAFT)

        file_names = [a.file_name for a in res.artifacts]
        self.assertTrue(any(fn.endswith(".md") for fn in file_names))
        self.assertTrue(any(fn.endswith(".docx") for fn in file_names))

        docx_art = next(a for a in res.artifacts if a.file_name.endswith(".docx"))
        self.assertGreater(docx_art.size_bytes, 0)
        bio = io.BytesIO(docx_art.content_bytes)
        self.assertTrue(zipfile.is_zipfile(bio))
        with zipfile.ZipFile(bio, "r") as zf:
            self.assertIn("[Content_Types].xml", zf.namelist())
            self.assertIn("word/document.xml", zf.namelist())

    def test_hwpx_documented_decision_fail_closed(self):
        req = ManualIntakeRequest(
            request_id="req-hwpx-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.KAKAO,
            action=ManualIntakeAction.QUOTE_DRAFT,
            raw_content="견적 요청서 품목: 테스트 1개",
            requested_format="hwpx",
        )
        with self.assertRaises(DocumentExportError) as ctx:
            self.router.process(req)
        self.assertIn("HWPX", str(ctx.exception))

    def test_disabled_actions_enforced(self):
        req = ManualIntakeRequest(
            request_id="req-reply-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.KAKAO,
            action=ManualIntakeAction.REPLY_DRAFT,
            raw_content="미팅 일정 회신 부탁드립니다.",
        )
        res = self.router.process(req)

        action_keys = [d.action_key for d in res.disabled_actions]
        self.assertIn("direct_kakao_send", action_keys)
        self.assertIn("direct_sms_send", action_keys)
        self.assertIn("share_link", action_keys)
        self.assertIn("google_drive_save", action_keys)
        self.assertIn("email_send", action_keys)

        safe = res.safe_dict()
        self.assertFalse(safe["direct_kakao_send"])
        self.assertFalse(safe["direct_sms_send"])

    def test_summarize_request_action(self):
        req = ManualIntakeRequest(
            request_id="req-sum-01",
            workspace_id="ws-test-01",
            channel=ManualIntakeChannel.EMAIL,
            action=ManualIntakeAction.SUMMARIZE_REQUEST,
            raw_content="""보낸사람: buyer@client.co.kr
제목: 긴급 견적 요청의 건
내용: 서버 5대 및 스토리지 10TB 내일까지 견적 송부 바랍니다.
연락처: 010-9999-8888""",
        )
        res = self.router.process(req)
        self.assertEqual(res.action, ManualIntakeAction.SUMMARIZE_REQUEST)
        self.assertIn("email", res.result_text)
        self.assertIn("핵심 요약", res.result_text)


if __name__ == '__main__':
    unittest.main()
