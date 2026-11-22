"""Web XLSX approved copy wire shared test preparation (#8061).

Moved out of test_3580_web_xlsx_approved_copy_wire so the test-to-test
import ratchet does not grow: the hub and its consumers all import this
name from here.
"""
from __future__ import annotations

__all__ = ["enable_real_copy"]


def enable_real_copy(app, metadata):
    app.state.web_xlsx_p01_workcopy_after_grant_enabled = True

    async def scoped_rows(*, tenant_id, key_prefix, now, limit=40):
        return [
            item for item in metadata.rows.values()
            if item.tenant_id == tenant_id
            and item.object_key.startswith(key_prefix)
            and item.expires_at > now
        ][:limit]

    metadata.list_web_xlsx = scoped_rows
