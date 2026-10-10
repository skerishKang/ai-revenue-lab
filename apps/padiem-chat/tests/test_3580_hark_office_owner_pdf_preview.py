"""#3580 Owner authenticated/private Broker PDF preview; no Drive permission."""
from __future__ import annotations

import asyncio
import httpx

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_office_binary_reader import VerifiedOfficeBinary
from app.claw_office_preview_routes import OFFICE_PDF_PREVIEW_PATH
from app.config import Settings

OWNER = "usr_3580_pdf_owner"
OTHER = "usr_3580_pdf_other"
RUN = "run_3580_pdf_original"
ORIGIN = "https://chat.example.test"
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


class ReadyStore:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []


class PrivateSource:
    configured = True

    def __init__(self, *, invalid=False, fail=False):
        self.calls = []
        self.invalid = invalid
        self.fail = fail

    async def read_staged_office_output(self, *, owner_id, run_ref, kind):
        self.calls.append((owner_id, run_ref, kind))
        if self.fail or owner_id != OWNER or run_ref != RUN:
            raise ValueError("PRIVATE_DEVICE_OR_OWNER_NOT_AVAILABLE")
        return VerifiedOfficeBinary(
            artifact_id="pdf_3580_output", filename="selected_original.pdf",
            kind="pdf", media_type="application/pdf",
            integrity_ref="a"*64,
            content=b"<script>bad</script>" if self.invalid else PDF,
        )


async def exchange(*, owner=OWNER, source=None, path=None):
    settings = Settings(
        session_secret="hark-office-owner-pdf-tests",
        auth_mode="mock", public_base_url=ORIGIN,
    )
    app = create_app(settings, history_store=ReadyStore(),
                     local_task_result_source=source)
    headers = {}
    if owner is not None:
        headers["Cookie"] = SESSION_COOKIE + "=" + create_session_token(settings, owner)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
    ) as client:
        return await client.get(
            path or OFFICE_PDF_PREVIEW_PATH.replace("{run_id}", RUN),
            headers=headers,
        )


def get(**kwargs):
    return asyncio.run(exchange(**kwargs))


def test_owner_gets_exact_verified_pdf_from_private_source():
    source = PrivateSource()
    resp = get(source=source)
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="hark-office.pdf"'
    assert resp.headers["cache-control"].startswith("private, no-store")
    assert resp.headers["content-security-policy"] == "sandbox"
    assert resp.headers["vary"] == "Cookie"
    assert source.calls == [(OWNER, RUN, "pdf")]


def test_unauthenticated_does_not_call_private_source():
    source = PrivateSource()
    resp = get(owner=None, source=source)
    assert resp.status_code == 401
    assert not source.calls


def test_default_source_is_unconfigured():
    assert get().status_code == 503


def test_foreign_owner_and_missing_run_do_not_leak_presence_or_private_error():
    source = PrivateSource()
    for kwargs in (
        {"owner": OTHER},
        {"path": OFFICE_PDF_PREVIEW_PATH.replace("{run_id}", "missing_run")},
    ):
        resp = get(source=source, **kwargs)
        assert resp.status_code == 404
        assert b"PRIVATE_DEVICE" not in resp.content


def test_invalid_run_and_tampered_pdf_fail_closed():
    source = PrivateSource()
    path = OFFICE_PDF_PREVIEW_PATH.replace("{run_id}", "..")
    assert get(source=source, path=path).status_code in (400, 404)
    assert not source.calls
    damaged = get(source=PrivateSource(invalid=True))
    assert damaged.status_code == 503
    assert damaged.headers["content-type"].startswith("application/json")
    assert b"<script>" not in damaged.content


def test_source_failure_never_exposes_exception():
    resp = get(source=PrivateSource(fail=True))
    assert resp.status_code == 404
    assert b"PRIVATE_DEVICE" not in resp.content
