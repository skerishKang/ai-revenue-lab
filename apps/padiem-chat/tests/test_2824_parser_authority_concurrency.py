"""#2824: Parser Authority lifecycle and concurrency inside one Chat isolate.

CENTRAL's review of PR #5817 asked whether the module-global
``_WORKER_ISOLATED_PARSER_ASYNC_COMPOSITION`` lets one request interfere with
another's parser readiness, because the Chat Worker composes or resets that slot
while building its app.

These tests drive the real composition seam, the real async client, the real
authority resolver and the real request path with controlled interleaving:

1. two document requests in flight in one isolate at the same time;
2. a re-initialisation that lands while another request is already awaiting the
   parser (the shape the ``if _worker_app is None`` block actually allows);
3. a reset that lands in the middle of another request's parse;
4. a parser outage in one request while another request keeps working;
5. two accounts' documents at the same time.

What they prove is held to what CPython can show: the installed authority keeps
no per-request or per-account state, a concurrent install of the same binding is
idempotent, and the only cross-request interference channel — a different
environment clearing the slot — fails closed instead of falling back to the
in-process parser. Whether one isolate ever sees two different environments is
a workerd lifecycle question and is measured after the freeze, not asserted here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from app.attachments import AttachmentValidationError, parse_attachments_async
from app.binary_documents import BinaryDocumentValidationError
from app.document_parser_transport import CloudflareDocumentParserServiceTransport
from padiem_ai_core.document_parser_boundary import (
    PRODUCTION_WORKER_PLATFORM,
    binary_document_parser_ready_async,
)
from padiem_ai_core.isolated_parser_async_client import IsolatedParserAsyncClient
from padiem_ai_core.isolated_parser_composition import (
    compose_worker_isolated_parser_authority_async,
    reset_worker_isolated_parser_async_composition,
    reset_worker_isolated_parser_composition,
)
from padiem_ai_core.isolated_parser_service import handle_isolated_parser_request

PDF_MIME = "application/pdf"
AUTHORITY_MESSAGE = "현재 실행 환경에서는 격리된 문서 파서를 사용할 수 없어 문서를 처리할 수 없습니다."
OUTAGE_MESSAGE = "문서 파서 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."


@pytest.fixture(autouse=True)
def _clean_parser_composition():
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()
    yield
    reset_worker_isolated_parser_async_composition()
    reset_worker_isolated_parser_composition()


def _worker_runtime():
    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


def _text_pdf(marker: str) -> bytes:
    PdfWriter = pytest.importorskip("pypdf").PdfWriter
    generic = pytest.importorskip("pypdf.generic")
    writer = PdfWriter()
    font = generic.DictionaryObject(
        {
            generic.NameObject("/Type"): generic.NameObject("/Font"),
            generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
            generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page = writer.add_blank_page(width=320, height=180)
    page[generic.NameObject("/Resources")] = generic.DictionaryObject(
        {generic.NameObject("/Font"): generic.DictionaryObject(
            {generic.NameObject("/F1"): font_ref}
        )}
    )
    content = generic.DecodedStreamObject()
    content.set_data(f"BT /F1 14 Tf 36 90 Td ({marker}) Tj ET".encode("ascii"))
    page[generic.NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _binary_item(name: str, payload: bytes) -> dict[str, str]:
    return {
        "type": "document",
        "name": name,
        "media_type": PDF_MIME,
        "base64": base64.b64encode(payload).decode("ascii"),
    }


class _FakeWorkersRequest:
    def __init__(self, url: str, method: str = "GET", headers: Any = None, body: Any = None) -> None:
        self.url = url
        self.method = method
        self.headers = headers or {}
        self.body = body
        self.js_object = self


class _FakeServiceResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = None
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")


class _GatedBinding:
    """A parser binding that stays inside ``fetch`` until the test releases it.

    The pause happens at the await the real Service Binding await performs, so a
    second request or a second composition can be scheduled in between.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.entered: list[str] = []
        self._gates: dict[str, asyncio.Event] = {}

    def gate_for(self, document_name: str) -> asyncio.Event:
        event = self._gates.setdefault(document_name, asyncio.Event())
        return event

    async def fetch(self, js_request: Any):
        envelope = json.loads(js_request.body)
        name = str(envelope["name"])
        self.calls.append(envelope)
        self.entered.append(name)
        await self.gate_for(name).wait()
        return _FakeServiceResponse(
            200, handle_isolated_parser_request(js_request.body.encode("utf-8"))
        )


class _FailingBinding:
    """Transport failure for one document, success for every other."""

    def __init__(self, failing_name: str) -> None:
        self.failing_name = failing_name
        self.calls = 0

    async def fetch(self, js_request: Any):
        self.calls += 1
        envelope = json.loads(js_request.body)
        if envelope["name"] == self.failing_name:
            raise RuntimeError("parser service is down")
        return _FakeServiceResponse(
            200, handle_isolated_parser_request(js_request.body.encode("utf-8"))
        )


def _transport(binding: Any) -> CloudflareDocumentParserServiceTransport:
    return CloudflareDocumentParserServiceTransport(binding, _FakeWorkersRequest)


async def _parse(name: str, marker: str):
    return await parse_attachments_async([_binary_item(name, _text_pdf(marker))])


# --- 1: two requests in flight in one isolate ---------------------------------


async def test_two_concurrent_document_requests_each_get_their_own_document() -> None:
    binding = _GatedBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    for name in ("account-a.pdf", "account-b.pdf"):
        binding.gate_for(name)

    with _worker_runtime():
        first = asyncio.create_task(_parse("account-a.pdf", "TOKEN-AAA"))
        second = asyncio.create_task(_parse("account-b.pdf", "TOKEN-BBB"))
        # Both requests are inside the parser await at the same time.
        while len(binding.entered) < 2:
            await asyncio.sleep(0)

        binding.gate_for("account-a.pdf").set()
        document_a = await first
        binding.gate_for("account-b.pdf").set()
        document_b = await second

    assert document_a[0].text == "TOKEN-AAA"
    assert document_b[0].text == "TOKEN-BBB"
    # One shared authority served both; each call carried only its own document.
    assert {call["name"] for call in binding.calls} == {"account-a.pdf", "account-b.pdf"}
    assert binary_document_parser_ready_async() is True


# --- 2: a re-initialisation lands while a request is awaiting the parser ------


async def test_a_concurrent_reinstall_of_the_same_binding_does_not_disturb_the_request() -> None:
    """The Chat ``if _worker_app is None`` block can run twice before assignment.

    Composition is a pure function of the deployment binding, so a second install
    built from the same binding replaces an equivalent authority rather than
    taking one away.
    """

    binding = _GatedBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    binding.gate_for("report.pdf")

    with _worker_runtime():
        in_flight = asyncio.create_task(_parse("report.pdf", "TOKEN-ONE"))
        while not binding.entered:
            await asyncio.sleep(0)

        # Same env, same binding: exactly what a second init computes.
        compose_worker_isolated_parser_authority_async(transport=_transport(binding))
        assert binary_document_parser_ready_async() is True

        binding.gate_for("report.pdf").set()
        parsed = await in_flight

    assert parsed[0].text == "TOKEN-ONE"
    assert len(binding.calls) == 1


def test_the_installed_authority_holds_no_request_or_account_state() -> None:
    """Nothing per-request can be stored in the process-wide slot.

    The installed object and the transport it closes over are both fixed-shape,
    binding-only holders, so one request cannot write state another reads.
    """

    assert IsolatedParserAsyncClient.__slots__ == ("_transport",)
    assert CloudflareDocumentParserServiceTransport.__slots__ == (
        "_binding",
        "_request_factory",
    )

    from padiem_ai_core import document_parser_boundary

    source = Path(document_parser_boundary.__file__).read_text(encoding="utf-8")
    writers = [
        line for line in source.splitlines()
        if "_WORKER_ISOLATED_PARSER_ASYNC_COMPOSITION =" in line
    ]
    # Only the two server-owned lifecycle statements assign the slot.
    assert len(writers) == 2


# --- 3: a reset landing mid-request fails closed, never in-process ------------


async def test_a_reset_during_another_request_fails_closed_instead_of_falling_back() -> None:
    binding = _GatedBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    binding.gate_for("first.pdf")
    binding.gate_for("second.pdf")

    with _worker_runtime():
        in_flight = asyncio.create_task(_parse("first.pdf", "TOKEN-AAA"))
        while not binding.entered:
            await asyncio.sleep(0)

        # A different environment would be the only thing that clears the slot.
        reset_worker_isolated_parser_async_composition()
        assert binary_document_parser_ready_async() is False

        binding.gate_for("first.pdf").set()
        parsed = await in_flight
        assert parsed[0].text == "TOKEN-AAA"

        # The next request resolves the slot again and fails closed: no silent
        # in-process parse, no partial document.
        with pytest.raises(AttachmentValidationError) as refused:
            await _parse("second.pdf", "TOKEN-BBB")
        assert AUTHORITY_MESSAGE in str(refused.value)

    assert binding.entered == ["first.pdf"]


# --- 4: one request's outage does not disable the shared authority ------------


async def test_a_parser_outage_leaves_the_authority_installed_for_other_requests() -> None:
    binding = _FailingBinding(failing_name="broken.pdf")
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))

    with _worker_runtime():
        failed, succeeded = await asyncio.gather(
            _parse("broken.pdf", "TOKEN-AAA"),
            _parse("healthy.pdf", "TOKEN-BBB"),
            return_exceptions=True,
        )

    assert isinstance(failed, BinaryDocumentValidationError) or "파서" in str(failed)
    assert succeeded[0].text == "TOKEN-BBB"
    # Recovery is the same authority: no re-composition was needed after a failure.
    assert binary_document_parser_ready_async() is True


async def test_authority_survives_a_transport_error_for_the_next_request() -> None:
    binding = _FailingBinding(failing_name="broken.pdf")
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))

    with _worker_runtime():
        with pytest.raises(AttachmentValidationError) as outage:
            await _parse("broken.pdf", "TOKEN-AAA")
        assert OUTAGE_MESSAGE in str(outage.value)

        recovered = await _parse("later.pdf", "TOKEN-BBB")

    assert recovered[0].text == "TOKEN-BBB"
    assert binding.calls == 2


# --- 5: two accounts' documents stay separate --------------------------------


async def test_account_documents_do_not_cross_under_concurrent_requests() -> None:
    binding = _GatedBinding()
    compose_worker_isolated_parser_authority_async(transport=_transport(binding))
    for name in ("alpha.pdf", "beta.pdf", "gamma.pdf"):
        binding.gate_for(name)

    with _worker_runtime():
        tasks = [
            asyncio.create_task(_parse("alpha.pdf", "SECRET-ALPHA")),
            asyncio.create_task(_parse("beta.pdf", "SECRET-BETA")),
            asyncio.create_task(_parse("gamma.pdf", "SECRET-GAMMA")),
        ]
        while len(binding.entered) < 3:
            await asyncio.sleep(0)
        for name in ("beta.pdf", "alpha.pdf", "gamma.pdf"):
            binding.gate_for(name).set()
        results = await asyncio.gather(*tasks)

    assert [item[0].text for item in results] == [
        "SECRET-ALPHA",
        "SECRET-BETA",
        "SECRET-GAMMA",
    ]
    # The wire carries one document per call and no caller identity at all.
    assert [call["name"] for call in binding.calls] == [
        "alpha.pdf",
        "beta.pdf",
        "gamma.pdf",
    ]
    wire = json.dumps(binding.calls)
    for forbidden in ("owner", "account", "user", "workspace", "tenant", "session"):
        assert forbidden not in wire.lower()
