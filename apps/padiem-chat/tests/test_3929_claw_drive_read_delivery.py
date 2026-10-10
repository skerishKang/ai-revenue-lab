"""#3929/#3932: D1-selected owner-scope Drive read / preview with fake READ port.

Real SQLite migration 026 and upload adapter; no external Drive READ/WRITE.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from starlette.testclient import TestClient
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.history import D1HistoryStore
from app.claw_durable_drive_output_pipeline import ClawDurableDriveOutputPipeline
from kagent.artifact_lineage import LineageArtifactRef

from test_3929_claw_drive_output_registration import (
    ports, PDF, ARTIFACT_ID, SHA, NOW, WORKSPACE, OWNER, CHAT, RUN,
)
from test_3929_claw_conversation_artifact_d1 import (
    D1Sqlite, setup_database, FOREIGN_CHAT, FOREIGN,
)
import test_b54_claw_general_p01_routing as base


class FakeDriveReader:
    def __init__(self, data=PDF):
        self.data = data
        self.calls = 0
        self.last = None

    async def read_authorized_artifact(
        self, *, owner_id, workspace_ref, artifact,
    ):
        self.calls += 1
        self.last = (owner_id, workspace_ref, artifact.artifact_id)
        return self.data


class DurableArtifactReadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.history = D1HistoryStore(D1Sqlite(self.db))
        self.adapter, self.intent, self.record, self.provider, _ = ports()
        self.reader = FakeDriveReader()

    def tearDown(self):
        self.db.close()

    async def register(self):
        result = await ClawDurableDriveOutputPipeline(
            history=self.history, uploader=self.adapter,
        ).upload_completed_run_output(
            owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            run_ref=RUN, artifact_ref=LineageArtifactRef(ARTIFACT_ID, SHA),
            source_record=self.record, intent=self.intent, now=NOW,
        )
        self.assertTrue(result.stored_in_conversation_index)

    async def request(self, *, suffix="download", reader=True,
                      conversation=CHAT, artifact=ARTIFACT_ID, owner=OWNER):
        async def canonical_workspace(_):
            return WORKSPACE
        app = create_app(
            settings=base._settings(), history_store=self.history,
            claw_drive_artifact_reader=self.reader if reader else None,
        )
        with patch("app.claw_durable_drive_artifact_routes._resolve_canonical_tenant",
                   canonical_workspace):
            with TestClient(app, base_url="https://chat.example.test") as client:
                client.cookies.set(
                    SESSION_COOKIE,
                    create_session_token(base._settings(), owner),
                    domain="chat.example.test", path="/",
                )
                return client.get(
                    f"/api/claw/conversations/{conversation}/artifacts/{artifact}/{suffix}"
                )

    async def test_owner_download_and_pdf_inline_preview_recheck_exact_bytes(self):
        await self.register()
        res = await self.request()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.content, PDF)
        self.assertIn("attachment;", res.headers["content-disposition"])
        self.assertEqual(res.headers["content-type"], "application/pdf")
        self.assertEqual(self.reader.last, (OWNER, WORKSPACE, ARTIFACT_ID))
        self.assertNotIn("provider_file_3929", str(res.headers))
        preview = await self.request(suffix="preview")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("inline;", preview.headers["content-disposition"])
        self.assertEqual(preview.headers["x-frame-options"], "SAMEORIGIN")

    async def test_no_implicit_google_read_grant_even_after_write(self):
        await self.register()
        res = await self.request(reader=False)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"]["code"], "drive_read_not_configured")
        self.assertEqual(self.reader.calls, 0)

    async def test_cross_conversation_and_nonexistent_artifact_never_call_reader(self):
        await self.register()
        for params in (
            {"conversation": FOREIGN_CHAT},
            {"artifact": "artifact_other_3929"},
        ):
            res = await self.request(**params)
            self.assertEqual(res.status_code, 404, res.text)
        self.assertEqual(self.reader.calls, 0)

    async def test_changed_bytes_and_invalid_pdf_refused(self):
        await self.register()
        self.reader.data = PDF + b"altered"
        res = await self.request()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"]["code"], "artifact_integrity_failed")
        self.reader.data = b"x" * len(PDF)
        res = await self.request()
        self.assertEqual(res.status_code, 503)

    async def test_foreign_user_cannot_read_even_with_exact_artifact_id(self):
        await self.register()
        res = await self.request(owner=FOREIGN)
        self.assertEqual(res.status_code, 404, res.text)
        self.assertEqual(self.reader.calls, 0)

    async def test_untrusted_artifact_id_format_refused_before_lookup(self):
        await self.register()
        res = await self.request(artifact="bad.file")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.reader.calls, 0)

    async def test_missing_index_no_download(self):
        res = await self.request()
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.reader.calls, 0)


if __name__ == "__main__":
    unittest.main()
