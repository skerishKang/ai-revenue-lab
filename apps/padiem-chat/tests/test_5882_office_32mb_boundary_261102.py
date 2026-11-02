"""#5882 A13 — the 32MB office byte bound is a memory guard, kept, and named.

Three byte-delivery routes for office documents and their bounds, checked on
2026-11-02: the broker-staged office preview/download refuses above 32MB
(``claw_local_office_binary_reader.py:23`` — the Worker holds bytes + base64 +
a JSON envelope inside the 128MB budget, so over-bound files are refused, not
partially opened), the PC read command parses office/PDF/HWPX files from a
16MB leading prefix with an honest ``partial`` marker and no size cap
(``claw_pc_read_command.py:35`` — a 40MB XLSX asked "read it" is answered
from its leading bytes), and the attachment upload parser carries a 1GB bound
(``document_normalization.py:41``). The 32MB bound stays; this test pins the
new honest refusal (``office_pdf_too_large`` with a Korean message) that
separates an over-bound file from a corrupted one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_3580_hark_office_owner_pdf_preview import (  # noqa: E402
    PDF,
    RUN,
    get,
)


class SizedSource:
    configured = True

    def __init__(self, size_bytes: int):
        self.calls = []
        self.size_bytes = size_bytes

    async def read_staged_office_output(self, *, owner_id, run_ref, kind):
        self.calls.append((owner_id, run_ref, kind))
        from app.claw_local_office_binary_reader import VerifiedOfficeBinary

        head = PDF[: len(PDF) - 5]
        filler = b"%" + b"A" * max(0, self.size_bytes - len(head) - 6)
        return VerifiedOfficeBinary(
            artifact_id="pdf_5882_sized", filename="sized_original.pdf",
            kind="pdf", media_type="application/pdf",
            integrity_ref="a" * 64,
            content=head + filler + b"%%EOF\n",
        )


def test_31mb_pdf_still_serves_inside_the_bound() -> None:
    resp = get(source=SizedSource(31 * 1024 * 1024))
    assert resp.status_code == 200, (resp.status_code, resp.content[:120])
    assert resp.headers["content-type"] == "application/pdf"


def test_33mb_pdf_refused_with_the_honest_too_large_reason() -> None:
    resp = get(source=SizedSource(33 * 1024 * 1024))
    assert resp.status_code == 503, resp.status_code
    body = resp.json()
    assert body["error"]["code"] == "office_pdf_too_large", body
    assert "너무 커서" in body["error"]["message"], body


def test_100mb_pdf_refused_with_the_same_reason_without_leaking_bytes() -> None:
    resp = get(source=SizedSource(100 * 1024 * 1024))
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "office_pdf_too_large"
    assert b"AAAA" not in resp.content[:400], "the file bytes must not leak into the refusal"
