"""Offline native Google Docs/Sheets copy/edit/export contract tests (#3908).

All Drive/Docs/Sheets calls use fakes. No OAuth tokens, API calls or grant
activation. The original source ID must never be an edit/export target.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import unittest

from kagent.artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)
from kagent.connector_trust import ConnectorBindingProjection, ConnectorWriteIntent
from kagent.google_drive_scope import DriveFileMetadata, DriveResourceProof, DriveScopeProjection
from kagent.google_workspace_working_copy import (
    DOCS_MIME, SHEETS_MIME, PDF_MIME, NativeEdit, WorkspaceCopyError,
    GoogleWorkspaceWorkingCopyAdapter, edit_fingerprint,
    PRODUCTION_WORKSPACE_WRITE_ACTIVATED, XLSX_TO_SHEETS_FIDELITY_PROVEN,
)

NOW = datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
SRC, FOLDER, COPY = "drive_source_one", "folder_output_one", "new_copy_01"
BIND, ACTOR, SPACE, RUN = "binding_google_1", "actor_1", "workspace_1", "run_1"
DOCS_EDIT = NativeEdit(kind="docs", find_text="old amount", replace_text="3 units")
SHEETS_EDIT = NativeEdit(kind="sheets", range_a1="'견적서'!B2", values=((3, "USD"),))
PDF = b"%PDF-1.7\nmock output\n%%EOF\n"


def source(mime=DOCS_MIME, **kw):
    data = dict(
        artifact_id="source_artifact", artifact_kind="source.native",
        filename="원본 문서", media_type=mime, size_bytes=512,
        integrity_ref="a" * 64, lifecycle=ArtifactLifecycle.DURABLE,
        durable_location=ArtifactLocation(location_kind="google_drive", location_ref=SRC),
        workspace_ref=SPACE, run_ref=RUN,
    )
    data.update(kw)
    return register_canonical_artifact(**data)


def binding(kind="docs", **kw):
    data = dict(
        binding_ref=BIND, connector_id="google-drive", actor_ref=ACTOR,
        account_ref="acct_1", workspace_ref=SPACE,
        granted_scopes=("https://www.googleapis.com/auth/drive.file",),
        granted_capabilities=("drive.files.copy", "drive.files.export",
                              "workspace.docs.replace" if kind == "docs"
                              else "workspace.sheets.values.write"),
        issued_at=NOW-timedelta(hours=1), updated_at=NOW-timedelta(hours=1),
        expires_at=NOW+timedelta(hours=1))
    data.update(kw)
    return ConnectorBindingProjection(**data)


def intent(original, edit, *, folder=FOLDER, new_name="작업 사본", pdf_filename="결과.pdf", **kw):
    data = dict(
        connector_id="google-drive", binding_ref=BIND, actor_ref=ACTOR,
        tool_name="workspace_copy_edit_export", target_ref=folder,
        payload_fingerprint=edit_fingerprint(source=original, folder_id=folder,
             new_name=new_name, edit=edit, pdf_filename=pdf_filename),
        idempotency_key="idempotent_one", approval_ref="approval_1",
        evidence_ref="evidence_1", requested_at=NOW)
    data.update(kw)
    return ConnectorWriteIntent(**data)


class Proofs:
    def __init__(self, *, mime=DOCS_MIME, source_id=SRC, folder_id=FOLDER,
                 source_trashed=False, folder_trashed=False, source_is_shortcut=False):
        self.calls=[]
        self.mime=mime;self.source_id=source_id;self.folder_id=folder_id
        self.source_trashed=source_trashed;self.folder_trashed=folder_trashed
        self.source_is_shortcut=source_is_shortcut

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return (
            DriveResourceProof(binding_ref=BIND, metadata=DriveFileMetadata(
                file_id=self.source_id, name="Original", mime_type=self.mime,
                version=3, trashed=self.source_trashed)),
            DriveResourceProof(binding_ref=BIND, metadata=DriveFileMetadata(
                file_id=self.folder_id, name="Output", mime_type="application/vnd.google-apps.folder",
                version=1, trashed=self.folder_trashed)),
        )


class Approval:
    def __init__(self, answer=True):
        self.answer=answer;self.calls=[]
    def verify(self, **kw):
        self.calls.append(kw)
        return self.answer


class Lease:
    def __init__(self, answer=True):
        self.answer=answer;self.calls=[]
    def verify(self, **kw):
        self.calls.append(kw)
        return self.answer


class Provider:
    def __init__(self, kind="docs"):
        self.kind=kind
        self.calls=[]
        self.copy_override=None;self.edit_override=None
        self.pdf_override=None;self.raise_on=None
        self.revision="rev_01"

    def _call(self, name, **kwargs):
        self.calls.append((name,kwargs))
        if self.raise_on==name:raise OSError("PRIVATE OAuth / sensitive response")
    def copy_file(self, *, file_id, body, query):
        self._call("copy",file_id=file_id,body=body,query=query)
        if self.copy_override is not None:return self.copy_override
        return dict(id=COPY, name=body["name"],
                    mimeType=DOCS_MIME if self.kind=="docs" else SHEETS_MIME,
                    parents=list(body["parents"]),version=1,trashed=False)
    def docs_revision(self, *, file_id):
        self._call("revision",file_id=file_id)
        return self.revision
    def docs_batch_update(self, *, file_id, body):
        self._call("docs_edit",file_id=file_id,body=body)
        return self.edit_override if self.edit_override is not None else {
            "replies":[{"replaceAllText":{"occurrencesChanged":1}}]}
    def sheets_values_batch_update(self, *, file_id, body):
        self._call("sheets_edit",file_id=file_id,body=body)
        return self.edit_override if self.edit_override is not None else {
            "spreadsheetId":file_id, "totalUpdatedCells":2, "responses":[{}]}
    def export_file(self, *, file_id, mime_type):
        self._call("export",file_id=file_id,mime_type=mime_type)
        return self.pdf_override if self.pdf_override is not None else PDF


def setup(kind="docs", *, b=None, proof=None, approval=None, lease=None, provider=None,
          scope=None):
    obj=Provider(kind) if provider is None else provider
    app=GoogleWorkspaceWorkingCopyAdapter(
        binding=b if b is not None else binding(kind),
        scope=scope if scope is not None else DriveScopeProjection(
            binding_ref=BIND, allowed_file_ids=(SRC,), allowed_folder_ids=(FOLDER,)),
        proofs=proof if proof is not None else Proofs(mime=DOCS_MIME if kind=="docs" else SHEETS_MIME),
        approval=approval if approval is not None else Approval(),
        lease=lease if lease is not None else Lease(),
        provider=obj)
    return app,obj


def invoke(app, kind="docs", **kw):
    doc=source(DOCS_MIME if kind=="docs" else SHEETS_MIME)
    edit=DOCS_EDIT if kind=="docs" else SHEETS_EDIT
    data=dict(source=doc,intent=intent(doc,edit),edit=edit,
              new_name="작업 사본",pdf_filename="결과.pdf",
              output_artifact_id="output_pdf_1",workspace_ref=SPACE,
              run_ref=RUN,now=NOW)
    data.update(kw)
    return app.copy_edit_export(**data)


class GoogleWorkspaceWorkingCopyTests(unittest.TestCase):
    def test_source_only_disabled_not_xlsx_conversion(self):
        self.assertFalse(PRODUCTION_WORKSPACE_WRITE_ACTIVATED)
        self.assertFalse(XLSX_TO_SHEETS_FIDELITY_PROVEN)
        with self.assertRaises(WorkspaceCopyError):
            NativeEdit(kind="xlsx")

    def test_docs_copy_exact_revision_edit_and_export_pdf_lineage(self):
        app,p=setup()
        result=invoke(app)
        self.assertEqual([name for name,_ in p.calls],["copy","revision","docs_edit","export"])
        self.assertEqual(p.calls[0][1]["file_id"],SRC)
        self.assertEqual(p.calls[0][1]["body"],{"name":"작업 사본","parents":[FOLDER]})
        self.assertEqual(p.calls[0][1]["query"]["supportsAllDrives"],"true")
        self.assertEqual(p.calls[2][1]["file_id"],COPY)
        self.assertEqual(p.calls[2][1]["body"]["writeControl"],{"requiredRevisionId":"rev_01"})
        self.assertEqual(p.calls[2][1]["body"]["requests"][0]["replaceAllText"]["replaceText"],"3 units")
        self.assertEqual(p.calls[3][1],{"file_id":COPY,"mime_type":PDF_MIME})
        self.assertEqual(result.pdf_bytes,PDF)
        self.assertEqual(result.output.integrity_ref,hashlib.sha256(PDF).hexdigest())
        self.assertEqual(result.output.lifecycle,ArtifactLifecycle.REGISTERED)
        self.assertEqual(result.lineage.source_artifact_id,"source_artifact")
        self.assertEqual(result.lineage.output_artifact_ids,("output_pdf_1",))
        self.assertEqual(result.copy_receipt.provider_operation_ref,COPY)
        self.assertNotIn(SRC,str(result.public_projection()))
        self.assertNotIn(COPY,str(result.public_projection()))
        self.assertNotIn(PDF.decode(),str(result.public_projection()))

    def test_sheets_copy_only_raw_cells_and_pdf(self):
        app,p=setup("sheets")
        result=invoke(app,"sheets")
        self.assertEqual([name for name,_ in p.calls],["copy","sheets_edit","export"])
        self.assertEqual(p.calls[1][1]["file_id"],COPY)
        self.assertEqual(p.calls[1][1]["body"],{
            "valueInputOption":"RAW",
            "data":[{"range":"'견적서'!B2","values":[[3,"USD"]]}]})
        self.assertEqual(result.output.media_type,PDF_MIME)

    def test_source_never_edited_even_if_new_copy_refuses(self):
        p=Provider()
        p.copy_override=dict(id=SRC,name="작업 사본",mimeType=DOCS_MIME,
                             parents=[FOLDER],version=1,trashed=False)
        app,_=setup(provider=p)
        with self.assertRaises(WorkspaceCopyError):invoke(app)
        self.assertEqual([name for name,_ in p.calls],["copy"])

    def test_scopes_capabilities_revocation_expiry_and_identity_fail_pre_side_effect(self):
        cases=[
            dict(granted_scopes=("https://www.googleapis.com/auth/drive.readonly",)),
            dict(granted_capabilities=("drive.files.copy","drive.files.export")),
            dict(expires_at=NOW),
            dict(connector_id="gmail"),
        ]
        for opts in cases:
            p=Provider()
            try:
                app,_=setup(b=binding(**opts),provider=p)
            except WorkspaceCopyError:
                self.assertEqual(p.calls,[])
                continue
            with self.assertRaises(WorkspaceCopyError):invoke(app)
            self.assertFalse(p.calls)

    def test_wrong_workspace_run_actor_and_fingerprint_fail_closed(self):
        for key,val in (("workspace_ref","wrong_workspace"),("run_ref","wrong_run")):
            app,p=setup()
            with self.assertRaises(WorkspaceCopyError):invoke(app,**{key:val})
            self.assertFalse(p.calls)
        app,p=setup()
        d=source()
        with self.assertRaises(WorkspaceCopyError):invoke(app,intent=intent(d,DOCS_EDIT,actor_ref="wrong_actor"))
        self.assertFalse(p.calls)
        app,p=setup()
        with self.assertRaises(WorkspaceCopyError):invoke(app,intent=intent(d,DOCS_EDIT,payload_fingerprint="f"*64))
        self.assertFalse(p.calls)

    def test_source_and_folder_proof_required_allowlisted(self):
        for proofs in (Proofs(source_id="other_source"),Proofs(folder_id="other_folder"),
                       Proofs(source_trashed=True),Proofs(folder_trashed=True),
                       Proofs(mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")):
            app,p=setup(proof=proofs)
            with self.assertRaises(WorkspaceCopyError):invoke(app)
            self.assertFalse(p.calls)
        app,p=setup(scope=DriveScopeProjection(binding_ref=BIND,allowed_file_ids=(SRC,)))
        with self.assertRaises(WorkspaceCopyError):invoke(app)
        self.assertFalse(p.calls)

    def test_approval_failure_and_lease_refusal(self):
        app,p=setup(approval=Approval(False))
        with self.assertRaisesRegex(WorkspaceCopyError,"approval"):invoke(app)
        self.assertFalse(p.calls)
        app,p=setup(lease=Lease(False))
        with self.assertRaisesRegex(WorkspaceCopyError,"lease"):invoke(app)
        self.assertEqual([name for name,_ in p.calls],["copy"])

    def test_docs_requires_revision_and_nonzero_changed_count(self):
        for revision in ("", "bad revision", None):
            p=Provider();p.revision=revision
            app,_=setup(provider=p)
            with self.assertRaises(WorkspaceCopyError):invoke(app)
            self.assertNotIn("docs_edit",[name for name,_ in p.calls])
        for reply in ({}, {"replies":[]},{"replies":[{"replaceAllText":{"occurrencesChanged":0}}]}):
            p=Provider();p.edit_override=reply
            app,_=setup(provider=p)
            with self.assertRaises(WorkspaceCopyError):invoke(app)
            self.assertNotIn("export",[name for name,_ in p.calls])

    def test_sheets_checks_updated_target_and_cell_count(self):
        for reply in ({}, {"spreadsheetId":SRC,"totalUpdatedCells":2,"responses":[{}]},
                      {"spreadsheetId":COPY,"totalUpdatedCells":1,"responses":[{}]},
                      {"spreadsheetId":COPY,"totalUpdatedCells":2,"responses":[]}):
            p=Provider("sheets");p.edit_override=reply
            app,_=setup("sheets",provider=p)
            with self.assertRaises(WorkspaceCopyError):invoke(app,"sheets")
            self.assertNotIn("export",[name for name,_ in p.calls])

    def test_invalid_copy_id_mime_parent_or_trash_refused(self):
        for alt in (dict(id=SRC),dict(id=FOLDER),dict(mimeType=SHEETS_MIME),
                    dict(parents=["wrong_folder"]),dict(trashed=True),dict(version=0)):
            p=Provider()
            p.copy_override=dict(id=COPY,name="작업 사본",mimeType=DOCS_MIME,
                                 parents=[FOLDER],version=1,trashed=False,**alt)
            # Python detects duplicate keys in keyword construction; merge above manually
            app,_=setup(provider=p)
            with self.assertRaises(WorkspaceCopyError):invoke(app)
            self.assertEqual([name for name,_ in p.calls],["copy"])

    def test_pdf_bytes_bound_and_signature(self):
        for pdf in (b"",b"not a pdf",b"%PDF-1.7\nmissing eof",b"x"*(8*1024*1024+1)):
            p=Provider();p.pdf_override=pdf
            app,_=setup(provider=p)
            with self.assertRaises(WorkspaceCopyError):invoke(app)

    def test_idempotency_no_second_copy_even_after_failure(self):
        p=Provider();app,_=setup(provider=p)
        invoke(app)
        with self.assertRaisesRegex(WorkspaceCopyError,"replay"):invoke(app)
        self.assertEqual([name for name,_ in p.calls].count("copy"),1)
        p=Provider();p.raise_on="docs_edit";app,_=setup(provider=p)
        with self.assertRaisesRegex(WorkspaceCopyError,"provider unavailable"):invoke(app)
        with self.assertRaisesRegex(WorkspaceCopyError,"replay"):invoke(app)
        self.assertEqual([name for name,_ in p.calls].count("copy"),1)

    def test_native_edits_bounded_and_raw_not_formula_execution(self):
        for edit in (
            NativeEdit(kind="sheets",range_a1="Sheet1!B2",values=(("=SUM(1,2)",),)),
            NativeEdit(kind="sheets",range_a1="'견적서'!B2",values=((True,2),))):
            self.assertEqual(edit.kind,"sheets")
        for kwargs in (
            dict(kind="docs",find_text="",replace_text="x"),
            dict(kind="sheets",range_a1="Sheet1!A1;DROP",values=((1,),)),
            dict(kind="sheets",range_a1="Sheet1!A1",values=((float("nan"),),)),
            dict(kind="sheets",range_a1="Sheet1!A1",values=((None,),)),
            dict(kind="sheets",range_a1="Sheet1!A1",values=tuple((i,) for i in range(33)))):
            with self.assertRaises(WorkspaceCopyError):NativeEdit(**kwargs)

    def test_native_only_and_wrong_output_are_rejected(self):
        app,p=setup()
        with self.assertRaises(WorkspaceCopyError):invoke(app,source=source(SHEETS_MIME))
        self.assertFalse(p.calls)
        app,p=setup()
        with self.assertRaises(WorkspaceCopyError):invoke(app,output_artifact_id="source_artifact")
        self.assertFalse(p.calls)


if __name__ == "__main__":
    unittest.main()
