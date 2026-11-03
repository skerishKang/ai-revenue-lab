"""Queue-owned filesystem cleanup layered onto the existing PC account store."""
from __future__ import annotations

from pathlib import Path

from app.pc_device_pairing_store import D1PcPairingStore, _user_id
from padiem_ai_core.pc_background import delete_account_background_jobs


class QueuePcAccountDataStore(D1PcPairingStore):
    """Use one idempotent queue RPC for account-bound SQL and disk cleanup."""

    def __init__(self, database, *, background_jobs_directory, pc_output_store):
        super().__init__(database)
        self.background_jobs_directory = (
            Path(background_jobs_directory) if background_jobs_directory else None
        )
        self.pc_output_store = pc_output_store

    async def delete_account_pc_data(self, *, user_id: str) -> bool:
        user_id = _user_id(user_id)
        if self.background_jobs_directory is None:
            raise RuntimeError("shared background jobs directory is not configured")
        # The files are removed before SQL so an unavailable shared filesystem fails
        # closed and leaves the account's queue rows available for a retry.
        delete_account_background_jobs(self.background_jobs_directory, user_id)
        self.pc_output_store.delete_account(user_id)
        return await super().delete_account_pc_data(user_id=user_id)
