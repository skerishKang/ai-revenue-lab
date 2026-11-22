"""#3929 Drive upload -> real D1 owner file index integration.

Uses the ACTUAL adapter, consent checks, real SQLite migration 026 and real
Starlette GET; only the provider and authorization are hermetic fakes. No real
Drive WRITE, B14/Engine model, Production mutation or browser credentials.
"""
from __future__ import annotations

from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.claw_durable_drive_output_pipeline import (
    ClawDurableDriveOutputPipeline, DurableArtifactCompletionError,
)
from app.history import D1HistoryStore
from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import register_canonical_artifact
from _support.conversation_artifact_d1 import (
    D1Sqlite, setup_database, OWNER, FOREIGN, CHAT, FOREIGN_CHAT,
    WORKSPACE, OTHER_WORKSPACE, RUN, RUN2,
)
from _support.claw_drive_output_registration import (
    ACTOR, ARTIFACT_ID, BINDING, FILE, FOLDER, NOW, PDF, SHA,
    Approval, ports,
)
import test_b54_claw_general_p01_routing as base

class ClawProviderToD1Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db=setup_database()
        self.history=D1HistoryStore(D1Sqlite(self.db))
        self.adapter,self.intent,self.record,self.provider,self.approval=ports()
        self.pipeline=ClawDurableDriveOutputPipeline(history=self.history,uploader=self.adapter)

    def tearDown(self):
        self.db.close()

    def params(self, **overrides):
        fields=dict(
            owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            run_ref=RUN,
            artifact_ref=LineageArtifactRef(ARTIFACT_ID, SHA),
            source_record=self.record,
            intent=self.intent, now=NOW,
        )
        fields.update(overrides)
        return fields

    async def test_actual_approved_adapter_upload_result_persists_in_d1_and_followup_get(self):
        result=await self.pipeline.upload_completed_run_output(**self.params())
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.approval.calls,1)
        self.assertTrue(result.stored_in_conversation_index)
        self.assertEqual(result.artifact_id,ARTIFACT_ID)
        self.assertNotIn(FILE,json.dumps(result.public_projection()))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0],1)
        private=self.db.execute(
            "SELECT location_ref,integrity_ref FROM claw_conversation_artifact_index"
        ).fetchone()
        self.assertEqual(private["location_ref"],FILE)
        self.assertEqual(private["integrity_ref"],SHA)

        async def cp(_):
            return WORKSPACE
        from app.claw_conversation_artifact_routes import claw_conversation_artifact_followup
        from app.auth import SESSION_COOKIE,create_session_token
        app=create_app(settings=base._settings(), history_store=self.history)
        self.assertIsNone(app.state.claw_durable_drive_output_pipeline)
        with patch("app.claw_conversation_artifact_routes._resolve_canonical_tenant",cp):
            with TestClient(app,base_url="https://chat.example.test") as client:
                client.cookies.set(SESSION_COOKIE,create_session_token(base._settings(),OWNER, canonical_session_id="session_test_a"),
                                   domain="chat.example.test",path="/")
                resp=client.get(f"/api/claw/conversations/{CHAT}/artifact-followup?kind=pdf")
                self.assertEqual(resp.status_code,200,resp.text)
                selected=resp.json()["followup"]
                self.assertEqual(selected["source_artifact_id"],ARTIFACT_ID)
                self.assertEqual(selected["source_integrity_ref"],SHA)
                self.assertTrue(selected["status"]=="resolved")
                self.assertNotIn(FILE,resp.text)
                self.assertEqual(client.get(
                    f"/api/claw/conversations/{FOREIGN_CHAT}/artifact-followup"
                ).status_code,404)

    async def test_xlsx_and_pdf_are_two_distinct_durable_artifacts_in_same_thread(self):
        from io import BytesIO
        from openpyxl import Workbook
        book = Workbook()
        book.active["A1"] = "New School"
        book.active["B2"] = 99_200_000
        book.active["B3"] = "=B2*0.1"
        buff = BytesIO()
        book.save(buff)
        data = buff.getvalue()

        # The real adapter's exact-byte / receipt gate handles XLSX as well.
        x_adapter, x_intent, x_record, x_provider, _ = ports(
            data=data,
            filename="verified-result.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            artifact_id="artifact_xlsx_p01_3929",
            file_ref="provider_xlsx_3929",
        )
        output = await ClawDurableDriveOutputPipeline(
            history=self.history, uploader=x_adapter
        ).upload_completed_run_output(
            **self.params(
                artifact_ref=LineageArtifactRef(
                    x_record.artifact_id, x_record.integrity_ref
                ),
                source_record=x_record,
                intent=x_intent,
            )
        )
        self.assertTrue(output.stored_in_conversation_index)
        self.assertEqual(x_provider.calls, 1)
        self.assertEqual(output.integrity_ref, sha256(data).hexdigest())
        pdf_output = await self.pipeline.upload_completed_run_output(**self.params())
        self.assertNotEqual(pdf_output.artifact_id, output.artifact_id)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 2)
        from app.claw_conversation_artifact_routes import _bounded_rows
        from kagent.conversation_artifact_followup import (
            FollowupSelection, resolve_followup_artifact,
        )
        from app.claw_conversation_artifact_routes import _VerifiedIndex
        indexed = await self.history.list_owner_conversation_artifacts(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE, limit=31
        )
        index = _VerifiedIndex(
            owner=OWNER, conversation=CHAT,
            workspace=WORKSPACE, rows=_bounded_rows(indexed)
        )
        for kind, expected in (("pdf", pdf_output.artifact_id), ("xlsx", output.artifact_id)):
            result = resolve_followup_artifact(
                selection=FollowupSelection(
                    owner_id=OWNER, conversation_id=CHAT,
                    workspace_ref=WORKSPACE, output_kind=kind
                ),
                index=index,
            )
            self.assertEqual(result.artifact_ref.artifact_id, expected)

    async def test_wrong_file_type_is_denied_before_any_provider_call(self):
        jpeg = register_canonical_artifact(
            artifact_id="artifact_jpg_out",
            artifact_kind="output.image", filename="image.jpg",
            media_type="image/jpeg", size_bytes=12, integrity_ref="b"*64,
            workspace_ref=WORKSPACE, run_ref=RUN,
        )
        with self.assertRaisesRegex(
            DurableArtifactCompletionError, "approved XLSX/PDF"
        ):
            await self.pipeline.upload_completed_run_output(
                **self.params(source_record=jpeg)
            )
        self.assertEqual(self.provider.calls, 0)

    async def test_wrong_preflight_record_digest_refuses_provider_call(self):
        other = register_canonical_artifact(
            artifact_id=ARTIFACT_ID,
            artifact_kind="output.pdf", filename="verified-result.pdf",
            media_type="application/pdf",
            size_bytes=len(PDF), integrity_ref="a"*64,
            workspace_ref=WORKSPACE, run_ref=RUN,
        )
        with self.assertRaisesRegex(
            DurableArtifactCompletionError, "approved XLSX/PDF"
        ):
            await self.pipeline.upload_completed_run_output(
                **self.params(source_record=other)
            )
        self.assertEqual(self.provider.calls, 0)

    async def test_no_completed_run_or_foreign_owner_before_upload(self):
        for parameters in (
            dict(owner_id=FOREIGN),
            dict(conversation_id=FOREIGN_CHAT),
            dict(workspace_ref=OTHER_WORKSPACE),
            dict(run_ref=RUN2),
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(DurableArtifactCompletionError):
                    await self.pipeline.upload_completed_run_output(
                        **self.params(**parameters))
        self.assertEqual(self.provider.calls,0)
        self.assertEqual(self.approval.calls,0)

    async def test_existing_write_approval_still_required(self):
        denied=Approval(False)
        adapter, intent, _, provider, _=ports(approval=denied)
        pipeline=ClawDurableDriveOutputPipeline(history=self.history,uploader=adapter)
        with self.assertRaises(ValueError):
            await pipeline.upload_completed_run_output(**self.params(intent=intent))
        self.assertEqual(provider.calls,0)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM claw_conversation_artifact_index").fetchone()[0],0)

    async def test_uncertain_post_upload_d1_refusal_is_not_auto_retried(self):
        class D1Refusal:
            def __init__(self, delegate): self.delegate=delegate
            async def verify_owner_conversation_artifacts(self,*a):
                return await self.delegate.verify_owner_conversation_artifacts(*a)
            async def get_claw_run(self,*a):
                return await self.delegate.get_claw_run(*a)
            async def register_owner_conversation_artifact(self,**kwargs):
                return False
        service=ClawDurableDriveOutputPipeline(
            history=D1Refusal(self.history),uploader=self.adapter)
        with self.assertRaisesRegex(DurableArtifactCompletionError,"no retry"):
            await service.upload_completed_run_output(**self.params())
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM claw_conversation_artifact_index").fetchone()[0],0)
        # Repeating the same approved Drive intent cannot create a duplicate.
        with self.assertRaises(ValueError):
            await service.upload_completed_run_output(**self.params())
        self.assertEqual(self.provider.calls,1)

    async def test_app_only_composes_explicit_trusted_adapter(self):
        app=create_app(settings=base._settings(),history_store=self.history,
                       claw_drive_artifact_uploader=self.adapter)
        self.assertIsInstance(
            app.state.claw_durable_drive_output_pipeline,ClawDurableDriveOutputPipeline)
        with self.assertRaises(DurableArtifactCompletionError):
            ClawDurableDriveOutputPipeline(history=self.history,uploader=object())
