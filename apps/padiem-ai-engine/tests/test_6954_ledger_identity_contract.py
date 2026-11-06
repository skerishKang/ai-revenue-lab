"""#6954 contract: a model call and its metrics report meet on one ledger row.

Two real halves meet here. The Engine half is the actual transport chain a model
call rides — the correlation headers from the turn collector plus the loopback
binding that used to overwrite the product. The ledger half is the platform's
real code — ``origin_from_headers`` → a written ``b14_model_call`` row →
``annotate_pc_work_metrics`` finding exactly that row.

Both applications own a package called ``app``, so the ledger half runs in a
fresh subprocess with the platform root on its path. If either half changes how
the identity is computed, carried or recorded, the row and the report stop
matching and this test fails.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.cloudflare_transport import CloudflareB14ServiceBindingTransport
from app.local_runtime import (
    B14_PROOF_SECRET_ENV, LocalB14Binding, LocalRequest, _APPS_AI_CLIENT_APP,
)
from app.pc_work_metrics import (
    PcWorkMetricsCollector, set_pc_work_metrics, reset_pc_work_metrics,
)
from app.pc_work_metrics_reporter import PcWorkMetricsReporter

PROOF = "synthetic-b14-proof-only-" + "x" * 32
IDENTITY = {"product": "chat", "subject_ref": "usr_contract_6954",
            "session_ref": "pcturn_" + "c" * 64}
CLIENT_APP = "synthetic-host-app"
ENGINE_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = ENGINE_ROOT.parent / "korean-ai-platform"

CHILD_SCRIPT = """
import asyncio, json, re, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])  # platform root: its ``app`` is the ledger side

from app.local_runtime import SqliteLedger
from app.pilot.call_ledger import (
    LedgerDraft, new_log_id, origin_from_headers, utc_now_iso, _REF_RE,
)
from app.pilot.call_ledger_store import CallLedgerStore

WIRE = json.load(open(sys.argv[2], encoding="utf-8"))
MODEL_HEADERS = WIRE["model_call_headers"]
REPORT = WIRE["report_body"]


async def main():
    ledger = SqliteLedger(Path(sys.argv[3]))
    ledger.apply_migrations()
    store = CallLedgerStore(ledger)

    origin = origin_from_headers(MODEL_HEADERS)
    draft = LedgerDraft(
        log_id=new_log_id(), request_id="b14req_contract_6954",
        endpoint="/api/pilot/v1/chat/completions",
        protocol="chat/completions", streaming=False, requested_model_id="synthetic",
        started_at=utc_now_iso(), origin=origin,
    )
    draft.record_attempt(provider="synthetic-pool", model_id="synthetic-model",
                         outcome="success", usage={"input_tokens": 100, "output_tokens": 20})
    record = draft.finish(outcome="success", http_status=200,
                          usage={"input_tokens": 100, "output_tokens": 20},
                          selected_provider="synthetic-pool",
                          selected_model_id="synthetic-model")
    record_status = await store.record(record)
    result = await store.annotate_pc_work_metrics(
        product=REPORT["product"], subject_ref=REPORT["subject_ref"],
        session_ref=REPORT["session_ref"], metrics=REPORT["metrics"],
    )
    subject = origin.get("subject_ref") or ""
    session = origin.get("session_ref") or ""
    print(json.dumps({
        "record_status": record_status,
        "annotate_status": result.get("status"),
        "annotate_log_id": result.get("log_id"),
        "product_recorded": origin.get("product"),
        "subject_matches_report": subject == REPORT["subject_ref"],
        "session_matches_report": session == REPORT["session_ref"],
        "subject_ref_format_ok": bool(_REF_RE.fullmatch(subject)) if subject else False,
        "session_ref_format_ok": bool(_REF_RE.fullmatch(session)) if session else False,
    }, ensure_ascii=True))


asyncio.run(main())
"""


async def _model_call_and_report_through_real_binding():
    """One turn through the real transport + loopback binding: the model call
    first, then the metrics report. Returns the wire both of them produced."""
    captured = []
    def capture(request: httpx.Request) -> httpx.Response:
        captured.append({
            "url": str(request.url),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": request.content.decode("utf-8", "replace"),
        })
        return httpx.Response(200, json={"ok": True})

    binding = LocalB14Binding(
        "http://127.0.0.1:8789",
        values={B14_PROOF_SECRET_ENV: PROOF},
        client=httpx.AsyncClient(transport=httpx.MockTransport(capture)),
    )
    # The host composition builds model-call requests through the same local
    # request wrapper worker.py uses as its request_factory.
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=LocalRequest,
        proof_secret=PROOF,
    )
    reporter = PcWorkMetricsReporter(transport=transport, base_url="https://b14.internal")

    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.ledger_identity = dict(IDENTITY)
    app_token = _APPS_AI_CLIENT_APP.set(CLIENT_APP)
    token = set_pc_work_metrics(collector)
    try:
        call_id = collector.model_start(messages=[{"role": "user", "content": "synthetic"}])
        collector.model_finish(call_id)
        request = httpx.Request(
            "POST", "https://b14.internal/api/pilot/v1/chat/completions",
            json={"model": "synthetic"},
        )
        response = await transport.handle_async_request(request)
        await response.aclose()
        # The real turn ends before the report: orchestration calls finish(),
        # then hands the snapshot to the reporter.
        collector.finish("completed", "completed")
        assert await reporter({**IDENTITY, "metrics": collector.snapshot()}) == "recorded"
    finally:
        reset_pc_work_metrics(token)
        _APPS_AI_CLIENT_APP.reset(app_token)

    model_calls = [row for row in captured if "pc-turn-metrics" not in row["url"]]
    reports = [row for row in captured if "pc-turn-metrics" in row["url"]]
    assert len(model_calls) == 1 and len(reports) == 1
    return model_calls[0], reports[0]


def test_model_call_and_metrics_report_meet_on_one_ledger_row(tmp_path, caplog):
    model_call, report = asyncio.run(_model_call_and_report_through_real_binding())

    # The loopback binding must not rebrand a request the collector already
    # identified: product stays the report's value, not "engine" (#6954).
    assert model_call["headers"]["x-padiem-product"] == IDENTITY["product"]
    assert model_call["headers"]["x-padiem-subject-ref"] == IDENTITY["subject_ref"]
    assert model_call["headers"]["x-padiem-session-ref"] == IDENTITY["session_ref"]
    assert report["headers"]["x-padiem-product"] == IDENTITY["product"]

    wire = {"model_call_headers": model_call["headers"],
            "report_body": json.loads(report["body"])}
    wire_file = tmp_path / "wire.json"
    wire_file.write_text(json.dumps(wire, ensure_ascii=True), encoding="utf-8")
    ledger_db = tmp_path / "b14-ledger.sqlite3"

    completed = subprocess.run(
        [sys.executable, "-c", CHILD_SCRIPT, str(PLATFORM_ROOT), str(wire_file), str(ledger_db)],
        check=False, capture_output=True, text=True, timeout=120,
        encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert completed.returncode == 0, completed.stderr[-2000:]

    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["record_status"] == "written"
    assert result["annotate_status"] == "recorded", result
    assert result["product_recorded"] == IDENTITY["product"]
    assert result["subject_matches_report"] is True
    assert result["session_matches_report"] is True
    # #6954 regression: the ledger accepts only bounded opaque references, so a
    # recorded row proves the header values respect B14's format and length contract.
    assert result["subject_ref_format_ok"] is True
    assert result["session_ref_format_ok"] is True
    # The identity values never travel raw through the journal or the response:
    # the child prints statuses and opaque log ids only, and the engine journal
    # (pinned in the reporter suite) carries the status word alone.
    assert IDENTITY["subject_ref"] not in completed.stdout
    assert IDENTITY["session_ref"] not in completed.stdout
    assert IDENTITY["subject_ref"] not in caplog.text
    assert IDENTITY["session_ref"] not in caplog.text
