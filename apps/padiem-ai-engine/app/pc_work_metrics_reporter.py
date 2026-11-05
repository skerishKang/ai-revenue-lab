"""Attach a finished PC turn to its existing B14 model-call ledger row.

Uses the same pinned B14 transport and service proof as model execution. The
small retry window covers B14's existing deferred ledger write; no new queue,
storage or provider call is created, and delivery never changes the PC answer.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

PC_WORK_METRICS_PATH = "/api/pilot/v1/internal/pc-turn-metrics"
# B14 deferred_writes.WRITE_TIMEOUT_SECONDS is also five seconds. This bounds
# telemetry delivery only; it is not a PC-command or model execution deadline.
DELIVERY_SECONDS = 5.0
# #6954: the retry ladder replaces the fixed 50 ms spin — the total wait still
# stays inside DELIVERY_SECONDS, which remains the only hard deadline.
RETRY_BACKOFF_SECONDS = (0.25, 0.5, 1.0)
logger = logging.getLogger(__name__)


class PcWorkMetricsReporter:
    def __init__(self, *, transport, base_url, delivery_seconds=DELIVERY_SECONDS):
        self._transport = transport
        self._url = base_url.rstrip("/") + PC_WORK_METRICS_PATH
        self._delivery_seconds = delivery_seconds

    async def __call__(self, payload):
        # #6954: a turn whose execution never reached a model call has no ledger
        # row to attach to — retrying would always end in the same 409. Skip it
        # (the journal distinguishes skipped from the delivered outcomes).
        metrics = payload.get("metrics") or {}
        if not metrics.get("model_calls"):
            logger.warning("pc_work_metrics_delivery status=skipped")
            return "skipped"
        # The ledger identity (product, subject_ref, session_ref) reaches B14 as
        # the correlation headers the transport already attaches from the
        # context collector; adding them here as well produced duplicated
        # header values that broke the ledger match.
        status = "unavailable"
        try:
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
            attempt = 0
            async with asyncio.timeout(self._delivery_seconds):
                while True:
                    response = await self._transport.handle_async_request(httpx.Request(
                        "POST", self._url, content=body,
                        headers={"Content-Type": "application/json"},
                    ))
                    try:
                        raw = await response.aread()
                        result = json.loads(raw)
                    finally:
                        await response.aclose()
                    if response.status_code == 200 and result.get("ok") is True:
                        status = "recorded"
                        break
                    error = result.get("error", {}) if isinstance(result, dict) else {}
                    code = error.get("code") if isinstance(error, dict) else None
                    if response.status_code == 409 and code == "ledger_pending":
                        await asyncio.sleep(
                            RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)]
                        )
                        attempt += 1
                        continue
                    status = "conflict" if response.status_code == 409 else "unavailable"
                    break
        except asyncio.CancelledError:
            # Preserve cancellation semantics; the lifecycle owns its outcome.
            raise
        except Exception:
            # No response body, identity, provider reference or exception detail
            # may be echoed into operational logs.
            status = "unavailable"
        # One line per delivery outcome (values only): the journal distinguishes
        # recorded / skipped / unavailable so #6954 cannot hide behind silence.
        logger.warning("pc_work_metrics_delivery status=%s", status)
        return status
