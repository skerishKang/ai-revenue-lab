"""#5568 U2 — the COM2 conversion queue worker loop.

Reuses U1's authority parts as they are: ``Com2SqliteLedger`` (the ledger),
``Com2ObjectStore`` (the original/markdown objects) and
``Com2ConversionEngine`` (the Core pypdf boundary). No new queue framework —
the queue IS the ledger's ``queued`` rows, and the loop is this module.

Two guarantees the owner asked for:

1. **No duplicate processing.** Items leave the queue through the ledger's
   atomic claim (one ``BEGIN IMMEDIATE`` transaction, queued→working
   conditioned on staying queued), so a second loop or a restarted worker
   cannot take the same row. ``failed`` is terminal and never re-claimed.
2. **Restart safety.** A worker that died mid-conversion leaves items in
   ``working``. Recovery completes an interrupted item from its markdown
   artifact when the deterministic output key already holds the converted
   body (the conversion had finished; no re-execution), and re-queues it
   otherwise (the conversion never produced output; the original bytes are
   still intact). Either way the item is processed exactly once.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .document_convert_com2 import (
    Com2ConversionEngine,
    Com2ObjectStore,
    Com2SqliteLedger,
    run_item_conversion,
)
from .document_convert_store import (
    JOB_STATUS_QUEUED,
    JOB_STATUS_WORKING,
    markdown_object_key,
)


class Com2ConversionWorker:
    """Drains the conversion queue using U1's authority parts as they are."""

    def __init__(
        self,
        *,
        ledger: Com2SqliteLedger,
        objects: Com2ObjectStore,
        engine: Com2ConversionEngine | None = None,
        poll_interval_seconds: float = 2.0,
        batch_size: int = 4,
    ) -> None:
        self._ledger = ledger
        self._objects = objects
        self._engine = engine or Com2ConversionEngine()
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = max(batch_size, 1)

    async def recover_interrupted(self) -> dict[str, int]:
        """Settle the ``working`` items a previous worker left behind.

        The markdown output key is deterministic from the item ids, so the
        artifact itself proves whether the conversion finished: an existing
        artifact completes the item (resume — no re-execution), a missing one
        re-queues the item (the original bytes are intact; the conversion
        never completed, so running it again is not duplication).
        """
        resumed = 0
        requeued = 0
        for claim in await self._ledger.working_items():
            item, user_id = claim.item, claim.user_id
            markdown_key = markdown_object_key(user_id, item.job_id, item.id)
            markdown = await asyncio.to_thread(self._objects.get, markdown_key)
            if markdown is not None:
                await self._ledger.complete_item(
                    user_id,
                    item.id,
                    status="done",
                    page_count=item.page_count,
                    character_count=len(markdown),
                    markdown_key=markdown_key,
                    report=item.report,
                    error_code=None,
                )
                resumed += 1
            else:
                await self._ledger.set_item_status(
                    user_id, item.id, JOB_STATUS_QUEUED
                )
                requeued += 1
            await self._ledger.refresh_job(user_id, item.job_id)
        return {"resumed": resumed, "requeued": requeued}

    async def process_one(self) -> str:
        """Claim and convert exactly one queued item.

        Returns ``converted``, ``failed`` or ``empty``. The conversion
        function records the outcome in the ledger either way and never
        re-raises application failures — the queue must keep draining.
        """
        claim = await self._ledger.claim_next_queued_item()
        if claim is None:
            return "empty"
        item, user_id = claim.item, claim.user_id
        try:
            record = await run_item_conversion(
                ledger=self._ledger,
                objects=self._objects,
                engine=self._engine,
                user_id=user_id,
                job_id=item.job_id,
                item_id=item.id,
            )
        except Exception:
            # Infrastructure-level failure (storage, runtime). The claim is
            # released back to the queue so a later loop retries it; the item
            # was never converted, so this is not duplicate processing.
            await self._ledger.set_item_status(user_id, item.id, JOB_STATUS_QUEUED)
            await self._ledger.refresh_job(user_id, item.job_id)
            return "failed"
        return "converted" if record is not None and record.status == "done" else "failed"

    async def run_once(self) -> dict[str, int]:
        """One maintenance pass: recovery, then drain up to ``batch_size``."""
        recovery = await self.recover_interrupted()
        converted = 0
        failed = 0
        for _ in range(self._batch_size):
            outcome = await self.process_one()
            if outcome == "converted":
                converted += 1
            elif outcome == "failed":
                failed += 1
            else:
                break
        return {"recovery": recovery, "converted": converted, "failed": failed}

    async def run_forever(self, stop: asyncio.Event) -> None:
        """The worker loop. ``stop`` (an ``asyncio.Event``) ends it cleanly."""
        await self.run_once()
        while not stop.is_set():
            try:
                result = await self.run_once()
            except Exception:
                result = {"converted": 0}
            if result["converted"] == 0 and result["failed"] == 0:
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=self._poll_interval_seconds
                    )
                except asyncio.TimeoutError:
                    pass
