"""Attach a finished PC turn to its existing B14 model-call ledger row.

Uses the same pinned B14 transport and service proof as model execution. The
small retry window covers B14's existing deferred ledger write; no new queue,
storage or provider call is created, and delivery never changes the PC answer.

A turn that made no model call cannot have a ledger row to attach to (an MCP
pc_* turn produces none), so its report is skipped outright with one journal
line instead of burning the whole delivery window on guaranteed 409s (#6954).
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
# #6954: a fixed 50 ms retry sent ~100 pointless requests per turn while B14
# kept answering 409 ledger_pending. Back off instead; the delivery window
# still caps everything at five seconds.
RETRY_BACKOFF_SECONDS = (0.25, 0.5, 1.0, 2.0)
logger = logging.getLogger(__name__)


class PcWorkMetricsReporter:
    def __init__(self, *, transport, base_url, delivery_seconds=DELIVERY_SECONDS):
        self._transport = transport
        self._url = base_url.rstrip("/") + PC_WORK_METRICS_PATH
        self._delivery_seconds = delivery_seconds

    async def __call__(self, payload):
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if not isinstance(metrics, dict) or metrics.get("model_calls", 0) == 0:
            # No model execution in this turn means no ledger row can ever
            # exist for the report to attach to. Skip the delivery instead of
            # retrying a guaranteed 409 through the whole window (#6954).
            logger.warning("pc_work_metrics_delivery status=skipped_no_model_call")
            return "skipped_no_model_call"
        status = "unavailable"
        try:
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
            async with asyncio.timeout(self._delivery_seconds):
                retries = 0
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
                        waits = RETRY_BACKOFF_SECONDS
                        await asyncio.sleep(waits[min(retries, len(waits) - 1)])
                        retries += 1
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
        if status != "recorded":
            logger.warning("pc_work_metrics_delivery status=%s", status)
        return status
