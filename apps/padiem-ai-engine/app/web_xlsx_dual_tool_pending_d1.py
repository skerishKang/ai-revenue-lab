"""Route independent READ and WRITE Core continuations to D1 stores.

The stores share the existing Engine D1 continuation table but never share
user approval scopes. No in-memory/READ fallback for a WRITE continuation.
"""
from __future__ import annotations
from .web_xlsx_p01_tool_binding import APP_ID as READ_APP
from .web_xlsx_quote_write_tool_binding import APP_ID as WRITE_APP

class DualWebXlsxToolPendingStore:
    def __init__(self, original_read, independent_write):
        if original_read is None or independent_write is None:
            raise ValueError("both durable Core pause stores required")
        self._stores = {READ_APP:original_read,WRITE_APP:independent_write}

    def _choose(self, app_id):
        store=self._stores.get(app_id)
        if store is None:
            raise ValueError("unknown Core tool app")
        return store

    async def issue(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).issue(**kwargs)
    async def issue_tool(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).issue_tool(**kwargs)
    async def resolve(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).resolve(**kwargs)
    async def load_tool_pending(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).load_tool_pending(**kwargs)
    async def claim(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).claim(**kwargs)
    async def commit(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).commit(**kwargs)
    async def release(self,**kwargs):
        return await self._choose(kwargs.get("app_id")).release(**kwargs)
